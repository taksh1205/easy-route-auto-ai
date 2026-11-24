"""Server-side constraint reconciliation between a customer's words and a typed plan.

Every rental plan, whether it comes from the offline grammar or from a live LLM, passes
through :func:`reconcile` before it can touch the saved search. The function enforces
three invariants that the planner alone cannot guarantee:

1. **Explicit evidence wins.** When the current message states a hard constraint
   (seat minimum, price bound, billing period, body type, dates), that value is
   applied even if the planner omitted or contradicted it.
2. **Every proposed value is grounded.** A planner value for a hard constraint must be
   attributable to the current message (or to the saved search it leaves unchanged).
   Ungrounded values are never saved; the customer is asked to clarify.
3. **Comparators keep their meaning.** Prices are integer cents, so a strict bound
   ``price < X`` is canonicalised to the exact inclusive bound ``price <= X - 1 cent``.
   Unsupported bounds (price floors, seat ceilings) trigger clarification instead of
   being silently converted into the opposite filter.

The extractor is intentionally *lenient* (it finds evidence anywhere in a sentence),
while :mod:`app.rental_language` is a *strict* grammar that must consume the whole
message. Leniency is safe here because evidence can only add or confirm constraints;
it never authorizes a business write.
"""

from __future__ import annotations

import calendar
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from .rental_language import Plan, Unclear

HARD_FIELDS = ("start", "end", "location", "body", "min_seats", "budget_cents", "period")

_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORD_VALUES = {w: i for i, w in enumerate(_UNITS)} | {w: 20 + 10 * i for i, w in enumerate(_TENS)}
_WORD = r"(?:" + "|".join(sorted(_WORD_VALUES, key=len, reverse=True)) + r")"
_NUMBER = r"(?:\d[\d,]*(?:\.\d{1,2})?|" + _WORD + r"(?:[ -]" + _WORD + r")?)"

_PERIODS = {
    "daily": "daily",
    "per day": "daily",
    "a day": "daily",
    "/day": "daily",
    "each day": "daily",
    "weekly": "weekly",
    "per week": "weekly",
    "a week": "weekly",
    "/week": "weekly",
    "/wk": "weekly",
    "monthly": "monthly",
    "per month": "monthly",
    "a month": "monthly",
    "/month": "monthly",
    "/mo": "monthly",
    "each month": "monthly",
    "every month": "monthly",
}
_PERIOD = r"(?:" + "|".join(re.escape(p) for p in sorted(_PERIODS, key=len, reverse=True)) + r")"

_STRICT = r"(?:under|below|(?<!no )(?<!not )less than|cheaper than|lower than|beneath)"
_INCLUSIVE = (
    r"(?:at most|up to|no more than|not more than|maximum(?: of)?|max(?: of)?|within|"
    r"budget(?: is| of)?|cap(?: is| of| at)?|ceiling(?: is| of)?|limit(?: is| of)?|"
    r"to|down to|afford|spend)"
)
_FLOOR = r"(?:at least|minimum(?: of)?|min(?: of)?|(?<!no )(?<!not )more than|over|above|no less than|upwards of|starting at|from)"
# "can't go over $X" / "not above $X" / "no higher than $X" are ceilings, not floors.
_NEGATED_FLOOR = (
    r"(?:(?:can'?t|cannot|won'?t|don'?t want to|do not want to|not|never|shouldn'?t)\s+"
    r"(?:go |spend |pay |be )?(?:over|above|more than|beyond|exceed(?:ing)?)|no (?:higher|more) than|not exceeding)"
)
_NARRATIVE = (
    r"\b(?:cost me|costs? us|paid|spent|used to|last (?:year|time|month)|previously|was|were)\b"
)

_BODIES = {
    "suv": "suv",
    "suvs": "suv",
    "crossover": "suv",
    "crossovers": "suv",
    "sedan": "sedan",
    "sedans": "sedan",
    "truck": "truck",
    "trucks": "truck",
    "pickup truck": "truck",
    "hatchback": "hatchback",
    "hatchbacks": "hatchback",
}
_BODY = r"\b(" + "|".join(sorted(_BODIES, key=len, reverse=True)) + r")\b"
_NEGATION = r"(?:not|no|never|except|instead of|other than|rather than|without|n't want|don't want)"

