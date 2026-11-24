import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Employee
from fastapi.testclient import TestClient

from .test_workflows import session


@pytest.fixture
def employee():
    with SessionLocal() as db:
        db.add(
            Employee(
                name="demo reviewer",
                role="reviewer",
                digest=hashlib.sha256(b"demo-private").hexdigest(),
            )
        )
        db.commit()
    return {"X-Employee-Token": "demo-private"}


def request_quote(c, start="2031-03-01", end="2031-04-01"):
    cid, h = session(c)
    base = "/sessions/" + cid + "/rentals"
    search = c.post(
        base + "/search",
        headers=h,
        json=dict(start=start, end=end, period="monthly", budget_cents=95000, body="suv"),
    ).json()
    assert [v["id"] for v in search["vehicles"]] == [6, 7]
    turn = search["turn"]
    for message in ["Compare the first two", "Does the second one have more seats?"]:
        data = c.post(base + "/ask", headers=h, json=dict(turn=turn, message=message)).json()
        assert [r["id"] for r in data["comparison"]] == [6, 7] and data["seat_difference"] == 0
    q = c.post(
        base + "/ask",
        headers=h,
        json=dict(turn=turn, message="Quote the second vehicle"),
    ).json()["quote"]
    return base, h, q


def submit(c, base, h, q):
    return c.post(
        base + "/" + q["id"] + "/submit",
        headers={**h, "Idempotency-Key": q["id"]},
        json={"terms": q["terms"]},
    )


def decision(c, employee, q, action="approve"):
    return c.post(
        "/rental-staff/" + q["id"] + "/decision",
        headers=employee,
        json={"action": action},
    )


def test_flagship(client, employee):
    base, h, q = request_quote(client)
    assert q["terms"]["total_cents"] == 93500 and q["terms"]["lines"] == [
        dict(unit="monthly", count=1, unit_cents=93500)
    ]
    assert submit(client, base, h, q).json()["status"] == "pending"
    assert decision(client, employee, q).json()["status"] == "confirmed"
    assert client.get(base, headers=h).json()["records"][0]["status"] == "confirmed"
    second, h2, adjacent = request_quote(client, "2031-04-01", "2031-05-01")
    submit(client, second, h2, adjacent)
    assert decision(client, employee, adjacent).status_code == 200
    ext = client.post(
        base + "/" + q["id"] + "/extension", headers=h, json={"end": "2031-04-05"}
    ).json()["quote"]
    submit(client, base, h, ext)
    assert decision(client, employee, ext).status_code == 409
    assert (
        next(r for r in client.get(base, headers=h).json()["records"] if r["id"] == q["id"])[
            "status"
        ]
        == "confirmed"
    )
    decision(client, employee, adjacent, "cancel")
    assert decision(client, employee, ext).json()["status"] == "confirmed"
    client.delete(base.removesuffix("/rentals"), headers=h)
    state = client.get(base, headers=h).json()
    assert state["context"] is None and any(r["status"] == "confirmed" for r in state["records"])
    assert decision(client, employee, ext, "cancel").json()["status"] == "cancelled"


def test_competing(client, employee):
    requests = [request_quote(client) for _ in range(2)]
    for base, h, q in requests:
        assert submit(client, base, h, q).status_code == 200

    def approve(entry):
        with TestClient(app) as c:
            return decision(c, employee, entry[2]).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(approve, requests)) == [200, 409]


def test_budget_and_context(client):
    base, h, q = request_quote(client)
    state = client.get(base, headers=h).json()["context"]
    turn = state["turn"]
    assert (
        "period"
        not in client.post(
            base + "/ask", headers=h, json={"turn": turn, "message": "under $900"}
        ).json()
    )
    for message in [
        "Make it a month instead",
        "Keep the same budget but switch to an SUV",
    ]:
        r = client.post(base + "/ask", headers=h, json=dict(turn=turn, message=message)).json()
        assert (
            r["query"]["period"] == "monthly"
            and r["query"]["budget_cents"] == 95000
            and r["query"]["end"] == "2031-04-01"
        )
        turn = r["turn"]
    assert (
        client.post(
            base + "/reference",
            headers=h,
            json=dict(turn=state["turn"], operation="quote"),
        ).status_code
        == 409
    )
    assert (
        client.post(
            base + "/" + q["id"] + "/submit",
            headers={**h, "Idempotency-Key": "changed"},
            json={"terms": {}},
        ).status_code
        == 409
    )


