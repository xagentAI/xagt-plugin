"""Persist replayable purchase reputation events."""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0005"
down_revision = "20260713_0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("reputation_events"):
        op.create_table(
            "reputation_events",
            sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("offering_id", sa.String(length=64), nullable=False),
            sa.Column("purchase_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("dimensions", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["offering_id"], ["offerings.offering_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint(
                "purchase_id", name="uq_reputation_events_purchase_id"
            ),
        )

    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("reputation_events")
    }
    for name, columns in (
        ("ix_reputation_events_offering_id", ["offering_id"]),
        ("ix_reputation_events_event_type", ["event_type"]),
        ("ix_reputation_events_created_at", ["created_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "reputation_events", columns)


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("reputation_events"):
        op.drop_table("reputation_events")
