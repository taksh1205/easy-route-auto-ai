"""Rental ledger is independent of purchase inventory and legacy appointments."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    c = sa.Column
    fk = sa.ForeignKey
    op.create_table(
        "rental_rates",
        c("vehicle_id", sa.Integer, fk("vehicles.id"), primary_key=True),
        c("location", sa.String(), nullable=False),
        *[c(k, sa.Integer, nullable=False) for k in ("daily", "weekly", "monthly")],
        c("active", sa.Boolean, nullable=False),
    )
    op.create_table(
        "rental_records",
        c("id", sa.String(36), primary_key=True),
        c(
            "owner",
            sa.String(36),
            fk("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        c("terms", sa.JSON, nullable=False),
        c("status", sa.String(), nullable=False),
        c("expires", sa.Integer, nullable=False),
    )
    op.create_table(
        "rental_days",
        c("vehicle_id", sa.Integer, fk("vehicles.id"), primary_key=True),
        c("day", sa.String(10), primary_key=True),
        c("reservation", sa.String(36), fk("rental_records.id"), nullable=False),
    )
    op.create_table(
        "rental_context",
        c("owner", sa.String(36), fk("conversations.id"), primary_key=True),
        c("data", sa.JSON, nullable=False),
    )
    op.create_table(
        "employees",
        c("name", sa.String(), primary_key=True),
        c("digest", sa.String(), nullable=False),
        c("role", sa.String(), nullable=False),
    )
    op.create_table(
        "rental_audit",
        c("id", sa.Integer, primary_key=True),
        *[c(k, sa.String(), nullable=False) for k in ("actor", "operation", "target")],
        c("created", sa.Integer, nullable=False),
    )


def downgrade():
    for name in (
        "rental_audit",
        "employees",
        "rental_context",
        "rental_days",
        "rental_records",
        "rental_rates",
    ):
        op.drop_table(name)
