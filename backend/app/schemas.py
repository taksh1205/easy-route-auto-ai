from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Body = Literal["sedan", "suv", "hatchback", "truck"]


class Search(Strict):
    max_price: int | None = Field(default=None, ge=0, le=1000000, strict=True)
    body: Body | None = None
    min_seats: int = Field(default=1, ge=1, le=9, strict=True)
    max_mileage: int | None = Field(default=None, ge=0, le=1000000, strict=True)
    min_mpg: int | None = Field(default=None, ge=1, le=150, strict=True)
    features: list[str] = Field(default_factory=list, max_length=10)
    low_mileage: bool = False
    fuel_efficient: bool = False
    semantic_query: str = Field(default="", max_length=300)


class PreferenceOp(Strict):
    field: Literal[
        "max_price",
        "body",
        "min_seats",
        "max_mileage",
        "min_mpg",
        "features",
        "low_mileage",
        "fuel_efficient",
        "semantic_query",
    ]
    op: Literal["set", "clear", "retain"]
    value: int | str | bool | list[str] | None = None
    evidence: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def check_value(self):
        if self.op == "set" and self.value is None:
            raise ValueError("set needs value")
        if self.op != "set" and self.value is not None:
            raise ValueError("clear/retain takes no value")
        return self


class PreferenceUpdate(Strict):
    expected_version: int = Field(ge=0)
    operations: list[PreferenceOp] = Field(max_length=9)


class ToolCall(Strict):
    name: Literal[
        "search_inventory",
        "retrieve_policy",
        "compare_vehicles",
        "appointment_availability",
        "lead_proposal",
        "booking_proposal",
        "cancellation_proposal",
        "reschedule_proposal",
    ]
    arguments: dict = Field(default_factory=dict)


class TurnPlan(Strict):
    intent: Literal["greeting", "inventory", "policy", "action", "clarify"]
    updates: list[PreferenceOp] = Field(default_factory=list, max_length=9)
    clarification: Literal["budget", "body", "seats", "preference", "action", "question"] | None = (
        None
    )
    tools: list[ToolCall] = Field(default_factory=list, max_length=4)
    # Optional model nominations are checked, never rendered directly.
    vehicle_refs: list[int] = Field(default_factory=list, max_length=20)


class Chat(Strict):
    message: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=0)


class LeadInput(Strict):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    consent: Literal[True]


class Booking(Strict):
    vehicle_id: int = Field(gt=0)
    starts_at: datetime

    @field_validator("starts_at")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("timezone required")
        return v


class Reschedule(Booking):
    appointment_id: str = Field(min_length=1, max_length=36)


class Cancel(Strict):
    appointment_id: str = Field(min_length=1, max_length=36)


class Compare(Strict):
    ids: list[int] = Field(min_length=2, max_length=4)


class VehicleID(Strict):
    vehicle_id: int = Field(gt=0)


class PolicyQuery(Strict):
    query: str = Field(min_length=1, max_length=2000)
    topic: str | None = Field(default=None, max_length=40)


class Confirmation(Strict):
    kind: Literal["booking", "lead", "cancellation", "reschedule", "preferences"]
    arguments: dict


class ProposalInput(Confirmation):
    pass


class Evidence(Strict):
    chunk_id: str
    doc_id: str
    version: str
    topic: str
    text: str
    score: float
    dense_score: float


class ActionResult(Strict):
    kind: str
    record_id: str
    committed: Literal[True]
    data: dict


class ComparisonRow(Strict):
    id: int
    name: str
    body: str
    price: int
    seats: int
    features: list[str]
    mileage: int | None
    mpg: int | None
    available: bool


class AvailabilityResult(Strict):
    vehicle_id: int
    slots: list[int]


class AssistantResult(Strict):
    comparison: list[ComparisonRow] = Field(default_factory=list)
    availability: list[AvailabilityResult] = Field(default_factory=list)
    reply: str
    mode: Literal["deterministic", "openai"]
    intent: str
    vehicles: list[dict] = Field(default_factory=list)
    citations: list[Evidence] = Field(default_factory=list)
    proposals: list[dict] = Field(default_factory=list)
    actions: list[ActionResult] = Field(default_factory=list)
    preferences: dict
    version: int = 0
    trace: dict
    notice: str = "Authoritative facts appear in database cards, quoted policy evidence and committed action records only."
