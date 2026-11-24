"""Canonical preference version, vehicle ranking data and confirmed actions."""

import sqlalchemy as s
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("vehicles", s.Column("mileage", s.Integer, nullable=True))
    op.add_column("vehicles", s.Column("mpg", s.Integer, nullable=True))
    op.add_column(
        "conversations", s.Column("version", s.Integer, nullable=False, server_default="0")
    )
    op.create_table(
        "action_proposals",
        s.Column("id", s.String(36), primary_key=True),
        s.Column(
            "conversation_id",
            s.String(36),
            s.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        s.Column("kind", s.String(30), nullable=False),
        s.Column("arguments", s.JSON, nullable=False),
        s.Column("expires_at", s.Integer, nullable=False),
        s.Column("consumed", s.Boolean, nullable=False),
    )
    op.create_index("ix_action_proposals_conversation_id", "action_proposals", ["conversation_id"])
    op.create_table(
        "idempotency",
        s.Column("id", s.String(36), primary_key=True),
        s.Column(
            "conversation_id",
            s.String(36),
            s.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        s.Column("key", s.String(100), nullable=False),
        s.Column("payload_hash", s.String(64), nullable=False),
        s.Column("result", s.JSON, nullable=False),
    )
    op.create_index(
        "uq_session_idempotency", "idempotency", ["conversation_id", "key"], unique=True
    )


def downgrade():
    op.drop_table("idempotency")
    op.drop_table("action_proposals")
    op.drop_column("conversations", "version")
    op.drop_column("vehicles", "mpg")
    op.drop_column("vehicles", "mileage")
