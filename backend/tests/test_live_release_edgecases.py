"""Targeted regressions for release-v06 live-model edge cases.

These tests use a mocked provider response; they do not claim a live-model
pass. Re-run the frozen release suite with real credentials before merging.
"""

from .test_v06_constraints import Customer, DATES, inject


def test_negated_ceiling_not_misread_as_price_floor(client, monkeypatch):
    inject(
        monkeypatch,
        dict(
            operation="edit",
            location="Tempe",
            body="suv",
            min_seats=7,
            budget_cents=95000,
            period="monthly",
            budget_comparator="maximum",
            **DATES,
        ),
    )
    customer = Customer(client)
    result = customer.discover(
        "Looking for an SUV that seats 7 in Tempe from 2031-04-01 "
        "to 2031-04-08; I can't go over $950 a month."
    )
    assert result.get("ids") == []
    assert customer.saved()["budget_cents"] == 95000
    assert customer.saved()["min_seats"] == 7


def test_explicit_out_of_range_ordinal_returns_conflict_before_model(client, monkeypatch):
    customer = Customer(client)
    result = customer.discover(
        "Tempe SUV from 2031-04-01 to 2031-04-08 at most $950 monthly"
    )
    assert result["ids"] == [6, 7]
    customer.ask("Quote the third car.")
    response = client.post(
        customer.root + "/rentals/ask",
        headers=customer.headers,
        json={"turn": customer.turn, "message": "Quote the third car."},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Choose a valid position from the current results."
