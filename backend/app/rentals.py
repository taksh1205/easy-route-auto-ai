"""Rental search, versioned customer display context and exact quote acceptance."""

import hashlib
import secrets
from calendar import monthrange
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import delete, select, update

from . import clock
from .config import settings
from .main import DB, TOKEN, owned
from .models import (
    Employee,
    RentalAudit,
    RentalContext,
    RentalDay,
    RentalRate,
    RentalRecord,
    Vehicle,
    now,
)
from .rental_constraints import reconcile
from .rental_language import Unclear, authorized_reference, check_comparators, offline
from .rental_planner import configured_model
from .schemas import Strict
from .services import idempotent

router = APIRouter()


def business_date():
    return clock.utcnow().astimezone(ZoneInfo("America/Phoenix")).date()


def require_open(original):
    if business_date() >= date.fromisoformat(original.terms["end"]):
        raise HTTPException(409, "The original return date has arrived. Start a new rental search.")


class Query(Strict):
    min_seats: int | None = Field(None, ge=1, le=100)
    start: date
    end: date
    location: str = "Tempe"
    body: Literal["suv", "sedan", "truck", "hatchback"] | None = None
    period: Literal["daily", "weekly", "monthly"] | None = None
    budget_cents: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def valid(self):
        if not 1 <= (self.end - self.start).days <= 366:
            raise ValueError("Choose 1–366 rental days")
        if self.budget_cents is not None and not self.period:
            raise ValueError("Is your budget daily, weekly or monthly?")
        return self


def month_after(start, n=1):
    idx = start.month - 1 + n
    y = start.year + idx // 12
    m = idx % 12 + 1
    return date(y, m, min(start.day, monthrange(y, m)[1]))


def quote_terms(rate, q):
    unit = q.period or "daily"
    days = (q.end - q.start).days
    if unit == "monthly":
        count = 0
        while month_after(q.start, count + 1) <= q.end:
            count += 1
        remainder = (q.end - month_after(q.start, count)).days
    elif unit == "weekly":
        count, remainder = divmod(days, 7)
    else:
        count, remainder = days, 0
    lines = [dict(unit=unit, count=count, unit_cents=getattr(rate, unit))]
    if remainder:
        lines.append(dict(unit="daily", count=remainder, unit_cents=rate.daily))
    return {
        **q.model_dump(mode="json"),
        "vehicle_id": rate.vehicle_id,
        "currency": "USD",
        "lines": lines,
        "total_cents": sum(line["count"] * line["unit_cents"] for line in lines),
    }


def options(db, q):
    occupied = select(RentalDay.vehicle_id).where(
        RentalDay.day >= q.start.isoformat(), RentalDay.day < q.end.isoformat()
    )
    stmt = (
        select(RentalRate, Vehicle)
        .join(Vehicle)
        .where(
            RentalRate.location == q.location,
            RentalRate.active,
            Vehicle.available,
            RentalRate.vehicle_id.not_in(occupied),
        )
    )
    if q.min_seats is not None:
        stmt = stmt.where(Vehicle.seats >= q.min_seats)
    if q.body:
        stmt = stmt.where(Vehicle.body == q.body)
    if q.budget_cents is not None:
        stmt = stmt.where(getattr(RentalRate, q.period) <= q.budget_cents)
    return [
        dict(id=v.id, name=v.name, seats=v.seats, **quote_terms(r, q))
        for r, v in db.execute(stmt.order_by(getattr(RentalRate, q.period or "daily"), Vehicle.id))
    ]


def ledger(r):
    return dict(id=r.id, status=r.status, terms=r.terms, expires=r.expires)


def account(db, token, roles):
    if not token:
        raise HTTPException(401, "Employee access token required")
    who = db.scalar(
        select(Employee).where(Employee.digest == hashlib.sha256(token.encode()).hexdigest())
    )
    if not who or who.role not in roles:
        raise HTTPException(403, "Employee role does not permit this action")
    return who


def remember(db, cid, data):
    row = db.get(RentalContext, cid)
    if row:
        row.data = data
    else:
        db.add(RentalContext(owner=cid, data=data))


@router.post("/sessions/{cid}/rentals/search")
def search(cid: str, q: Query, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token)
    if q.start < business_date():
        raise HTTPException(422, "Choose a future rental interval")
    rows = options(db, q)
    state = dict(
        query=q.model_dump(mode="json"),
        ids=[v["id"] for v in rows],
        turn=secrets.token_hex(12),
    )
    remember(db, cid, state)
    db.commit()
    return {**state, "vehicles": rows}