def test_evaluator_gate(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "bad",
                        "kind": "ranking",
                        "preferences": {},
                        "expected_top": 9999,
                    }
                ]
            }
        )
    )
    env = dict(os.environ, EASY_TASK_DATASET=str(path))
    env.pop("DATABASE_URL", None)
    r = subprocess.run(
        [sys.executable, "evaluate.py", "tasks", "--output", str(tmp_path)],
        env=env,
        capture_output=True,
    )
    assert r.returncode == 1 and json.loads((tmp_path / "tasks.json").read_text())["failed"] == 1


def test_named_dates_and_permissions(client, employee):
    cid, h = session(client)
    url = "/sessions/" + cid + "/rental-discovery"
    msg = "SUV in Tempe for March 1 through April 1 with a $950 monthly budget"
    d = client.post(url, headers=h, json={"message": msg}).json()
    assert d["query"]["start"] == "2031-03-01" and d["query"]["end"] == "2031-04-01"
    assert [r["id"] for r in d["vehicles"]] == [6, 7]
    assert client.patch("/rental-staff/fleet/6?active=false", headers=employee).status_code == 403
    assert client.get("/rental-staff/queue").status_code == 401


def test_expiry_rate_change_and_exact_terms(client, employee, monkeypatch):
    from datetime import timedelta

    from app import clock
    from app.models import RentalRate

    base, h, q = request_quote(client)
    with SessionLocal() as db:
        db.get(RentalRate, 7).monthly = 120000
        db.commit()
    result = submit(client, base, h, q)
    assert result.json()["terms"]["total_cents"] == 93500
    assert decision(client, employee, q).json()["terms"]["total_cents"] == 93500
    from app.rentals import Query, quote_terms

    with SessionLocal() as db:
        rate = db.get(RentalRate, 7)
        partial = quote_terms(rate, Query(start="2031-01-31", end="2031-03-01", period="monthly"))
        assert partial["total_cents"] == 120000 + 4400
        assert (
            quote_terms(rate, Query(start="2031-04-01", end="2031-04-10", period="weekly"))[
                "total_cents"
            ]
            == 24000 + 2 * 4400
        )
        rate.monthly = 93500
        db.commit()
    base, h, q = request_quote(client, "2031-06-01", "2031-07-01")
    instant = clock.utcnow()
    monkeypatch.setattr(clock, "utcnow", lambda: instant + timedelta(minutes=16))
    assert submit(client, base, h, q).status_code == 409


def test_live_rental_planner_contract(client, monkeypatch):
    import httpx
    from app.config import settings

    base, h, q = request_quote(client)
    turn = client.get(base, headers=h).json()["context"]["turn"]
    original = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        assert '"ids": [6, 7]' in payload["input"][0]["content"]
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "name": "rental_followup",
                        "call_id": "x",
                        "arguments": '{"operation":"seats","position":2}',
                    }
                ]
            },
        )

    monkeypatch.setattr(settings, "openai_api_key", "fake")
    monkeypatch.setattr(settings, "ai_mode", "openai")
    monkeypatch.setattr(settings, "openai_model", "mock")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    actual = client.post(
        base + "/ask",
        headers=h,
        json={"turn": turn, "message": "Does number two seat more?"},
    ).json()
    assert actual["comparison"][1]["id"] == 7 and actual["seat_difference"] == 0


