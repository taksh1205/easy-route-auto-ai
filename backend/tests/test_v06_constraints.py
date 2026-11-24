"""v0.6 release gates: first-message constraint reconciliation and comparator meaning.

Every test drives the public HTTP API, then independently reads the saved session and
checks returned vehicles against the SQL inventory rows.
"""

import json

import httpx
import pytest
from app.db import SessionLocal
from app.models import RentalRate, Vehicle
from app.rental_planner import capture_calls

from .test_v05 import provider
from .test_workflows import session

DATES = dict(start="2031-04-01", end="2031-04-08")


def inject(monkeypatch, *plans):
    """Serve schema-valid planner responses in order through the real provider path."""
    queue = iter(plans)
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
                        arguments=json.dumps(next(queue)),
                    )
                ]
            },
        ),
    )


class Customer:
    def __init__(self, client):
        self.client = client
        cid, self.headers = session(client)
        self.root = f"/sessions/{cid}"
        self.turn = None

    def discover(self, message):
        data = self.client.post(
            self.root + "/rental-discovery", headers=self.headers, json={"message": message}
        ).json()
        self.turn = data.get("turn", self.turn)
        return data

    def ask(self, message):
        data = self.client.post(
            self.root + "/rentals/ask",
            headers=self.headers,
            json={"message": message, "turn": self.turn},
        ).json()
        self.turn = data.get("turn", self.turn)
        return data

    def saved(self):
        """Independent read of persisted session state."""
        ctx = self.client.get(self.root + "/rentals", headers=self.headers).json()["context"]
        return ctx and ctx["query"]


def assert_vehicles_satisfy(vehicles, query):
    """Re-derive each returned vehicle's facts from SQL, not from the API payload."""
    with SessionLocal() as db:
        for shown in vehicles:
            row = db.get(Vehicle, shown["id"])
            rate = db.get(RentalRate, shown["id"])
            assert row.available and rate.active and rate.location == query["location"]
            assert shown["seats"] == row.seats
            if query.get("min_seats"):
                assert row.seats >= query["min_seats"]
            if query.get("body"):
                assert row.body == query["body"]
            if query.get("budget_cents") is not None:
                assert getattr(rate, query["period"]) <= query["budget_cents"]


FIRST = "Please find a seven-seat SUV in Tempe from 2031-04-01 to 2031-04-08 under $950 monthly."
PLAN_NO_SEATS = dict(
    operation="edit",
    location="Tempe",
    body="suv",
    budget_cents=95000,
    period="monthly",
    budget_comparator="maximum",
    **DATES,
)


def test_first_message_omitted_seats_is_restored(client, monkeypatch):
    """The reviewer's reproduction: a schema-valid plan that drops min_seats."""
    inject(
        monkeypatch, PLAN_NO_SEATS, dict(operation="edit", budget_cents=120000, period="monthly")
    )
    customer = Customer(client)
    with capture_calls() as events:
        data = customer.discover(FIRST)
    assert len(events) == 1 and events[0]["validated"]
    assert data["vehicles"] == [] and data["ids"] == []
    expected = dict(
        location="Tempe", body="suv", min_seats=7, budget_cents=94999, period="monthly", **DATES
    )
    assert customer.saved() == expected
    overrides = {o["field"]: o for o in data["reconciliation"]["overrides"]}
    assert overrides["min_seats"]["reason"] == "planner omitted explicit text"

    raised = customer.ask("Raise my budget to $1,200 monthly")
    assert raised["ids"] == [5]
    assert customer.saved() == {**expected, "budget_cents": 120000}
    assert_vehicles_satisfy(raised["vehicles"], customer.saved())


def test_first_message_contradicted_values_use_customer_text(client, monkeypatch):
    plan = {**PLAN_NO_SEATS, "min_seats": 5, "budget_cents": 120000, "body": "sedan"}
    inject(monkeypatch, plan)
    customer = Customer(client)
    data = customer.discover(FIRST)
    assert customer.saved()["min_seats"] == 7
    assert customer.saved()["budget_cents"] == 94999
    assert customer.saved()["body"] == "suv"
    assert data["vehicles"] == []
    reasons = {o["field"] for o in data["reconciliation"]["overrides"]}
    assert {"min_seats", "budget_cents", "body"} <= reasons


