"""Initial synthetic dealership schema."""

import sqlalchemy as s
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "vehicles",
        s.Column("id", s.Integer, primary_key=True),
        s.Column("name", s.String(120), nullable=False),
        s.Column("body", s.String(30), nullable=False),
        s.Column("price", s.Integer, nullable=False),
        s.Column("seats", s.Integer, nullable=False),
        s.Column("features", s.JSON, nullable=False),
        s.Column("available", s.Boolean, nullable=False),
        s.CheckConstraint("price >= 0"),
        s.CheckConstraint("seats > 0"),
    )
    op.create_table(
        "conversations",
        s.Column("id", s.String(36), primary_key=True),
        s.Column("token_hash", s.String(64), nullable=False),
        s.Column("preferences", s.JSON, nullable=False),
        s.Column("updated_at", s.Integer, nullable=False),
    )
    op.create_table(
        "messages",
        s.Column("id", s.Integer, primary_key=True),
        s.Column(
            "conversation_id",
            s.String(36),
            s.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        s.Column("role", s.String(20), nullable=False),
        s.Column("content", s.String(12000), nullable=False),
        s.Column("trace", s.JSON, nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "leads",
        s.Column("id", s.String(36), primary_key=True),
        s.Column(
            "conversation_id",
            s.String(36),
            s.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        s.Column("name", s.String(100), nullable=False),
        s.Column("email", s.String(254), nullable=False),
        s.Column("status", s.String(20), nullable=False),
    )
    op.create_table(
        "appointments",
        s.Column("id", s.String(36), primary_key=True),
        s.Column(
            "conversation_id",
            s.String(36),
            s.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        s.Column("vehicle_id", s.Integer, s.ForeignKey("vehicles.id"), nullable=False),
        s.Column("slot", s.Integer, nullable=False),
        s.Column("cancelled", s.Boolean, nullable=False),
    )
    op.create_index(
        "uq_active_vehicle_slot",
        "appointments",
        ["vehicle_id", "slot"],
        unique=True,
        postgresql_where=s.text("cancelled = false"),
        sqlite_where=s.text("cancelled = 0"),
    )


def downgrade():
    for table in ["appointments", "leads", "messages", "conversations", "vehicles"]:
        op.drop_table(table)
