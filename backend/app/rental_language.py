"""Bounded offline rental grammar. Changes are sparse patches to a canonical SQL query."""

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from .schemas import Strict


class Plan(Strict):
    operation: Literal["edit", "compare", "seats", "select", "quote", "policy", "clarify"]
    position: int | None = Field(None, ge=1, le=100)
    selected_reference: bool = False
    start: date | None = None
    end: date | None = None
    calendar_month: bool = False
    location: Literal["Tempe"] | None = None
    body: Literal["suv", "sedan", "truck", "hatchback"] | None = None
    min_seats: int | None = Field(None, ge=1, le=100)
    budget_cents: int | None = Field(None, ge=0)
    period: Literal["daily", "weekly", "monthly"] | None = None

    budget_comparator: Literal["maximum", "minimum", "range"] | None = None

    def patch(self):
        return self.model_dump(
            include={
                "start",
                "end",
                "location",
                "body",
                "min_seats",
                "budget_cents",
                "period",
            },
            exclude_none=True,
        )


class Unclear(ValueError):
    pass


ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
WRITE_COMMAND = re.compile(
    r"(?:(?:please|(?:can|could|would) you(?: please)?) )?"
    r"(?P<verb>select|choose|quote|(?:could|can) i (?:get|have) a quote (?:on|for)) "
    r"(?:(?:the )?(?P<ordinal>first|second|third|fourth|fifth|[1-9][0-9]?(?:st|nd|rd|th))"
    r"(?: (?:one|car|vehicle|option))?|(?P<selected>it|(?:that|this|the selected) (?:one|car|vehicle)))"
    r"(?: please)?[.!?]?",
    re.I,
)


def authorized_reference(message):
    """Only a complete affirmative command binds a language request to a write."""
    match = WRITE_COMMAND.fullmatch(" ".join(message.split()))
    if not match:
        raise Unclear(
            "No action taken. To proceed, say “Select the first car” or “Quote the second car”."
        )
    verb = match["verb"].lower()
    ordinal = (match["ordinal"] or "").lower()
    position = ORDINALS.get(ordinal)
    if ordinal and position is None:
        position = int(ordinal[:-2])
    return Plan(
        operation="select" if verb in ("select", "choose") else "quote",
        position=position,
        selected_reference=bool(match["selected"]),
    )


def check_comparators(message, plan):
    text = message.casefold().replace(",", "")
    # Bind each comparator to the quantity it governs before discarding filler.
    # A minimum-only SQL filter cannot represent upper bounds or exclusive limits.
    seat_quantity = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -]+(?:seats?|seaters?|passengers?|people)\b"
    unsupported_bound = (
        r"(?:under|below|less than|fewer than|at most|maximum(?: of)?|up to|no more than)"
    )
    if re.search(r"\b" + unsupported_bound + r"\s+" + seat_quantity, text) or re.search(
        seat_quantity + r"\s+(?:or (?:less|fewer)|at most|maximum|or below)", text
    ):
        raise Unclear("This search supports a minimum seat count. What minimum should I use?")
    seat_min = re.sub(
        r"\b(?:at least|minimum(?: of)?|more than|over|above|greater than)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -]+(?:seats?|passengers?|people)\b",
        "",
        text,
    )
    seat_min = seat_min.replace("no more than", "at most")
    # A negated upper-price expression is not an unsupported price floor.
    seat_min = re.sub(
        r"\b(?:can'?t|cannot|won't|don't want to|do not want to|shouldn't|not|never)\s+"
        r"(?:go\s+|spend\s+|pay\s+|be\s+)?(?:over|above|more than|beyond|exceed(?:ing)?)"
        r"(?=\s*\$)",
        "",
        seat_min,
    )
    if len(re.findall(r"\$\s*\d", text)) > 1:
        raise Unclear("Please give one maximum budget and its billing period.")
    if plan.budget_comparator in ("minimum", "range") or (
        re.search(r"\$|dollars?|monthly|weekly|daily|budget|price", text)
        and re.search(
            r"\b(at least|minimum|floor|between|more than|at or above|no less than|upwards of|over)\b|\$[\d.]+\s*[-–]\s*\$?\d|\$[\d.]+\s*(?:and up|or more)",
            seat_min,
        )
    ):
        raise Unclear(
            "This search supports a maximum rental budget. What upper limit should I use?"
        )
    if re.search(
        r"(?:at most|no more than|between|fewer than) [^$]{0,20}(?:seats|passengers)",
        text,
    ):
        raise Unclear("This search uses a minimum seat count. How many seats are required?")