class Reference(Strict):
    turn: str
    operation: Literal["compare", "seats", "quote", "month", "suv", "select"]
    position: int | None = Field(default=None, ge=1, le=100)


@router.post("/sessions/{cid}/rentals/reference")
def reference(cid: str, b: Reference, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token)
    ctx = db.scalar(select(RentalContext).where(RentalContext.owner == cid).with_for_update())
    if not ctx or ctx.data["turn"] != b.turn:
        raise HTTPException(409, "Results changed. Search again to select the vehicle.")
    state = dict(ctx.data)
    q = Query(**state["query"])
    if b.operation in ("month", "suv"):
        changed = q.model_dump()
        if b.operation == "month":
            changed["end"] = month_after(q.start)
        else:
            changed["body"] = "suv"
        return search(cid, Query(**changed), db, x_session_token)
    ids = state["ids"]
    rows = {v["id"]: v for v in options(db, q)}
    if q.start < business_date():
        raise HTTPException(409, "Pickup has passed. Choose new dates.")
    if b.position is None or b.position > len(ids) or ids[b.position - 1] not in rows:
        raise HTTPException(409, "Choose a valid position from the current results.")
    if b.operation in ("compare", "seats") and ids[0] not in rows:
        raise HTTPException(409, "That reference is unavailable. Refresh the results.")
    selected = rows[ids[b.position - 1]]
    if b.operation == "quote":
        terms = {k: v for k, v in selected.items() if k not in ("id", "name", "seats")}
        record = RentalRecord(owner=cid, terms=terms, status="quoted", expires=now() + 900)
        db.add(record)
        db.flush()
        ctx.data = {**state, "quote_id": record.id}
        result = {"quote": ledger(record)}
    elif b.operation == "select":
        ctx.data = {**state, "selected": selected["id"], "explicit_selection": True}
        result = {"selection": selected}
    else:
        first = rows[ids[0]]
        result = {
            "comparison": [first, selected],
            "seat_difference": selected["seats"] - first["seats"],
        }
    db.commit()
    return result


class Accept(Strict):
    terms: dict


@router.post("/sessions/{cid}/rentals/{rid}/submit")
def submit(
    cid: str,
    rid: str,
    b: Accept,
    db: DB,
    x_session_token: TOKEN = None,
    idempotency_key: TOKEN = None,
):
    owned(cid, db, x_session_token, operational=True)

    def commit():
        row = db.scalar(
            select(RentalRecord)
            .where(RentalRecord.id == rid, RentalRecord.owner == cid)
            .with_for_update()
        )
        if not row:
            raise HTTPException(404, "Quote unavailable")
        if row.status != "quoted" or row.expires <= now():
            raise HTTPException(409, "Quote expired or already submitted")
        from .services import payload_digest

        if payload_digest("quote", row.terms) != payload_digest("quote", b.terms):
            raise HTTPException(409, "Quoted terms differ")
        row.status = "pending"
        return ledger(row)

    return idempotent(
        db, cid, idempotency_key, "rental-submit", {"id": rid, "terms": b.terms}, commit
    )


@router.get("/sessions/{cid}/rentals")
def rentals(cid: str, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token, operational=True)
    ctx = db.scalar(select(RentalContext).where(RentalContext.owner == cid).with_for_update())
    display = []
    if ctx:
        current = {v["id"]: v for v in options(db, Query(**ctx.data["query"]))}
        ids = (
            [i for i in ctx.data["ids"] if i in current]
            if date.fromisoformat(ctx.data["query"]["start"]) >= business_date()
            else []
        )
        display = [current[i] for i in ids]
        legacy_selection = "selected" in ctx.data and not ctx.data.get("explicit_selection")
        if ids != ctx.data["ids"] or legacy_selection:
            previous = dict(ctx.data)
            if legacy_selection or previous.get("selected") not in ids:
                previous.pop("explicit_selection", None)
                previous.pop("selected", None)
                previous.pop("quote_id", None)
            ctx.data = {**previous, "ids": ids, "turn": secrets.token_hex(12)}
            db.commit()
    return {
        "displayed": display,
        "mode": settings.ai_mode,
        "model": configured_model(),
        "context": ctx.data if ctx else None,
        "records": [
            ledger(r)
            for r in db.scalars(select(RentalRecord).where(RentalRecord.owner == cid).limit(100))
        ],
    }


@router.get("/rental-staff/queue")
def queue(db: DB, x_employee_token: TOKEN = None):
    account(db, x_employee_token, {"reviewer", "manager"})
    return [
        ledger(r)
        for r in db.scalars(
            select(RentalRecord).where(RentalRecord.status.in_(["pending", "confirmed"])).limit(100)
        )
    ]


