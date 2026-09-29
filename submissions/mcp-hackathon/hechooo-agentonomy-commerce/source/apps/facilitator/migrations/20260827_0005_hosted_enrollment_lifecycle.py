"""Persist idempotent Hosted enrollment, rotation and revocation state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0005"
down_revision: Union[str, None] = "20260827_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A consumed invite remains replayable only when both binding fields are
    # present.  Existing unconsumed rows retain two NULLs.
    op.add_column(
        "hosted_enrollment_tokens",
        sa.Column("enrolled_node_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "hosted_enrollment_tokens",
        sa.Column(
            "enrollment_binding_digest",
            sa.LargeBinary(length=32),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_hosted_enrollment_binding",
        "hosted_enrollment_tokens",
        "(enrolled_node_id IS NULL AND enrollment_binding_digest IS NULL) OR "
        "(enrolled_node_id IS NOT NULL AND enrollment_binding_digest IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_hosted_enrollment_node_binding",
        "hosted_enrollment_tokens",
        ["tenant_id", "enrolled_node_id"],
    )

    op.add_column(
        "hosted_node_registrations",
        sa.Column("revocation_id", sa.String(length=256), nullable=True),
    )
    op.create_unique_constraint(
        "uq_hosted_node_revocation_id",
        "hosted_node_registrations",
        ["revocation_id"],
    )

    op.create_table(
        "hosted_node_rotations",
        sa.Column("rotation_id", sa.String(length=256), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("wallet_binding_id", sa.String(length=256), nullable=False),
        sa.Column("expected_epoch", sa.Integer(), nullable=False),
        sa.Column("next_epoch", sa.Integer(), nullable=False),
        sa.Column("pending_public_jwk", sa.JSON(), nullable=False),
        sa.Column("pending_device_key_id", sa.String(length=128), nullable=False),
        sa.Column(
            "pending_access_token_digest",
            sa.LargeBinary(length=32),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prepared_at", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "expected_epoch > 0",
            name="ck_hosted_rotation_expected_epoch_positive",
        ),
        sa.CheckConstraint(
            "next_epoch = expected_epoch + 1",
            name="ck_hosted_rotation_epoch_step",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'committed', 'cancelled')",
            name="ck_hosted_rotation_status",
        ),
        sa.CheckConstraint(
            "(status = 'committed' AND committed_at IS NOT NULL) OR "
            "(status IN ('prepared', 'cancelled') AND committed_at IS NULL)",
            name="ck_hosted_rotation_commit_timestamp",
        ),
        sa.PrimaryKeyConstraint("rotation_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "expected_epoch",
            name="uq_hosted_rotation_node_expected_epoch",
        ),
        sa.UniqueConstraint(
            "pending_access_token_digest",
            name="uq_hosted_rotation_pending_access_digest",
        ),
    )
    op.create_index(
        "ix_hosted_node_rotations_scope_status",
        "hosted_node_rotations",
        ["tenant_id", "node_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hosted_node_rotations_scope_status",
        table_name="hosted_node_rotations",
    )
    op.drop_table("hosted_node_rotations")
    op.drop_constraint(
        "uq_hosted_node_revocation_id",
        "hosted_node_registrations",
        type_="unique",
    )
    op.drop_column("hosted_node_registrations", "revocation_id")
    op.drop_constraint(
        "ck_hosted_enrollment_binding",
        "hosted_enrollment_tokens",
        type_="check",
    )
    op.drop_constraint(
        "uq_hosted_enrollment_node_binding",
        "hosted_enrollment_tokens",
        type_="unique",
    )
    op.drop_column("hosted_enrollment_tokens", "enrollment_binding_digest")
    op.drop_column("hosted_enrollment_tokens", "enrolled_node_id")
