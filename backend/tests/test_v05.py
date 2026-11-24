"""Exercise ordinary HTTP routes and inspect owned persisted state after each turn."""

import json

import httpx
import pytest
from app.config import settings
from app.rental_planner import capture_calls

from .test_workflows import session

QUERY = dict(
    body="suv",
    start="2031-04-01",
    end="2031-04-08",
    min_seats=None,
    location="Tempe",
    period="monthly",
    budget_cents=95000,
)


def customer(client):
    cid, headers = session(client)
    base = f"/sessions/{cid}/rentals"
    state = client.post(base + "/search", json=QUERY, headers=headers).json()
    assert state["ids"] == [6, 7]

    def ask(message, turn=None):
        r = client.post(
            base + "/ask",
            json={"message": message, "turn": turn or state["turn"]},
            headers=headers,
        )
        if "turn" in r.json():
            state.update(turn=r.json()["turn"])
        return r

    def snapshot():
        restored = client.get(base, headers=headers).json()
        ctx = restored["context"]
        return (
            ctx.get("selected"),
            [(r["terms"]["vehicle_id"], r["status"]) for r in restored["records"]],
            ctx["query"],
            ctx["ids"],
        )

    return ask, snapshot


@pytest.mark.parametrize(
    "message",
    [
        "Don’t quote the first one",
        "Quote the second only after I confirm",
        "Don't select the second option yet",
        "Select the first and quote the second",
        "I might get a quote for the first vehicle later",
        "Maybe choose that car tomorrow",
    ],
)
def test_unintended_action(client, message):
    ask, snapshot = customer(client)
    before = snapshot()
    assert before == (None, [], QUERY, [6, 7])
    assert ask(message).json().get("clarification")
    assert snapshot() == before


def test_explicit_selection_only(client):
    ask, snapshot = customer(client)

    def turn(message, field, selected, records):
        response = ask(message).json()
        assert response.get(field), response
        assert snapshot() == (selected, records, QUERY, [6, 7])

    turn("Compare the first two", "comparison", None, [])
    turn("Quote that vehicle", "clarification", None, [])
    turn("Choose the first car", "selection", 6, [])
    turn("Compare the first two", "comparison", 6, [])
    turn("Does the second one have more seats?", "comparison", 6, [])
    turn("Quote that vehicle", "quote", 6, [(6, "quoted")])


@pytest.mark.parametrize(
    "text,changes,ids,clarify",
    [
        ("I need at least seven seats", {"min_seats": 7}, [], False),
        (
            "Change my budget to at most $900 monthly",
            {"budget_cents": 90000},
            [6],
            False,
        ),
        ("At most $950 monthly", {}, [6, 7], False),
        ("I need at least $950 monthly", {}, [6, 7], True),
        ("Between $800 and $950 monthly", {}, [6, 7], True),
    ],
)
def test_full_constraints(client, text, changes, ids, clarify):
    ask, snapshot = customer(client)
    data = ask(text).json()
    assert bool(data.get("clarification")) == clarify
    assert snapshot() == (None, [], {**QUERY, **changes}, ids)
    if not clarify:
        assert data["ids"] == ids


def provider(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(settings, "ai_mode", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "mock")
    monkeypatch.setattr(settings, "openai_model", "mock")


@pytest.mark.parametrize(
    "message,plan",
    [
        ("Don't quote the first one", dict(operation="quote", position=1)),
        ("Select the second after I agree", dict(operation="select", position=2)),
        ("Quote the first car", dict(operation="quote", position=2)),
        (
            "I need at least $950 monthly",
            dict(
                operation="edit",
                budget_cents=95000,
                period="monthly",
                budget_comparator="maximum",
            ),
        ),
    ],
)
def test_provider_cannot_authorize(client, monkeypatch, message, plan):
    ask, snapshot = customer(client)
    before = snapshot()
    provider(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "output": [
                    dict(
                        type="function_call",
                        name="rental_followup",
                        call_id="mock",
                        arguments=json.dumps(plan),
                    )
                ]
            },
        ),
    )
    with capture_calls() as events:
        assert ask(message).json().get("clarification")
        assert len(events) == 1 and events[0]["validated"]
    assert snapshot() == before


def test_provider_fault_and_preflight(client, monkeypatch):
    ask, snapshot = customer(client)
    before = snapshot()
    provider(monkeypatch, lambda r: httpx.Response(503))
    with capture_calls() as events:
        assert ask("Quote the first car", "stale").status_code == 409
        assert events == []
        assert ask("Quote the first car").status_code == 502
        assert len(events) == 1 and events[0]["error"] == "HTTPStatusError"
        assert not events[0]["completed"] and not events[0]["validated"]
    assert snapshot() == before


def test_v04_selection_requires_reselection(client):
    from app.db import SessionLocal
    from app.models import RentalContext

    cid, h = session(client)
    base = f"/sessions/{cid}/rentals"
    state = client.post(base + "/search", headers=h, json=QUERY).json()
    with SessionLocal() as db:
        ctx = db.get(RentalContext, cid)
        ctx.data = {**ctx.data, "selected": 7}
        db.commit()
    raw = client.post(
        base + "/ask",
        headers=h,
        json={"turn": state["turn"], "message": "Quote that vehicle"},
    ).json()
    assert raw.get("clarification")
    restored = client.get(base, headers=h).json()
    assert restored["records"] == [] and "selected" not in restored["context"]
    assert restored["context"]["turn"] != state["turn"]


@pytest.mark.parametrize(
    "question",
    [
        "Can I pick up the keys at 3 am?",
        "What is the cancellation cost?",
        "When is pickup?",
    ],
)
def test_topical_text_is_insufficient(question):
    from app.rental_evidence import assess

    hits = [
        dict(
            doc_id="rental_pickup",
            text="After staff approval, coordinate a meeting time at the fictional Tempe pickup desk.",
        ),
        dict(
            doc_id="rental_changes",
            text="Staff may cancel a confirmed reservation and release its occupied dates.",
        ),
    ]
    evidence, missing = assess(question, hits)
    assert evidence == [] and missing
