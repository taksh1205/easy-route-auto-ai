import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return str(uuid.uuid4())


def now():
    from .clock import timestamp

    return timestamp()


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(30))
    price: Mapped[int] = mapped_column(Integer)
    seats: Mapped[int] = mapped_column(Integer)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mpg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list] = mapped_column(JSON)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("price >= 0"), CheckConstraint("seats > 0"))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64))
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer, default=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(String(12000))
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(20), default="new")


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT", name="fk_appointments_conversation")
    )
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    slot: Mapped[int] = mapped_column(Integer)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        Index(
            "uq_active_vehicle_slot",
            "vehicle_id",
            "slot",
            unique=True,
            postgresql_where=text("cancelled = false"),
            sqlite_where=text("cancelled = 0"),
        ),
    )


class ActionProposal(Base):
    __tablename__ = "action_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    arguments: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[int] = mapped_column(Integer)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Idempotency(Base):
    __tablename__ = "idempotency"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (Index("uq_session_idempotency", "conversation_id", "key", unique=True),)


class RentalRate(Base):
    __tablename__ = "rental_rates"
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    location: Mapped[str]
    daily: Mapped[int]
    weekly: Mapped[int]
    monthly: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True)


class RentalRecord(Base):
    """Immutable quote terms shared by the quote, inquiry and reservation ledger."""

    __tablename__ = "rental_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="RESTRICT"))
    terms: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str]
    expires: Mapped[int]


class RentalDay(Base):
    __tablename__ = "rental_days"
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    reservation: Mapped[str] = mapped_column(ForeignKey("rental_records.id"))


class RentalContext(Base):
    __tablename__ = "rental_context"
    owner: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Employee(Base):
    __tablename__ = "employees"
    name: Mapped[str] = mapped_column(primary_key=True)
    digest: Mapped[str]
    role: Mapped[str]


class RentalAudit(Base):
    __tablename__ = "rental_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]
    operation: Mapped[str]
    target: Mapped[str]
    created: Mapped[int] = mapped_column(default=now)