_SEAT_NOUN = r"(?:seats?|seaters?|passengers?|people|persons?|riders?)"
_RETAIN_VERB = (
    r"(?:keep|retain|preserve|same|unchanged|leave|don'?t change|do not change|stick with)"
)
_RETAIN_TARGETS = {
    "budget": r"(?:budget|cap|ceiling|limit|price|max(?:imum)?)",
    "seats": r"(?:seats?|seat count|seating)",
    "body": r"(?:body|type|kind of car|vehicle type)",
    "dates": r"(?:dates?|pickup|return|trip|days)",
}
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if i}
_MONTHS |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if i}


def number_value(token: str) -> Decimal | None:
    """Parse digits (with commas/decimals) or English words up to ninety-nine."""
    token = token.strip().replace(",", "")
    if not token:
        return None
    try:
        return Decimal(token)
    except InvalidOperation:
        pass
    total = 0
    for word in re.split(r"[ -]+", token):
        if word not in _WORD_VALUES:
            return None
        total += _WORD_VALUES[word]
    return Decimal(total)


@dataclass(frozen=True)
class Amount:
    cents: int
    comparator: str  # "strict" | "inclusive" | "floor" | "bare"
    period: str | None
    narrative: bool
    span: tuple[int, int]

    @property
    def ceiling_cents(self) -> int:
        """Canonical inclusive ceiling. Exact because currency is discrete."""
        return self.cents - 1 if self.comparator == "strict" else self.cents


@dataclass
class Evidence:
    """Constraints the customer's message states explicitly, with no model involved."""

    text: str
    amounts: list[Amount] = field(default_factory=list)
    periods: set[str] = field(default_factory=set)
    seat_minimum: int | None = None
    seat_ceiling: bool = False
    seat_conflict: bool = False
    bodies: set[str] = field(default_factory=set)
    negated_bodies: set[str] = field(default_factory=set)
    dates: list[date] = field(default_factory=list)
    temporal: bool = False
    trip_month: bool = False
    location: str | None = None
    retained: set[str] = field(default_factory=set)
    numbers: set[Decimal] = field(default_factory=set)

    @property
    def budget_amounts(self) -> list[Amount]:
        return [a for a in self.amounts if not a.narrative and a.comparator != "floor"]


def _preceding(text: str, start: int, width: int = 32) -> str:
    return text[max(0, start - width) : start]


