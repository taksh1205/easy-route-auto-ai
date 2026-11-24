import hashlib
import json
import secrets
import time
import uuid
from collections import OrderedDict, deque
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from . import __version__
from .ai import run
from .config import settings
from .db import get_db
from .models import (
    ActionProposal,
    Appointment,
    Conversation,
    Idempotency,
    Lead,
    Message,
    now,
)
from .preferences import resolve
from .rag import Document, PolicyIndex, RAGError
from .schemas import (
    Booking,
    Chat,
    Confirmation,
    LeadInput,
    PreferenceUpdate,
    ProposalInput,
    Reschedule,
    Search,
)
from .services import (
    appointment_record,
    availability,
    book,
    cancel_pending,
    idempotent,
    inventory,
    payload_digest,
    reschedule_pending,
)
from .tools import commit_action, proposal

app = FastAPI(title="Easy Route Auto AI", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=[
        "Content-Type",
        "X-Session-Token",
        "Authorization",
        "Idempotency-Key",
        "X-Employee-Token",
    ],
    expose_headers=["X-Request-ID"],
)
DB = Annotated[Session, Depends(get_db)]
TOKEN = Annotated[str | None, Header()]
buckets = OrderedDict()
bucket_lock = Lock()


@app.middleware("http")
async def limits(request: Request, call_next):
    request.state.trace_id = uuid.uuid4().hex
    key = request.client.host if request.client else "unknown"
    t = time.monotonic()
    with bucket_lock:
        q = buckets.setdefault(key, deque())
        while q and q[0] < t - 60:
            q.popleft()
        limited = len(q) >= settings.request_limit_per_minute
        if not limited:
            q.append(t)
        buckets.move_to_end(key)
        while len(buckets) > 4096:
            buckets.popitem(last=False)
    if limited:
        return JSONResponse(
            status_code=429,
            content={"detail": "Request limit reached"},
            headers={"Retry-After": "60", "X-Request-ID": request.state.trace_id},
        )
    # Bound actual bytes, including requests without Content-Length; never buffer unbounded input.
    if request.method in {"POST", "PATCH", "PUT"}:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 320000:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Body limit is 320KB"},
                    headers={"X-Request-ID": request.state.trace_id},
                )
        request._body = bytes(data)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.trace_id
    return response


@app.exception_handler(ValidationError)
async def internal_validation(request, exc):
    return JSONResponse(status_code=422, content={"detail": "Invalid typed arguments"})


@app.exception_handler(RAGError)
async def rag_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def owned(cid, db, token, operational=False):
    c = db.get(Conversation, cid)
    if (
        not c
        or not token
        or not secrets.compare_digest(c.token_hash, hashlib.sha256(token.encode()).hexdigest())
    ):
        raise HTTPException(404, "Session not found")
    if not operational and c.updated_at < now() - settings.retention_days * 86400:
        raise HTTPException(410, "Chat expired; operational booking access remains available")
    return c


def staff(authorization: TOKEN = None):
    if (
        not settings.staff_token
        or not authorization
        or not secrets.compare_digest(authorization, "Bearer " + settings.staff_token)
    ):
        raise HTTPException(401, "Staff authentication required")


def clear_chat(db, c):
    from .models import RentalContext

    db.execute(delete(RentalContext).where(RentalContext.owner == c.id))
    # Acquire the session write boundary before deletion, and increment from the DB value.
    # In-flight inference using an old version cannot commit after this privacy operation.
    db.execute(
        update(Conversation)
        .where(Conversation.id == c.id)
        .values(preferences={}, version=Conversation.version + 1)
    )
    db.refresh(c)
    db.execute(delete(Message).where(Message.conversation_id == c.id))
    db.execute(delete(Lead).where(Lead.conversation_id == c.id))
    db.execute(delete(ActionProposal).where(ActionProposal.conversation_id == c.id))
    for marker in db.scalars(select(Idempotency).where(Idempotency.conversation_id == c.id)):
        if marker.result.get("kind") in {"lead", "preferences"}:
            db.delete(marker)
    c.preferences = {}
    # Keep a minimal ownership anchor and operational appointment/idempotency records.


@app.get("/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "ai_mode": settings.ai_mode,
        "version": __version__,
        "staff_auth": "individual-role-tokens (rental); shared demo token (legacy)",
    }


