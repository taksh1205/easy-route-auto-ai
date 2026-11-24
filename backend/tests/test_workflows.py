from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Appointment, Conversation, Lead, Message, Vehicle, now
from app.preferences import deterministic_extract
from fastapi.testclient import TestClient
from sqlalchemy import select, update


def session(c):
    s = c.post("/sessions").json()
    return s["id"], {"X-Session-Token": s["token"]}


def key(h, value="test-key"):
    return {**h, "Idempotency-Key": value}


def slot(c, vid=1, n=0):
    return datetime.fromtimestamp(c.get("/availability/" + str(vid)).json()[n], UTC).isoformat()


def booking(c, cid, h, vid=1, k="book", dt=None):
    return c.post(
        f"/sessions/{cid}/appointments",
        headers=key(h, k),
        json={"vehicle_id": vid, "starts_at": dt or slot(c, vid)},
    )


def chat(c, cid, h, text, **kw):
    return c.post(f"/sessions/{cid}/chat", headers=h, json={"message": text, **kw})


def test_health_inventory(client):
    from app import __version__

    assert client.get("/health").json()["version"] == __version__ == "0.6.0"
    rows = client.get("/inventory?max_price=20000&body=suv").json()
    assert {r["id"] for r in rows} == {6, 7, 12}
    assert client.get("/inventory?body=invalid").status_code == 422
    assert client.get("/inventory?limit=101").status_code == 422


@pytest.mark.parametrize("budget", [0, 18000, 18500, 24000, 100000])
def test_hard_constraints(client, budget):
    rows = client.get("/inventory", params={"max_price": budget, "min_seats": 5}).json()
    assert all(v["price"] <= budget and v["seats"] >= 5 and v["available"] for v in rows)
    assert 11 not in {v["id"] for v in rows}


def test_rank_changes(client):
    plain = client.get("/inventory?body=sedan").json()
    fuel = client.get("/inventory?body=sedan&fuel_efficient=true").json()
    mileage = client.get("/inventory?body=sedan&low_mileage=true").json()
    assert plain[0]["id"] == 1 and fuel[0]["id"] == 10 and mileage[0]["id"] == 9
    assert "52 mpg" in " ".join(fuel[0]["explanations"])
    assert client.get("/inventory?body=suv&min_seats=7&max_price=20000").json() == []


def test_live_sql_updates(client):
    with SessionLocal() as db:
        v = db.get(Vehicle, 1)
        v.price = 9999
        db.get(Vehicle, 2).available = False
        db.commit()
    rows = client.get("/inventory").json()
    assert next(v for v in rows if v["id"] == 1)["price"] == 9999
    assert 2 not in {v["id"] for v in rows}


def test_preference_sequence(client):
    cid, h = session(client)
    for text, expected in [
        ("SUV under $20,000", {"body": "suv", "max_price": 20000}),
        ("Increase budget to $26,000", {"max_price": 26000, "body": "suv"}),
        ("Switch to sedan", {"body": "sedan", "max_price": 26000}),
        ("Remove my budget limit", {"max_price": None, "body": "sedan"}),
        ("Seven seats", {"min_seats": 7}),
        ("five seats is enough", {"min_seats": 5}),
        ("Low mileage and high fuel efficiency", {"low_mileage": True, "fuel_efficient": True}),
    ]:
        r = chat(client, cid, h, text)
        assert r.status_code == 200, r.text
        assert all(r.json()["preferences"][k] == v for k, v in expected.items()), r.json()
    assert client.get(f"/sessions/{cid}", headers=h).json()["version"] == 7


@pytest.mark.parametrize(
    "text,expected",
    [
        ("not an SUV, show sedans", {"body": "sedan"}),
        ("under 20.5k", {"max_price": 20500}),
        ("remove my budget limit", {"max_price": None}),
    ],
)
def test_fixed_grammar(text, expected):
    actual = deterministic_extract(text, {"max_price": 20000, "body": "suv"}).model_dump()
    assert all(actual[k] == v for k, v in expected.items())


@pytest.mark.parametrize(
    "text", ["SUV or sedan", "under 20000 or under 30000", "five seats or seven seats"]
)
def test_ambiguous(client, text):
    cid, h = session(client)
    r = chat(client, cid, h, text).json()
    assert r["intent"] == "clarify" and r["preferences"]["max_price"] is None


def test_ownership_version_and_isolation(client):
    cid, h = session(client)
    cid2, h2 = session(client)
    assert client.get(f"/sessions/{cid}", headers=h2).status_code == 404
    chat(client, cid, h, "under 20k")
    assert client.get(f"/sessions/{cid2}", headers=h2).json()["preferences"] == {}
    assert chat(client, cid, h, "SUV", expected_version=0).status_code == 409


def test_concurrent_turns(client):
    cid, h = session(client)

    def submit(text):
        with TestClient(app) as c:
            return chat(c, cid, h, text, expected_version=0).status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, ["under 20k", "7 seats"]))
    assert sorted(results) == [200, 409]


def test_booking_idempotency_conflict(client):
    cid, h = session(client)
    other, oh = session(client)
    dt = slot(client)
    a = booking(client, cid, h, dt=dt)
    assert a.status_code == 201
    assert booking(client, cid, h, dt=dt).json() == a.json()
    assert booking(client, cid, h, vid=2, dt=dt).status_code == 409
    assert booking(client, other, oh, dt=dt).status_code == 409
    assert (
        client.post(
            f"/sessions/{cid}/appointments", headers=h, json={"vehicle_id": 1, "starts_at": dt}
        ).status_code
        == 422
    )


