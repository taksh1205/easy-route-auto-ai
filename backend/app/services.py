import hashlib
import json
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import clock
from .config import settings
from .models import Appointment, Idempotency, Vehicle
from .schemas import Booking, Reschedule, Search

BUSINESS_ZONE = ZoneInfo("America/Phoenix")


def vehicle_record(v):
    return {
        "id": v.id,
        "name": v.name,
        "body": v.body,
        "price": v.price,
        "seats": v.seats,
        "features": v.features,
        "mileage": v.mileage,
        "mpg": v.mpg,
        "available": v.available,
    }


def inventory(db, args: Search, limit=50, offset=0):
    stmt = select(Vehicle).where(Vehicle.available.is_(True), Vehicle.seats >= args.min_seats)
    if args.max_price is not None:
        stmt = stmt.where(Vehicle.price <= args.max_price)
    if args.body:
        stmt = stmt.where(Vehicle.body == args.body)
    if args.max_mileage is not None:
        stmt = stmt.where(Vehicle.mileage <= args.max_mileage)
    if args.min_mpg is not None:
        stmt = stmt.where(Vehicle.mpg >= args.min_mpg)
    rows = db.scalars(stmt).all()
    # Scores use fixed domain bounds, not result-set normalization; missing soft data contributes zero.
    semantic = {}
    if settings.semantic_ranking and args.semantic_query and rows:
        from .rag import embed

        q = embed([args.semantic_query])[0]
        texts = [f"{v.body} {v.seats} seats " + " ".join(v.features) for v in rows]
        semantic = {
            v.id: max(0, min(1, float(score)))
            for v, score in zip(rows, embed(texts) @ q, strict=True)
        }
    weights = {
        "features": settings.weight_features,
        "mileage": settings.weight_mileage,
        "mpg": settings.weight_mpg,
        "semantic": settings.weight_semantic,
    }
    if any(v < 0 for v in weights.values()):
        raise HTTPException(503, "Invalid ranking weights")
    active = {
        "features": bool(args.features),
        "mileage": args.low_mileage,
        "mpg": args.fuel_efficient,
        "semantic": bool(semantic),
    }
    denom = sum(w for key, w in weights.items() if active[key]) or 1
    result = []
    for v in rows:
        matches = sorted(set(args.features) & set(v.features))
        components = {
            "features": len(matches) / len(set(args.features)) if args.features else 0,
            "mileage": max(0, 1 - v.mileage / 200000)
            if v.mileage is not None and args.low_mileage
            else 0,
            "mpg": min(1, max(0, (v.mpg - 10) / 50))
            if v.mpg is not None and args.fuel_efficient
            else 0,
            "semantic": semantic.get(v.id, 0),
        }
        score = sum(components[k] * weights[k] for k in weights if active[k]) / denom
        explanation = []
        if args.max_price is not None:
            explanation.append(f"Price ${v.price:,} is within your ${args.max_price:,} limit.")
        if args.low_mileage:
            explanation.append(
                f"Mileage: {v.mileage:,} miles."
                if v.mileage is not None
                else "Mileage unknown; no mileage score awarded."
            )
        if args.fuel_efficient:
            explanation.append(
                f"Fuel efficiency: {v.mpg} mpg."
                if v.mpg is not None
                else "Fuel efficiency unknown; no fuel score awarded."
            )
        if matches:
            explanation.append("Matching features: " + ", ".join(matches) + ".")
        result.append(
            {
                **vehicle_record(v),
                "matched_features": matches,
                "score": round(score, 6),
                "score_components": components,
                "explanations": explanation,
            }
        )
    return sorted(result, key=lambda v: (-v["score"], v["price"], v["id"]))[offset : offset + limit]


def valid_slot(dt):
    utc = dt.astimezone(UTC)
    local = utc.astimezone(BUSINESS_ZONE)
    now = clock.utcnow()
    if utc <= now or utc > now + timedelta(days=30):
        raise HTTPException(422, "Choose a future slot within 30 days")
    if local.minute or local.second or local.microsecond or not 9 <= local.hour <= 16:
        raise HTTPException(422, "Slots start on the hour, 09:00–16:00 America/Phoenix")
    return int(utc.timestamp())


def availability(db, vehicle_id):
    v = db.get(Vehicle, vehicle_id)
    if not v or not v.available:
        raise HTTPException(404, "Vehicle unavailable")
    occupied = set(
        db.scalars(
            select(Appointment.slot).where(
                Appointment.vehicle_id == vehicle_id, Appointment.cancelled.is_(False)
            )
        )
    )
    start = clock.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return [
        int(dt.timestamp())
        for i in range(24 * 7)
        if 9 <= (dt := start + timedelta(hours=i)).astimezone(BUSINESS_ZONE).hour <= 16
        and int(dt.timestamp()) not in occupied
    ]


def appointment_record(a):
    return {"id": a.id, "vehicle_id": a.vehicle_id, "slot": a.slot, "cancelled": a.cancelled}


def lock_vehicle(db, vid):
    v = db.scalar(select(Vehicle).where(Vehicle.id == vid).with_for_update())
    if not v or not v.available:
        raise HTTPException(409, "Vehicle unavailable")
    return v


def book_pending(db, cid, args: Booking):
    slot = valid_slot(args.starts_at)
    lock_vehicle(db, args.vehicle_id)
    a = Appointment(conversation_id=cid, vehicle_id=args.vehicle_id, slot=slot)
    db.add(a)
    db.flush()
    return appointment_record(a)


def cancel_pending(db, cid, aid):
    a = db.scalar(select(Appointment).where(Appointment.id == aid).with_for_update())
    if not a or a.conversation_id != cid:
        raise HTTPException(404, "Appointment not found")
    a.cancelled = True
    db.flush()
    return appointment_record(a)


def reschedule_pending(db, cid, args: Reschedule):
    a = db.scalar(
        select(Appointment).where(Appointment.id == args.appointment_id).with_for_update()
    )
    if not a or a.conversation_id != cid or a.cancelled:
        raise HTTPException(404, "Active appointment not found")
    slot = valid_slot(args.starts_at)
    lock_vehicle(db, args.vehicle_id)
    a.vehicle_id = args.vehicle_id
    a.slot = slot
    db.flush()
    return appointment_record(a)


def payload_digest(kind, payload):
    return hashlib.sha256(
        json.dumps(
            {"kind": kind, "arguments": payload}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def idempotent(db, cid, key, kind, payload, execute):
    if not key or len(key) > 100:
        raise HTTPException(422, "A 1–100 character Idempotency-Key is required")
    digest = payload_digest(kind, payload)
    prior = db.scalar(
        select(Idempotency).where(Idempotency.conversation_id == cid, Idempotency.key == key)
    )
    if prior:
        if prior.payload_hash != digest:
            raise HTTPException(409, "Idempotency key payload mismatch")
        return prior.result
    try:
        # Reserve the key before any business write. Concurrent repeats block at this unique index.
        marker = Idempotency(conversation_id=cid, key=key, payload_hash=digest, result={})
        db.add(marker)
        db.flush()
        result = execute()
        marker.result = result
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        prior = db.scalar(
            select(Idempotency).where(Idempotency.conversation_id == cid, Idempotency.key == key)
        )
        if prior and prior.payload_hash == digest:
            return prior.result
        raise HTTPException(409, "Booking conflict or idempotency payload mismatch") from exc
    except Exception:
        db.rollback()
        raise


def book(db, cid, args: Booking, key):
    return idempotent(
        db, cid, key, "booking", args.model_dump(mode="json"), lambda: book_pending(db, cid, args)
    )
