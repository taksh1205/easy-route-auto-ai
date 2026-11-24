"""Prevent parent deletion from silently cancelling operational appointment records."""

import sqlalchemy as s
from alembic import op

revision = "0003"
down_revision = "0002"


def change(ondelete):
    fk = next(
        f
        for f in s.inspect(op.get_bind()).get_foreign_keys("appointments")
        if f["constrained_columns"] == ["conversation_id"]
    )
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    name = fk["name"] or "fk_appointments_conversation_id_conversations"
    with op.batch_alter_table("appointments", naming_convention=convention) as batch:
        batch.drop_constraint(name, type_="foreignkey")
        batch.create_foreign_key(
            "fk_appointments_conversation",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade():
    change("RESTRICT")


def downgrade():
    change("CASCADE")