def test_concurrent_booking(client):
    pairs = [session(client), session(client)]
    dt = slot(client)

    def submit(pair):
        cid, h = pair
        with TestClient(app) as c:
            return booking(c, cid, h, dt=dt).status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, pairs))
    assert sorted(results) == [201, 409]


def test_atomic_reschedule(client):
    cid, h = session(client)
    other, oh = session(client)
    dt1 = slot(client)
    dt2 = slot(client, n=1)
    first = booking(client, cid, h, dt=dt1).json()
    booking(client, other, oh, dt=dt2)
    body = {"appointment_id": first["id"], "vehicle_id": 1, "starts_at": dt2}
    assert (
        client.post(f"/sessions/{cid}/reschedule", headers=key(h, "move"), json=body).status_code
        == 409
    )
    assert client.get(f"/sessions/{cid}/appointments", headers=h).json()[0]["slot"] == first["slot"]
    body["starts_at"] = slot(client, n=2)
    assert (
        client.post(f"/sessions/{cid}/reschedule", headers=key(h, "move2"), json=body).status_code
        == 200
    )


def test_delete_and_expiry_preserve_booking(client):
    cid, h = session(client)
    a = booking(client, cid, h).json()
    chat(client, cid, h, "under 20k")
    client.post(
        f"/sessions/{cid}/leads",
        headers=key(h, "lead"),
        json={"name": "Synthetic Test", "email": "a@example.com", "consent": True},
    )
    assert client.delete(f"/sessions/{cid}", headers=h).status_code == 204
    assert client.get(f"/sessions/{cid}/appointments", headers=h).json()[0]["id"] == a["id"]
    with SessionLocal() as db:
        assert db.scalar(select(Message)) is None and db.scalar(select(Lead)) is None
        db.execute(
            update(Conversation).where(Conversation.id == cid).values(updated_at=now() - 31 * 86400)
        )
        db.commit()
    assert client.get(f"/sessions/{cid}", headers=h).status_code == 410
    assert client.delete(
        "/staff/expired", headers={"Authorization": "Bearer test-only-local-secret"}
    ).json()["appointments_preserved"]
    assert (
        client.delete(
            f"/sessions/{cid}/appointments/{a['id']}", headers=key(h, "cancel")
        ).status_code
        == 204
    )


@pytest.mark.parametrize("delta", [timedelta(days=-1), timedelta(days=40), timedelta(minutes=30)])
def test_clock_controlled_bad_slots(client, delta):
    from app import clock

    cid, h = session(client)
    dt = clock.utcnow() + delta
    assert booking(client, cid, h, dt=dt.isoformat()).status_code == 422


def test_staff_and_request_limits(client, monkeypatch):
    assert client.get("/staff/overview").status_code == 401
    assert (
        client.get(
            "/staff/overview", headers={"Authorization": "Bearer test-only-local-secret"}
        ).status_code
        == 200
    )
    assert client.post("/sessions", content=b"x" * 320001).status_code == 413
    monkeypatch.setattr(settings, "request_limit_per_minute", 1)
    assert client.get("/health").status_code == 429


def proposal(client, cid, h, kind, args):
    return client.post(
        f"/sessions/{cid}/proposals", headers=h, json={"kind": kind, "arguments": args}
    )


def confirm(client, cid, h, p, k="confirm", **changes):
    return client.post(
        f"/sessions/{cid}/proposals/{p['id']}/confirm",
        headers=key(h, k),
        json={"kind": p["kind"], "arguments": p["arguments"], **changes},
    )


def test_proposal_exact_confirmation(client):
    cid, h = session(client)
    other, oh = session(client)
    p = proposal(client, cid, h, "booking", {"vehicle_id": 1, "starts_at": slot(client)}).json()
    assert confirm(client, other, oh, p).status_code == 404
    assert (
        confirm(client, cid, h, p, arguments={**p["arguments"], "vehicle_id": 2}).status_code == 409
    )
    r = confirm(client, cid, h, p)
    assert r.status_code == 200 and r.json()["committed"] is True and r.json()["record_id"]
    assert confirm(client, cid, h, p).json() == r.json()
    assert confirm(client, cid, h, p, k="replay").status_code == 409


def test_proposal_expired_and_failed_transaction(client, monkeypatch):
    from app import clock

    cid, h = session(client)
    other, oh = session(client)
    dt = slot(client)
    p = proposal(client, cid, h, "booking", {"vehicle_id": 1, "starts_at": dt}).json()
    booking(client, other, oh, dt=dt)
    r = confirm(client, cid, h, p)
    assert r.status_code == 409 and "committed" not in r.json()
    instant = clock.utcnow()
    monkeypatch.setattr(clock, "utcnow", lambda: instant + timedelta(minutes=6))
    assert confirm(client, cid, h, p, k="expired").status_code == 410


def test_greeting_generic_yes_no_writes(client):
    cid, h = session(client)
    r = chat(client, cid, h, "hello").json()
    assert r["vehicles"] == [] and r["trace"]["tools"] == []
    assert chat(client, cid, h, "yes").json()["actions"] == []
    with SessionLocal() as db:
        assert db.scalar(select(Appointment)) is None


def test_db_cannot_cascade_delete_active_bookings(client):
    from sqlalchemy.exc import IntegrityError

    cid, h = session(client)
    booking(client, cid, h)
    with SessionLocal() as db:
        db.delete(db.get(Conversation, cid))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert len(client.get(f"/sessions/{cid}/appointments", headers=h).json()) == 1
