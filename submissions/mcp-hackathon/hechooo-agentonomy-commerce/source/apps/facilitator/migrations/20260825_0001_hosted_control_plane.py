"""Persist Hosted enrollment, credentials, replay and preflight bindings."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosted_tenants",
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "hosted_enrollment_tokens",
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("token_digest"),
    )
    op.create_index(
        "ix_hosted_enrollment_tokens_tenant_id",
        "hosted_enrollment_tokens",
        ["tenant_id"],
    )
    op.create_index(
        "ix_hosted_enrollment_tokens_expires_at",
        "hosted_enrollment_tokens",
        ["expires_at"],
    )
    op.create_table(
        "hosted_node_registrations",
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("wallet_binding_id", sa.String(length=256), nullable=False),
        sa.Column("device_public_jwk", sa.JSON(), nullable=False),
        sa.Column("device_key_id", sa.String(length=128), nullable=False),
        sa.Column("access_token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("credential_epoch", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "node_id"),
        sa.UniqueConstraint(
            "access_token_digest", name="uq_hosted_node_access_digest"
        ),
    )
    op.create_index(
        "ix_hosted_node_registrations_status",
        "hosted_node_registrations",
        ["status"],
    )
    op.create_table(
        "hosted_retired_credentials",
        sa.Column("access_token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("retired_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("access_token_digest"),
    )
    op.create_table(
        "hosted_dpop_replays",
        sa.Column("replay_id", sa.String(length=96), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("credential_epoch", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=256), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("replay_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "credential_epoch",
            "jti",
            name="uq_hosted_dpop_scope_jti",
        ),
    )
    op.create_index(
        "ix_hosted_dpop_replays_expires_at",
        "hosted_dpop_replays",
        ["expires_at"],
    )
    op.create_table(
        "hosted_preflight_records",
        sa.Column("record_id", sa.String(length=96), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("request_id", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_nonce", sa.String(length=66), nullable=False),
        sa.Column("capability_hash", sa.String(length=66), nullable=False),
        sa.Column("reservation_id", sa.String(length=256), nullable=False),
        sa.Column("request_hash", sa.String(length=66), nullable=False),
        sa.Column("signed_response_jws", sa.String(length=64 * 1024), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "request_id",
            name="uq_hosted_preflight_request_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "idempotency_key",
            name="uq_hosted_preflight_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "request_nonce",
            name="uq_hosted_preflight_request_nonce",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "capability_hash",
            name="uq_hosted_preflight_capability",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "reservation_id",
            name="uq_hosted_preflight_reservation",
        ),
    )


def downgrade() -> None:
    op.drop_table("hosted_preflight_records")
    op.drop_index(
        "ix_hosted_dpop_replays_expires_at", table_name="hosted_dpop_replays"
    )
    op.drop_table("hosted_dpop_replays")
    op.drop_table("hosted_retired_credentials")
    op.drop_index(
        "ix_hosted_node_registrations_status",
        table_name="hosted_node_registrations",
    )
    op.drop_table("hosted_node_registrations")
    op.drop_index(
        "ix_hosted_enrollment_tokens_expires_at",
        table_name="hosted_enrollment_tokens",
    )
    op.drop_index(
        "ix_hosted_enrollment_tokens_tenant_id",
        table_name="hosted_enrollment_tokens",
    )
    op.drop_table("hosted_enrollment_tokens")
    op.drop_table("hosted_tenants")
