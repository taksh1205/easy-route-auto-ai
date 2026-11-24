"""Typed registry; all tools reuse SQL services or the versioned policy index."""

from fastapi import HTTPException
from sqlalchemy import select

from .models import ActionProposal, Appointment, Conversation, Lead, Vehicle, now
from .preferences import resolve
from .rag import PolicyIndex, RAGError
from .schemas import (
    Booking,
    Cancel,
    Compare,
    LeadInput,
    PolicyQuery,
    PreferenceUpdate,
    Reschedule,
    Search,
    VehicleID,
)
from .services import (
    availability,
    book_pending,
    cancel_pending,
    inventory,
    reschedule_pending,
    vehicle_record,
)

REGISTRY = {
    "search_inventory": Search,
    "retrieve_policy": PolicyQuery,
    "compare_vehicles": Compare,
    "appointment_availability": VehicleID,
    "lead_proposal": LeadInput,
    "booking_proposal": Booking,
    "cancellation_proposal": Cancel,
    "reschedule_proposal": Reschedule,
}


def proposal(db, cid, kind, args):
    row = ActionProposal(conversation_id=cid, kind=kind, arguments=args, expires_at=now() + 300)
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "kind": row.kind,
        "arguments": row.arguments,
        "expires_at": row.expires_at,
        "status": "proposed",
    }


def execute_read(db, cid, call, canonical, message):
    args = REGISTRY[call.name].model_validate(call.arguments)
    if call.name == "search_inventory":
        # Plan cannot override canonical constraints through a second tool argument route.
        return inventory(db, Search.model_validate(canonical))
    if call.name == "retrieve_policy":
        # Ignore model query rewrites. Preserve original question and explicit topic filter.
        try:
            return PolicyIndex().answer(message, args.topic)
        except RAGError as exc:
            raise HTTPException(503, str(exc)) from exc
    if call.name == "compare_vehicles":
        rows = db.scalars(
            select(Vehicle).where(Vehicle.id.in_(args.ids), Vehicle.available.is_(True))
        ).all()
        if len({v.id for v in rows}) != len(set(args.ids)):
            raise HTTPException(404, "Comparison vehicle unavailable")
        return [vehicle_record(v) for v in sorted(rows, key=lambda v: args.ids.index(v.id))]
    if call.name == "appointment_availability":
        return availability(db, args.vehicle_id)
    kind = {
        "lead_proposal": "lead",
        "booking_proposal": "booking",
        "cancellation_proposal": "cancellation",
        "reschedule_proposal": "reschedule",
    }[call.name]
    if kind in {"cancellation", "reschedule"}:
        a = db.get(Appointment, args.appointment_id)
        if not a or a.conversation_id != cid:
            raise HTTPException(404, "Appointment not found")
    return proposal(db, cid, kind, args.model_dump(mode="json"))


def commit_action(db, cid, kind, args):
    if kind == "booking":
        data = book_pending(db, cid, Booking.model_validate(args))
    elif kind == "cancellation":
        data = cancel_pending(db, cid, Cancel.model_validate(args).appointment_id)
    elif kind == "reschedule":
        data = reschedule_pending(db, cid, Reschedule.model_validate(args))
    elif kind == "lead":
        data_in = LeadInput.model_validate(args)
        row = Lead(conversation_id=cid, name=data_in.name, email=data_in.email)
        db.add(row)
        db.flush()
        data = {"id": row.id, "status": row.status}
    elif kind == "preferences":
        update = PreferenceUpdate.model_validate(args)
        c = db.get(Conversation, cid)
        from sqlalchemy import update as sql_update

        updated = resolve(c.preferences, update.operations).model_dump()
        count = db.execute(
            sql_update(Conversation)
            .where(Conversation.id == cid, Conversation.version == update.expected_version)
            .values(preferences=updated, version=update.expected_version + 1, updated_at=now())
        ).rowcount
        if count != 1:
            raise HTTPException(409, "Preferences changed; review a new proposal")
        data = {"id": cid, "preferences": updated, "version": update.expected_version + 1}
    else:
        raise HTTPException(422, "Unknown action")
    return {"kind": kind, "record_id": data["id"], "committed": True, "data": data}