@app.post("/sessions", status_code=201)
def session(db: DB):
    token = secrets.token_urlsafe(32)
    c = Conversation(token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(c)
    db.commit()
    return {"id": c.id, "token": token, "ai_mode": settings.ai_mode, "version": c.version}


@app.get("/inventory")
def vehicles(
    db: DB,
    max_price: int | None = Query(None, ge=0, le=1000000),
    body: str | None = None,
    min_seats: int = Query(1, ge=1, le=9),
    max_mileage: int | None = Query(None, ge=0),
    min_mpg: int | None = Query(None, ge=1, le=150),
    low_mileage: bool = False,
    fuel_efficient: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    args = Search(
        max_price=max_price,
        body=body,
        min_seats=min_seats,
        max_mileage=max_mileage,
        min_mpg=min_mpg,
        low_mileage=low_mileage,
        fuel_efficient=fuel_efficient,
    )
    return inventory(db, args, limit, offset)


@app.post("/sessions/{cid}/chat")
async def chat(cid: str, body: Chat, request: Request, db: DB, x_session_token: TOKEN = None):
    c = owned(cid, db, x_session_token)
    version = c.version
    preferences = dict(c.preferences)
    if body.expected_version is not None and body.expected_version != version:
        raise HTTPException(409, "Session version changed; reload before sending")
    history = [
        {
            "role": m.role,
            "content": m.content
            + (
                " Displayed vehicle IDs in order: "
                + json.dumps([v["id"] for v in m.trace.get("vehicles", [])[:50]])
                if m.role == "assistant"
                else ""
            ),
        }
        for m in list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == cid)
                .order_by(Message.id.desc())
                .limit(8)
            )
        )[::-1]
    ]
    db.rollback()  # Snapshot copied; inference holds no DB locks or transaction.
    try:
        result = await run(
            db, cid, body.message, preferences, history, version, request.state.trace_id
        )
        count = db.execute(
            update(Conversation)
            .where(Conversation.id == cid, Conversation.version == version)
            .values(preferences=result.preferences, version=version + 1, updated_at=now())
        ).rowcount
        if count != 1:
            raise HTTPException(409, "Concurrent turn changed this session; reload and retry")
        db.add_all(
            [
                Message(conversation_id=cid, role="user", content=body.message),
                Message(
                    conversation_id=cid,
                    role="assistant",
                    content=result.reply,
                    trace=result.model_dump(exclude={"preferences"}),
                ),
            ]
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def restored_result(db, stored):
    result = dict(stored)
    current = []
    for original in result.get("proposals", []):
        item = dict(original)
        row = db.get(ActionProposal, item["id"])
        item["status"] = (
            "unavailable"
            if not row
            else "consumed"
            if row.consumed
            else "expired"
            if row.expires_at <= now()
            else "proposed"
        )
        current.append(item)
    result["proposals"] = current
    return result


@app.get("/sessions/{cid}")
def history(
    cid: str,
    db: DB,
    x_session_token: TOKEN = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    c = owned(cid, db, x_session_token)
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == cid)
        .order_by(Message.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "preferences": c.preferences,
        "version": c.version,
        "ai_mode": settings.ai_mode,
        "inventory": inventory(db, Search.model_validate(c.preferences)),
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "result": restored_result(db, m.trace) if m.role == "assistant" else None,
            }
            for m in messages
        ],
    }


@app.patch("/sessions/{cid}/preferences")
def preferences(cid: str, body: PreferenceUpdate, db: DB, x_session_token: TOKEN = None):
    c = owned(cid, db, x_session_token)
    resolved = resolve(c.preferences, body.operations).model_dump()
    count = db.execute(
        update(Conversation)
        .where(Conversation.id == cid, Conversation.version == body.expected_version)
        .values(preferences=resolved, version=body.expected_version + 1, updated_at=now())
    ).rowcount
    if count != 1:
        db.rollback()
        raise HTTPException(409, "Session version changed")
    db.commit()
    return {
        "preferences": resolved,
        "version": body.expected_version + 1,
        "inventory": inventory(db, Search(**resolved)),
    }


@app.delete("/sessions/{cid}", status_code=204)
def forget(cid: str, db: DB, x_session_token: TOKEN = None):
    c = owned(cid, db, x_session_token, operational=True)
    clear_chat(db, c)
    c.updated_at = now()
    db.commit()


@app.post("/sessions/{cid}/leads", status_code=201)
def lead(
    cid: str, body: LeadInput, db: DB, x_session_token: TOKEN = None, idempotency_key: TOKEN = None
):
    owned(cid, db, x_session_token)
    return idempotent(
        db,
        cid,
        idempotency_key,
        "lead",
        body.model_dump(mode="json"),
        lambda: commit_action(db, cid, "lead", body.model_dump(mode="json")),
    )


@app.get("/availability/{vehicle_id}")
def slots(vehicle_id: int, db: DB):
    return availability(db, vehicle_id)


@app.post("/sessions/{cid}/appointments", status_code=201)
def booking(
    cid: str, body: Booking, db: DB, x_session_token: TOKEN = None, idempotency_key: TOKEN = None
):
    owned(cid, db, x_session_token, operational=True)
    return book(db, cid, body, idempotency_key)