def offline(message, today, initial):
    text = message.casefold().replace(",", "")
    # Consume only supported grammar. Unknown modifiers must not weaken hard requirements.
    text = re.sub(
        r"^(?:could|can|would) you (?:please )?(?=(?:find|show|change|switch|lower|raise|select|compare|quote)\b)",
        "",
        text,
    )
    if initial and re.search(r"^when\b.*\b(?:reservation|quote|booking)\b.*expir", text):
        return Plan(operation="policy")
    if initial and re.search(
        r"\b(policy|cancellation|extension|paperwork|procedure|documents?|refund|insurance)\b",
        text,
    ):
        return Plan(operation="policy")
    if not initial:
        if re.search(r"\b(?:quote|quoting|select|choose)\b", text) and not re.match(
            r"(?:what|how|when|where|who|does|is)\b", text
        ):
            return authorized_reference(message)
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
        positions = [
            ordinals[x] for x in re.findall(r"\b(first|second|third|fourth|fifth)\b", text)
        ]
        positions += [int(x) for x in re.findall(r"\b(\d+)(?:st|nd|rd|th)\b", text)]
        for op, pattern in [
            ("seats", r"more seats|seat more"),
            ("compare", r"compare"),
        ]:
            if (
                not re.search(pattern, text)
                or re.search(r"how|policy|procedure|include", text)
                and op == "quote"
            ):
                continue
            if op == "compare" and re.fullmatch(
                r".*compare (?:the )?(?:first|top) (?:two|2)[.?! ]*", text
            ):
                positions = [2]
            if len(positions) > 1 or any(p < 1 or p > 100 for p in positions):
                raise Unclear("Choose one displayed position.")
            selected = bool(re.search(r"\b(that|selected|it|this)\b", text))
            if selected and positions:
                raise Unclear("Give a single position or refer to the selected vehicle.")
            return Plan(
                operation=op,
                position=positions[0] if positions else None,
                selected_reference=selected,
            )
        if re.search(
            r"\b(policy|pickup|cancel\w*|extension|extend|billing|documents?|paperwork|refund|insurance|keys|pets?)\b",
            text,
        ) or re.match(r"(what|who|how|can|does|where|is|are|would|could|will|why|when)\b", text):
            return Plan(operation="policy")
    check_comparators(message, Plan(operation="edit"))
    data = {}

    def take(pattern):
        nonlocal text
        matches = list(re.finditer(pattern, text))
        text = re.sub(pattern, " ", text)
        return matches

    dates = []
    for m in take(r"\b\d{4}-\d{2}-\d{2}\b"):
        dates.append(date.fromisoformat(m[0]))
    months = {name.lower(): i for i, name in enumerate(calendar.month_name) if i}
    for m in take(r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:\s+(20\d{2}))?\b"):
        anchor = dates[-1] if dates else today
        day = date(int(m[3] or anchor.year), months[m[1]], int(m[2]))
        if not m[3] and day < anchor:
            day = day.replace(year=day.year + 1)
        dates.append(day)
    if dates:
        if len(dates) != 2:
            raise Unclear("Please give both pickup and return dates.")
        data.update(start=dates[0], end=dates[1])
    amounts = take(r"\$\s*(\d+(?:\.\d{1,2})?)(?![.\d])")
    units = take(r"\b(daily|weekly|monthly|per day|per week|per month)\b")
    if amounts:
        if len(amounts) != 1 or len(units) != 1:
            raise Unclear("Is your budget daily, weekly or monthly?")
        data.update(
            budget_comparator="maximum",
            budget_cents=int(Decimal(amounts[0][1]) * 100),
            period={
                "per day": "daily",
                "per week": "weekly",
                "per month": "monthly",
            }.get(units[0][0], units[0][0]),
        )
    elif units:
        raise Unclear("Please specify the amount and its billing period.")
    take(
        r"\b(?:more than|over|above|greater than)\b(?= +(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -]+(?:seats?|seaters?|passengers?|people))"
    )
    words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
    seats = take(r"\b(\d+|" + "|".join(words) + r")[ -]+(?:seats?|seaters?|passengers?|people)\b")
    if seats:
        if len(seats) != 1:
            raise Unclear("How many seats do you need?")
        value = seats[0][1]
        data["min_seats"] = int(value) if value.isdigit() else 1 + words.index(value)
    bodies = take(r"\b(suv|sedan|truck|hatchback)s?\b")
    if bodies:
        if len(bodies) != 1:
            raise Unclear("Which single body type should I search for?")
        data["body"] = bodies[0][1]
    if take(r"\btempe\b"):
        data["location"] = "Tempe"
    if take(r"\b(?:a|one|1) (?:calendar )?month\b"):
        data["calendar_month"] = True
    take(
        r"\b(?:i|we|need|want|looking|for|a|an|in|from|through|to|with|under|budget|monthly cap|cap|maximum|at most|no more than|of|at|least|seating|seats|and|rent|rental|please|find|show|me|my|change|the|instead|make|it|keep|same|but|switch|set|only|up|lower|reduce|raise|limit|cost|price|require)\b"
    )
    if text.strip(" .,?!\t\n") or not data:
        raise Unclear(
            "Please specify the required dates, body type, seat count and budget period, or use the search form."
        )
    return Plan(operation="edit", **data)
