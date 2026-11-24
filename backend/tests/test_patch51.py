import json
from pathlib import Path

import httpx
import pytest

from .test_v05 import QUERY, customer, provider


def test_preserve_budget_despite_provider(client, monkeypatch):
    ask, snapshot = customer(client)
    plan = dict(operation="edit", min_seats=7, budget_cents=120000, period="monthly")
    provider(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json={
                "output": [
                    dict(
                        type="function_call",
                        name="rental_followup",
                        call_id="fixture",
                        arguments=json.dumps(plan),
                    )
                ]
            },
        ),
    )
    response = ask("Keep my budget and require seven seats").json()
    saved = {**QUERY, "min_seats": 7}
    assert response["query"] == saved and response["vehicles"] == []
    assert snapshot() == (None, [], saved, [])
    response = ask("Raise my cap to $1,200 monthly").json()
    assert response["ids"] == [5]
    assert snapshot() == (None, [], {**saved, "budget_cents": 120000}, [5])


@pytest.mark.parametrize(
    "message", ["Under seven seats", "Maximum of five seats", "Less than 7 seats"]
)
def test_upper_limit_clarifies(client, message):
    ask, snapshot = customer(client)
    before = snapshot()
    assert ask(message).json().get("clarification")
    assert snapshot() == before


@pytest.mark.parametrize(
    "message,topic,phrase",
    [
        ("When does my quote expire?", "rental_terms", "Quotes expire in fifteen minutes"),
        ("When does my reservation expire?", None, None),
        (
            "What happens if my extension overlaps someone else's booking?",
            "rental_changes",
            "original reservation stays active",
        ),
    ],
)
def test_record_scope(client, monkeypatch, message, topic, phrase):
    from app.rag import PolicyIndex
    from app.rental_evidence import assess

    hits = [
        dict(doc_id=d["id"], text=d["text"])
        for d in json.loads(Path("corpus/synthetic_policies.json").read_text())
    ]
    monkeypatch.setattr(PolicyIndex, "rental_answer", lambda _, question: assess(question, hits))
    ask, snapshot = customer(client)
    before = snapshot()
    answer = ask(message).json()
    assert answer["operation"] == "policy"
    if topic:
        assert any(c["doc_id"] == topic and phrase in c["text"] for c in answer["citations"])
        assert not answer["unresolved"]
    else:
        assert answer["citations"] == [] and answer["unresolved"]
    assert snapshot() == before


def test_price_mention_does_not_raise_saved_budget(client, monkeypatch):
    ask, snapshot = customer(client)
    before = snapshot()
    plan = dict(operation="edit", budget_cents=120000, period="monthly")
    provider(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json={
                "output": [
                    dict(
                        type="function_call",
                        name="rental_followup",
                        call_id="fixture",
                        arguments=json.dumps(plan),
                    )
                ]
            },
        ),
    )
    assert ask("Last year a rental cost me $1,200 monthly.").json().get("clarification")
    assert snapshot() == before


def test_seat_boundaries_with_seven_seater_available(client):
    ask, snapshot = customer(client)
    response = ask("Raise my cap to $1200 monthly").json()
    assert set(response["ids"]) == {5, 6, 7}
    before = snapshot()
    for text in ("Under seven seats", "Maximum of five seats"):
        assert ask(text).json().get("clarification") and snapshot() == before
    for seats, ids in ((7, [5]), (8, [])):
        data = ask(f"At least {seats} seats").json()
        assert data["ids"] == ids
        assert all(v["seats"] >= seats for v in data["vehicles"])
        assert snapshot() == (None, [], {**QUERY, "budget_cents": 120000, "min_seats": seats}, ids)