def extract(message: str, today: date) -> Evidence:
    """Collect explicit constraint evidence from one customer message."""
    text = " ".join(message.casefold().replace("’", "'").split())
    ev = Evidence(text=text)

    ev.periods = {_PERIODS[p] for p in re.findall(_PERIOD, text)}

    # ---- money -------------------------------------------------------------
    money_patterns = [
        r"\$\s*(?P<n>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<k>k\b)?",
        r"(?<![-\d])\b(?P<n>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<k>k\b)?\s*(?:dollars?|usd|bucks)\b",
        r"(?<![-\d])\b(?P<n>\d[\d,]*(?:\.\d{1,2})?)\s*(?=" + _PERIOD + r")",
        r"\b(?P<w>"
        + _WORD
        + r"(?:[ -]"
        + _WORD
        + r")?) (?P<scale>hundred|thousand)(?: dollars?)?\b",
    ]
    taken: list[tuple[int, int]] = []
    for pattern in money_patterns:
        for m in re.finditer(pattern, text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if m.groupdict().get("w"):
                base = number_value(m["w"])
                if base is None:
                    continue
                value = base * (100 if m["scale"] == "hundred" else 1000)
            else:
                value = number_value(m["n"])
                if value is None:
                    continue
                if m.groupdict().get("k"):
                    value *= 1000
            # A bare number followed by a seat noun is a seat count, not money.
            if re.match(r"\s*[- ]?" + _SEAT_NOUN, text[m.end() :]):
                continue
            taken.append((m.start(), m.end()))
            before = _preceding(text, m.start())
            after = text[m.end() : m.end() + 24]
            if re.search(_NEGATED_FLOOR + r"\s*$", before):
                comparator = "inclusive"
            elif re.search(_STRICT + r"\s*$", before):
                comparator = "strict"
            elif re.search(_FLOOR + r"\s*$", before) or re.match(
                r"\s*(?:\+|or more|and up|plus)\b", after
            ):
                comparator = "floor"
            elif re.search(_INCLUSIVE + r"\s*$", before) or re.match(
                r"\s*(?:or less|max|tops)\b", after
            ):
                comparator = "inclusive"
            else:
                comparator = "bare"
            unit = re.match(r"\s*(" + _PERIOD + r")", after)
            clause_start = max(text.rfind(".", 0, m.start()), text.rfind(";", 0, m.start()), 0)
            clause = text[clause_start : m.end() + 24]
            ev.amounts.append(
                Amount(
                    cents=int(value * 100),
                    comparator=comparator,
                    period=_PERIODS[unit[1]] if unit else None,
                    narrative=bool(re.search(_NARRATIVE, clause)),
                    span=(m.start(), m.end()),
                )
            )
    if re.search(r"\$\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|to|and)\s*\$?\s*\d", text) or re.search(
        r"\bbetween\b[^.]{0,20}\$", text
    ):
        ev.amounts.append(Amount(0, "floor", None, False, (0, 0)))

    # ---- seats -------------------------------------------------------------
    seat_minima: set[int] = set()
    for m in re.finditer(
        r"\b("
        + _NUMBER
        + r")[ -]*"
        + _SEAT_NOUN
        + r"\b|\b(?:seats?|seating|room) for ("
        + _NUMBER
        + r")\b|\bfamily of ("
        + _NUMBER
        + r")\b",
        text,
    ):
        value = number_value(m[1] or m[2] or m[3])
        if value is None or value != value.to_integral_value() or not 1 <= value <= 100:
            continue
        n = int(value)
        before = _preceding(text, m.start(), 24)
        after = text[m.end() : m.end() + 16]
        if re.search(
            r"(?:under|below|less than|fewer than|at most|maximum(?: of)?|max|up to|no more than|not more than)\s*$",
            before,
        ) or re.match(r"\s*(?:or (?:less|fewer)|at most|max(?:imum)?|or below)\b", after):
            ev.seat_ceiling = True
        elif re.search(r"(?:more than|over|above|greater than)\s*$", before):
            seat_minima.add(n + 1)
        else:
            seat_minima.add(n)
    if len(seat_minima) > 1:
        ev.seat_conflict = True
    elif seat_minima:
        ev.seat_minimum = seat_minima.pop()

    # ---- body type ---------------------------------------------------------
    for m in re.finditer(_BODY, text):
        kind = _BODIES[m[1]]
        if re.search(_NEGATION + r"(?: an?| the| any)?\s*$", _preceding(text, m.start(), 20)):
            ev.negated_bodies.add(kind)
        else:
            ev.bodies.add(kind)

    # ---- dates -------------------------------------------------------------
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        with suppress(ValueError):  # impossible calendar dates are simply not evidence
            ev.dates.append(date(int(m[1]), int(m[2]), int(m[3])))
    month_names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for m in re.finditer(
        r"\b(" + month_names + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b", text
    ):
        anchor = ev.dates[-1] if ev.dates else today
        try:
            day = date(int(m[3] or anchor.year), _MONTHS[m[1]], int(m[2]))
        except ValueError:
            continue
        if not m[3] and day < anchor:
            day = day.replace(year=day.year + 1)
        ev.dates.append(day)
    ev.temporal = bool(ev.dates) or bool(
        re.search(
            r"\b(?:"
            + month_names
            + r")\b|\b(?:week|weekend|weeks|days?|nights?|tomorrow|today|through|until|thru)\b",
            text,
        )
    )
    money_month = {a.span for a in ev.amounts if a.period == "monthly"}
    for m in re.finditer(
        r"\b(?:for |make it |change it to |switch to )?(?:a|one|1|calendar|full|whole) (?:calendar )?month\b(?! budget| cap| rate)",
        text,
    ):
        if not any(s <= m.start() <= e + 2 for s, e in money_month):
            ev.trip_month = True
            ev.temporal = True

    # Numbers that could ground a seat count: everything except dates and money.
    plain = text
    for s_, e_ in taken:  # length-preserving blanking keeps the money spans aligned
        plain = plain[:s_] + " " * (e_ - s_) + plain[e_:]
    plain = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", plain)
    plain = re.sub(
        r"\b(?:" + month_names + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d{2})?\b", " ", plain
    )
    for m in re.finditer(r"\b" + _NUMBER + r"\b", plain):
        value = number_value(m[0])
        if value is not None:
            ev.numbers.add(value)

    if re.search(r"\btempe\b", text):
        ev.location = "Tempe"

    for name, target in _RETAIN_TARGETS.items():
        if re.search(
            r"\b" + _RETAIN_VERB + r"\b(?:\s+\w+){0,3}\s+" + target + r"\b", text
        ) or re.search(
            r"\b" + target + r"\b(?:\s+\w+){0,2}\s+(?:unchanged|the same|as is)\b", text
        ):
            ev.retained.add(name)
    return ev