class Decision(Strict):
    action: Literal["approve", "decline", "cancel"]


@router.post("/rental-staff/{rid}/decision")
def decide(rid: str, b: Decision, db: DB, x_employee_token: TOKEN = None):
    actor = account(db, x_employee_token, {"reviewer", "manager"})
    row = db.scalar(select(RentalRecord).where(RentalRecord.id == rid).with_for_update())
    required = "confirmed" if b.action == "cancel" else "pending"
    if not row or row.status != required:
        raise HTTPException(409, "Request status changed")
    if b.action == "approve":
        terms = row.terms
        rate = db.scalar(
            select(RentalRate).where(RentalRate.vehicle_id == terms["vehicle_id"]).with_for_update()
        )
        if not rate.active or not db.get(Vehicle, rate.vehicle_id).available:
            raise HTTPException(409, "Fleet vehicle unavailable")
        start = date.fromisoformat(terms["start"])
        end = date.fromisoformat(terms["end"])
        if not terms.get("extends") and start < business_date():
            raise HTTPException(409, "Requested pickup date has passed")
        original_id = terms.get("extends")
        if original_id:
            original = db.scalar(
                select(RentalRecord)
                .where(RentalRecord.id == original_id, RentalRecord.owner == row.owner)
                .with_for_update()
            )
            if not original or original.status != "confirmed":
                raise HTTPException(409, "Original reservation changed")
            require_open(original)
            db.execute(delete(RentalDay).where(RentalDay.reservation == original_id))
            original.status = "extended"
        for i in range((end - start).days):
            db.add(
                RentalDay(
                    vehicle_id=rate.vehicle_id,
                    day=(start + timedelta(days=i)).isoformat(),
                    reservation=rid,
                )
            )
        row.status = "confirmed"
    elif b.action == "cancel":
        db.execute(delete(RentalDay).where(RentalDay.reservation == rid))
        row.status = "cancelled"
    else:
        row.status = "declined"
    db.add(RentalAudit(actor=actor.name, operation=b.action, target=rid))
    from sqlalchemy.exc import IntegrityError

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Vehicle already reserved on requested dates") from exc
    return ledger(row)


@router.patch("/rental-staff/fleet/{vid}")
def fleet(vid: int, active: bool, db: DB, x_employee_token: TOKEN = None):
    actor = account(db, x_employee_token, {"manager"})
    if not db.execute(
        update(RentalRate).where(RentalRate.vehicle_id == vid).values(active=active)
    ).rowcount:
        raise HTTPException(404, "Rental vehicle unavailable")
    db.add(
        RentalAudit(
            actor=actor.name,
            operation="enable" if active else "disable",
            target=str(vid),
        )
    )
    db.commit()
    return {"id": vid, "active": active}


class Extension(Strict):
    end: date


@router.post("/sessions/{cid}/rentals/{rid}/extension")
def extend(cid: str, rid: str, b: Extension, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token, operational=True)
    original = db.get(RentalRecord, rid)
    if not original or original.owner != cid or original.status != "confirmed":
        raise HTTPException(404, "Active reservation required")
    require_open(original)
    terms = original.terms
    if b.end <= date.fromisoformat(terms["end"]):
        raise HTTPException(422, "Extension must increase the end date")
    q = Query(**{**{k: v for k, v in terms.items() if k in Query.model_fields}, "end": b.end})
    revised = quote_terms(db.get(RentalRate, terms["vehicle_id"]), q)
    revised["extends"] = rid
    row = RentalRecord(owner=cid, terms=revised, status="quoted", expires=now() + 900)
    db.add(row)
    db.commit()
    return {"quote": ledger(row)}


class Followup(Strict):
    turn: str
    message: str = Field(min_length=1, max_length=500)


async def interpret(message, snapshot, initial):
    """Plan one customer turn, then hold the plan to the server's invariants.

    The planner (offline grammar or live model) proposes; the server decides:
    business writes need a complete affirmative command, and every hard-constraint
    edit is reconciled against the customer's own words before it can be saved.
    """
    if settings.ai_mode != "deterministic":
        from .rental_planner import plan_followup

        plan, usage = await plan_followup(
            message,
            {**snapshot, "today": business_date().isoformat(), "initial": initial},
        )
    else:
        plan, usage = offline(message, business_date(), initial), None
    if plan.operation in ("quote", "select"):
        command = authorized_reference(message)
        if (command.operation, command.position, command.selected_reference) != (
            plan.operation,
            plan.position,
            plan.selected_reference,
        ):
            raise Unclear("No action taken. Please specify the vehicle and action together.")
    reconciliation = None
    if plan.operation == "edit":
        check_comparators(message, plan)
        reconciliation = reconcile(plan, message, snapshot.get("query") or {}, business_date())
    return plan, usage, reconciliation