def test_valid_plan_control_is_applied_unchanged(client, monkeypatch):
    plan = {**PLAN_NO_SEATS, "min_seats": 7, "budget_cents": 110000}
    inject(monkeypatch, plan)
    customer = Customer(client)
    data = customer.discover(
        "Seven seats, SUV, Tempe, 2031-04-01 to 2031-04-08, at most $1,100 a month"
    )
    assert data["ids"] == [5]
    assert customer.saved() == dict(
        location="Tempe", body="suv", min_seats=7, budget_cents=110000, period="monthly", **DATES
    )
    assert data["reconciliation"]["overrides"] == []
    assert_vehicles_satisfy(data["vehicles"], customer.saved())


@pytest.mark.parametrize(
    "message",
    [
        "SUV in Tempe 2031-04-01 to 2031-04-08 under $950 monthly with seats for six or seven people",
        "Tempe SUV 2031-04-01 to 2031-04-08 for 5 people, actually 7 passengers, under $950 monthly",
    ],
)
def test_ambiguous_quantity_clarifies_without_saving(client, monkeypatch, message):
    inject(monkeypatch, {**PLAN_NO_SEATS, "min_seats": 7})
    customer = Customer(client)
    data = customer.discover(message)
    assert data.get("clarification") and "vehicles" not in data
    assert customer.saved() is None


def test_ungrounded_planner_value_is_never_saved(client, monkeypatch):
    """A model-invented seat count with no supporting text asks instead of filtering."""
    inject(monkeypatch, {**PLAN_NO_SEATS, "min_seats": 8})
    customer = Customer(client)
    data = customer.discover("Tempe SUV from 2031-04-01 to 2031-04-08 under $950 monthly")
    assert data.get("clarification") and customer.saved() is None


def test_free_form_paraphrase_still_plans(client, monkeypatch):
    """Grounding does not require the offline grammar: a paraphrase the grammar cannot parse."""
    inject(monkeypatch, {**PLAN_NO_SEATS, "min_seats": 7, "budget_cents": 110000})
    customer = Customer(client)
    data = customer.discover(
        "We're a family of seven heading to Tempe the first week of April, "
        "an SUV for no more than eleven hundred dollars a month would be ideal"
    )
    assert data["ids"] == [5], data
    assert customer.saved()["min_seats"] == 7 and customer.saved()["budget_cents"] == 110000


@pytest.mark.parametrize("live", [False, True])
def test_more_than_seats_is_an_exact_minimum(client, monkeypatch, live):
    if live:
        inject(monkeypatch, {**PLAN_NO_SEATS, "min_seats": 6, "budget_cents": 120000})
    customer = Customer(client)
    data = customer.discover(
        "Tempe SUV with more than six seats from 2031-04-01 to 2031-04-08 at most $1200 monthly"
    )
    assert customer.saved()["min_seats"] == 7 and data["ids"] == [5]


# --- strict versus inclusive price bounds ---------------------------------------


@pytest.mark.parametrize(
    "rate,under,at_most",
    [
        (87499, [6], [6]),  # one cent below the bound: both include it
        (87500, [], [6]),  # exactly at the bound: only inclusive includes it
        (87501, [], []),  # one cent above: neither
    ],
)
@pytest.mark.parametrize("live", [False, True])
def test_price_boundaries(client, monkeypatch, rate, under, at_most, live):
    with SessionLocal() as db:
        db.get(RentalRate, 6).monthly = rate
        db.commit()
    if live:
        # The model reports the face value; the server applies the comparator.
        inject(monkeypatch, *[{**PLAN_NO_SEATS, "budget_cents": 87500}] * 2)
    for phrase, expected, cap in (("under", under, 87499), ("at most", at_most, 87500)):
        customer = Customer(client)
        data = customer.discover(f"Tempe SUV from 2031-04-01 to 2031-04-08 {phrase} $875 monthly")
        assert data["ids"] == expected, (phrase, rate, data)
        assert customer.saved()["budget_cents"] == cap
        assert_vehicles_satisfy(data["vehicles"], customer.saved())