@dataclass
class Reconciliation:
    """The reconciled patch plus an auditable record of every server decision."""

    patch: dict
    calendar_month: bool
    overrides: list[dict] = field(default_factory=list)

    def trace(self) -> dict:
        return {"overrides": self.overrides, "fields": sorted(self.patch)}


def _note(rec: Reconciliation, field_name: str, planner, applied, reason: str) -> None:
    rec.overrides.append(
        {"field": field_name, "planner": planner, "applied": applied, "reason": reason}
    )


def reconcile(plan: Plan, message: str, previous: dict, today: date) -> Reconciliation:
    """Return the hard-constraint patch the server will apply for an ``edit`` plan.

    Raises :class:`Unclear` whenever the safe action is to ask rather than to save.
    """
    ev = extract(message, today)
    proposed = plan.patch()
    patch: dict = {}
    rec = Reconciliation(patch=patch, calendar_month=False)

    # -- unsupported bounds: clarify before anything is saved ---------------
    if ev.seat_ceiling:
        raise Unclear("This search supports a minimum seat count. What minimum should I use?")
    if ev.seat_conflict:
        raise Unclear("How many seats do you need?")
    if any(
        a.comparator == "floor" and not a.narrative for a in ev.amounts
    ) or plan.budget_comparator in ("minimum", "range"):
        raise Unclear(
            "This search supports a maximum rental budget. What upper limit should I use?"
        )

    # -- seats ---------------------------------------------------------------
    if ev.seat_minimum is not None:
        if proposed.get("min_seats") not in (None, ev.seat_minimum):
            _note(
                rec,
                "min_seats",
                proposed["min_seats"],
                ev.seat_minimum,
                "contradicted explicit text",
            )
        elif "min_seats" not in proposed:
            _note(rec, "min_seats", None, ev.seat_minimum, "planner omitted explicit text")
        patch["min_seats"] = ev.seat_minimum
    elif "min_seats" in proposed:
        if "seats" in ev.retained or proposed["min_seats"] == previous.get("min_seats"):
            pass
        elif Decimal(proposed["min_seats"]) in ev.numbers:
            patch["min_seats"] = proposed["min_seats"]
        else:
            raise Unclear(
                "How many seats do you need? I could not find that number in your message."
            )

    # -- budget --------------------------------------------------------------
    budgets = ev.budget_amounts
    if "budget" in ev.retained:
        if proposed.get("budget_cents", previous.get("budget_cents")) != previous.get(
            "budget_cents"
        ):
            _note(
                rec,
                "budget_cents",
                proposed.get("budget_cents"),
                previous.get("budget_cents"),
                "customer retained budget",
            )
    elif len({a.ceiling_cents for a in budgets}) > 1:
        raise Unclear("Please give one maximum budget and its billing period.")
    elif budgets:
        amount = budgets[0]
        if (
            amount.comparator == "bare"
            and previous.get("budget_cents") is not None
            and not re.search(
                r"\b(?:budget|cap|ceiling|limit|raise|lower|increase|reduce|bring|change|set|make)\b",
                ev.text,
            )
        ):
            raise Unclear(
                "Should that amount become your maximum budget? Please say “set my budget to …”."
            )
        period = amount.period or (next(iter(ev.periods)) if len(ev.periods) == 1 else None)
        if period is None:
            raise Unclear("Is your budget daily, weekly or monthly?")
        planned = proposed.get("budget_cents")
        if planned is not None and planned not in (amount.cents, amount.ceiling_cents):
            _note(rec, "budget_cents", planned, amount.ceiling_cents, "contradicted explicit text")
        elif planned is None:
            _note(rec, "budget_cents", None, amount.ceiling_cents, "planner omitted explicit text")
        elif amount.comparator == "strict" and planned == amount.cents:
            _note(rec, "budget_cents", planned, amount.ceiling_cents, "strict bound canonicalised")
        patch["budget_cents"] = amount.ceiling_cents
        patch["period"] = period
    elif proposed.get("budget_cents") not in (None, previous.get("budget_cents")):
        raise Unclear("Please give the new budget amount and billing period.")
    elif ev.amounts and any(a.narrative for a in ev.amounts) and "budget_cents" in proposed:
        raise Unclear(
            "Should that amount become your maximum budget? Please say “set my budget to …”."
        )

    if "period" not in patch and proposed.get("period") not in (None, previous.get("period")):
        if proposed["period"] not in ev.periods:
            raise Unclear("Which billing period should the budget use?")
        if previous.get("budget_cents") is None:
            raise Unclear("What maximum budget should that billing period use?")
        patch["period"] = proposed["period"]

    # -- body type -----------------------------------------------------------
    bodies = ev.bodies - ev.negated_bodies
    if len(bodies) > 1:
        raise Unclear("Which single body type should I search for?")
    if bodies:
        body = bodies.pop()
        if proposed.get("body") not in (None, body):
            _note(rec, "body", proposed["body"], body, "contradicted explicit text")
        elif "body" not in proposed and body != previous.get("body"):
            _note(rec, "body", None, body, "planner omitted explicit text")
        patch["body"] = body
    elif proposed.get("body") not in (None, previous.get("body")):
        if proposed["body"] in ev.negated_bodies:
            raise Unclear("Which body type would you like instead?")
        raise Unclear("Which body type should I search for?")
    elif previous.get("body") in ev.negated_bodies:
        raise Unclear("Which body type would you like instead?")

    # -- dates ---------------------------------------------------------------
    if len(ev.dates) == 2:
        start, end = ev.dates
        if (proposed.get("start"), proposed.get("end")) not in ((None, None), (start, end)):
            _note(
                rec,
                "dates",
                [str(proposed.get("start")), str(proposed.get("end"))],
                [str(start), str(end)],
                "contradicted explicit text",
            )
        patch.update(start=start, end=end)
    elif ev.dates:
        raise Unclear("Please give both pickup and return dates.")
    else:
        for key in ("start", "end"):
            if key in proposed and str(proposed[key]) != str(previous.get(key)):
                if not ev.temporal:
                    raise Unclear("Please give the pickup and return dates you want.")
                patch[key] = proposed[key]

    if plan.calendar_month or ev.trip_month:
        if not ev.trip_month:
            raise Unclear("Should the trip last one calendar month? Please confirm the duration.")
        if "end" in patch and len(ev.dates) == 2:
            raise Unclear("Please give either a return date or a one-month duration, not both.")
        patch.pop("end", None)
        rec.calendar_month = True

    # -- location ------------------------------------------------------------
    if proposed.get("location") or ev.location:
        patch["location"] = "Tempe"

    return rec
