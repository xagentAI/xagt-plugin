"""Durable Hosted execution state and atomic relayer nonce allocation."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from collections.abc import Mapping
import hashlib
import re
import time
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from evm import EvmEncodingError, raw_transaction_hash
from execution_models import (
    ExecutionIntent,
    ExecutionState,
    HostedExecution,
    allowed_transitions,
)
from pilot_gate import PilotGateDenied, PilotGatePolicy, utc_day
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


class ExecutionRepositoryError(RuntimeError):
    """Base class for bounded repository failures."""


class ExecutionConflict(ExecutionRepositoryError):
    """An immutable binding, state, or replay invariant was violated."""


class ExecutionNotFound(ExecutionRepositoryError):
    """The requested durable execution does not exist."""


MAX_RELAYER_NONCE = 2**63 - 2
SIGNING_CLAIM_LEASE_SECONDS = 15
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_OBSERVATION_EVIDENCE_KEYS = frozenset(
    {
        "accepted_transfer",
        "boundary",
        "capability_used",
        "confirmations",
        "finality_boundary_timestamp",
        "owner_nonce_used",
        "payment_event_found",
        "reason",
        "receipt_block_number",
        "safe_block_number",
        "transfer_event_found",
        "watcher_version",
        "finality_boundary",
    }
)
_RELEASE_EVIDENCE_KEYS = frozenset(
    {
        "receipt_status",
        "canonical_receipt",
        "finality_boundary_timestamp",
        "capability_used",
        "owner_nonce_used",
        "payment_event_found",
        "transfer_event_found",
    }
)
_REORG_EVIDENCE_KEYS = frozenset(
    {"canonical", "observed_block_hash", "previous_block_hash", "reason", "watcher_version"}
)
def _public_evidence(
    evidence: object,
    *,
    allowed_keys: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ExecutionConflict("watcher evidence must be a public object")
    unknown = set(evidence) - allowed_keys
    if unknown:
        raise ExecutionConflict("watcher evidence contains a private or unknown field")
    projected: dict[str, Any] = {}
    for key, value in evidence.items():
        if not isinstance(key, str):
            raise ExecutionConflict("watcher evidence field is invalid")
        if isinstance(value, bool):
            projected[key] = value
        elif type(value) is int and value >= 0:
            projected[key] = value
        elif isinstance(value, str) and 0 < len(value) <= 256:
            if key == "watcher_version" and len(value) > 128:
                raise ExecutionConflict("watcher version is invalid")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ExecutionConflict("watcher evidence field is invalid")
            projected[key] = value
        else:
            raise ExecutionConflict("watcher evidence field is invalid")
    return projected


def _release_evidence(value: object) -> dict[str, Any]:
    """Validate the small, public proof required to release a reverted payment."""

    projected = _public_evidence(value, allowed_keys=_RELEASE_EVIDENCE_KEYS)
    if set(projected) != _RELEASE_EVIDENCE_KEYS:
        raise ExecutionConflict("release evidence is incomplete")
    if (
        type(projected["receipt_status"]) is not int
        or projected["receipt_status"] != 0
        or projected["canonical_receipt"] is not True
        or projected["capability_used"] is not False
        or projected["owner_nonce_used"] is not False
        or projected["payment_event_found"] is not False
        or projected["transfer_event_found"] is not False
        or type(projected["finality_boundary_timestamp"]) is not int
        or projected["finality_boundary_timestamp"] <= 0
    ):
        raise ExecutionConflict("release evidence is invalid")
    return projected


def _require_finality_boundary(
    *,
    receipt_block_number: object,
    confirmations: object,
    safe_block_number: object,
    safe_block_hash: object,
    finality_boundary: object,
    minimum_confirmations: int,
) -> None:
    if type(receipt_block_number) is not int or receipt_block_number < 0:
        raise ExecutionConflict("receipt block evidence is invalid")
    if finality_boundary not in {"safe", "finalized"}:
        raise ExecutionConflict("finality boundary is invalid")
    if type(minimum_confirmations) is not int or minimum_confirmations < 2:
        raise ExecutionConflict("finality depth is invalid")
    if type(confirmations) is not int or confirmations < minimum_confirmations:
        raise ExecutionConflict("confirmation depth is insufficient")
    if type(safe_block_number) is not int or safe_block_number < receipt_block_number:
        raise ExecutionConflict("safe boundary is behind receipt")
    if not isinstance(safe_block_hash, str) or not safe_block_hash:
        raise ExecutionConflict("safe boundary evidence is missing")


class HostedExecutionBase(DeclarativeBase):
    pass


class HostedExecutionRow(HostedExecutionBase):
    __tablename__ = "hosted_executions"
    __table_args__ = (
        UniqueConstraint("capability_id", name="uq_hosted_execution_capability"),
        UniqueConstraint("reservation_id", name="uq_hosted_execution_reservation"),
        UniqueConstraint("purchase_id", name="uq_hosted_execution_purchase"),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "idempotency_key",
            name="uq_hosted_execution_idempotency",
        ),
        CheckConstraint(
            "chain IN ('eip155:8453', 'eip155:137', 'eip155:84532', 'eip155:80002')",
            name="ck_hosted_execution_supported_chain",
        ),
        CheckConstraint(
            "length(amount_atomic) > 0", name="ck_hosted_execution_amount_present"
        ),
        CheckConstraint(
            "length(capability_hash) = 66",
            name="ck_hosted_execution_capability_hash_length",
        ),
        CheckConstraint(
            "length(reservation_hash) = 66",
            name="ck_hosted_execution_reservation_hash_length",
        ),
        CheckConstraint(
            "length(execution_scope_hash) = 66",
            name="ck_hosted_execution_scope_hash_length",
        ),
        CheckConstraint(
            "length(execution_digest) = 66",
            name="ck_hosted_execution_digest_length",
        ),
        CheckConstraint(
            "length(canonical_hash) = 66",
            name="ck_hosted_execution_canonical_hash_length",
        ),
        CheckConstraint(
            "signer_epoch > 0", name="ck_hosted_execution_signer_epoch_positive"
        ),
        CheckConstraint(
            "length(owner_nonce) > 0",
            name="ck_hosted_execution_owner_nonce_present",
        ),
        CheckConstraint(
            "relayer_nonce >= 0",
            name="ck_hosted_execution_relayer_nonce_nonnegative",
        ),
        CheckConstraint(
            "signing_claim_generation >= 0",
            name="ck_hosted_execution_signing_claim_generation_nonnegative",
        ),
        CheckConstraint(
            "signing_claim_expires_at IS NULL OR "
            "(signing_claim_generation > 0 AND signing_claim_expires_at > 0)",
            name="ck_hosted_execution_signing_claim_expiry",
        ),
        CheckConstraint("deadline > 0", name="ck_hosted_execution_deadline_positive"),
        CheckConstraint(
            "status IN ('requested', 'preflight_approved', 'signing', 'signed', "
            "'submitted', 'submission_unknown', 'submission_rejected', "
            "'confirmed', 'finalized', 'reverted', 'expired', 'released', "
            "'reorg_review')",
            name="ck_hosted_execution_status",
        ),
        CheckConstraint(
            "status NOT IN ('confirmed', 'finalized', 'reverted', 'reorg_review') OR "
            "(finality_boundary IS NOT NULL AND (((chain IN ('eip155:8453', 'eip155:84532')) "
            "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
            "((chain IN ('eip155:137', 'eip155:80002')) "
            "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
            "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL)",
            name="ck_hosted_execution_terminal_finality_evidence",
        ),
        Index("ix_hosted_execution_status_updated", "status", "updated_at"),
        Index(
            "uq_hosted_execution_active_chain_relayer_nonce",
            "chain",
            "relayer_address",
            "relayer_nonce",
            unique=True,
            postgresql_where=text("status NOT IN ('expired', 'released')"),
            sqlite_where=text("status NOT IN ('expired', 'released')"),
        ),
        Index(
            "ix_hosted_execution_watch_attempt",
            "status",
            "watcher_attempted_at",
            "execution_id",
        ),
    )

    execution_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    wallet_binding_id: Mapped[str] = mapped_column(String(256), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(256), nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(256), nullable=False)
    purchase_id: Mapped[str] = mapped_column(String(256), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    owner: Mapped[str] = mapped_column(String(42), nullable=False)
    payee: Mapped[str] = mapped_column(String(42), nullable=False)
    token: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_atomic: Mapped[str] = mapped_column(String(78), nullable=False)
    executor: Mapped[str] = mapped_column(String(42), nullable=False)
    signer_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_nonce: Mapped[str] = mapped_column(String(78), nullable=False)
    deadline: Mapped[int] = mapped_column(BigInteger, nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    reservation_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    execution_scope_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    execution_digest: Mapped[str] = mapped_column(String(66), nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary)
    relayer_address: Mapped[str] = mapped_column(String(42), nullable=False)
    relayer_nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signing_claim_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    signing_claim_expires_at: Mapped[int | None] = mapped_column(BigInteger)
    unsigned_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    raw_transaction: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    broadcast_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    broadcasted_at: Mapped[int | None] = mapped_column(BigInteger)
    receipt_status: Mapped[int | None] = mapped_column(Integer)
    receipt_block_number: Mapped[int | None] = mapped_column(BigInteger)
    receipt_block_hash: Mapped[str | None] = mapped_column(String(66))
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_block_number: Mapped[int | None] = mapped_column(BigInteger)
    safe_block_hash: Mapped[str | None] = mapped_column(String(66))
    watcher_version: Mapped[str | None] = mapped_column(String(128))
    watcher_attempted_at: Mapped[int | None] = mapped_column(BigInteger)
    finality_boundary: Mapped[str | None] = mapped_column(String(32))
    reorg_state: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    reorg_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    submission_failure_code: Mapped[str | None] = mapped_column(String(64))
    release_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confirmed_at: Mapped[int | None] = mapped_column(BigInteger)
    finalized_at: Mapped[int | None] = mapped_column(BigInteger)
    reverted_at: Mapped[int | None] = mapped_column(BigInteger)
    released_at: Mapped[int | None] = mapped_column(BigInteger)
    expired_at: Mapped[int | None] = mapped_column(BigInteger)
    reorg_reviewed_at: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RelayerNonceRow(HostedExecutionBase):
    __tablename__ = "hosted_relayer_nonce_allocations"
    __table_args__ = (
        CheckConstraint(
            "chain IN ('eip155:8453', 'eip155:137', 'eip155:84532', 'eip155:80002')",
            name="ck_hosted_relayer_nonce_supported_chain",
        ),
        CheckConstraint("next_nonce >= 0", name="ck_hosted_relayer_nonce_nonnegative"),
    )

    chain: Mapped[str] = mapped_column(String(32), primary_key=True)
    relayer_address: Mapped[str] = mapped_column(String(42), primary_key=True)
    next_nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class HostedExecutionAttemptRow(HostedExecutionBase):
    __tablename__ = "hosted_execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "attempt_number",
            name="uq_hosted_execution_attempt_number",
        ),
        Index("ix_hosted_execution_attempts_execution_created", "execution_id", "created_at"),
    )

    attempt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("hosted_executions.execution_id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class HostedExecutionObservationRow(HostedExecutionBase):
    __tablename__ = "hosted_execution_observations"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "tx_hash",
            "block_hash",
            name="uq_hosted_execution_observation_block",
        ),
        Index("ix_hosted_execution_observations_execution_observed", "execution_id", "observed_at"),
    )

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("hosted_executions.execution_id"), nullable=False
    )
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    receipt_status: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_block_number: Mapped[int | None] = mapped_column(BigInteger)
    safe_block_hash: Mapped[str | None] = mapped_column(String(66))
    watcher_version: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class HostedGateControlRow(HostedExecutionBase):
    __tablename__ = "hosted_gate_controls"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('platform', 'tenant', 'node')",
            name="ck_hosted_gate_control_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'platform' AND tenant_id = '' AND node_id = '') OR "
            "(scope_type = 'tenant' AND length(tenant_id) > 0 AND node_id = '') OR "
            "(scope_type = 'node' AND length(tenant_id) > 0 AND length(node_id) > 0)",
            name="ck_hosted_gate_control_scope_shape",
        ),
    )

    scope_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), primary_key=True, default="")
    node_id: Mapped[str] = mapped_column(String(256), primary_key=True, default="")
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class HostedGateReservationRow(HostedExecutionBase):
    __tablename__ = "hosted_gate_reservations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_hosted_gate_reservation_state",
        ),
        CheckConstraint(
            "utc_day >= 0", name="ck_hosted_gate_reservation_utc_day_nonnegative"
        ),
        CheckConstraint(
            "gas_cost_usd_micros >= 0",
            name="ck_hosted_gate_reservation_gas_nonnegative",
        ),
        CheckConstraint(
            "(gas_cost_usd_micros = 0 AND gas_utc_day IS NULL) OR "
            "(gas_cost_usd_micros > 0 AND gas_utc_day >= 0)",
            name="ck_hosted_gate_reservation_gas_day",
        ),
        Index(
            "ix_hosted_gate_reservations_tenant_node_day_state",
            "tenant_id",
            "node_id",
            "utc_day",
            "state",
        ),
        Index(
            "ix_hosted_gate_reservations_platform_day_state",
            "gas_utc_day",
            "state",
        ),
    )

    execution_id: Mapped[str] = mapped_column(
        ForeignKey("hosted_executions.execution_id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    utc_day: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    gas_cost_usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gas_utc_day: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class HostedGateEventRow(HostedExecutionBase):
    __tablename__ = "hosted_gate_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('allowed', 'denied', 'gas_reserved', 'settled', "
            "'released', 'pause_changed')",
            name="ck_hosted_gate_event_type",
        ),
        CheckConstraint(
            "gas_cost_usd_micros >= 0",
            name="ck_hosted_gate_event_gas_nonnegative",
        ),
        Index(
            "ix_hosted_gate_events_tenant_node_created",
            "tenant_id",
            "node_id",
            "created_at",
        ),
        Index(
            "ix_hosted_gate_events_execution_created",
            "execution_id",
            "created_at",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("hosted_executions.execution_id")
    )
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    gas_cost_usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


def _ethereum_transaction_hash(raw_transaction: bytes) -> str:
    try:
        return "0x" + raw_transaction_hash(raw_transaction).hex()
    except EvmEncodingError as exc:
        raise ExecutionConflict("raw transaction is invalid") from exc


class ExecutionRepository:
    """A single durable boundary for Hosted execution state and nonce ownership."""

    def __init__(
        self,
        database_url: str,
        *,
        create_schema: bool | None = None,
        pilot_policy: PilotGatePolicy | None = None,
    ) -> None:
        if not isinstance(database_url, str) or not database_url:
            raise ValueError("execution database URL is invalid")
        if pilot_policy is not None and not isinstance(pilot_policy, PilotGatePolicy):
            raise TypeError("pilot gate policy is invalid")
        self.pilot_policy = pilot_policy
        self.engine = create_engine(
            database_url,
            connect_args={"timeout": 5} if database_url.startswith("sqlite") else {},
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.dialect_name = self.engine.dialect.name
        if create_schema is None:
            create_schema = self.dialect_name == "sqlite"
        if create_schema:
            HostedExecutionBase.metadata.create_all(self.engine)

    @contextmanager
    def _write_session(self) -> Iterator[Any]:
        session = self.sessions()
        try:
            if self.dialect_name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            else:
                session.begin()
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def allocate_or_return(
        self,
        intent: ExecutionIntent,
        *,
        chain_pending_nonce: int,
        chain_confirmed_nonce: int | None = None,
        now: int | None = None,
    ) -> HostedExecution:
        intent = self._validated_intent(intent)
        chain_pending_nonce = self._canonical_nonce(chain_pending_nonce)
        if chain_confirmed_nonce is None:
            chain_confirmed_nonce = chain_pending_nonce
        chain_confirmed_nonce = self._canonical_nonce(chain_confirmed_nonce)
        if chain_confirmed_nonce > chain_pending_nonce:
            raise ExecutionConflict("chain nonce observations are inconsistent")
        timestamp = self._now(now)
        denial_reason: str | None = None
        record: HostedExecution | None = None
        with self._write_session() as session:
            existing = self._existing_for_intent(session, intent)
            if existing is not None:
                self._require_exact_intent(existing, intent)
                return self._record(existing)

            if self.pilot_policy is not None:
                self._acquire_pilot_locks(
                    session,
                    tenant_id=intent.tenant_id,
                    node_id=intent.node_id,
                )
                existing = self._existing_for_intent(session, intent)
                if existing is not None:
                    self._require_exact_intent(existing, intent)
                    return self._record(existing)
                denial_reason = self._pilot_admission_denial(
                    session,
                    tenant_id=intent.tenant_id,
                    node_id=intent.node_id,
                    timestamp=timestamp,
                    include_quotas=True,
                )
                if denial_reason is not None:
                    self._add_gate_event(
                        session,
                        execution_id=None,
                        tenant_id=intent.tenant_id,
                        node_id=intent.node_id,
                        idempotency_key=intent.idempotency_key,
                        event_type="denied",
                        reason_code=denial_reason,
                        gas_cost_usd_micros=0,
                        now=timestamp,
                    )

            if denial_reason is None:
                for _attempt in range(4):
                    try:
                        with session.begin_nested():
                            relayer_nonce = self._allocate_relayer_nonce(
                                session,
                                chain=intent.chain,
                                relayer_address=intent.relayer_address,
                                chain_pending_nonce=chain_pending_nonce,
                                chain_confirmed_nonce=chain_confirmed_nonce,
                                now=timestamp,
                            )
                            row = HostedExecutionRow(
                                execution_id="exec_" + uuid4().hex[:32],
                                **self._intent_columns(intent),
                                relayer_nonce=relayer_nonce,
                                status=ExecutionState.PREFLIGHT_APPROVED.value,
                                broadcast_attempts=0,
                                confirmations=0,
                                reorg_state="none",
                                created_at=timestamp,
                                updated_at=timestamp,
                            )
                            session.add(row)
                            session.flush()
                            if self.pilot_policy is not None:
                                session.add(
                                    HostedGateReservationRow(
                                        execution_id=row.execution_id,
                                        tenant_id=intent.tenant_id,
                                        node_id=intent.node_id,
                                        idempotency_key=intent.idempotency_key,
                                        utc_day=utc_day(timestamp),
                                        state="reserved",
                                        gas_cost_usd_micros=0,
                                        gas_utc_day=None,
                                        created_at=timestamp,
                                        updated_at=timestamp,
                                    )
                                )
                                self._add_gate_event(
                                    session,
                                    execution_id=row.execution_id,
                                    tenant_id=intent.tenant_id,
                                    node_id=intent.node_id,
                                    idempotency_key=intent.idempotency_key,
                                    event_type="allowed",
                                    reason_code="pilot_admission_allowed",
                                    gas_cost_usd_micros=0,
                                    now=timestamp,
                                )
                                session.flush()
                        record = self._record(row)
                        break
                    except IntegrityError:
                        existing = self._existing_for_intent(session, intent)
                        if existing is not None:
                            self._require_exact_intent(existing, intent)
                            record = self._record(existing)
                            break
                if record is None:
                    raise ExecutionConflict("execution allocation could not be committed")
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        if record is None:  # pragma: no cover - guarded by the transaction path above
            raise ExecutionConflict("execution allocation could not be committed")
        return record

    def find_for_intent(self, intent: ExecutionIntent) -> HostedExecution | None:
        """Return the exact durable replay without requiring any chain dependency."""

        intent = self._validated_intent(intent)
        with self.sessions() as session:
            existing = self._existing_for_intent(session, intent)
            if existing is None:
                return None
            self._require_exact_intent(existing, intent)
            return self._record(existing)

    def find_for_identity(
        self,
        *,
        tenant_id: str,
        node_id: str,
        idempotency_key: str,
    ) -> HostedExecution | None:
        """Find one execution by the immutable authenticated lookup tuple."""

        for field_name, value in (
            ("tenant_id", tenant_id),
            ("node_id", node_id),
            ("idempotency_key", idempotency_key),
        ):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ExecutionConflict(f"{field_name} is invalid")
        statement = select(HostedExecutionRow).where(
            HostedExecutionRow.tenant_id == tenant_id,
            HostedExecutionRow.node_id == node_id,
            HostedExecutionRow.idempotency_key == idempotency_key,
        )
        with self.sessions() as session:
            row = session.scalar(statement)
            return self._record(row) if row is not None else None

    def get_execution(self, execution_id: str) -> HostedExecution | None:
        with self.sessions() as session:
            row = session.get(HostedExecutionRow, execution_id)
            return self._record(row) if row is not None else None

    def list_watchable_ids(
        self,
        *,
        chain: str,
        after_execution_id: str | None,
        limit: int,
    ) -> list[str]:
        """Return a bounded retry-fair set of reconciliation IDs."""

        if chain not in HOSTED_CHAIN_PROFILES:
            raise ValueError("watch chain is not supported")

        if after_execution_id is not None:
            if (
                not isinstance(after_execution_id, str)
                or not after_execution_id
                or len(after_execution_id) > 96
                or any(ord(char) < 0x21 or ord(char) > 0x7E for char in after_execution_id)
            ):
                raise ValueError("execution cursor is invalid")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("watch limit is unsafe")
        watchable_states = (
            ExecutionState.PREFLIGHT_APPROVED.value,
            ExecutionState.SIGNING.value,
            ExecutionState.SUBMITTED.value,
            ExecutionState.SUBMISSION_UNKNOWN.value,
            ExecutionState.SUBMISSION_REJECTED.value,
            ExecutionState.CONFIRMED.value,
            ExecutionState.FINALIZED.value,
        )
        statement = select(HostedExecutionRow.execution_id).where(
            HostedExecutionRow.chain == chain,
            or_(
                HostedExecutionRow.status.in_(watchable_states),
                (
                    HostedExecutionRow.status == ExecutionState.REVERTED.value
                )
                & HostedExecutionRow.release_evidence.is_(None),
            ),
        )
        if after_execution_id is not None:
            statement = statement.where(HostedExecutionRow.execution_id > after_execution_id)
        statement = statement.order_by(
            func.coalesce(HostedExecutionRow.watcher_attempted_at, 0),
            HostedExecutionRow.execution_id,
        ).limit(limit)
        with self.sessions() as session:
            return list(session.scalars(statement).all())

    def record_watcher_attempt(
        self,
        execution_id: str,
        *,
        now_ns: int | None = None,
    ) -> None:
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("execution ID is invalid")
        timestamp_ns = time.time_ns() if now_ns is None else now_ns
        if type(timestamp_ns) is not int or timestamp_ns <= 0:
            raise ValueError("watcher attempt timestamp is invalid")
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            row.watcher_attempted_at = timestamp_ns
            row.updated_at = max(row.updated_at, timestamp_ns // 1_000_000_000)
            session.flush()

    def assert_pilot_gate_open(
        self,
        *,
        tenant_id: str,
        node_id: str,
        now: int | None = None,
    ) -> None:
        """Read paused scopes early; funding mutations recheck and audit atomically."""

        self._pilot_identity(tenant_id=tenant_id, node_id=node_id)
        if self.pilot_policy is None:
            return
        timestamp = self._now(now)
        with self.sessions() as session:
            denial_reason = self._pilot_admission_denial(
                session,
                tenant_id=tenant_id,
                node_id=node_id,
                timestamp=timestamp,
                include_quotas=False,
            )
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)

    def set_pilot_pause(
        self,
        *,
        scope_type: str,
        paused: bool,
        reason_code: str,
        tenant_id: str = "",
        node_id: str = "",
        now: int | None = None,
    ) -> None:
        """Persist one operator pause or resume decision with an audit event."""

        if scope_type not in {"platform", "tenant", "node"}:
            raise ValueError("pilot pause scope is invalid")
        if type(paused) is not bool:
            raise ValueError("pilot pause state is invalid")
        if (
            not isinstance(reason_code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason_code) is None
        ):
            raise ValueError("pilot pause reason is invalid")
        if scope_type == "platform":
            if tenant_id or node_id:
                raise ValueError("platform pause scope is invalid")
        elif scope_type == "tenant":
            if not isinstance(tenant_id, str) or _IDENTIFIER.fullmatch(tenant_id) is None:
                raise ValueError("tenant pause scope is invalid")
            if node_id:
                raise ValueError("tenant pause scope is invalid")
        else:
            self._pilot_identity(tenant_id=tenant_id, node_id=node_id)
        timestamp = self._now(now)
        lock_tenant = tenant_id or "_platform"
        lock_node = node_id or ("_tenant" if tenant_id else "_platform")
        key = (scope_type, tenant_id, node_id)
        with self._write_session() as session:
            self._acquire_named_pilot_locks(
                session,
                (self._pilot_lock_name(scope_type, tenant_id, node_id),),
            )
            row = session.get(HostedGateControlRow, key)
            if row is None:
                row = HostedGateControlRow(
                    scope_type=scope_type,
                    tenant_id=tenant_id,
                    node_id=node_id,
                    paused=paused,
                    reason_code=reason_code,
                    updated_at=timestamp,
                )
                session.add(row)
            else:
                row.paused = paused
                row.reason_code = reason_code
                row.updated_at = timestamp
            self._add_gate_event(
                session,
                execution_id=None,
                tenant_id="" if scope_type == "platform" else lock_tenant,
                node_id="" if scope_type != "node" else lock_node,
                idempotency_key="",
                event_type="pause_changed",
                reason_code=reason_code,
                gas_cost_usd_micros=0,
                now=timestamp,
            )
            session.flush()

    def reserve_pilot_gas(
        self,
        execution_id: str,
        *,
        gas_cost_usd_micros: int,
        signing_claim_generation: int,
        now: int | None = None,
    ) -> int:
        """Atomically reserve a conservative USD gas ceiling before gas signing."""

        if self.pilot_policy is None:
            raise ExecutionConflict("pilot gate policy is unavailable")
        if type(gas_cost_usd_micros) is not int or gas_cost_usd_micros <= 0:
            raise ExecutionConflict("gas budget reservation is invalid")
        if type(signing_claim_generation) is not int or signing_claim_generation <= 0:
            raise ExecutionConflict("signing claim is invalid")
        timestamp = self._now(now)
        denial_reason: str | None = None
        with self._write_session() as session:
            execution = self._require_row(self._locked_execution(session, execution_id))
            if self._state(execution.status) is not ExecutionState.SIGNING:
                raise ExecutionConflict("execution is not awaiting gas reservation")
            if execution.signing_claim_generation != signing_claim_generation:
                raise ExecutionConflict("signing claim is stale")
            self._acquire_pilot_locks(
                session,
                tenant_id=execution.tenant_id,
                node_id=execution.node_id,
            )
            reservation = self._locked_gate_reservation(session, execution.execution_id)
            if reservation is None or reservation.state != "reserved":
                raise ExecutionConflict("pilot gate reservation is unavailable")
            denial_reason = self._pilot_admission_denial(
                session,
                tenant_id=execution.tenant_id,
                node_id=execution.node_id,
                timestamp=timestamp,
                include_quotas=False,
            )
            current_cost = reservation.gas_cost_usd_micros
            current_gas_day = reservation.gas_utc_day
            if denial_reason is None:
                day = utc_day(timestamp)
                node_total = self._pilot_gas_total(
                    session,
                    utc_day_value=day,
                    tenant_id=execution.tenant_id,
                    node_id=execution.node_id,
                    excluding_execution_id=execution.execution_id,
                )
                platform_total = self._pilot_gas_total(
                    session,
                    utc_day_value=day,
                    excluding_execution_id=execution.execution_id,
                )
                if (
                    node_total + gas_cost_usd_micros
                    > self.pilot_policy.max_gas_usd_micros_per_node_utc_day
                ):
                    denial_reason = "node_daily_gas_limit"
                elif (
                    platform_total + gas_cost_usd_micros
                    > self.pilot_policy.max_gas_usd_micros_platform_utc_day
                ):
                    denial_reason = "platform_daily_gas_limit"
            if denial_reason is not None:
                self._add_gate_event(
                    session,
                    execution_id=execution.execution_id,
                    tenant_id=execution.tenant_id,
                    node_id=execution.node_id,
                    idempotency_key=execution.idempotency_key,
                    event_type="denied",
                    reason_code=denial_reason,
                    gas_cost_usd_micros=gas_cost_usd_micros,
                    now=timestamp,
                )
            elif current_cost != gas_cost_usd_micros or current_gas_day != day:
                reservation.gas_cost_usd_micros = gas_cost_usd_micros
                reservation.gas_utc_day = day
                reservation.updated_at = timestamp
                self._add_gate_event(
                    session,
                    execution_id=execution.execution_id,
                    tenant_id=execution.tenant_id,
                    node_id=execution.node_id,
                    idempotency_key=execution.idempotency_key,
                    event_type="gas_reserved",
                    reason_code="gas_budget_reserved",
                    gas_cost_usd_micros=gas_cost_usd_micros,
                    now=timestamp,
                )
            session.flush()
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        return gas_cost_usd_micros

    def close(self) -> None:
        self.engine.dispose()

    def transition(
        self,
        execution_id: str,
        target: ExecutionState | str,
        *,
        expected: ExecutionState | str | None = None,
        now: int | None = None,
    ) -> HostedExecution:
        target = self._state(target)
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._locked_execution(session, execution_id)
            current = self._require_row(row)
            current_state = self._state(current.status)
            if expected is not None and current_state is not self._state(expected):
                raise ExecutionConflict("execution state changed")
            if target not in allowed_transitions(current_state):
                raise ExecutionConflict("execution state transition is not allowed")
            if target in {
                ExecutionState.SIGNING,
                ExecutionState.SIGNED,
                ExecutionState.SUBMITTED,
                ExecutionState.SUBMISSION_UNKNOWN,
                ExecutionState.CONFIRMED,
                ExecutionState.REVERTED,
                ExecutionState.REORG_REVIEW,
            }:
                raise ExecutionConflict(
                    "state requires dedicated persistence or watcher evidence"
                )
            if target in {ExecutionState.EXPIRED, ExecutionState.RELEASED} and (
                current.signature is not None or current.raw_transaction is not None
            ):
                raise ExecutionConflict("signed execution cannot be released")
            if (
                target in {ExecutionState.EXPIRED, ExecutionState.RELEASED}
                and timestamp < current.deadline
            ):
                raise ExecutionConflict("execution deadline has not expired")
            current.status = target.value
            if target is ExecutionState.RELEASED:
                current.released_at = timestamp
            elif target is ExecutionState.EXPIRED:
                current.expired_at = timestamp
            if target in {ExecutionState.EXPIRED, ExecutionState.RELEASED}:
                current.signing_claim_expires_at = None
                self._mark_gate_terminal(
                    session,
                    current,
                    state="released",
                    reason_code="deadline_expired",
                    clear_gas=True,
                    now=timestamp,
                )
            current.updated_at = timestamp
            session.flush()
            return self._record(current)

    def persist_signed_transaction(
        self,
        execution_id: str,
        *,
        signature: bytes,
        raw_transaction: bytes,
        signing_claim_generation: int,
        unsigned_transaction_hash: str | None = None,
        now: int | None = None,
    ) -> HostedExecution:
        if not isinstance(signature, bytes) or len(signature) != 65:
            raise ExecutionConflict("signature is invalid")
        if not isinstance(raw_transaction, bytes) or not raw_transaction:
            raise ExecutionConflict("raw transaction is invalid")
        if type(signing_claim_generation) is not int or signing_claim_generation <= 0:
            raise ExecutionConflict("signing claim is invalid")
        timestamp = self._now(now)
        raw_hash = _ethereum_transaction_hash(raw_transaction)
        denial_reason: str | None = None
        record: HostedExecution | None = None
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current_state = self._state(row.status)
            if row.signing_claim_generation != signing_claim_generation:
                raise ExecutionConflict("signing claim is stale")
            if current_state is ExecutionState.SIGNED:
                if row.signature != signature or row.raw_transaction != raw_transaction:
                    raise ExecutionConflict("signed raw transaction is immutable")
                return self._record(row)
            if current_state is not ExecutionState.SIGNING:
                raise ExecutionConflict("execution is not awaiting signing")
            if timestamp >= row.deadline:
                raise ExecutionConflict("execution deadline has expired")
            if self.pilot_policy is not None:
                self._acquire_pilot_locks(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                )
                denial_reason = self._pilot_admission_denial(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    timestamp=timestamp,
                    include_quotas=False,
                )
                if denial_reason is not None:
                    self._add_gate_event(
                        session,
                        execution_id=row.execution_id,
                        tenant_id=row.tenant_id,
                        node_id=row.node_id,
                        idempotency_key=row.idempotency_key,
                        event_type="denied",
                        reason_code=denial_reason,
                        gas_cost_usd_micros=0,
                        now=timestamp,
                    )
                else:
                    gate_reservation = self._locked_gate_reservation(
                        session, row.execution_id
                    )
                    if (
                        gate_reservation is None
                        or gate_reservation.state != "reserved"
                        or gate_reservation.gas_cost_usd_micros <= 0
                        or gate_reservation.gas_utc_day is None
                    ):
                        raise ExecutionConflict("gas budget reservation is unavailable")
            if denial_reason is None:
                row.signature = bytes(signature)
                row.raw_transaction = bytes(raw_transaction)
                row.raw_transaction_hash = raw_hash
                row.unsigned_transaction_hash = unsigned_transaction_hash
                row.signing_claim_expires_at = None
                row.status = ExecutionState.SIGNED.value
                row.updated_at = timestamp
                self._add_attempt(
                    session,
                    row,
                    attempt_kind="signed",
                    raw_transaction_hash=raw_hash,
                    attempt_number=0,
                    now=timestamp,
                )
                record = self._record(row)
            session.flush()
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        if record is None:  # pragma: no cover - guarded above
            raise ExecutionConflict("signed transaction persistence is unavailable")
        return record

    def claim_signing(
        self, execution_id: str, *, now: int | None = None
    ) -> tuple[HostedExecution, bool]:
        timestamp = self._now(now)
        denial_reason: str | None = None
        result: tuple[HostedExecution, bool] | None = None
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if self.pilot_policy is not None:
                self._acquire_pilot_locks(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                )
                denial_reason = self._pilot_admission_denial(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    timestamp=timestamp,
                    include_quotas=False,
                )
                if denial_reason is not None:
                    self._add_gate_event(
                        session,
                        execution_id=row.execution_id,
                        tenant_id=row.tenant_id,
                        node_id=row.node_id,
                        idempotency_key=row.idempotency_key,
                        event_type="denied",
                        reason_code=denial_reason,
                        gas_cost_usd_micros=0,
                        now=timestamp,
                    )
            if denial_reason is None:
                if current is ExecutionState.SIGNING:
                    if timestamp >= row.deadline:
                        raise ExecutionConflict("execution deadline has expired")
                    if (
                        row.signing_claim_generation <= 0
                        or row.signing_claim_expires_at is None
                    ):
                        raise ExecutionConflict("execution signing claim is invalid")
                    if timestamp < row.signing_claim_expires_at:
                        result = (self._record(row), False)
                    else:
                        row.signing_claim_generation += 1
                        row.signing_claim_expires_at = min(
                            row.deadline,
                            timestamp + SIGNING_CLAIM_LEASE_SECONDS,
                        )
                        row.updated_at = timestamp
                        result = (self._record(row), True)
                elif current is not ExecutionState.PREFLIGHT_APPROVED:
                    raise ExecutionConflict("execution cannot be claimed for signing")
                elif timestamp >= row.deadline:
                    raise ExecutionConflict("execution deadline has expired")
                else:
                    row.status = ExecutionState.SIGNING.value
                    row.signing_claim_generation += 1
                    row.signing_claim_expires_at = min(
                        row.deadline,
                        timestamp + SIGNING_CLAIM_LEASE_SECONDS,
                    )
                    row.updated_at = timestamp
                    result = (self._record(row), True)
            session.flush()
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        if result is None:  # pragma: no cover - guarded above
            raise ExecutionConflict("execution signing claim is unavailable")
        return result

    def claim_submission(
        self, execution_id: str, *, now: int | None = None
    ) -> tuple[HostedExecution, bool]:
        timestamp = self._now(now)
        denial_reason: str | None = None
        result: tuple[HostedExecution, bool] | None = None
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if self.pilot_policy is not None:
                self._acquire_pilot_locks(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                )
                denial_reason = self._pilot_admission_denial(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    timestamp=timestamp,
                    include_quotas=False,
                )
                if denial_reason is None:
                    denial_reason = self._ensure_pilot_gas_reservation(
                        session,
                        row,
                        timestamp=timestamp,
                    )
                if denial_reason is not None:
                    self._add_gate_event(
                        session,
                        execution_id=row.execution_id,
                        tenant_id=row.tenant_id,
                        node_id=row.node_id,
                        idempotency_key=row.idempotency_key,
                        event_type="denied",
                        reason_code=denial_reason,
                        gas_cost_usd_micros=0,
                        now=timestamp,
                    )
            if denial_reason is None:
                if current is ExecutionState.SUBMISSION_UNKNOWN:
                    self._require_raw_transaction(row)
                    result = (self._record(row), False)
                elif current is not ExecutionState.SIGNED:
                    raise ExecutionConflict("execution cannot be claimed for submission")
                else:
                    self._require_raw_transaction(row)
                    if row.raw_transaction_hash is None:
                        raise ExecutionConflict("transaction hash is missing")
                    row.broadcast_attempts += 1
                    row.broadcasted_at = timestamp
                    row.status = ExecutionState.SUBMISSION_UNKNOWN.value
                    row.updated_at = timestamp
                    self._add_attempt(
                        session,
                        row,
                        attempt_kind="broadcast_claimed",
                        raw_transaction_hash=row.raw_transaction_hash,
                        attempt_number=row.broadcast_attempts,
                        now=timestamp,
                    )
                    result = (self._record(row), True)
            session.flush()
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        if result is None:  # pragma: no cover - guarded above
            raise ExecutionConflict("execution submission claim is unavailable")
        return result

    def mark_submitted(
        self, execution_id: str, *, now: int | None = None
    ) -> HostedExecution:
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if current is ExecutionState.SUBMITTED:
                self._require_raw_transaction(row)
                return self._record(row)
            if current not in {
                ExecutionState.SIGNED,
                ExecutionState.SUBMISSION_UNKNOWN,
                ExecutionState.SUBMISSION_REJECTED,
            }:
                raise ExecutionConflict("only a signed execution may be submitted")
            self._require_raw_transaction(row)
            if row.raw_transaction_hash is None:
                raise ExecutionConflict("transaction hash is missing")
            row.status = ExecutionState.SUBMITTED.value
            if current is ExecutionState.SIGNED:
                row.broadcast_attempts += 1
                row.broadcasted_at = timestamp
            row.submission_failure_code = None
            row.updated_at = timestamp
            if current is ExecutionState.SIGNED:
                self._add_attempt(
                    session,
                    row,
                    attempt_kind="broadcast",
                    raw_transaction_hash=row.raw_transaction_hash,
                    attempt_number=row.broadcast_attempts,
                    now=timestamp,
                )
            session.flush()
            return self._record(row)

    def mark_submission_unknown(
        self, execution_id: str, *, now: int | None = None
    ) -> HostedExecution:
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if current is ExecutionState.SUBMISSION_UNKNOWN:
                self._require_raw_transaction(row)
                return self._record(row)
            if current not in {
                ExecutionState.SIGNED,
                ExecutionState.SUBMITTED,
                ExecutionState.SUBMISSION_REJECTED,
            }:
                raise ExecutionConflict("execution cannot become submission_unknown")
            self._require_raw_transaction(row)
            if current is ExecutionState.SUBMISSION_REJECTED:
                row.submission_failure_code = None
            if current is ExecutionState.SIGNED:
                if row.raw_transaction_hash is None:
                    raise ExecutionConflict("transaction hash is missing")
                row.broadcast_attempts += 1
                row.broadcasted_at = timestamp
                self._add_attempt(
                    session,
                    row,
                    attempt_kind="broadcast_unknown",
                    raw_transaction_hash=row.raw_transaction_hash,
                    attempt_number=row.broadcast_attempts,
                    now=timestamp,
                )
            row.status = ExecutionState.SUBMISSION_UNKNOWN.value
            row.updated_at = timestamp
            session.flush()
            return self._record(row)

    def mark_submission_rejected(
        self,
        execution_id: str,
        *,
        reason_code: str,
        now: int | None = None,
    ) -> HostedExecution:
        if (
            not isinstance(reason_code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code) is None
        ):
            raise ExecutionConflict("submission failure code is invalid")
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if current is ExecutionState.SUBMISSION_REJECTED:
                self._require_raw_transaction(row)
                if row.submission_failure_code != reason_code:
                    raise ExecutionConflict("submission failure reason conflicts")
                return self._record(row)
            if current not in {
                ExecutionState.SIGNED,
                ExecutionState.SUBMISSION_UNKNOWN,
            }:
                raise ExecutionConflict("only a signed execution may be rejected")
            self._require_raw_transaction(row)
            if row.raw_transaction_hash is None:
                raise ExecutionConflict("transaction hash is missing")
            if current is ExecutionState.SIGNED:
                row.broadcast_attempts += 1
                row.broadcasted_at = timestamp
            row.submission_failure_code = reason_code
            row.status = ExecutionState.SUBMISSION_REJECTED.value
            row.updated_at = timestamp
            if current is ExecutionState.SIGNED:
                self._add_attempt(
                    session,
                    row,
                    attempt_kind="broadcast_rejected",
                    raw_transaction_hash=row.raw_transaction_hash,
                    attempt_number=row.broadcast_attempts,
                    now=timestamp,
                )
            session.flush()
            return self._record(row)

    def rebroadcast_raw_transaction(
        self,
        execution_id: str,
        raw_transaction: bytes | None = None,
        *,
        now: int | None = None,
    ) -> bytes:
        timestamp = self._now(now)
        denial_reason: str | None = None
        stored_result: bytes | None = None
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            if self._state(row.status) not in {
                ExecutionState.SUBMITTED,
                ExecutionState.SUBMISSION_UNKNOWN,
                ExecutionState.SUBMISSION_REJECTED,
            }:
                raise ExecutionConflict("replacement or rebroadcast is not allowed")
            stored = self._require_raw_transaction(row)
            if raw_transaction is not None and raw_transaction != stored:
                raise ExecutionConflict("raw transaction replacement is forbidden")
            if row.raw_transaction_hash is None:
                raise ExecutionConflict("transaction hash is missing")
            if self.pilot_policy is not None:
                self._acquire_pilot_locks(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                )
                denial_reason = self._pilot_admission_denial(
                    session,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    timestamp=timestamp,
                    include_quotas=False,
                )
                if denial_reason is None:
                    denial_reason = self._ensure_pilot_gas_reservation(
                        session,
                        row,
                        timestamp=timestamp,
                    )
                if denial_reason is not None:
                    self._add_gate_event(
                        session,
                        execution_id=row.execution_id,
                        tenant_id=row.tenant_id,
                        node_id=row.node_id,
                        idempotency_key=row.idempotency_key,
                        event_type="denied",
                        reason_code=denial_reason,
                        gas_cost_usd_micros=0,
                        now=timestamp,
                    )
            if denial_reason is None:
                row.broadcast_attempts += 1
                row.updated_at = timestamp
                self._add_attempt(
                    session,
                    row,
                    attempt_kind="rebroadcast",
                    raw_transaction_hash=row.raw_transaction_hash,
                    attempt_number=row.broadcast_attempts,
                    now=timestamp,
                )
                stored_result = stored
            session.flush()
        if denial_reason is not None:
            raise PilotGateDenied(denial_reason)
        if stored_result is None:  # pragma: no cover - guarded above
            raise ExecutionConflict("persisted transaction is unavailable")
        return stored_result

    def release_expired(
        self, execution_id: str, *, now: int | None = None
    ) -> HostedExecution:
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            if current in {ExecutionState.RELEASED, ExecutionState.EXPIRED}:
                return self._record(row)
            if current not in {
                ExecutionState.PREFLIGHT_APPROVED,
                ExecutionState.SIGNING,
            }:
                raise ExecutionConflict("signed execution cannot be released")
            if timestamp < row.deadline:
                raise ExecutionConflict("execution deadline has not expired")
            if row.signature is not None or row.raw_transaction is not None:
                raise ExecutionConflict("signed execution cannot be released")
            row.status = ExecutionState.RELEASED.value
            row.signing_claim_expires_at = None
            row.released_at = timestamp
            row.updated_at = timestamp
            self._mark_gate_terminal(
                session,
                row,
                state="released",
                reason_code="deadline_expired",
                clear_gas=True,
                now=timestamp,
            )
            session.flush()
            return self._record(row)

    def confirm(
        self,
        execution_id: str,
        *,
        receipt_status: int,
        receipt_block_number: int,
        receipt_block_hash: str,
        confirmations: int,
        safe_block_number: int,
        safe_block_hash: str,
        watcher_version: str,
        finality_boundary: str,
        now: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> HostedExecution:
        if receipt_status != 1:
            raise ExecutionConflict("only a successful receipt may be confirmed")
        return self._record_observation(
            execution_id,
            target=ExecutionState.CONFIRMED,
            receipt_status=receipt_status,
            receipt_block_number=receipt_block_number,
            receipt_block_hash=receipt_block_hash,
            confirmations=confirmations,
            safe_block_number=safe_block_number,
            safe_block_hash=safe_block_hash,
            watcher_version=watcher_version,
            finality_boundary=finality_boundary,
            evidence=(
                {"boundary": finality_boundary} if evidence is None else evidence
            ),
            now=now,
        )

    def finalize(
        self,
        execution_id: str,
        *,
        finality_boundary: str,
        now: int | None = None,
    ) -> HostedExecution:
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            current = self._state(row.status)
            profile = HOSTED_CHAIN_PROFILES.get(row.chain)
            if profile is None:
                raise ExecutionConflict("execution chain is not supported")
            if finality_boundary != profile.finality_boundary:
                raise ExecutionConflict("finality boundary does not match execution chain")
            if current is ExecutionState.FINALIZED:
                if row.safe_block_number is None or row.safe_block_hash is None:
                    raise ExecutionConflict("finality evidence is missing")
                if row.finality_boundary != profile.finality_boundary:
                    raise ExecutionConflict("finality boundary does not match execution chain")
                return self._record(row)
            if current is not ExecutionState.CONFIRMED:
                raise ExecutionConflict("only a confirmed execution may be finalized")
            if row.safe_block_number is None or row.safe_block_hash is None:
                raise ExecutionConflict("finality evidence is missing")
            if finality_boundary != row.finality_boundary:
                raise ExecutionConflict("finality boundary conflicts with confirmation")
            if row.finality_boundary != profile.finality_boundary:
                raise ExecutionConflict("finality boundary does not match execution chain")
            row.status = ExecutionState.FINALIZED.value
            row.finalized_at = timestamp
            row.updated_at = timestamp
            self._mark_gate_terminal(
                session,
                row,
                state="settled",
                reason_code="execution_finalized",
                clear_gas=False,
                now=timestamp,
            )
            session.flush()
            return self._record(row)

    def revert(
        self,
        execution_id: str,
        *,
        receipt_status: int,
        receipt_block_number: int,
        receipt_block_hash: str,
        confirmations: int,
        safe_block_number: int,
        safe_block_hash: str,
        accepted_transfer: bool,
        watcher_version: str,
        finality_boundary: str,
        now: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> HostedExecution:
        if receipt_status != 0 or accepted_transfer:
            raise ExecutionConflict("revert requires proof of no accepted transfer")
        return self._record_observation(
            execution_id,
            target=ExecutionState.REVERTED,
            receipt_status=receipt_status,
            receipt_block_number=receipt_block_number,
            receipt_block_hash=receipt_block_hash,
            confirmations=confirmations,
            safe_block_number=safe_block_number,
            safe_block_hash=safe_block_hash,
            watcher_version=watcher_version,
            finality_boundary=finality_boundary,
            evidence=(
                {"accepted_transfer": False} if evidence is None else evidence
            ),
            now=now,
        )

    def release_reverted(
        self,
        execution_id: str,
        *,
        receipt_status: int,
        receipt_block_number: int,
        receipt_block_hash: str,
        confirmations: int,
        safe_block_number: int,
        safe_block_hash: str,
        watcher_version: str,
        finality_boundary: str,
        release_evidence: Mapping[str, Any],
        now: int | None = None,
    ) -> HostedExecution:
        """Release a reverted execution only after immutable replay-safe proof."""

        evidence = _release_evidence(release_evidence)
        if type(receipt_status) is not int or receipt_status != 0:
            raise ExecutionConflict("release requires a reverted receipt")
        if (
            not isinstance(receipt_block_hash, str)
            or re.fullmatch(r"0x[0-9a-fA-F]{64}", receipt_block_hash) is None
        ):
            raise ExecutionConflict("receipt block evidence is invalid")
        if (
            not isinstance(safe_block_hash, str)
            or re.fullmatch(r"0x[0-9a-fA-F]{64}", safe_block_hash) is None
        ):
            raise ExecutionConflict("safe boundary evidence is invalid")
        if (
            not isinstance(watcher_version, str)
            or not watcher_version
            or len(watcher_version) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in watcher_version)
        ):
            raise ExecutionConflict("watcher evidence is invalid")
        timestamp = self._now(now)
        boundary_timestamp = evidence["finality_boundary_timestamp"]
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            profile = HOSTED_CHAIN_PROFILES.get(row.chain)
            if profile is None:
                raise ExecutionConflict("execution chain is not supported")
            if finality_boundary != profile.finality_boundary:
                raise ExecutionConflict("finality boundary does not match execution chain")
            _require_finality_boundary(
                receipt_block_number=receipt_block_number,
                confirmations=confirmations,
                safe_block_number=safe_block_number,
                safe_block_hash=safe_block_hash,
                finality_boundary=finality_boundary,
                minimum_confirmations=profile.min_confirmation_depth,
            )
            if boundary_timestamp < row.deadline:
                raise ExecutionConflict("release finality boundary precedes deadline")
            if timestamp < boundary_timestamp:
                raise ExecutionConflict("release finality boundary is in the future")

            current = self._state(row.status)
            receipt_identity_matches = (
                row.receipt_status == receipt_status
                and row.receipt_block_number == receipt_block_number
                and isinstance(row.receipt_block_hash, str)
                and row.receipt_block_hash.lower() == receipt_block_hash.lower()
                and row.watcher_version == watcher_version
                and row.finality_boundary == finality_boundary
            )
            if not receipt_identity_matches:
                raise ExecutionConflict("release evidence identity conflicts")
            if current is ExecutionState.RELEASED:
                same_release = (
                    row.confirmations == confirmations
                    and row.safe_block_number == safe_block_number
                    and isinstance(row.safe_block_hash, str)
                    and row.safe_block_hash.lower() == safe_block_hash.lower()
                    and row.release_evidence == evidence
                )
                if not same_release:
                    raise ExecutionConflict("release evidence changed")
                return self._record(row)
            if current is not ExecutionState.REVERTED:
                raise ExecutionConflict("only a reverted execution can be released")
            if row.release_evidence is not None:
                raise ExecutionConflict("release evidence is already recorded")
            if row.reverted_at is None or timestamp < row.reverted_at:
                raise ExecutionConflict("release timestamp is invalid")
            if (
                type(row.confirmations) is not int
                or confirmations < row.confirmations
                or type(row.safe_block_number) is not int
                or safe_block_number < row.safe_block_number
            ):
                raise ExecutionConflict("release finality boundary regressed")
            if (
                safe_block_number == row.safe_block_number
                and (
                    not isinstance(row.safe_block_hash, str)
                    or row.safe_block_hash.lower() != safe_block_hash.lower()
                )
            ):
                raise ExecutionConflict("release finality boundary changed")
            row.release_evidence = deepcopy(evidence)
            row.confirmations = confirmations
            row.safe_block_number = safe_block_number
            row.safe_block_hash = safe_block_hash.lower()
            row.status = ExecutionState.RELEASED.value
            row.released_at = timestamp
            row.updated_at = timestamp
            self._release_gate_reservation(
                session,
                row,
                now=timestamp,
            )
            session.flush()
            return self._record(row)

    def mark_reorg_review(
        self,
        execution_id: str,
        *,
        evidence: dict[str, Any],
        now: int | None = None,
    ) -> HostedExecution:
        evidence = _public_evidence(
            evidence,
            allowed_keys=_REORG_EVIDENCE_KEYS,
        )
        if evidence.get("canonical") is not False:
            raise ExecutionConflict("reorg evidence is invalid")
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            if self._state(row.status) is not ExecutionState.FINALIZED:
                raise ExecutionConflict("only finalized execution can enter reorg_review")
            row.status = ExecutionState.REORG_REVIEW.value
            row.reorg_state = "review"
            row.reorg_evidence = deepcopy(evidence)
            row.reorg_reviewed_at = timestamp
            row.updated_at = timestamp
            session.flush()
            return self._record(row)

    def _record_observation(
        self,
        execution_id: str,
        *,
        target: ExecutionState,
        receipt_status: int,
        receipt_block_number: int,
        receipt_block_hash: str,
        confirmations: int,
        safe_block_number: int | None,
        safe_block_hash: str | None,
        watcher_version: str,
        finality_boundary: str,
        evidence: dict[str, Any],
        now: int | None,
    ) -> HostedExecution:
        if (
            not isinstance(watcher_version, str)
            or not watcher_version
            or len(watcher_version) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in watcher_version)
        ):
            raise ExecutionConflict("watcher evidence is invalid")
        evidence = _public_evidence(
            evidence,
            allowed_keys=_OBSERVATION_EVIDENCE_KEYS,
        )
        timestamp = self._now(now)
        with self._write_session() as session:
            row = self._require_row(self._locked_execution(session, execution_id))
            profile = HOSTED_CHAIN_PROFILES.get(row.chain)
            if profile is None:
                raise ExecutionConflict("execution chain is not supported")
            if finality_boundary != profile.finality_boundary:
                raise ExecutionConflict("finality boundary does not match execution chain")
            _require_finality_boundary(
                receipt_block_number=receipt_block_number,
                confirmations=confirmations,
                safe_block_number=safe_block_number,
                safe_block_hash=safe_block_hash,
                finality_boundary=finality_boundary,
                minimum_confirmations=profile.min_confirmation_depth,
            )
            current = self._state(row.status)
            if current is target:
                return self._replayed_observation(
                    session,
                    row,
                    target=target,
                    receipt_status=receipt_status,
                    receipt_block_number=receipt_block_number,
                    receipt_block_hash=receipt_block_hash,
                    confirmations=confirmations,
                    safe_block_number=safe_block_number,
                    safe_block_hash=safe_block_hash,
                    watcher_version=watcher_version,
                    finality_boundary=finality_boundary,
                    evidence=evidence,
                )
            if target is ExecutionState.CONFIRMED and current not in {
                ExecutionState.SUBMITTED,
                ExecutionState.SUBMISSION_UNKNOWN,
                ExecutionState.SUBMISSION_REJECTED,
            }:
                raise ExecutionConflict("execution is not awaiting confirmation")
            if target is ExecutionState.REVERTED and current not in {
                ExecutionState.SUBMITTED,
                ExecutionState.SUBMISSION_UNKNOWN,
                ExecutionState.SUBMISSION_REJECTED,
            }:
                raise ExecutionConflict("execution is not awaiting revert evidence")
            if row.raw_transaction_hash is None:
                raise ExecutionConflict("transaction hash is missing")
            tx_hash = row.raw_transaction_hash
            row.receipt_status = receipt_status
            row.receipt_block_number = receipt_block_number
            row.receipt_block_hash = receipt_block_hash.lower()
            row.confirmations = confirmations
            row.safe_block_number = safe_block_number
            row.safe_block_hash = safe_block_hash.lower() if safe_block_hash else None
            row.watcher_version = watcher_version
            row.finality_boundary = finality_boundary
            if target is ExecutionState.REVERTED:
                row.reverted_at = timestamp
            else:
                row.confirmed_at = timestamp
            row.status = target.value
            row.updated_at = timestamp
            if target is ExecutionState.REVERTED:
                self._mark_gate_terminal(
                    session,
                    row,
                    state="settled",
                    reason_code="execution_reverted",
                    clear_gas=False,
                    now=timestamp,
                )
            session.add(
                HostedExecutionObservationRow(
                    observation_id="observation_" + uuid4().hex[:32],
                    execution_id=row.execution_id,
                    tx_hash=tx_hash,
                    block_number=receipt_block_number,
                    block_hash=receipt_block_hash.lower(),
                    receipt_status=receipt_status,
                    confirmations=confirmations,
                    safe_block_number=safe_block_number,
                    safe_block_hash=safe_block_hash.lower() if safe_block_hash else None,
                    watcher_version=watcher_version,
                    canonical=True,
                    evidence=deepcopy(evidence),
                    observed_at=timestamp,
                )
            )
            session.flush()
            return self._record(row)

    def _replayed_observation(
        self,
        session: Any,
        row: HostedExecutionRow,
        *,
        target: ExecutionState,
        receipt_status: int,
        receipt_block_number: int,
        receipt_block_hash: str,
        confirmations: int,
        safe_block_number: int | None,
        safe_block_hash: str | None,
        watcher_version: str,
        finality_boundary: str,
        evidence: dict[str, Any],
    ) -> HostedExecution:
        """Return an exact watcher replay without appending an observation."""
        self._require_raw_transaction(row)
        expected_block_hash = receipt_block_hash.lower()
        expected_safe_hash = safe_block_hash.lower() if safe_block_hash else None
        statement = select(HostedExecutionObservationRow).where(
            HostedExecutionObservationRow.execution_id == row.execution_id
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        observations = session.scalars(statement).all()
        if len(observations) != 1:
            raise ExecutionConflict("watcher observation replay is inconsistent")
        observation = observations[0]
        if (
            observation.tx_hash != row.raw_transaction_hash
            or observation.block_number != receipt_block_number
            or observation.block_hash.lower() != expected_block_hash
            or observation.receipt_status != receipt_status
            or observation.confirmations != confirmations
            or observation.safe_block_number != safe_block_number
            or (
                observation.safe_block_hash.lower()
                if observation.safe_block_hash
                else None
            )
            != expected_safe_hash
            or observation.watcher_version != watcher_version
            or observation.canonical is not True
            or observation.evidence != evidence
            or row.receipt_status != receipt_status
            or row.receipt_block_number != receipt_block_number
            or (
                row.receipt_block_hash.lower()
                if row.receipt_block_hash
                else None
            )
            != expected_block_hash
            or row.confirmations != confirmations
            or row.safe_block_number != safe_block_number
            or (
                row.safe_block_hash.lower() if row.safe_block_hash else None
            )
            != expected_safe_hash
            or row.watcher_version != watcher_version
            or row.finality_boundary != finality_boundary
        ):
            raise ExecutionConflict("watcher observation replay conflicts with evidence")
        return self._record(row)

    def _pilot_admission_denial(
        self,
        session: Any,
        *,
        tenant_id: str,
        node_id: str,
        timestamp: int,
        include_quotas: bool,
    ) -> str | None:
        policy = self.pilot_policy
        if policy is None:
            return None
        controls = (
            (("platform", "", ""), "platform_paused"),
            (("tenant", tenant_id, ""), "tenant_paused"),
            (("node", tenant_id, node_id), "node_paused"),
        )
        for key, reason_code in controls:
            row = session.get(HostedGateControlRow, key)
            if row is not None and row.paused is True:
                return reason_code
        if not include_quotas:
            return None
        scope = (
            HostedGateReservationRow.tenant_id == tenant_id,
            HostedGateReservationRow.node_id == node_id,
        )
        in_flight = int(
            session.scalar(
                select(func.count())
                .select_from(HostedGateReservationRow)
                .where(*scope, HostedGateReservationRow.state == "reserved")
            )
            or 0
        )
        if in_flight >= policy.max_in_flight_per_node:
            return "node_in_flight_limit"
        accepted_today = int(
            session.scalar(
                select(func.count())
                .select_from(HostedGateReservationRow)
                .where(
                    *scope,
                    HostedGateReservationRow.utc_day == utc_day(timestamp),
                )
            )
            or 0
        )
        if accepted_today >= policy.max_accepted_per_node_utc_day:
            return "node_daily_limit"
        accepted_lifetime = int(
            session.scalar(
                select(func.count())
                .select_from(HostedGateReservationRow)
                .where(*scope)
            )
            or 0
        )
        if accepted_lifetime >= policy.max_accepted_per_node_lifetime:
            return "node_lifetime_limit"
        return None

    def _pilot_gas_total(
        self,
        session: Any,
        *,
        utc_day_value: int,
        tenant_id: str | None = None,
        node_id: str | None = None,
        excluding_execution_id: str,
    ) -> int:
        statement = select(
            func.coalesce(func.sum(HostedGateReservationRow.gas_cost_usd_micros), 0)
        ).where(
            HostedGateReservationRow.gas_utc_day == utc_day_value,
            HostedGateReservationRow.execution_id != excluding_execution_id,
        )
        if tenant_id is not None:
            statement = statement.where(HostedGateReservationRow.tenant_id == tenant_id)
        if node_id is not None:
            statement = statement.where(HostedGateReservationRow.node_id == node_id)
        return int(session.scalar(statement) or 0)

    def _ensure_pilot_gas_reservation(
        self,
        session: Any,
        row: HostedExecutionRow,
        *,
        timestamp: int,
    ) -> str | None:
        """Fail closed or conservatively meter a pre-PilotGate signed execution."""

        policy = self.pilot_policy
        if policy is None:  # pragma: no cover - callers guard this path
            raise ExecutionConflict("pilot gate policy is unavailable")
        reservation = self._locked_gate_reservation(session, row.execution_id)
        if reservation is None or reservation.state != "reserved":
            raise ExecutionConflict("pilot gate reservation is unavailable")
        day = utc_day(timestamp)
        if reservation.gas_cost_usd_micros > 0:
            if reservation.gas_utc_day is None:
                raise ExecutionConflict("pilot gate gas reservation is invalid")
            if reservation.gas_utc_day == day:
                return None
            gas_cost = reservation.gas_cost_usd_micros
            reason_code = "gas_budget_reassigned"
        else:
            if reservation.gas_utc_day is not None:
                raise ExecutionConflict("pilot gate gas reservation is invalid")
            gas_cost = policy.max_gas_usd_micros_per_node_utc_day
            reason_code = "legacy_gas_budget_reserved"

        node_total = self._pilot_gas_total(
            session,
            utc_day_value=day,
            tenant_id=row.tenant_id,
            node_id=row.node_id,
            excluding_execution_id=row.execution_id,
        )
        if node_total + gas_cost > policy.max_gas_usd_micros_per_node_utc_day:
            return "node_daily_gas_limit"
        platform_total = self._pilot_gas_total(
            session,
            utc_day_value=day,
            excluding_execution_id=row.execution_id,
        )
        if platform_total + gas_cost > policy.max_gas_usd_micros_platform_utc_day:
            return "platform_daily_gas_limit"

        reservation.gas_cost_usd_micros = gas_cost
        reservation.gas_utc_day = day
        reservation.updated_at = timestamp
        self._add_gate_event(
            session,
            execution_id=row.execution_id,
            tenant_id=row.tenant_id,
            node_id=row.node_id,
            idempotency_key=row.idempotency_key,
            event_type="gas_reserved",
            reason_code=reason_code,
            gas_cost_usd_micros=gas_cost,
            now=timestamp,
        )
        return None

    def _acquire_pilot_locks(
        self,
        session: Any,
        *,
        tenant_id: str,
        node_id: str,
    ) -> None:
        self._acquire_named_pilot_locks(
            session,
            (
                self._pilot_lock_name("platform", "", ""),
                self._pilot_lock_name("tenant", tenant_id, ""),
                self._pilot_lock_name("node", tenant_id, node_id),
            ),
        )

    def _acquire_named_pilot_locks(
        self,
        session: Any,
        lock_names: tuple[str, ...],
    ) -> None:
        if self.dialect_name == "sqlite":
            return
        for name in sorted(set(lock_names)):
            digest = hashlib.sha256(name.encode("utf-8")).digest()
            key = int.from_bytes(digest[:8], "big", signed=True)
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": key},
            )

    @staticmethod
    def _pilot_lock_name(scope_type: str, tenant_id: str, node_id: str) -> str:
        return f"agentonomy-hosted-gate:{scope_type}:{tenant_id}:{node_id}"

    @staticmethod
    def _pilot_identity(*, tenant_id: str, node_id: str) -> None:
        for field_name, value in (("tenant_id", tenant_id), ("node_id", node_id)):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ExecutionConflict(f"{field_name} is invalid")

    def _locked_gate_reservation(
        self,
        session: Any,
        execution_id: str,
    ) -> HostedGateReservationRow | None:
        statement = select(HostedGateReservationRow).where(
            HostedGateReservationRow.execution_id == execution_id
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _add_gate_event(
        session: Any,
        *,
        execution_id: str | None,
        tenant_id: str,
        node_id: str,
        idempotency_key: str,
        event_type: str,
        reason_code: str,
        gas_cost_usd_micros: int,
        now: int,
    ) -> None:
        session.add(
            HostedGateEventRow(
                event_id="gate_event_" + uuid4().hex[:32],
                execution_id=execution_id,
                tenant_id=tenant_id,
                node_id=node_id,
                idempotency_key=idempotency_key,
                event_type=event_type,
                reason_code=reason_code,
                gas_cost_usd_micros=gas_cost_usd_micros,
                created_at=now,
            )
        )

    def _mark_gate_terminal(
        self,
        session: Any,
        row: HostedExecutionRow,
        *,
        state: str,
        reason_code: str,
        clear_gas: bool,
        now: int,
    ) -> None:
        if self.pilot_policy is None:
            return
        reservation = self._locked_gate_reservation(session, row.execution_id)
        if reservation is None:
            raise ExecutionConflict("pilot gate reservation is unavailable")
        if reservation.state == state:
            return
        if reservation.state != "reserved":
            raise ExecutionConflict("pilot gate reservation state conflicts")
        reservation.state = state
        if clear_gas:
            reservation.gas_cost_usd_micros = 0
            reservation.gas_utc_day = None
        reservation.updated_at = now
        self._add_gate_event(
            session,
            execution_id=row.execution_id,
            tenant_id=row.tenant_id,
            node_id=row.node_id,
            idempotency_key=row.idempotency_key,
            event_type=state,
            reason_code=reason_code,
            gas_cost_usd_micros=reservation.gas_cost_usd_micros,
            now=now,
        )

    def _release_gate_reservation(
        self,
        session: Any,
        row: HostedExecutionRow,
        *,
        now: int,
    ) -> None:
        """Close a reverted gate reservation without refunding spent gas."""

        if self.pilot_policy is None:
            return
        reservation = self._locked_gate_reservation(session, row.execution_id)
        if reservation is None:
            raise ExecutionConflict("pilot gate reservation is unavailable")
        if reservation.state == "released":
            return
        if reservation.state not in {"reserved", "settled"}:
            raise ExecutionConflict("pilot gate reservation state conflicts")
        reservation.state = "released"
        reservation.updated_at = now
        self._add_gate_event(
            session,
            execution_id=row.execution_id,
            tenant_id=row.tenant_id,
            node_id=row.node_id,
            idempotency_key=row.idempotency_key,
            event_type="released",
            reason_code="safe_revert_release",
            gas_cost_usd_micros=reservation.gas_cost_usd_micros,
            now=now,
        )

    def _allocate_relayer_nonce(
        self,
        session: Any,
        *,
        chain: str,
        relayer_address: str,
        chain_pending_nonce: int,
        chain_confirmed_nonce: int,
        now: int,
    ) -> int:
        statement = select(RelayerNonceRow).where(
            RelayerNonceRow.chain == chain,
            RelayerNonceRow.relayer_address == relayer_address,
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            row = RelayerNonceRow(
                chain=chain,
                relayer_address=relayer_address,
                next_nonce=chain_pending_nonce + 1,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return chain_pending_nonce
        active_nonces = select(HostedExecutionRow.relayer_nonce).where(
            HostedExecutionRow.chain == chain,
            HostedExecutionRow.relayer_address == relayer_address,
            HostedExecutionRow.status.not_in(
                (ExecutionState.EXPIRED.value, ExecutionState.RELEASED.value)
            ),
        )
        tainted_nonces = select(HostedExecutionRow.relayer_nonce).where(
            HostedExecutionRow.chain == chain,
            HostedExecutionRow.relayer_address == relayer_address,
            or_(
                HostedExecutionRow.signature.is_not(None),
                HostedExecutionRow.raw_transaction.is_not(None),
            ),
        )
        recyclable_nonce = session.scalar(
            select(func.min(HostedExecutionRow.relayer_nonce)).where(
                HostedExecutionRow.chain == chain,
                HostedExecutionRow.relayer_address == relayer_address,
                HostedExecutionRow.status.in_(
                    (ExecutionState.EXPIRED.value, ExecutionState.RELEASED.value)
                ),
                HostedExecutionRow.signature.is_(None),
                HostedExecutionRow.raw_transaction.is_(None),
                HostedExecutionRow.relayer_nonce >= chain_confirmed_nonce,
                HostedExecutionRow.relayer_nonce.not_in(active_nonces),
                HostedExecutionRow.relayer_nonce.not_in(tainted_nonces),
            )
        )
        if recyclable_nonce is not None:
            row.updated_at = now
            session.flush()
            return int(recyclable_nonce)
        nonce = int(row.next_nonce)
        if nonce < 0:
            raise ExecutionConflict("relayer nonce allocator is invalid")
        nonce = max(nonce, chain_pending_nonce)
        row.next_nonce = nonce + 1
        row.updated_at = now
        session.flush()
        return nonce

    @staticmethod
    def _intent_columns(intent: ExecutionIntent) -> dict[str, Any]:
        columns = {
            **intent.model_dump(mode="json"),
            "canonical_payload": intent.canonical_payload(),
            "canonical_hash": intent.canonical_hash,
        }
        columns.pop("request_id")
        columns.pop("request_hash")
        columns["owner_nonce"] = str(intent.owner_nonce)
        return columns

    def _existing_for_intent(self, session: Any, intent: ExecutionIntent):
        rows = []
        for column, value in (
            (HostedExecutionRow.capability_id, intent.capability_id),
            (HostedExecutionRow.reservation_id, intent.reservation_id),
            (HostedExecutionRow.purchase_id, intent.purchase_id),
            (
                HostedExecutionRow.idempotency_key,
                intent.idempotency_key,
            ),
        ):
            if column is HostedExecutionRow.idempotency_key:
                statement = select(HostedExecutionRow).where(
                    column == value,
                    HostedExecutionRow.tenant_id == intent.tenant_id,
                    HostedExecutionRow.node_id == intent.node_id,
                )
            else:
                statement = select(HostedExecutionRow).where(column == value)
            if self.dialect_name != "sqlite":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is not None and row not in rows:
                rows.append(row)
        if len(rows) > 1:
            raise ExecutionConflict("execution uniqueness bindings are inconsistent")
        return rows[0] if rows else None

    @staticmethod
    def _require_exact_intent(row: HostedExecutionRow, intent: ExecutionIntent) -> None:
        if (
            row.canonical_hash != intent.canonical_hash
            or row.canonical_payload != intent.canonical_payload()
        ):
            raise ExecutionConflict("immutable execution scope changed")

    def _locked_execution(self, session: Any, execution_id: str):
        statement = select(HostedExecutionRow).where(
            HostedExecutionRow.execution_id == execution_id
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _require_row(row: HostedExecutionRow | None) -> HostedExecutionRow:
        if row is None:
            raise ExecutionNotFound("execution not found")
        return row

    @staticmethod
    def _state(value: ExecutionState | str) -> ExecutionState:
        try:
            return ExecutionState(value)
        except (TypeError, ValueError) as exc:
            raise ExecutionConflict("execution state is invalid") from exc

    @staticmethod
    def _validated_intent(intent: ExecutionIntent) -> ExecutionIntent:
        if isinstance(intent, ExecutionIntent):
            return intent
        try:
            return ExecutionIntent.model_validate(intent, strict=True)
        except (TypeError, ValueError) as exc:
            raise ExecutionConflict("execution intent is invalid") from exc

    @staticmethod
    def _now(value: int | None) -> int:
        if value is None:
            return int(time.time())
        if type(value) is not int or value <= 0:
            raise ExecutionConflict("execution clock is invalid")
        return value

    @staticmethod
    def _canonical_nonce(value: object) -> int:
        if type(value) is not int or value < 0 or value > MAX_RELAYER_NONCE:
            raise ExecutionConflict("chain pending nonce is invalid")
        return value

    @staticmethod
    def _require_raw_transaction(row: HostedExecutionRow) -> bytes:
        if not isinstance(row.raw_transaction, bytes) or not row.raw_transaction:
            raise ExecutionConflict("raw transaction is missing")
        expected = _ethereum_transaction_hash(row.raw_transaction)
        if row.raw_transaction_hash != expected:
            raise ExecutionConflict("raw transaction hash is inconsistent")
        return bytes(row.raw_transaction)

    @staticmethod
    def _add_attempt(
        session: Any,
        row: HostedExecutionRow,
        *,
        attempt_kind: str,
        raw_transaction_hash: str,
        attempt_number: int,
        now: int,
    ) -> None:
        session.add(
            HostedExecutionAttemptRow(
                attempt_id="attempt_" + uuid4().hex[:32],
                execution_id=row.execution_id,
                attempt_number=attempt_number,
                attempt_kind=attempt_kind,
                raw_transaction_hash=raw_transaction_hash,
                created_at=now,
            )
        )

    @staticmethod
    def _record(row: HostedExecutionRow) -> HostedExecution:
        return HostedExecution(
            tenant_id=row.tenant_id,
            node_id=row.node_id,
            wallet_binding_id=row.wallet_binding_id,
            capability_id=row.capability_id,
            reservation_id=row.reservation_id,
            purchase_id=row.purchase_id,
            request_id=row.canonical_payload["request_id"],
            request_hash=row.canonical_payload["request_hash"],
            idempotency_key=row.idempotency_key,
            chain=row.chain,
            owner=row.owner,
            payee=row.payee,
            token=row.token,
            amount_atomic=row.amount_atomic,
            executor=row.executor,
            signer_epoch=row.signer_epoch,
            owner_nonce=int(row.owner_nonce),
            deadline=row.deadline,
            capability_hash=row.capability_hash,
            reservation_hash=row.reservation_hash,
            execution_scope_hash=row.execution_scope_hash,
            execution_digest=row.execution_digest,
            relayer_address=row.relayer_address,
            signature=bytes(row.signature) if row.signature is not None else None,
            raw_transaction=(
                bytes(row.raw_transaction) if row.raw_transaction is not None else None
            ),
            execution_id=row.execution_id,
            status=ExecutionState(row.status),
            relayer_nonce=row.relayer_nonce,
            signing_claim_generation=row.signing_claim_generation,
            signing_claim_expires_at=row.signing_claim_expires_at,
            broadcast_attempts=row.broadcast_attempts,
            unsigned_transaction_hash=row.unsigned_transaction_hash,
            raw_transaction_hash=row.raw_transaction_hash,
            broadcasted_at=row.broadcasted_at,
            receipt_status=row.receipt_status,
            receipt_block_number=row.receipt_block_number,
            receipt_block_hash=row.receipt_block_hash,
            confirmations=row.confirmations,
            safe_block_number=row.safe_block_number,
            safe_block_hash=row.safe_block_hash,
            watcher_version=row.watcher_version,
            finality_boundary=row.finality_boundary,
            reorg_state=row.reorg_state,
            reorg_evidence=deepcopy(row.reorg_evidence),
            submission_failure_code=row.submission_failure_code,
            release_evidence=deepcopy(row.release_evidence),
            confirmed_at=row.confirmed_at,
            finalized_at=row.finalized_at,
            reverted_at=row.reverted_at,
            released_at=row.released_at,
            expired_at=row.expired_at,
            reorg_reviewed_at=row.reorg_reviewed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