def test_eval_index_isolation(tmp_path):
    # Call the actual launcher in a subprocess with an incompatible sentinel directory.
    env = dict(os.environ, RAG_PATH=str(tmp_path / "production"), HF_HUB_OFFLINE="1")
    target = Path(env["RAG_PATH"])
    target.mkdir()
    (target / "CURRENT").write_text("must-stay")
    if os.getenv("EASY_RUN_NEURAL") != "1":
        pytest.skip("Actual neural evaluation enabled in neural suite")
    r = subprocess.run(
        [sys.executable, "evaluate.py", "retrieval", "--output", str(tmp_path / "out")],
        env=env,
        capture_output=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert [f.name for f in target.iterdir()] == ["CURRENT"] and (
        target / "CURRENT"
    ).read_text() == "must-stay"


@pytest.mark.parametrize(
    "instant,accepted",
    [
        ("2031-02-28T20:00:00+00:00", True),
        ("2031-03-12T20:00:00+00:00", True),
        ("2031-04-01T06:59:59+00:00", True),
        ("2031-04-01T07:00:00+00:00", False),
        ("2031-04-02T07:00:00+00:00", False),
    ],
)
def test_extension_business_boundary(client, employee, monkeypatch, instant, accepted):
    from datetime import datetime

    from app import clock
    from app.models import RentalDay
    from sqlalchemy import select

    base, h, q = request_quote(client)
    submit(client, base, h, q)
    assert decision(client, employee, q).status_code == 200
    monkeypatch.setattr(clock, "utcnow", lambda: datetime.fromisoformat(instant))
    result = client.post(base + "/" + q["id"] + "/extension", headers=h, json={"end": "2031-04-05"})
    assert result.status_code == (200 if accepted else 409)
    with SessionLocal() as db:
        days = list(db.scalars(select(RentalDay).where(RentalDay.reservation == q["id"])))
        assert len(days) == 31


def test_wrong_budget_fails_rental_gate(tmp_path):
    dataset = tmp_path / "challenge.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "bad-budget",
                    "steps": [
                        {
                            "action": "search",
                            "query": {
                                "start": "2031-04-01",
                                "end": "2031-04-08",
                                "period": "monthly",
                                "budget_cents": 80000,
                            },
                            "expected": {"query.budget_cents": 95000},
                        }
                    ],
                }
            ]
        )
    )
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    output = tmp_path / "scored.json"
    result = subprocess.run(
        [
            sys.executable,
            "rental_eval.py",
            "--dataset",
            str(dataset),
            "--out",
            str(output),
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 1
    assert json.loads(output.read_text())["failed_steps"] == 1


def test_mock_live_discovery_and_edit(client, monkeypatch):
    import httpx
    from app.config import settings

    plans = iter(
        [
            dict(
                operation="edit",
                location="Tempe",
                body="suv",
                min_seats=7,
                start="2031-04-01",
                end="2031-04-08",
                period="monthly",
                budget_cents=110000,
            ),
            dict(operation="edit", budget_cents=80000, period="monthly"),
        ]
    )
    original = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        schema = payload["tools"][0]["parameters"]
        assert set(schema["properties"]) == set(schema["required"])
        return httpx.Response(
            200,
            json={
                "output": [
                    dict(
                        type="function_call",
                        name="rental_followup",
                        call_id="mock",
                        arguments=json.dumps(next(plans)),
                    )
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    for name, value in [
        ("ai_mode", "openai"),
        ("openai_model", "mock"),
        ("openai_api_key", "mock"),
    ]:
        monkeypatch.setattr(settings, name, value)
    cid, h = session(client)
    root = "/sessions/" + cid
    found = client.post(
        root + "/rental-discovery",
        headers=h,
        json={
            "message": "A seven-seat SUV for the first week of April in Tempe, 1100 dollars per month."
        },
    ).json()
    assert found["ids"] == [5] and found["vehicles"][0]["seats"] == 7
    revised = client.post(
        root + "/rentals/ask",
        headers=h,
        json={
            "message": "Bring the monthly ceiling down to eight hundred.",
            "turn": found["turn"],
        },
    ).json()
    assert (
        revised["query"] == {**found["query"], "budget_cents": 80000} and revised["vehicles"] == []
    )
    assert revised["query"] == client.get(root + "/rentals", headers=h).json()["context"]["query"]


def test_unsupported_requirement_clarifies_before_display(client):
    cid, h = session(client)
    response = client.post(
        "/sessions/" + cid + "/rental-discovery",
        headers=h,
        json={
            "message": "Tempe SUV with wheelchair lift 2031-04-01 to 2031-04-08 under $950 monthly"
        },
    ).json()
    assert "clarification" in response and "vehicles" not in response
    assert client.get("/sessions/" + cid + "/rentals", headers=h).json()["context"] is None