@app.get("/sessions/{cid}/appointments")
def my_bookings(
    cid: str,
    db: DB,
    x_session_token: TOKEN = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    owned(cid, db, x_session_token, operational=True)
    return [
        appointment_record(a)
        for a in db.scalars(
            select(Appointment)
            .where(Appointment.conversation_id == cid)
            .order_by(Appointment.slot)
            .limit(limit)
            .offset(offset)
        )
    ]


@app.delete("/sessions/{cid}/appointments/{aid}", status_code=204)
def cancel(
    cid: str, aid: str, db: DB, x_session_token: TOKEN = None, idempotency_key: TOKEN = None
):
    owned(cid, db, x_session_token, operational=True)
    idempotent(
        db,
        cid,
        idempotency_key,
        "cancellation",
        {"appointment_id": aid},
        lambda: cancel_pending(db, cid, aid),
    )


@app.post("/sessions/{cid}/reschedule")
def reschedule(
    cid: str, body: Reschedule, db: DB, x_session_token: TOKEN = None, idempotency_key: TOKEN = None
):
    owned(cid, db, x_session_token, operational=True)
    return idempotent(
        db,
        cid,
        idempotency_key,
        "reschedule",
        body.model_dump(mode="json"),
        lambda: reschedule_pending(db, cid, body),
    )


@app.post("/sessions/{cid}/proposals", status_code=201)
def propose(cid: str, body: ProposalInput, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token, operational=True)
    # Validate exact payload without executing it.
    from .schemas import Cancel

    schema = {
        "booking": Booking,
        "lead": LeadInput,
        "cancellation": Cancel,
        "reschedule": Reschedule,
        "preferences": PreferenceUpdate,
    }[body.kind]
    args = schema.model_validate(body.arguments).model_dump(mode="json")
    if body.kind in {"cancellation", "reschedule"}:
        a = db.get(Appointment, args["appointment_id"])
        if not a or a.conversation_id != cid:
            raise HTTPException(404, "Appointment not found")
    row = proposal(db, cid, body.kind, args)
    db.commit()
    return row


@app.post("/sessions/{cid}/proposals/{pid}/confirm")
def confirm(
    cid: str,
    pid: str,
    body: Confirmation,
    db: DB,
    x_session_token: TOKEN = None,
    idempotency_key: TOKEN = None,
):
    owned(cid, db, x_session_token, operational=True)

    def execute():
        row = db.scalar(select(ActionProposal).where(ActionProposal.id == pid).with_for_update())
        if not row or row.conversation_id != cid:
            raise HTTPException(404, "Proposal not found")
        if row.consumed:
            raise HTTPException(409, "Proposal already consumed")
        if row.expires_at <= now():
            raise HTTPException(410, "Proposal expired")
        if body.kind != row.kind or payload_digest(body.kind, body.arguments) != payload_digest(
            row.kind, row.arguments
        ):
            raise HTTPException(409, "Proposal arguments changed")
        result = commit_action(db, cid, row.kind, row.arguments)
        row.consumed = True
        return result

    # Same request/key replays original committed result; a new key cannot consume twice.
    return idempotent(
        db, cid, idempotency_key, "confirm", {"proposal_id": pid, **body.model_dump()}, execute
    )


@app.get("/staff/overview", dependencies=[Depends(staff)])
def overview(db: DB, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {
        "leads": [
            {"id": lead.id, "name": lead.name, "email": lead.email, "status": lead.status}
            for lead in db.scalars(select(Lead).order_by(Lead.id).limit(limit).offset(offset))
        ],
        "appointments": [
            appointment_record(a)
            for a in db.scalars(
                select(Appointment).order_by(Appointment.slot).limit(limit).offset(offset)
            )
        ],
        "conversations": [
            {"id": c.id, "preferences": c.preferences, "version": c.version}
            for c in db.scalars(
                select(Conversation).order_by(Conversation.id).limit(limit).offset(offset)
            )
        ],
        "ai_mode": settings.ai_mode,
        "warning": "Local demo shared token; individual roles not implemented",
    }


@app.delete("/staff/expired", dependencies=[Depends(staff)])
def purge(db: DB):
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.updated_at < now() - settings.retention_days * 86400)
        .with_for_update()
    ).all()
    for c in rows:
        clear_chat(db, c)
    db.commit()
    return {"chat_data_purged": len(rows), "appointments_preserved": True}


@app.post("/staff/policies", dependencies=[Depends(staff)])
def ingest(documents: list[Document]):
    return PolicyIndex().ingest([d.model_dump() for d in documents])


@app.delete("/staff/policies/{doc_id}", dependencies=[Depends(staff)])
def delete_policy(doc_id: str):
    return PolicyIndex().ingest(delete_ids=[doc_id])


# Imported last: the rentals router depends on objects defined in this module.
from .rentals import router as rental_router  # noqa: E402

app.include_router(rental_router)
