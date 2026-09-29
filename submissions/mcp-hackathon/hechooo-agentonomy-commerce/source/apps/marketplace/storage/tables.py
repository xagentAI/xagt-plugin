from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProviderRow(Base):
    __tablename__ = "providers"
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(42), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    domain_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_domain_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_domain_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfferingRow(Base):
    __tablename__ = "offerings"
    offering_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    candidate_payload: Mapped[dict | None] = mapped_column(JSON)
    candidate_registry_id: Mapped[str | None] = mapped_column(String(128))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_check_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProvenanceRow(Base):
    __tablename__ = "offering_provenance"
    provenance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("offerings.offering_id", ondelete="CASCADE"), index=True)
    registry_id: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[str] = mapped_column(String(512))
    etag: Mapped[str | None] = mapped_column(String(255))
    cursor: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("offering_id", "registry_id", "source_id"),)


class ManifestRow(Base):
    __tablename__ = "manifests"
    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    owner_wallet_address: Mapped[str] = mapped_column(String(42), index=True)
    manifest_hash: Mapped[str] = mapped_column(String(66))
    payload: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(Text)
    signer: Mapped[str | None] = mapped_column(String(42))
    status: Mapped[str] = mapped_column(String(32), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "owner_wallet_address",
            "manifest_hash",
            name="uq_manifests_owner_manifest_hash",
        ),
    )


class ChallengeRow(Base):
    __tablename__ = "auth_challenges"
    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class MerchantSessionRow(Base):
    __tablename__ = "merchant_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(42), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReputationRow(Base):
    __tablename__ = "reputation_snapshots"
    reputation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("offerings.offering_id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float]
    dimensions: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ReputationEventRow(Base):
    __tablename__ = "reputation_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(
        ForeignKey("offerings.offering_id", ondelete="CASCADE"), index=True
    )
    purchase_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    dimensions: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PurchasePreviewRow(Base):
    __tablename__ = "purchase_previews"
    preview_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("offerings.offering_id"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    quote_hash: Mapped[str] = mapped_column(String(66), index=True)
    input_hash: Mapped[str] = mapped_column(String(66))
    payment: Mapped[dict] = mapped_column(JSON)
    execution_mode: Mapped[str] = mapped_column(String(40))
    opc_installation_id: Mapped[str | None] = mapped_column(
        String(44), nullable=True
    )
    payment_capability: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PurchaseRow(Base):
    __tablename__ = "purchases"
    purchase_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preview_id: Mapped[str] = mapped_column(ForeignKey("purchase_previews.preview_id"), unique=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("offerings.offering_id"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    execution_mode: Mapped[str] = mapped_column(String(40))
    input_hash: Mapped[str] = mapped_column(String(66))
    output_hash: Mapped[str | None] = mapped_column(String(66))
    reservation_id: Mapped[str | None] = mapped_column(String(96), unique=True)
    action_id: Mapped[str | None] = mapped_column(String(96), unique=True)
    policy_decision_id: Mapped[str | None] = mapped_column(String(96), unique=True)
    receipt_id: Mapped[str | None] = mapped_column(String(96), unique=True)
    audit_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason_code: Mapped[str | None] = mapped_column(String(96))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    execution_claim_token: Mapped[str | None] = mapped_column(String(64), index=True)
    execution_claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PurchaseFinalizationRow(Base):
    __tablename__ = "purchase_finalizations"
    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_id: Mapped[str] = mapped_column(ForeignKey("purchases.purchase_id", ondelete="CASCADE"), unique=True, index=True)
    target_state: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    claim_token: Mapped[str | None] = mapped_column(String(64), index=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RegistryCursorRow(Base):
    __tablename__ = "registry_cursors"
    registry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(512))
    etag: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    sync_owner_token: Mapped[str | None] = mapped_column(String(64))
    sync_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkerStageRow(Base):
    __tablename__ = "worker_stage_runs"
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    stage: Mapped[str] = mapped_column(String(64), primary_key=True)
    cycle_token: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


Index("ix_offerings_public", OfferingRow.status, OfferingRow.last_verified_at)