def test_strict_bound_survives_later_turns(client):
    customer = Customer(client)
    customer.discover("Tempe SUV from 2031-04-01 to 2031-04-08 under $875 monthly")
    assert customer.saved()["budget_cents"] == 87499
    data = customer.ask("Keep my budget and require five seats")
    assert customer.saved()["budget_cents"] == 87499 and data["ids"] == []
    data = customer.ask("Change my budget to at most $875 monthly")
    assert customer.saved()["budget_cents"] == 87500 and data["ids"] == [6]


def test_legacy_inclusive_saved_search_is_unchanged(client):
    """v0.5 saved maximum-budget searches keep their inclusive meaning."""
    cid, headers = session(client)
    query = dict(
        location="Tempe", body="suv", min_seats=None, budget_cents=87500, period="monthly", **DATES
    )
    data = client.post(f"/sessions/{cid}/rentals/search", headers=headers, json=query).json()
    assert data["ids"] == [6]


def test_retained_budget_with_bare_amount_mention(client, monkeypatch):
    customer = Customer(client)
    customer.discover("Tempe SUV from 2031-04-01 to 2031-04-08 at most $950 monthly")
    inject(monkeypatch, dict(operation="edit", budget_cents=120000, period="monthly", min_seats=7))
    data = customer.ask(
        "Keep the same budget, I paid $1,200 monthly last year, and require 7 seats"
    )
    assert customer.saved()["budget_cents"] == 95000 and customer.saved()["min_seats"] == 7
    assert data["ids"] == []


def test_relaxation_metric_ignores_clarified_turns(tmp_path):
    """A clarification that saves nothing is a task failure, never a silent relaxation."""
    import json
    import os
    import subprocess
    import sys

    query = dict(
        location="Tempe", body="suv", min_seats=7, budget_cents=95000, period="monthly", **DATES
    )
    case = [
        {
            "id": "clarified",
            "steps": [
                {
                    "action": "discover",
                    "message": "Something nice, money is no object",
                    "expected": {"saved_query": query},
                }
            ],
        }
    ]
    dataset = tmp_path / "d.json"
    dataset.write_text(json.dumps(case))
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    out = tmp_path / "r.json"
    proc = subprocess.run(
        [sys.executable, "rental_eval.py", "--dataset", str(dataset), "--out", str(out)],
        env=env,
        capture_output=True,
        text=True,
    )
    result = json.loads(out.read_text())
    assert proc.returncode == 1 and result["failed_steps"] == 1
    assert result["safety"]["silent_relaxations"] == 0 and result["gate_failed"]

    # The same task failure does not fail a safety-only gate: nothing unsafe happened.
    proc = subprocess.run(
        [
            sys.executable,
            "rental_eval.py",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
            "--gate",
            "safety",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    result = json.loads(out.read_text())
    assert proc.returncode == 0 and result["failed_steps"] == 1 and not result["gate_failed"]


def test_clarified_edit_is_not_a_silent_relaxation(tmp_path):
    """A clarification keeps the last accepted search; the customer was told, so it is not silent."""
    import json
    import os
    import subprocess
    import sys

    base = dict(
        location="Tempe", body="suv", min_seats=None, budget_cents=95000, period="monthly", **DATES
    )
    case = [
        {
            "id": "clarified-edit",
            "steps": [
                {"action": "search", "query": base, "expected": {"ids": [6, 7]}},
                {
                    "action": "ask",
                    "message": "We would like something roomy for our big family please",
                    "expected": {"saved_query": {**base, "min_seats": 7}},
                },
            ],
        }
    ]
    dataset = tmp_path / "d.json"
    dataset.write_text(json.dumps(case))
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    out = tmp_path / "r.json"
    subprocess.run(
        [
            sys.executable,
            "rental_eval.py",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
            "--gate",
            "safety",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    result = json.loads(out.read_text())
    step = result["scenarios"][0]["steps"][1]
    assert step["actual"]["clarification"] and not step["passed"]
    assert result["safety"]["silent_relaxations"] == 0 and not result["gate_failed"]
