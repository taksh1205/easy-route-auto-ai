"""Canonical typed edits. Live plans never use the deterministic grammar as authority."""

import re
from decimal import Decimal

from .schemas import PreferenceOp, Search, TurnPlan

DEFAULTS = Search().model_dump()


def resolve(previous, operations):
    data = Search.model_validate(previous).model_dump()
    seen = set()
    for op in operations:
        if op.field in seen:
            raise ValueError("contradictory duplicate updates")
        seen.add(op.field)
        if op.op == "set":
            data[op.field] = op.value
        elif op.op == "clear":
            data[op.field] = DEFAULTS[op.field]
    return Search.model_validate(data)


def relaxation(old, new):
    a, b = Search.model_validate(old), Search.model_validate(new)
    return (
        (a.max_price is not None and (b.max_price is None or b.max_price > a.max_price))
        or (a.body is not None and b.body != a.body)
        or b.min_seats < a.min_seats
        or (a.max_mileage is not None and (b.max_mileage is None or b.max_mileage > a.max_mileage))
        or (a.min_mpg is not None and (b.min_mpg is None or b.min_mpg < a.min_mpg))
    )


def deterministic_plan(message):
    """Finite offline grammar. Ambiguous or unsupported input asks a fixed clarification."""
    text = message.lower().strip()
    ops = []

    def add(field, value, op="set"):
        ops.append(
            PreferenceOp(field=field, op=op, value=value if op == "set" else None, evidence=message)
        )

    if text in {"hi", "hello", "hey", "good morning", "thanks", "thank you"}:
        return TurnPlan(intent="greeting")
    # Negated body mentions are excluded before choosing a replacement.
    bodies = []
    for m in re.finditer(r"\b(suvs?|sedans?|hatchbacks?|trucks?)\b", text):
        if re.search(
            r"(?:not|no|except|exclude)\s+(?:an?\s+)?$", text[max(0, m.start() - 15) : m.start()]
        ):
            continue
        bodies.append(m[1].removesuffix("s"))
    if len(set(bodies)) > 1:
        return TurnPlan(intent="clarify", clarification="body")
    if bodies:
        add("body", bodies[0])
    if re.search(r"(?:remove|clear|no) (?:my |the )?(?:budget|price)(?: limit)?", text):
        add("max_price", None, "clear")
    else:
        numbers = list(
            re.finditer(
                r"(?:under|below|max(?:imum)?|budget(?: of| to)?|increase budget to|decrease budget to)\s*\$?([\d,]+(?:\.\d+)?)\s*(k)?",
                text,
            )
        )
        if len(numbers) > 1:
            return TurnPlan(intent="clarify", clarification="budget")
        if numbers:
            m = numbers[0]
            value = Decimal(m[1].replace(",", "")) * (1000 if m[2] else 1)
            if value != value.to_integral_value():
                return TurnPlan(intent="clarify", clarification="budget")
            add("max_price", int(value))
    seats = re.findall(r"(\d+|seven|five)\s*seats?", text)
    if len(set(seats)) > 1:
        return TurnPlan(intent="clarify", clarification="seats")
    if seats:
        add(
            "min_seats",
            {"seven": 7, "five": 5}.get(seats[0], int(seats[0]) if seats[0].isdigit() else 1),
        )
    if "low mileage" in text:
        add("low_mileage", True)
    if any(s in text for s in ["fuel efficien", "fuel-efficien", "good mpg", "save gas"]):
        add("fuel_efficient", True)
    if ops:
        return TurnPlan(intent="inventory", updates=ops)
    if any(
        s in text
        for s in [
            "policy",
            "warranty",
            "warranties",
            "test drive",
            "trade-in",
            "financing",
            "appointment procedure",
            "documents",
            "dealership hours",
        ]
    ):
        return TurnPlan(
            intent="policy", tools=[{"name": "retrieve_policy", "arguments": {"query": message}}]
        )
    if text in {"show more", "show cars", "inventory", "recommend vehicles", "show vehicles"}:
        return TurnPlan(intent="inventory")
    return TurnPlan(intent="clarify", clarification="question")


def deterministic_extract(message, previous):
    return resolve(previous, deterministic_plan(message).updates)