def edit_query(reconciliation, previous):
    """Apply a reconciled patch to the saved search and validate the result."""
    changes = reconciliation.patch
    if not changes and not reconciliation.calendar_month:
        raise Unclear("Which rental requirement should change?")
    values = {**previous, **changes}
    if values.get("budget_cents") is not None and not values.get("period"):
        raise Unclear("Is your budget daily, weekly or monthly?")
    if not values.get("location"):
        raise Unclear("Which pickup location? This demo serves Tempe.")
    if reconciliation.calendar_month:
        if not values.get("start"):
            raise Unclear("Please specify the pickup date.")
        values["end"] = month_after(date.fromisoformat(str(values["start"])))
    if not values.get("start") or not values.get("end"):
        raise Unclear("Please give both pickup and return dates.")
    return Query.model_validate(values)


def policy_reply(message, usage):
    from .rag import PolicyIndex

    citations, missing = PolicyIndex().rental_answer(message)
    return {
        "citations": citations,
        "question": message,
        "operation": "policy",
        "usage": usage,
        "unresolved": missing,
        "explanation": "Please ask staff to confirm " + "; ".join(missing) + "."
        if missing
        else None,
    }


@router.post("/sessions/{cid}/rentals/ask")
async def ask(cid: str, b: Followup, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token)
    ctx = db.get(RentalContext, cid)
    if not ctx or ctx.data["turn"] != b.turn:
        raise HTTPException(409, "Refresh rental results before referring to them.")
    snapshot = dict(ctx.data)
    db.rollback()
    try:
        plan, usage, reconciliation = await interpret(b.message, snapshot, False)
        if plan.operation == "policy":
            return policy_reply(b.message, usage)
        locked = db.scalar(
            select(RentalContext).where(RentalContext.owner == cid).with_for_update()
        )
        if not locked or locked.data["turn"] != b.turn:
            raise HTTPException(409, "Results changed. Please review the refreshed list.")
        if plan.operation == "edit":
            q = edit_query(reconciliation, locked.data["query"])
            return {
                **search(cid, q, db, x_session_token),
                "operation": "edit",
                "usage": usage,
                "reconciliation": reconciliation.trace(),
            }
        if plan.operation == "clarify":
            raise Unclear(
                "Please specify the date, budget period, seat count or displayed vehicle you mean."
            )
        position = plan.position
        if plan.selected_reference:
            if not locked.data.get("explicit_selection"):
                raise Unclear("Please select a vehicle from the displayed list first.")
            selected = locked.data.get("selected")
            if snapshot.get("selected") != selected:
                raise HTTPException(409, "Selection changed. Choose the vehicle again.")
            if position is not None or selected not in locked.data["ids"]:
                raise Unclear("Please select a vehicle from the displayed list first.")
            position = locked.data["ids"].index(selected) + 1
        if position is None:
            raise Unclear(
                "Which displayed vehicle do you mean? Give its position or select it first."
            )
        return {
            **reference(
                cid,
                Reference(turn=b.turn, operation=plan.operation, position=position),
                db,
                x_session_token,
            ),
            "operation": plan.operation,
            "usage": usage,
        }
    except (Unclear, ValueError) as exc:
        return {
            "clarification": str(exc)
            if isinstance(exc, Unclear)
            else "Please check the dates and required constraints."
        }


class RentalMessage(Strict):
    message: str = Field(min_length=1, max_length=500)


@router.post("/sessions/{cid}/rental-discovery")
async def discover(cid: str, b: RentalMessage, db: DB, x_session_token: TOKEN = None):
    owned(cid, db, x_session_token)
    db.rollback()
    try:
        plan, usage, reconciliation = await interpret(b.message, {}, True)
        if plan.operation == "policy":
            return policy_reply(b.message, usage)
        if plan.operation != "edit":
            raise Unclear("Please describe the location, dates and required vehicle features.")
        q = edit_query(reconciliation, {})
    except ValueError as exc:
        return {
            "clarification": str(exc)
            if isinstance(exc, Unclear)
            else "Please check pickup and return dates, budget period and minimum seats."
        }
    return {
        **search(cid, q, db, x_session_token),
        "operation": "edit",
        "usage": usage,
        "reconciliation": reconciliation.trace(),
    }
