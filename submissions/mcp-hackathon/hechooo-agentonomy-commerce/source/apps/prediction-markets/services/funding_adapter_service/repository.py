from __future__ import annotations

import json
import re
from hashlib import sha256
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator
from pydantic import ValidationError

from services.funding_adapter_service.schemas import (
    FundingOperationStatus,
    POLYMARKET_BRIDGE_FAILURE_REASON,
    PolymarketBridgeDeposit,
    PolymarketBridgeStatus,
    PolymarketFundingOperation,
    RISK_ASSESSMENT_CLOCK_SKEW,
    RISK_ASSESSMENT_MAX_AGE,
    UINT256_MAX_ATOMIC,
)


BRIDGE_SCHEMA_VERSION = 4
CORE_PREBROADCAST_RELEASE_REASON = "CORE_PREBROADCAST_RELEASED"
_RECOVERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$")
_POSTGRES_MIGRATION_LOCK = 1_702_760_821
_POSTGRES_MIGRATION_LOCK_TIMEOUT_MS = 2_000
_POSTGRES_MIGRATION_STATEMENT_TIMEOUT_MS = 5_000
_POSTGRES_CHECK_EXPRESSION_MAX_CHARS = 131_072
_POSTGRES_EXPLAIN_PLAN_MAX_BYTES = 262_144
_POSTGRES_EXPLAIN_PLAN_MAX_DEPTH = 16
_POSTGRES_CHECK_DEPARSE_IDENTIFIERS = frozenset(
    {
        "all",
        "any",
        "array",
        "bigint",
        "boolean",
        "character",
        "integer",
        "numeric",
        "text",
        "time",
        "timestamp",
        "varchar",
        "varying",
        "with",
        "without",
        "zone",
    }
)
_POSTGRES_CHECK_DEPARSE_CALLS = frozenset({"all", "any"})
_POSTGRES_CHECK_DEPARSE_OPERATORS = frozenset({"::", "<=", ">="})
_V1_MANAGED_TABLES = {
    "polymarket_bridge_deposit_claims",
    "polymarket_bridge_deposit_targets",
    "polymarket_bridge_observations",
}
_MANAGED_TABLES = {*_V1_MANAGED_TABLES, "polymarket_funding_operations"}
_OPERATION_UPDATE_GUARD_NAME = "trg_pm_funding_operation_update_guard"
_OPERATION_UPDATE_GUARD_FUNCTION = "fn_pm_funding_operation_update_guard"
_OPERATION_INSERT_GUARD_NAME = "trg_pm_funding_operation_insert_guard"
_OPERATION_INSERT_GUARD_FUNCTION = "fn_pm_funding_operation_insert_guard"
_TARGET_OPERATION_SCOPE_INDEX_NAME = "uq_bridge_target_operation_scope"


class BridgeRepositoryError(RuntimeError):
    pass


class Base(DeclarativeBase):
    pass


class BridgeSchemaVersionRow(Base):
    __tablename__ = "polymarket_bridge_schema_version"

    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("singleton = 1", name="ck_polymarket_bridge_schema_singleton"),
        CheckConstraint("version >= 0", name="ck_polymarket_bridge_schema_version_nonnegative"),
    )


def _only_characters_sql(expression: str, allowed: str) -> str:
    stripped = expression
    for character in allowed:
        stripped = f"replace({stripped}, '{character}', '')"
    return f"{stripped} = ''"


_LOWER_HEX_SUFFIX_CHECK = _only_characters_sql(
    "substr({column}, 3)", "0123456789abcdef"
)
_ADDRESS_CHECK = (
    "length({column}) = 42 AND substr({column}, 1, 2) = '0x' "
    "AND {column} = lower({column}) "
    f"AND {_LOWER_HEX_SUFFIX_CHECK} "
    "AND {column} <> '0x0000000000000000000000000000000000000000'"
)
_ID_CHECK = "length({column}) BETWEEN 1 AND 96"
_TX_HASH_CHECK = (
    "length({column}) = 66 AND substr({column}, 1, 2) = '0x' "
    "AND {column} = lower({column}) "
    f"AND {_LOWER_HEX_SUFFIX_CHECK}"
)
_ATOMIC_AMOUNT_CHECK = (
    "length({column}) BETWEEN 1 AND 78 "
    "AND substr({column}, 1, 1) BETWEEN '1' AND '9' "
    f"AND {_only_characters_sql('{column}', '0123456789')} "
    f"AND (length({{column}}) < 78 OR {{column}} <= '{UINT256_MAX_ATOMIC}')"
)
_UINT256_AMOUNT_CHECK = (
    "length({column}) BETWEEN 1 AND 78 "
    "AND ({column} = '0' OR substr({column}, 1, 1) BETWEEN '1' AND '9') "
    f"AND {_only_characters_sql('{column}', '0123456789')} "
    f"AND (length({{column}}) < 78 OR {{column}} <= '{UINT256_MAX_ATOMIC}')"
)
_USDC_DIGITS_CHECK = _only_characters_sql(
    "replace({column}, '.', '')", "0123456789"
)
_USDC_AMOUNT_CHECK = (
    "length({column}) BETWEEN 8 AND 79 "
    "AND substr({column}, length({column}) - 6, 1) = '.' "
    "AND length({column}) - length(replace({column}, '.', '')) = 1 "
    f"AND {_USDC_DIGITS_CHECK} "
    "AND (substr({column}, 1, length({column}) - 7) = '0' "
    "OR substr({column}, 1, 1) BETWEEN '1' AND '9') "
    "AND {column} <> '0.000000'"
)
_OPTIONAL_ID_CHECK = "{column} IS NULL OR (length({column}) BETWEEN 1 AND 96)"
_OPC_INSTALLATION_CHECK = (
    "{column} IS NULL OR (length({column}) = 44 "
    "AND substr({column}, 1, 4) = 'opc_' "
    "AND {column} = lower({column}) "
    "AND "
    + _only_characters_sql("substr({column}, 5)", "0123456789abcdef")
    + ")"
)
_REASON_CHECK = (
    "{column} IS NULL OR (length({column}) BETWEEN 1 AND 64 "
    "AND substr({column}, 1, 1) BETWEEN 'A' AND 'Z' "
    "AND {column} = upper({column}))"
)
_MAX_EPOCH_MICROSECONDS = 253_402_300_799_999_999
_RISK_MAX_AGE_MICROSECONDS = int(
    RISK_ASSESSMENT_MAX_AGE.total_seconds() * 1_000_000
)
_RISK_CLOCK_SKEW_MICROSECONDS = int(
    RISK_ASSESSMENT_CLOCK_SKEW.total_seconds() * 1_000_000
)
_EPOCH_MICROSECONDS_CHECK = (
    "{column} BETWEEN 0 AND " + str(_MAX_EPOCH_MICROSECONDS)
)
_RESOURCE_CHECK = "length({column}) BETWEEN 1 AND 256"
FUNDING_OPERATION_STATUSES = {
    "created",
    "confirmed",
    "action_creating",
    "action_unknown",
    "action_created",
    "policy_evaluating",
    "policy_unknown",
    "policy_approved",
    "reservation_creating",
    "reserved",
    "transaction_prepared",
    "settlement_submitting",
    "settlement_unknown",
    "submitted",
    "chain_confirmed",
    "bridge_pending",
    "venue_credited",
    "finalizing",
    "finalized",
    "failed",
    "released",
    "manual_review",
}
FUNDING_OPERATION_TERMINAL_STATUSES = {"finalized", "failed", "released"}
_FUNDING_STATUS_SQL = ", ".join(
    f"'{status}'" for status in sorted(FUNDING_OPERATION_STATUSES)
)
_BRIDGE_STATUS_SQL = ", ".join(
    f"'{status}'"
    for status in (
        "DEPOSIT_DETECTED",
        "PROCESSING",
        "ORIGIN_TX_CONFIRMED",
        "SUBMITTED",
        "COMPLETED",
        "FAILED",
    )
)
_RISK_ACTION_SQL = ", ".join(
    f"'{action}'"
    for action in (
        "approve",
        "hold",
        "block",
        "blocked",
        "reject",
        "deny",
        "manual_review",
        "review",
    )
)

_OPERATION_CORE_FAILURE_PROOF_SQL = (
    "((core_replacement_forbidden = false AND core_failure_evidence_kind IS NULL) "
    "OR COALESCE((core_replacement_forbidden = true "
    "AND core_failure_evidence_kind IN ('definite_rpc_rejection', 'failed_receipt') "
    "AND core_tx_hash IS NOT NULL AND failure_reason_code IS NOT NULL "
    "AND core_state IN ('spending_reserved', 'released')), false))"
)
def _decimal_chunk_sql(column: str, *, index: int) -> str:
    chunk_digits = 18
    chunk_count = 5
    width = chunk_digits * chunk_count
    zero_pad = "0" * width
    padded = (
        f"substr('{zero_pad}' || {column}, "
        f"length('{zero_pad}' || {column}) - {width - 1}, {width})"
    )
    return (
        f"CAST(substr({padded}, {index * chunk_digits + 1}, "
        f"{chunk_digits}) AS BIGINT)"
    )


def _exact_operation_credit_sql() -> str:
    """Portable exact compare: after >= before + amount, without big-int casts."""

    chunk_count = 5
    base = 1_000_000_000_000_000_000
    before = [
        _decimal_chunk_sql("venue_buying_power_before_atomic", index=index)
        for index in range(chunk_count)
    ]
    amount = [
        _decimal_chunk_sql("amount_atomic", index=index)
        for index in range(chunk_count)
    ]
    after = [
        _decimal_chunk_sql("venue_buying_power_after_atomic", index=index)
        for index in range(chunk_count)
    ]

    carry = "0"
    required_chunks = [""] * chunk_count
    for index in range(chunk_count - 1, -1, -1):
        raw_sum = f"({before[index]} + {amount[index]} + {carry})"
        required_chunks[index] = f"(({raw_sum}) % {base})"
        carry = f"(({raw_sum}) / {base})"

    greater_terms: list[str] = []
    equal_prefix: list[str] = []
    for observed, required in zip(after, required_chunks, strict=True):
        greater_terms.append(
            "(" + " AND ".join((*equal_prefix, f"{observed} > {required}")) + ")"
        )
        equal_prefix.append(f"{observed} = {required}")
    greater_terms.append("(" + " AND ".join(equal_prefix) + ")")
    return (
        "venue_buying_power_after_atomic IS NOT NULL AND ("
        + " OR ".join(greater_terms)
        + ")"
    )


_OPERATION_CREDIT_INCREASE_SQL = _exact_operation_credit_sql()
_OPERATION_VENUE_FAILURE_PROOF_SQL = (
    "(status = 'failed' "
    f"AND failure_reason_code = '{POLYMARKET_BRIDGE_FAILURE_REASON}' "
    "AND core_tx_hash IS NOT NULL AND core_state = 'settled' "
    "AND core_replacement_forbidden = false "
    "AND core_failure_evidence_kind IS NULL "
    "AND bridge_observation_id IS NOT NULL AND bridge_status = 'FAILED' "
    "AND venue_buying_power_after_atomic IS NULL AND finalized_at IS NULL)"
)
_OPERATION_STAGE_PROOF_SQL = f"""
(
  (status = 'created' AND confirmed_at IS NULL AND action_id IS NULL
   AND policy_decision_id IS NULL AND audit_event_id IS NULL
   AND reservation_id IS NULL AND core_tx_hash IS NULL AND core_state IS NULL
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status IN ('confirmed', 'action_creating', 'action_unknown')
   AND confirmed_at IS NOT NULL AND action_id IS NULL
   AND policy_decision_id IS NULL AND audit_event_id IS NULL
   AND reservation_id IS NULL AND core_tx_hash IS NULL AND core_state IS NULL
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status IN ('action_created', 'policy_evaluating', 'policy_unknown')
   AND confirmed_at IS NOT NULL AND action_id IS NOT NULL
   AND policy_decision_id IS NULL AND audit_event_id IS NULL
   AND reservation_id IS NULL AND core_tx_hash IS NULL AND core_state IS NULL
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status IN ('policy_approved', 'reservation_creating')
   AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NULL AND reservation_id IS NULL
   AND core_tx_hash IS NULL AND core_state IS NULL
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status IN ('reserved', 'transaction_prepared', 'settlement_submitting')
   AND confirmed_at IS NOT NULL AND action_id IS NOT NULL
   AND policy_decision_id IS NOT NULL AND audit_event_id IS NOT NULL
   AND reservation_id IS NOT NULL AND core_tx_hash IS NULL
   AND core_state = 'spending_reserved' AND bridge_observation_id IS NULL
   AND bridge_status IS NULL AND venue_buying_power_after_atomic IS NULL
   AND failure_reason_code IS NULL AND finalized_at IS NULL
   AND core_replacement_forbidden = false)
  OR
  (status = 'settlement_unknown' AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND (core_state IS NULL OR core_state IN ('spending_reserved', 'payment_submitted'))
   AND (((core_state IS NULL OR core_state = 'spending_reserved')
         AND core_tx_hash IS NULL)
        OR (core_state = 'payment_submitted' AND core_tx_hash IS NOT NULL))
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status = 'submitted' AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND core_tx_hash IS NOT NULL AND core_state = 'payment_submitted'
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status = 'chain_confirmed' AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND core_tx_hash IS NOT NULL AND core_state = 'settled'
   AND bridge_observation_id IS NULL AND bridge_status IS NULL
   AND venue_buying_power_after_atomic IS NULL AND failure_reason_code IS NULL
   AND finalized_at IS NULL AND core_replacement_forbidden = false)
  OR
  (status = 'bridge_pending' AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND core_tx_hash IS NOT NULL AND core_state = 'settled'
   AND ((bridge_observation_id IS NULL AND bridge_status IS NULL)
        OR (bridge_observation_id IS NOT NULL AND bridge_status IS NOT NULL))
   AND failure_reason_code IS NULL AND finalized_at IS NULL
   AND core_replacement_forbidden = false)
  OR
  (status IN ('venue_credited', 'finalizing') AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND core_tx_hash IS NOT NULL AND core_state = 'settled'
   AND bridge_observation_id IS NOT NULL AND bridge_status = 'COMPLETED'
   AND {_OPERATION_CREDIT_INCREASE_SQL}
   AND failure_reason_code IS NULL AND finalized_at IS NULL
   AND core_replacement_forbidden = false)
  OR
  (status = 'finalized' AND confirmed_at IS NOT NULL
   AND action_id IS NOT NULL AND policy_decision_id IS NOT NULL
   AND audit_event_id IS NOT NULL AND reservation_id IS NOT NULL
   AND core_tx_hash IS NOT NULL AND core_state = 'finalized'
   AND bridge_observation_id IS NOT NULL AND bridge_status = 'COMPLETED'
   AND {_OPERATION_CREDIT_INCREASE_SQL}
   AND failure_reason_code IS NULL AND finalized_at IS NOT NULL
   AND core_replacement_forbidden = false)
  OR status IN ('failed', 'released', 'manual_review')
)
"""

_IMMUTABLE_OPERATION_FIELDS = (
    "user_id",
    "agent_id",
    "idempotency_key",
    "opc_installation_id",
    "binding_id",
    "venue_wallet_address",
    "bridge_address",
    "source_network",
    "source_token_address",
    "destination_network",
    "destination_token_address",
    "amount_usdc",
    "amount_atomic",
    "resource",
    "request_hash",
    "quote_hash",
    "wallet_identity_id",
    "spending_grant_id",
    "asset_allowance_id",
    "spender_address",
    "venue_buying_power_before_atomic",
    "risk_assessment_id",
    "risk_level",
    "risk_score",
    "risk_action",
    "risk_assessed_at",
)
_WRITE_ONCE_OPERATION_FIELDS = (
    "action_id",
    "policy_decision_id",
    "audit_event_id",
    "reservation_id",
    "core_tx_hash",
    "core_failure_evidence_kind",
    "confirmed_at",
    "finalized_at",
    "failure_reason_code",
)
_ALLOWED_OPERATION_TRANSITIONS = {
    "created": {"confirmed", "failed", "released", "manual_review"},
    "confirmed": {"action_creating", "failed", "released", "manual_review"},
    "action_creating": {
        "action_created",
        "action_unknown",
        "failed",
        "released",
        "manual_review",
    },
    "action_unknown": {"action_created", "manual_review"},
    "action_created": {
        "policy_evaluating",
        "failed",
        "released",
        "manual_review",
    },
    "policy_evaluating": {
        "policy_approved",
        "policy_unknown",
        "failed",
        "released",
        "manual_review",
    },
    "policy_unknown": {"policy_approved", "manual_review"},
    "policy_approved": {"reservation_creating", "manual_review"},
    "reservation_creating": {"reserved", "manual_review"},
    "reserved": {
        "transaction_prepared",
        "settlement_submitting",
        "failed",
        "released",
        "manual_review",
    },
    "transaction_prepared": {
        "settlement_submitting",
        "submitted",
        "failed",
        "released",
        "manual_review",
    },
    "settlement_submitting": {
        "settlement_unknown",
        "submitted",
        "failed",
        "released",
        "manual_review",
    },
    "settlement_unknown": {
        "submitted",
        "chain_confirmed",
        "failed",
        "released",
        "manual_review",
    },
    "submitted": {"chain_confirmed", "failed", "released", "manual_review"},
    "chain_confirmed": {"bridge_pending", "failed", "manual_review"},
    "bridge_pending": {"venue_credited", "failed", "manual_review"},
    "venue_credited": {"finalizing", "manual_review"},
    "finalizing": {"finalized", "manual_review"},
    "manual_review": set(),
    "finalized": set(),
    "failed": set(),
    "released": set(),
}


class UTCDateTimeMicros(TypeDecorator):
    """Store an aware UTC instant as portable epoch microseconds."""

    impl = BigInteger
    cache_ok = True

    _epoch = datetime(1970, 1, 1, tzinfo=UTC)

    def process_bind_param(self, value, _dialect):
        if value is None:
            return None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("funding operation timestamp must be timezone aware")
        delta = value.astimezone(UTC) - self._epoch
        microseconds = (
            delta.days * 86_400_000_000
            + delta.seconds * 1_000_000
            + delta.microseconds
        )
        if not 0 <= microseconds <= _MAX_EPOCH_MICROSECONDS:
            raise ValueError("funding operation timestamp is out of range")
        return microseconds

    def process_result_value(self, value, _dialect):
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("funding operation timestamp is invalid")
        if not 0 <= value <= _MAX_EPOCH_MICROSECONDS:
            raise ValueError("funding operation timestamp is out of range")
        return self._epoch + timedelta(microseconds=value)


class BridgeDepositTargetRow(Base):
    __tablename__ = "polymarket_bridge_deposit_targets"

    deposit_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(96), nullable=False)
    venue_wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    bridge_address: Mapped[str] = mapped_column(String(42), nullable=False)
    source_network: Mapped[str] = mapped_column(String(32), nullable=False)
    source_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    destination_network: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_ID_CHECK.format(column="deposit_id"), name="ck_bridge_target_deposit_id_length"),
        CheckConstraint(_ID_CHECK.format(column="user_id"), name="ck_bridge_target_user_id_length"),
        CheckConstraint(_ID_CHECK.format(column="binding_id"), name="ck_bridge_target_binding_id_length"),
        CheckConstraint(_ADDRESS_CHECK.format(column="venue_wallet_address"), name="ck_bridge_target_venue_wallet"),
        CheckConstraint(_ADDRESS_CHECK.format(column="bridge_address"), name="ck_bridge_target_bridge_address"),
        CheckConstraint(_ADDRESS_CHECK.format(column="source_token_address"), name="ck_bridge_target_source_token"),
        CheckConstraint(_ADDRESS_CHECK.format(column="destination_token_address"), name="ck_bridge_target_destination_token"),
        CheckConstraint("source_network = 'eip155:137'", name="ck_bridge_target_source_network"),
        CheckConstraint("destination_network = 'eip155:137'", name="ck_bridge_target_destination_network"),
        CheckConstraint("status = 'ready'", name="ck_bridge_target_status"),
        UniqueConstraint(
            "user_id",
            "binding_id",
            name="uq_bridge_target_owner_binding",
        ),
        UniqueConstraint(
            "user_id",
            "binding_id",
            "venue_wallet_address",
            "bridge_address",
            name="uq_bridge_target_full_scope",
        ),
        Index(
            _TARGET_OPERATION_SCOPE_INDEX_NAME,
            "user_id",
            "binding_id",
            "venue_wallet_address",
            "bridge_address",
            "source_network",
            "source_token_address",
            "destination_network",
            "destination_token_address",
            unique=True,
        ),
    )


class BridgeDepositClaimRow(Base):
    __tablename__ = "polymarket_bridge_deposit_claims"

    user_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    venue_wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    claim_token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(_ID_CHECK.format(column="user_id"), name="ck_bridge_claim_user_id_length"),
        CheckConstraint(_ID_CHECK.format(column="binding_id"), name="ck_bridge_claim_binding_id_length"),
        CheckConstraint(_ID_CHECK.format(column="claim_token"), name="ck_bridge_claim_token_length"),
        CheckConstraint(_ADDRESS_CHECK.format(column="venue_wallet_address"), name="ck_bridge_claim_venue_wallet"),
        CheckConstraint(
            "lease_expires_at > claimed_at", name="ck_bridge_claim_lease_window"
        ),
    )


class BridgeObservationRow(Base):
    __tablename__ = "polymarket_bridge_observations"

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(96), nullable=False)
    venue_wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    bridge_address: Mapped[str] = mapped_column(String(42), nullable=False)
    source_network: Mapped[str] = mapped_column(String(32), nullable=False)
    source_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    destination_network: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    amount_atomic: Mapped[str] = mapped_column(String(78), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bridge_created_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(_ID_CHECK.format(column="observation_id"), name="ck_bridge_observation_id_length"),
        CheckConstraint(_ID_CHECK.format(column="user_id"), name="ck_bridge_observation_user_id_length"),
        CheckConstraint(_ID_CHECK.format(column="binding_id"), name="ck_bridge_observation_binding_id_length"),
        CheckConstraint(_ADDRESS_CHECK.format(column="venue_wallet_address"), name="ck_bridge_observation_venue_wallet"),
        CheckConstraint(_ADDRESS_CHECK.format(column="bridge_address"), name="ck_bridge_observation_bridge_address"),
        CheckConstraint(_ADDRESS_CHECK.format(column="source_token_address"), name="ck_bridge_observation_source_token"),
        CheckConstraint(_ADDRESS_CHECK.format(column="destination_token_address"), name="ck_bridge_observation_destination_token"),
        CheckConstraint("source_network = 'eip155:137'", name="ck_bridge_observation_source_network"),
        CheckConstraint("destination_network = 'eip155:137'", name="ck_bridge_observation_destination_network"),
        CheckConstraint(
            "status IN ('DEPOSIT_DETECTED', 'PROCESSING', 'ORIGIN_TX_CONFIRMED', "
            "'SUBMITTED', 'COMPLETED', 'FAILED')",
            name="ck_bridge_observation_status",
        ),
        CheckConstraint(
            f"tx_hash IS NULL OR ({_TX_HASH_CHECK.format(column='tx_hash')})",
            name="ck_bridge_observation_tx_hash",
        ),
        CheckConstraint(
            _ATOMIC_AMOUNT_CHECK.format(column="amount_atomic"),
            name="ck_bridge_observation_amount_atomic",
        ),
        CheckConstraint(
            "bridge_created_time_ms IS NULL OR bridge_created_time_ms >= 0",
            name="ck_bridge_observation_created_time",
        ),
        ForeignKeyConstraint(
            ["user_id", "binding_id", "venue_wallet_address", "bridge_address"],
            [
                "polymarket_bridge_deposit_targets.user_id",
                "polymarket_bridge_deposit_targets.binding_id",
                "polymarket_bridge_deposit_targets.venue_wallet_address",
                "polymarket_bridge_deposit_targets.bridge_address",
            ],
            name="fk_bridge_observation_target_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "binding_id",
            "venue_wallet_address",
            "bridge_address",
            "tx_hash",
            "status",
            "amount_atomic",
            "bridge_created_time_ms",
            "checked_at",
            name="uq_bridge_observation_exact_event",
        ),
    )


class PolymarketFundingOperationRow(Base):
    __tablename__ = "polymarket_funding_operations"

    operation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(96), nullable=False)
    venue_wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    bridge_address: Mapped[str] = mapped_column(String(42), nullable=False)
    source_network: Mapped[str] = mapped_column(String(32), nullable=False)
    source_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    destination_network: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_usdc: Mapped[str] = mapped_column(String(79), nullable=False)
    amount_atomic: Mapped[str] = mapped_column(String(78), nullable=False)
    resource: Mapped[str] = mapped_column(String(256), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    wallet_identity_id: Mapped[str] = mapped_column(String(96), nullable=False)
    spending_grant_id: Mapped[str] = mapped_column(String(96), nullable=False)
    asset_allowance_id: Mapped[str] = mapped_column(String(96), nullable=False)
    spender_address: Mapped[str] = mapped_column(String(42), nullable=False)
    venue_buying_power_before_atomic: Mapped[str] = mapped_column(
        String(78), nullable=False
    )
    risk_assessment_id: Mapped[str] = mapped_column(String(96), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_action: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_assessed_at: Mapped[datetime] = mapped_column(
        UTCDateTimeMicros(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    policy_decision_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    audit_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    reservation_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    core_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    core_state: Mapped[str | None] = mapped_column(String(96), nullable=True)
    core_replacement_forbidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    core_failure_evidence_kind: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    bridge_observation_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    bridge_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    venue_buying_power_after_atomic: Mapped[str | None] = mapped_column(
        String(78), nullable=True
    )
    failure_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTimeMicros(), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        UTCDateTimeMicros(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTimeMicros(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTimeMicros(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    opc_installation_id: Mapped[str | None] = mapped_column(
        String(44), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            _ID_CHECK.format(column="operation_id"), name="ck_pm_funding_op_id"
        ),
        CheckConstraint(
            _ID_CHECK.format(column="user_id"), name="ck_pm_funding_user_id"
        ),
        CheckConstraint(
            _ID_CHECK.format(column="agent_id"), name="ck_pm_funding_agent_id"
        ),
        CheckConstraint(
            _ID_CHECK.format(column="idempotency_key"),
            name="ck_pm_funding_idempotency",
        ),
        CheckConstraint(
            _ID_CHECK.format(column="binding_id"), name="ck_pm_funding_binding_id"
        ),
        CheckConstraint(
            _ADDRESS_CHECK.format(column="venue_wallet_address"),
            name="ck_pm_funding_venue_wallet",
        ),
        CheckConstraint(
            _ADDRESS_CHECK.format(column="bridge_address"),
            name="ck_pm_funding_bridge_address",
        ),
        CheckConstraint(
            _ADDRESS_CHECK.format(column="source_token_address"),
            name="ck_pm_funding_source_token",
        ),
        CheckConstraint(
            _ADDRESS_CHECK.format(column="destination_token_address"),
            name="ck_pm_funding_destination_token",
        ),
        CheckConstraint(
            _ADDRESS_CHECK.format(column="spender_address"),
            name="ck_pm_funding_spender",
        ),
        CheckConstraint(
            "source_network = 'eip155:137'", name="ck_pm_funding_source_network"
        ),
        CheckConstraint(
            "destination_network = 'eip155:137'",
            name="ck_pm_funding_destination_network",
        ),
        CheckConstraint(
            _USDC_AMOUNT_CHECK.format(column="amount_usdc"),
            name="ck_pm_funding_amount_usdc",
        ),
        CheckConstraint(
            _ATOMIC_AMOUNT_CHECK.format(column="amount_atomic"),
            name="ck_pm_funding_amount_atomic",
        ),
        CheckConstraint(
            "ltrim(replace(amount_usdc, '.', ''), '0') = amount_atomic",
            name="ck_pm_funding_amount_match",
        ),
        CheckConstraint(
            _RESOURCE_CHECK.format(column="resource"),
            name="ck_pm_funding_resource",
        ),
        CheckConstraint(
            _TX_HASH_CHECK.format(column="request_hash"),
            name="ck_pm_funding_request_hash",
        ),
        CheckConstraint(
            _TX_HASH_CHECK.format(column="quote_hash"),
            name="ck_pm_funding_quote_hash",
        ),
        CheckConstraint(
            _ID_CHECK.format(column="wallet_identity_id"),
            name="ck_pm_funding_wallet_id",
        ),
        CheckConstraint(
            _ID_CHECK.format(column="spending_grant_id"),
            name="ck_pm_funding_grant_id",
        ),
        CheckConstraint(
            _ID_CHECK.format(column="asset_allowance_id"),
            name="ck_pm_funding_allowance_id",
        ),
        CheckConstraint(
            _UINT256_AMOUNT_CHECK.format(
                column="venue_buying_power_before_atomic"
            ),
            name="ck_pm_funding_buying_power_before",
        ),
        CheckConstraint(
            _ID_CHECK.format(column="risk_assessment_id"),
            name="ck_pm_funding_risk_assessment_id",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_pm_funding_risk_level",
        ),
        CheckConstraint(
            "risk_score BETWEEN 0 AND 100", name="ck_pm_funding_risk_score"
        ),
        CheckConstraint(
            f"risk_action IN ({_RISK_ACTION_SQL})",
            name="ck_pm_funding_risk_action",
        ),
        CheckConstraint(
            f"status IN ({_FUNDING_STATUS_SQL})", name="ck_pm_funding_status"
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="action_id"),
            name="ck_pm_funding_action_id",
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="policy_decision_id"),
            name="ck_pm_funding_policy_id",
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="audit_event_id"),
            name="ck_pm_funding_audit_id",
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="reservation_id"),
            name="ck_pm_funding_reservation_id",
        ),
        CheckConstraint(
            f"core_tx_hash IS NULL OR ({_TX_HASH_CHECK.format(column='core_tx_hash')})",
            name="ck_pm_funding_core_tx_hash",
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="core_state"),
            name="ck_pm_funding_core_state",
        ),
        CheckConstraint(
            "core_state IS NULL OR core_state IN "
            "('spending_reserved', 'payment_submitted', 'settled', "
            "'finalized', 'released')",
            name="ck_pm_funding_core_state_allowlist",
        ),
        CheckConstraint(
            "core_failure_evidence_kind IS NULL OR "
            "core_failure_evidence_kind IN ('definite_rpc_rejection', 'failed_receipt')",
            name="ck_pm_funding_failure_evidence_kind",
        ),
        CheckConstraint(
            "core_replacement_forbidden IN (false, true)",
            name="ck_pm_funding_replacement_forbidden_bool",
        ),
        CheckConstraint(
            _OPTIONAL_ID_CHECK.format(column="bridge_observation_id"),
            name="ck_pm_funding_bridge_observation",
        ),
        CheckConstraint(
            f"bridge_status IS NULL OR bridge_status IN ({_BRIDGE_STATUS_SQL})",
            name="ck_pm_funding_bridge_status",
        ),
        CheckConstraint(
            "venue_buying_power_after_atomic IS NULL OR ("
            + _UINT256_AMOUNT_CHECK.format(
                column="venue_buying_power_after_atomic"
            )
            + ")",
            name="ck_pm_funding_buying_power_after",
        ),
        CheckConstraint(
            _REASON_CHECK.format(column="failure_reason_code"),
            name="ck_pm_funding_failure_reason",
        ),
        CheckConstraint("revision >= 0", name="ck_pm_funding_revision"),
        CheckConstraint(
            _OPC_INSTALLATION_CHECK.format(column="opc_installation_id"),
            name="ck_pm_funding_opc_installation",
        ),
        CheckConstraint(
            _EPOCH_MICROSECONDS_CHECK.format(column="created_at"),
            name="ck_pm_funding_created_utc",
        ),
        CheckConstraint(
            _EPOCH_MICROSECONDS_CHECK.format(column="risk_assessed_at"),
            name="ck_pm_funding_risk_assessed_utc",
        ),
        CheckConstraint(
            _EPOCH_MICROSECONDS_CHECK.format(column="updated_at"),
            name="ck_pm_funding_updated_utc",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR ("
            + _EPOCH_MICROSECONDS_CHECK.format(column="confirmed_at")
            + ")",
            name="ck_pm_funding_confirmed_utc",
        ),
        CheckConstraint(
            "finalized_at IS NULL OR ("
            + _EPOCH_MICROSECONDS_CHECK.format(column="finalized_at")
            + ")",
            name="ck_pm_funding_finalized_utc",
        ),
        CheckConstraint(
            "updated_at >= created_at", name="ck_pm_funding_updated_at"
        ),
        CheckConstraint(
            "risk_assessed_at BETWEEN "
            f"created_at - {_RISK_MAX_AGE_MICROSECONDS} AND "
            f"created_at + {_RISK_CLOCK_SKEW_MICROSECONDS}",
            name="ck_pm_funding_risk_freshness",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at",
            name="ck_pm_funding_confirmed_at",
        ),
        CheckConstraint(
            "finalized_at IS NULL OR finalized_at >= created_at",
            name="ck_pm_funding_finalized_at",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR finalized_at IS NULL OR finalized_at >= confirmed_at",
            name="ck_pm_funding_finalized_after_confirmed",
        ),
        CheckConstraint(
            "status <> 'finalized' OR finalized_at IS NOT NULL",
            name="ck_pm_funding_finalized_timestamp",
        ),
        CheckConstraint(
            "status NOT IN ('failed', 'released') OR failure_reason_code IS NOT NULL",
            name="ck_pm_funding_terminal_reason",
        ),
        CheckConstraint(
            "failure_reason_code IS NULL OR status IN ('failed', 'released', 'manual_review')",
            name="ck_pm_funding_failure_reason_stage",
        ),
        CheckConstraint(
            "finalized_at IS NULL OR status = 'finalized'",
            name="ck_pm_funding_finalized_stage",
        ),
        CheckConstraint(
            _OPERATION_CORE_FAILURE_PROOF_SQL,
            name="ck_pm_funding_core_failure_proof",
        ),
        CheckConstraint(
            "status NOT IN ('failed', 'released') OR "
            "((core_tx_hash IS NULL AND core_replacement_forbidden = false "
            "AND core_failure_evidence_kind IS NULL "
            "AND (core_state IS NULL OR core_state IN ('spending_reserved', 'released'))) "
            "OR (core_tx_hash IS NOT NULL AND core_replacement_forbidden = true "
            "AND core_failure_evidence_kind IS NOT NULL "
            "AND core_state IN ('spending_reserved', 'released')) "
            f"OR {_OPERATION_VENUE_FAILURE_PROOF_SQL})",
            name="ck_pm_funding_terminal_core_proof",
        ),
        CheckConstraint(
            "status <> 'released' OR reservation_id IS NULL OR core_state = 'released'",
            name="ck_pm_funding_released_core_state",
        ),
        CheckConstraint(
            "(bridge_observation_id IS NULL AND bridge_status IS NULL) OR "
            "(bridge_observation_id IS NOT NULL AND bridge_status IS NOT NULL)",
            name="ck_pm_funding_bridge_observation_pair",
        ),
        CheckConstraint(
            _OPERATION_STAGE_PROOF_SQL,
            name="ck_pm_funding_stage_proof",
        ),
        ForeignKeyConstraint(
            [
                "user_id",
                "binding_id",
                "venue_wallet_address",
                "bridge_address",
                "source_network",
                "source_token_address",
                "destination_network",
                "destination_token_address",
            ],
            [
                "polymarket_bridge_deposit_targets.user_id",
                "polymarket_bridge_deposit_targets.binding_id",
                "polymarket_bridge_deposit_targets.venue_wallet_address",
                "polymarket_bridge_deposit_targets.bridge_address",
                "polymarket_bridge_deposit_targets.source_network",
                "polymarket_bridge_deposit_targets.source_token_address",
                "polymarket_bridge_deposit_targets.destination_network",
                "polymarket_bridge_deposit_targets.destination_token_address",
            ],
            name="fk_pm_funding_bridge_target_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_pm_funding_user_idempotency"
        ),
        UniqueConstraint(
            "risk_assessment_id", name="uq_pm_funding_risk_assessment"
        ),
        UniqueConstraint(
            "operation_id",
            "user_id",
            "binding_id",
            name="uq_pm_funding_full_scope",
        ),
    )


_VERSION_TABLE = BridgeSchemaVersionRow.__table__
_V1_TABLE_OBJECTS = (
    BridgeDepositTargetRow.__table__,
    BridgeDepositClaimRow.__table__,
    BridgeObservationRow.__table__,
)
_V2_TABLE_OBJECTS = (*_V1_TABLE_OBJECTS, PolymarketFundingOperationRow.__table__)


def _sql_statuses(values: set[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))


def _valid_operation_transition_sql() -> str:
    transitions = [
        f"(OLD.status = '{old}' AND NEW.status IN ({_sql_statuses(next_states)}))"
        for old, next_states in _ALLOWED_OPERATION_TRANSITIONS.items()
        if next_states
    ]
    transitions.append(
        "(NEW.status = OLD.status AND OLD.status IN "
        "('action_unknown', 'policy_unknown', 'settlement_unknown', 'bridge_pending'))"
    )
    return "(" + " OR ".join(transitions) + ")"


def _operation_update_guard_predicate(
    *, distinct_operator: str, version: int = BRIDGE_SCHEMA_VERSION
) -> str:
    if version not in {2, 3, 4}:
        raise BridgeRepositoryError("bridge database schema version is unsupported")
    immutable_operation_fields = tuple(
        field_name
        for field_name in _IMMUTABLE_OPERATION_FIELDS
        if version >= 4 or field_name != "opc_installation_id"
    )
    immutable_fields = (
        "operation_id",
        *immutable_operation_fields,
        "created_at",
    )
    immutable_drift = " OR ".join(
        f"NEW.{field_name} {distinct_operator} OLD.{field_name}"
        for field_name in immutable_fields
    )
    write_once_drift = " OR ".join(
        f"(OLD.{field_name} IS NOT NULL AND "
        f"NEW.{field_name} {distinct_operator} OLD.{field_name})"
        for field_name in _WRITE_ONCE_OPERATION_FIELDS
    )
    if version == 2:
        broadcast_terminal_without_proof = """
        (OLD.status IN ('settlement_submitting', 'settlement_unknown', 'submitted')
         AND NEW.status IN ('failed', 'released')
         AND COALESCE((
           NEW.core_tx_hash IS NOT NULL
           AND NEW.core_replacement_forbidden = true
           AND NEW.core_failure_evidence_kind IN
               ('definite_rpc_rejection', 'failed_receipt')
           AND NEW.failure_reason_code IS NOT NULL
           AND NEW.core_state IN ('spending_reserved', 'released')
         ), false) = false)
        """
    else:
        prebroadcast_release_proof = f"""
          (OLD.status = 'settlement_unknown'
           AND OLD.core_tx_hash IS NULL
           AND (OLD.core_state IS NULL OR OLD.core_state = 'spending_reserved')
           AND NEW.status = 'released'
           AND NEW.core_tx_hash IS NULL
           AND NEW.core_state = 'released'
           AND NEW.core_replacement_forbidden = false
           AND NEW.core_failure_evidence_kind IS NULL
           AND NEW.failure_reason_code = '{CORE_PREBROADCAST_RELEASE_REASON}')
        """
        broadcast_terminal_without_proof = f"""
        (OLD.status IN ('settlement_submitting', 'settlement_unknown', 'submitted')
         AND NEW.status IN ('failed', 'released')
         AND COALESCE((
           (NEW.core_tx_hash IS NOT NULL
            AND NEW.core_replacement_forbidden = true
            AND NEW.core_failure_evidence_kind IN
                ('definite_rpc_rejection', 'failed_receipt')
            AND NEW.failure_reason_code IS NOT NULL
            AND NEW.core_state IN ('spending_reserved', 'released'))
           OR ({prebroadcast_release_proof})
         ), false) = false)
        """
    settlement_unknown_regression = f"""
        (OLD.status = 'settlement_unknown'
         AND NEW.status = 'settlement_unknown'
         AND COALESCE((
           (OLD.core_state IS NULL
            AND (NEW.core_state IS NULL
                 OR NEW.core_state IN ('spending_reserved', 'payment_submitted')))
           OR (OLD.core_state = 'spending_reserved'
               AND NEW.core_state IN ('spending_reserved', 'payment_submitted'))
           OR (OLD.core_state = 'payment_submitted'
               AND NOT (
                 NEW.core_state {distinct_operator} 'payment_submitted'))
         ), false) = false)
    """
    venue_failure_proof = f"""
        COALESCE((
          NEW.status = 'failed'
          AND NEW.failure_reason_code = '{POLYMARKET_BRIDGE_FAILURE_REASON}'
          AND NEW.core_tx_hash IS NOT NULL
          AND NEW.core_state = 'settled'
          AND NEW.core_replacement_forbidden = false
          AND NEW.core_failure_evidence_kind IS NULL
          AND NEW.bridge_observation_id IS NOT NULL
          AND NEW.bridge_status = 'FAILED'
          AND NEW.venue_buying_power_after_atomic IS NULL
          AND NEW.finalized_at IS NULL
        ), false)
    """
    invalid_venue_failure_origin = f"""
        ((OLD.status IN ('chain_confirmed', 'bridge_pending')
          AND NEW.status = 'failed'
          AND ({venue_failure_proof}) = false)
         OR
         (OLD.status NOT IN ('chain_confirmed', 'bridge_pending')
          AND ({venue_failure_proof}) = true))
    """
    return f"""
        OLD.status IN ('finalized', 'failed', 'released')
        OR NEW.revision <> OLD.revision + 1
        OR NEW.updated_at < OLD.updated_at
        OR ({immutable_drift})
        OR ({write_once_drift})
        OR (OLD.core_replacement_forbidden = true
            AND NEW.core_replacement_forbidden = false)
        OR {broadcast_terminal_without_proof}
        OR {settlement_unknown_regression}
        OR {invalid_venue_failure_origin}
        OR NOT {_valid_operation_transition_sql()}
    """


def _operation_grammar_guard_predicate(
    *, dialect: str, version: int = BRIDGE_SCHEMA_VERSION
) -> str:
    if version not in {2, 3, 4}:
        raise BridgeRepositoryError("bridge database schema version is unsupported")
    required_ids = (
        "operation_id",
        "user_id",
        "agent_id",
        "idempotency_key",
        "binding_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "risk_assessment_id",
    )
    optional_ids = (
        "action_id",
        "policy_decision_id",
        "audit_event_id",
        "reservation_id",
        "core_state",
        "bridge_observation_id",
    )
    if dialect == "sqlite":
        required_checks = [
            f"(NEW.{field_name} NOT GLOB '[A-Za-z0-9]*' "
            f"OR NEW.{field_name} GLOB '*[^A-Za-z0-9._:@/-]*')"
            for field_name in required_ids
        ]
        optional_checks = [
            f"(NEW.{field_name} IS NOT NULL AND "
            f"(NEW.{field_name} NOT GLOB '[A-Za-z0-9]*' "
            f"OR NEW.{field_name} GLOB '*[^A-Za-z0-9._:@/-]*'))"
            for field_name in optional_ids
        ]
        checks = [
                *required_checks,
                *optional_checks,
                "(NEW.resource NOT GLOB '[A-Za-z0-9]*' OR "
                "NEW.resource GLOB '*[^A-Za-z0-9._:@/-]*')",
                "(NEW.failure_reason_code IS NOT NULL AND "
                "(NEW.failure_reason_code NOT GLOB '[A-Z]*' OR "
                "NEW.failure_reason_code GLOB '*[^A-Z0-9_]*'))",
                "typeof(NEW.revision) <> 'integer'",
                "typeof(NEW.core_replacement_forbidden) <> 'integer'",
                "typeof(NEW.created_at) <> 'integer'",
                "typeof(NEW.updated_at) <> 'integer'",
                "typeof(NEW.risk_assessed_at) <> 'integer'",
                "(NEW.confirmed_at IS NOT NULL AND "
                "typeof(NEW.confirmed_at) <> 'integer')",
                "(NEW.finalized_at IS NOT NULL AND "
                "typeof(NEW.finalized_at) <> 'integer')",
            ]
        if version >= 4:
            checks.append(
                "(NEW.opc_installation_id IS NOT NULL AND "
                "(length(NEW.opc_installation_id) <> 44 OR "
                "substr(NEW.opc_installation_id, 1, 4) <> 'opc_' OR "
                "NEW.opc_installation_id <> lower(NEW.opc_installation_id) OR "
                "substr(NEW.opc_installation_id, 5) "
                "GLOB '*[^0-9a-f]*'))"
            )
        return " OR ".join(checks)
    if dialect == "postgresql":
        required_checks = [
            f"NEW.{field_name} !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]*$'"
            for field_name in required_ids
        ]
        optional_checks = [
            f"(NEW.{field_name} IS NOT NULL AND "
            f"NEW.{field_name} !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]*$')"
            for field_name in optional_ids
        ]
        checks = [
                *required_checks,
                *optional_checks,
                "NEW.resource !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]*$'",
                "(NEW.failure_reason_code IS NOT NULL AND "
                "NEW.failure_reason_code !~ '^[A-Z][A-Z0-9_]*$')",
            ]
        if version >= 4:
            checks.append(
                "(NEW.opc_installation_id IS NOT NULL AND "
                "NEW.opc_installation_id !~ '^opc_[0-9a-f]{40}$')"
            )
        return " OR ".join(checks)
    raise BridgeRepositoryError("bridge database dialect is unsupported")


def _normalize_guard_sql(statement: str) -> str:
    return " ".join(statement.lower().split())


def _sqlite_operation_guard_statements(
    *, version: int = BRIDGE_SCHEMA_VERSION
) -> dict[str, str]:
    predicate = _operation_update_guard_predicate(
        distinct_operator="IS NOT", version=version
    )
    grammar_predicate = _operation_grammar_guard_predicate(
        dialect="sqlite", version=version
    )
    return {
        _OPERATION_INSERT_GUARD_NAME: f"""
            CREATE TRIGGER {_OPERATION_INSERT_GUARD_NAME}
            BEFORE INSERT ON polymarket_funding_operations
            FOR EACH ROW
            BEGIN
              SELECT CASE WHEN (({grammar_predicate})
                OR (NEW.status = 'failed' AND NEW.bridge_status = 'FAILED'))
                THEN RAISE(ABORT, 'funding operation insert guard') END;
            END
        """,
        _OPERATION_UPDATE_GUARD_NAME: f"""
            CREATE TRIGGER {_OPERATION_UPDATE_GUARD_NAME}
            BEFORE UPDATE ON polymarket_funding_operations
            FOR EACH ROW
            BEGIN
              SELECT CASE WHEN (({predicate}) OR ({grammar_predicate}))
                THEN RAISE(ABORT, 'funding operation update guard') END;
            END
        """,
    }


def _signed_postgres_guard_body(
    *, kind: str, body: str, version: int = BRIDGE_SCHEMA_VERSION
) -> str:
    implementation_hash = sha256(
        _normalize_guard_sql(body).encode("utf-8")
    ).hexdigest()
    return (
        f"-- clink-operation-guard-v{version}-{kind}-sha256:"
        f"{implementation_hash}\n{body}"
    )


def _postgres_operation_guard_definitions(
    *, schema_prefix: str = "", version: int = BRIDGE_SCHEMA_VERSION
) -> dict[str, dict[str, object]]:
    predicate = _operation_update_guard_predicate(
        distinct_operator="IS DISTINCT FROM", version=version
    )
    grammar_predicate = _operation_grammar_guard_predicate(
        dialect="postgresql", version=version
    )
    insert_body = _signed_postgres_guard_body(
        kind="insert",
        version=version,
        body=f"""
            BEGIN
              IF (({grammar_predicate})
                  OR (NEW.status = 'failed' AND NEW.bridge_status = 'FAILED')) THEN
                RAISE EXCEPTION 'funding operation insert guard'
                  USING ERRCODE = '23514';
              END IF;
              RETURN NEW;
            END;
        """,
    )
    update_body = _signed_postgres_guard_body(
        kind="update",
        version=version,
        body=f"""
            BEGIN
              IF (({predicate}) OR ({grammar_predicate})) THEN
                RAISE EXCEPTION 'funding operation update guard'
                  USING ERRCODE = '23514';
              END IF;
              RETURN NEW;
            END;
        """,
    )
    return {
        _OPERATION_INSERT_GUARD_NAME: {
            "function_name": _OPERATION_INSERT_GUARD_FUNCTION,
            "function_body": insert_body,
            "function_ddl": f"""
                CREATE FUNCTION {schema_prefix}{_OPERATION_INSERT_GUARD_FUNCTION}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                {insert_body}
                $$
            """,
            "trigger_ddl": f"""
                CREATE TRIGGER {_OPERATION_INSERT_GUARD_NAME}
                BEFORE INSERT ON {schema_prefix}polymarket_funding_operations
                FOR EACH ROW EXECUTE FUNCTION
                  {schema_prefix}{_OPERATION_INSERT_GUARD_FUNCTION}()
            """,
            "trigger_type": 7,
        },
        _OPERATION_UPDATE_GUARD_NAME: {
            "function_name": _OPERATION_UPDATE_GUARD_FUNCTION,
            "function_body": update_body,
            "function_ddl": f"""
                CREATE FUNCTION {schema_prefix}{_OPERATION_UPDATE_GUARD_FUNCTION}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                {update_body}
                $$
            """,
            "trigger_ddl": f"""
                CREATE TRIGGER {_OPERATION_UPDATE_GUARD_NAME}
                BEFORE UPDATE ON {schema_prefix}polymarket_funding_operations
                FOR EACH ROW EXECUTE FUNCTION
                  {schema_prefix}{_OPERATION_UPDATE_GUARD_FUNCTION}()
            """,
            "trigger_type": 19,
        },
    }


def _postgres_schema_prefix(connection, schema_name: str | None) -> str:
    if schema_name is None:
        return ""
    preparer = connection.dialect.identifier_preparer
    return f"{preparer.quote_schema(schema_name)}."


def _install_operation_update_guard(
    connection,
    *,
    schema_name: str | None = None,
    version: int = BRIDGE_SCHEMA_VERSION,
) -> None:
    if connection.dialect.name == "sqlite":
        for statement in _sqlite_operation_guard_statements(version=version).values():
            connection.exec_driver_sql(statement)
        return
    if connection.dialect.name == "postgresql":
        schema_prefix = _postgres_schema_prefix(connection, schema_name)
        for definition in _postgres_operation_guard_definitions(
            schema_prefix=schema_prefix,
            version=version,
        ).values():
            connection.exec_driver_sql(str(definition["function_ddl"]))
            connection.exec_driver_sql(str(definition["trigger_ddl"]))
        return
    raise BridgeRepositoryError("bridge database dialect is unsupported")


def _replace_operation_update_guard(
    connection,
    *,
    schema_name: str | None = None,
    version: int = BRIDGE_SCHEMA_VERSION,
) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(f"DROP TRIGGER {_OPERATION_UPDATE_GUARD_NAME}")
        connection.exec_driver_sql(f"DROP TRIGGER {_OPERATION_INSERT_GUARD_NAME}")
    elif connection.dialect.name == "postgresql":
        schema_prefix = _postgres_schema_prefix(connection, schema_name)
        connection.exec_driver_sql(
            f"DROP TRIGGER {_OPERATION_UPDATE_GUARD_NAME} ON "
            f"{schema_prefix}polymarket_funding_operations"
        )
        connection.exec_driver_sql(
            f"DROP TRIGGER {_OPERATION_INSERT_GUARD_NAME} ON "
            f"{schema_prefix}polymarket_funding_operations"
        )
        connection.exec_driver_sql(
            f"DROP FUNCTION {schema_prefix}{_OPERATION_UPDATE_GUARD_FUNCTION}()"
        )
        connection.exec_driver_sql(
            f"DROP FUNCTION {schema_prefix}{_OPERATION_INSERT_GUARD_FUNCTION}()"
        )
    else:
        raise BridgeRepositoryError("bridge database dialect is unsupported")
    _install_operation_update_guard(
        connection,
        schema_name=schema_name,
        version=version,
    )


def _add_opc_installation_column(
    connection,
    *,
    schema_name: str | None = None,
) -> None:
    if connection.dialect.name == "sqlite":
        table_name = "polymarket_funding_operations"
    elif connection.dialect.name == "postgresql":
        table_name = (
            f"{_postgres_schema_prefix(connection, schema_name)}"
            "polymarket_funding_operations"
        )
    else:
        raise BridgeRepositoryError("bridge database dialect is unsupported")
    check = _OPC_INSTALLATION_CHECK.format(column="opc_installation_id")
    connection.exec_driver_sql(
        f"ALTER TABLE {table_name} ADD COLUMN "
        "opc_installation_id VARCHAR(44) "
        "CONSTRAINT ck_pm_funding_opc_installation "
        f"CHECK ({check})"
    )


def _operation_update_guard_exists(
    connection,
    *,
    schema_name: str | None = None,
    version: int = BRIDGE_SCHEMA_VERSION,
) -> bool:
    parameters = {
        "update_guard_name": _OPERATION_UPDATE_GUARD_NAME,
        "insert_guard_name": _OPERATION_INSERT_GUARD_NAME,
    }
    if connection.dialect.name == "sqlite":
        rows = connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
                "AND name IN (:update_guard_name, :insert_guard_name) "
                "AND tbl_name = 'polymarket_funding_operations'"
            ),
            parameters,
        ).mappings().all()
        actual = {
            str(row["name"]): _normalize_guard_sql(str(row["sql"] or ""))
            for row in rows
        }
        expected = {
            name: _normalize_guard_sql(statement)
            for name, statement in _sqlite_operation_guard_statements(
                version=version
            ).items()
        }
        return actual == expected
    if connection.dialect.name == "postgresql":
        operation_table = (
            f"{_postgres_schema_prefix(connection, schema_name)}"
            "polymarket_funding_operations"
        )
        parameters["operation_table"] = operation_table
        rows = connection.execute(
            text(
                "SELECT t.tgname AS trigger_name, t.tgtype AS trigger_type, "
                "t.tgenabled AS trigger_enabled, "
                "p.proname AS function_name, p.prosrc AS function_definition "
                "FROM pg_catalog.pg_trigger AS t "
                "JOIN pg_catalog.pg_proc AS p ON p.oid = t.tgfoid "
                "WHERE t.tgname IN (:update_guard_name, :insert_guard_name) "
                "AND NOT t.tgisinternal "
                "AND t.tgrelid = pg_catalog.to_regclass(:operation_table)"
            ),
            parameters,
        ).mappings().all()
        actual = {str(row["trigger_name"]): row for row in rows}
        expected = _postgres_operation_guard_definitions(version=version)
        if set(actual) != set(expected):
            return False
        return all(
            str(actual[name].get("function_name")) == definition["function_name"]
            and actual[name].get("trigger_type") == definition["trigger_type"]
            and actual[name].get("trigger_enabled") == "O"
            and _normalize_guard_sql(
                str(actual[name].get("function_definition") or "")
            )
            == _normalize_guard_sql(str(definition["function_body"]))
            for name, definition in expected.items()
        )
    return False


def _normalize_schema_sql(statement: str) -> str:
    normalized = statement.strip().lower().replace("%%", "%")
    normalized = re.sub(r'"([a-z_][a-z0-9_]*)"', r"\1", normalized)
    normalized = re.sub(
        r"::(?:character varying(?:\(\d+\))?|varchar(?:\(\d+\))?|"
        r"text|bigint|integer|boolean|numeric|timestamp with time zone)(?:\[\])?",
        "",
        normalized,
    )
    normalized = re.sub(
        r"=\s*any\s*\(\s*\(?\s*array\s*\[([^\]]*)\]\s*\)?\s*\)",
        r"in (\1)",
        normalized,
    )
    normalized = " ".join(normalized.split())
    if normalized.startswith("check (") and normalized.endswith(")"):
        normalized = normalized[7:-1].strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        depth = 0
        encloses_all = True
        in_string = False
        for index, character in enumerate(normalized):
            if character == "'":
                in_string = not in_string
            elif not in_string:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0 and index != len(normalized) - 1:
                        encloses_all = False
                        break
        if not encloses_all or depth != 0:
            break
        normalized = normalized[1:-1].strip()
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _type_signature(type_value, dialect) -> str:
    try:
        rendered = type_value.compile(dialect=dialect)
    except (AttributeError, TypeError, ValueError):
        raise BridgeRepositoryError("bridge database schema is incomplete") from None
    return " ".join(str(rendered).upper().split())


def _constraint_items_by_name(items) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in items:
        name = item.get("name")
        if not isinstance(name, str) or not name or name in result:
            raise BridgeRepositoryError("bridge database schema is incomplete")
        result[name] = item
    return result


def _unique_columns(item: dict) -> tuple[str, ...]:
    return tuple(item.get("column_names") or item.get("constrained_columns") or ())


def _postgres_check_lexemes(
    expression: str,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression) > _POSTGRES_CHECK_EXPRESSION_MAX_CHARS
    ):
        raise ValueError
    identifiers: set[str] = set()
    calls: set[str] = set()
    operators: set[str] = set()
    delimiters: list[str] = []
    index = 0
    while index < len(expression):
        character = expression[index]
        if character in " \t\r\n":
            index += 1
            continue
        if expression.startswith("--", index) or expression.startswith("/*", index):
            raise ValueError
        if expression.startswith("*/", index):
            raise ValueError
        if character == "'":
            index += 1
            while index < len(expression):
                if expression[index] == "\\":
                    raise ValueError
                if expression[index] != "'":
                    index += 1
                    continue
                if index + 1 < len(expression) and expression[index + 1] == "'":
                    index += 2
                    continue
                index += 1
                break
            else:
                raise ValueError
            continue
        if character.isascii() and (character.isalpha() or character == "_"):
            end = index + 1
            while end < len(expression) and expression[end].isascii() and (
                expression[end].isalnum() or expression[end] == "_"
            ):
                end += 1
            identifier = expression[index:end].lower()
            identifiers.add(identifier)
            lookahead = end
            while lookahead < len(expression) and expression[lookahead] in " \t\r\n":
                lookahead += 1
            if lookahead < len(expression) and expression[lookahead] == "(":
                calls.add(identifier)
            index = end
            continue
        if character.isascii() and character.isdigit():
            end = index + 1
            while end < len(expression) and expression[end].isdigit():
                end += 1
            if (
                end + 1 < len(expression)
                and expression[end] == "."
                and expression[end + 1].isdigit()
            ):
                end += 2
                while end < len(expression) and expression[end].isdigit():
                    end += 1
            index = end
            continue
        if character in "([":
            delimiters.append(character)
            index += 1
            continue
        if character in ")]":
            expected = "(" if character == ")" else "["
            if not delimiters or delimiters.pop() != expected:
                raise ValueError
            index += 1
            continue
        if character == ",":
            index += 1
            continue
        two_character = expression[index : index + 2]
        if two_character in {"::", "<=", ">=", "<>", "!=", "||"}:
            operators.add(two_character)
            index += 2
            continue
        if character in "=<>+-*/%":
            operators.add(character)
            index += 1
            continue
        raise ValueError
    if delimiters:
        raise ValueError
    return frozenset(identifiers), frozenset(calls), frozenset(operators)


def _postgres_expected_check_lexemes(
    table_name: str,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    table = next(
        (
            candidate
            for candidate in (_VERSION_TABLE, *_V2_TABLE_OBJECTS)
            if candidate.name == table_name
        ),
        None,
    )
    if table is None:
        raise ValueError
    identifiers: set[str] = set()
    calls: set[str] = set()
    operators: set[str] = set()
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        constraint_identifiers, constraint_calls, constraint_operators = (
            _postgres_check_lexemes(str(constraint.sqltext))
        )
        identifiers.update(constraint_identifiers)
        calls.update(constraint_calls)
        operators.update(constraint_operators)
    return frozenset(identifiers), frozenset(calls), frozenset(operators)


def _validate_postgres_check_expression(table_name: str, expression: str) -> None:
    identifiers, calls, operators = _postgres_check_lexemes(expression)
    expected_identifiers, expected_calls, expected_operators = (
        _postgres_expected_check_lexemes(table_name)
    )
    if not identifiers.issubset(
        expected_identifiers | _POSTGRES_CHECK_DEPARSE_IDENTIFIERS
    ):
        raise ValueError
    if not calls.issubset(expected_calls | _POSTGRES_CHECK_DEPARSE_CALLS):
        raise ValueError
    if not operators.issubset(
        expected_operators | _POSTGRES_CHECK_DEPARSE_OPERATORS
    ):
        raise ValueError


def _validate_postgres_explain_plan_bounds(plan: object) -> None:
    serialized_size = 0
    seen_containers: set[int] = set()
    pending: list[tuple[object, int]] = [(plan, 1)]
    while pending:
        value, depth = pending.pop()
        if depth > _POSTGRES_EXPLAIN_PLAN_MAX_DEPTH:
            raise ValueError
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen_containers:
                raise ValueError
            seen_containers.add(identity)
            serialized_size += 2 + max(0, len(value) - 1)
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > _POSTGRES_EXPLAIN_PLAN_MAX_BYTES:
                    raise ValueError
                serialized_size += len(
                    json.dumps(key, ensure_ascii=True).encode("ascii")
                ) + 1
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            identity = id(value)
            if identity in seen_containers:
                raise ValueError
            seen_containers.add(identity)
            serialized_size += 2 + max(0, len(value) - 1)
            pending.extend((child, depth + 1) for child in value)
        else:
            if isinstance(value, str) and len(value) > _POSTGRES_EXPLAIN_PLAN_MAX_BYTES:
                raise ValueError
            serialized_size += len(
                json.dumps(
                    value,
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("ascii")
            )
        if serialized_size > _POSTGRES_EXPLAIN_PLAN_MAX_BYTES:
            raise ValueError


def _postgres_check_fingerprint(
    inspector,
    table_name: str,
    expression: str,
    *,
    schema_name: str | None = None,
) -> str:
    try:
        _validate_postgres_check_expression(table_name, expression)
        connection = getattr(inspector, "bind", None)
        if connection is None or not callable(
            getattr(connection, "exec_driver_sql", None)
        ):
            return _normalize_schema_sql(expression)
        if not isinstance(schema_name, str) or not schema_name:
            raise ValueError
        preparer = connection.dialect.identifier_preparer
        quoted_table = (
            f"{preparer.quote_schema(schema_name)}."
            f"{preparer.quote(table_name)}"
        )
        driver_expression = expression.replace("%%", "%").replace("%", "%%")
        plan = connection.exec_driver_sql(
            "EXPLAIN (VERBOSE, FORMAT JSON, COSTS FALSE) "
            f"SELECT ({driver_expression}) AS check_value "
            f"FROM {quoted_table} LIMIT 0"
        ).scalar_one()
        _validate_postgres_explain_plan_bounds(plan)
        output = plan[0]["Plan"]["Output"]
        if not isinstance(output, list) or len(output) != 1:
            raise ValueError
        fingerprint = output[0]
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError
        return fingerprint
    except Exception:
        pass
    raise BridgeRepositoryError("bridge database schema is incomplete")


def _check_fingerprint(
    inspector,
    table_name: str,
    expression: str,
    *,
    schema_name: str | None = None,
) -> str:
    dialect = getattr(getattr(inspector, "bind", None), "dialect", None)
    if getattr(dialect, "name", None) == "postgresql":
        return _postgres_check_fingerprint(
            inspector,
            table_name,
            expression,
            schema_name=schema_name,
        )
    return _normalize_schema_sql(expression)


def _inspect_table(inspector, method_name: str, table_name: str, schema_name):
    method = getattr(inspector, method_name)
    if schema_name is None:
        return method(table_name)
    return method(table_name, schema=schema_name)


def _validate_table_signature(
    inspector,
    table,
    *,
    schema_name: str | None = None,
    excluded_columns: frozenset[str] = frozenset(),
    excluded_checks: frozenset[str] = frozenset(),
) -> None:
    table_name = table.name
    dialect = getattr(getattr(inspector, "bind", None), "dialect", None)
    if dialect is None:
        raise BridgeRepositoryError("bridge database schema is incomplete")
    actual_columns = _inspect_table(
        inspector, "get_columns", table_name, schema_name
    )
    expected_columns = tuple(
        column
        for column in table.columns
        if column.name not in excluded_columns
    )
    if tuple(column.get("name") for column in actual_columns) != tuple(
        column.name for column in expected_columns
    ):
        raise BridgeRepositoryError("bridge database schema is incomplete")
    for actual, expected in zip(actual_columns, expected_columns, strict=True):
        if (
            _type_signature(actual.get("type"), dialect)
            != _type_signature(expected.type, dialect)
            or actual.get("nullable") is not expected.nullable
        ):
            raise BridgeRepositoryError("bridge database schema is incomplete")
    actual_pk = tuple(
        _inspect_table(
            inspector, "get_pk_constraint", table_name, schema_name
        ).get("constrained_columns")
        or ()
    )
    expected_pk = tuple(column.name for column in table.primary_key.columns)
    if actual_pk != expected_pk:
        raise BridgeRepositoryError("bridge database schema is incomplete")

    expected_uniques = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    actual_uniques = _inspect_table(
        inspector, "get_unique_constraints", table_name, schema_name
    )
    expected_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in expected_uniques
    }
    actual_unique_columns = {
        _unique_columns(item) for item in actual_uniques
    }
    if actual_unique_columns != expected_unique_columns:
        raise BridgeRepositoryError("bridge database schema is incomplete")
    actual_named_uniques = {
        item.get("name"): _unique_columns(item)
        for item in actual_uniques
        if item.get("name")
    }
    unnamed_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in expected_uniques
        if constraint.name is None
    }
    for constraint in expected_uniques:
        expected_mapping = tuple(column.name for column in constraint.columns)
        if (
            constraint.name is not None
            and actual_named_uniques.get(constraint.name) != expected_mapping
        ):
            raise BridgeRepositoryError("bridge database schema is incomplete")
    if any(
        name not in {
            constraint.name
            for constraint in expected_uniques
            if constraint.name is not None
        }
        and columns not in unnamed_unique_columns
        for name, columns in actual_named_uniques.items()
    ):
        raise BridgeRepositoryError("bridge database schema is incomplete")

    expected_check_sql = {
        constraint.name: str(
            constraint.sqltext.compile(
                dialect=dialect, compile_kwargs={"literal_binds": True}
            )
        )
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name is not None
        and constraint.name not in excluded_checks
    }
    actual_check_items = _constraint_items_by_name(
        _inspect_table(
            inspector, "get_check_constraints", table_name, schema_name
        )
    )
    actual_check_sql = {
        name: str(item.get("sqltext") or "")
        for name, item in actual_check_items.items()
    }
    if set(actual_check_sql) != set(expected_check_sql):
        raise BridgeRepositoryError("bridge database schema is incomplete")
    if any(
        _check_fingerprint(
            inspector,
            table_name,
            actual_check_sql[name],
            schema_name=schema_name,
        )
        != _check_fingerprint(
            inspector,
            table_name,
            expected_check_sql[name],
            schema_name=schema_name,
        )
        for name in expected_check_sql
    ):
        raise BridgeRepositoryError("bridge database schema is incomplete")

    expected_foreign_keys = {}
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint) or constraint.name is None:
            continue
        elements = tuple(constraint.elements)
        expected_foreign_keys[constraint.name] = (
            tuple(element.parent.name for element in elements),
            elements[0].column.table.name,
            tuple(element.column.name for element in elements),
            (constraint.ondelete or "").upper(),
        )
    actual_fk_items = _constraint_items_by_name(
        _inspect_table(inspector, "get_foreign_keys", table_name, schema_name)
    )
    actual_foreign_keys = {
        name: (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            str((item.get("options") or {}).get("ondelete") or "").upper(),
        )
        for name, item in actual_fk_items.items()
    }
    if actual_foreign_keys != expected_foreign_keys:
        raise BridgeRepositoryError("bridge database schema is incomplete")


def _validate_schema_signature(
    connection, *, version: int, schema_name: str | None = None
) -> None:
    inspector = inspect(connection)
    _validate_table_signature(
        inspector, _VERSION_TABLE, schema_name=schema_name
    )
    if version not in {1, 2, 3, 4}:
        raise BridgeRepositoryError("bridge database schema version is unsupported")
    tables = _V1_TABLE_OBJECTS if version == 1 else _V2_TABLE_OBJECTS
    for table in tables:
        legacy_operation = (
            version in {2, 3}
            and table is PolymarketFundingOperationRow.__table__
        )
        _validate_table_signature(
            inspector,
            table,
            schema_name=schema_name,
            excluded_columns=(
                frozenset({"opc_installation_id"})
                if legacy_operation
                else frozenset()
            ),
            excluded_checks=(
                frozenset({"ck_pm_funding_opc_installation"})
                if legacy_operation
                else frozenset()
            ),
        )
    if version >= 2:
        target_index = next(
            index
            for index in BridgeDepositTargetRow.__table__.indexes
            if index.name == _TARGET_OPERATION_SCOPE_INDEX_NAME
        )
        target_indexes = {
            item.get("name"): (
                bool(item.get("unique")),
                tuple(item.get("column_names") or ()),
            )
            for item in _inspect_table(
                inspector,
                "get_indexes",
                BridgeDepositTargetRow.__tablename__,
                schema_name,
            )
            if item.get("name")
        }
        if target_indexes.get(_TARGET_OPERATION_SCOPE_INDEX_NAME) != (
            True,
            tuple(column.name for column in target_index.columns),
        ):
            raise BridgeRepositoryError("bridge database schema is incomplete")
        if not _operation_update_guard_exists(
            connection,
            schema_name=schema_name,
            version=version,
        ):
            raise BridgeRepositoryError("bridge database schema is incomplete")


def _active_target_conflict_exists(connection) -> bool:
    target_scope = (
        PolymarketFundingOperationRow.user_id,
        PolymarketFundingOperationRow.binding_id,
        PolymarketFundingOperationRow.venue_wallet_address,
        PolymarketFundingOperationRow.bridge_address,
        PolymarketFundingOperationRow.source_network,
        PolymarketFundingOperationRow.source_token_address,
        PolymarketFundingOperationRow.destination_network,
        PolymarketFundingOperationRow.destination_token_address,
    )
    statement = (
        select(PolymarketFundingOperationRow.user_id)
        .where(
            PolymarketFundingOperationRow.status.not_in(
                sorted(FUNDING_OPERATION_TERMINAL_STATUSES)
            )
        )
        .group_by(*target_scope)
        .having(func.count(PolymarketFundingOperationRow.operation_id) > 1)
        .limit(1)
    )
    return connection.execute(statement).first() is not None


class BridgeRepository(Protocol):
    def save_deposit_target(self, target: PolymarketBridgeDeposit) -> PolymarketBridgeDeposit: ...

    def find_deposit_target(
        self, *, user_id: str, binding_id: str, venue_wallet_address: str
    ) -> PolymarketBridgeDeposit | None: ...

    def find_deposit_target_for_binding(
        self, *, user_id: str, binding_id: str
    ) -> PolymarketBridgeDeposit | None: ...

    def try_claim_deposit_creation(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        claim_token: str,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> str: ...

    def release_deposit_creation_claim(
        self, *, user_id: str, binding_id: str, claim_token: str
    ) -> None: ...

    def get_deposit_target(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
    ) -> PolymarketBridgeDeposit | None: ...

    def save_bridge_observation(self, status: PolymarketBridgeStatus) -> PolymarketBridgeStatus: ...

    def get_bridge_observation(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
        expected_tx_hash: str | None = None,
    ) -> PolymarketBridgeStatus | None: ...

    def create_funding_operation(
        self, operation: PolymarketFundingOperation
    ) -> tuple[PolymarketFundingOperation, bool]: ...

    def get_funding_operation(
        self, *, user_id: str, binding_id: str, operation_id: str
    ) -> PolymarketFundingOperation | None: ...

    def get_funding_operation_by_idempotency(
        self, *, user_id: str, binding_id: str, idempotency_key: str
    ) -> PolymarketFundingOperation | None: ...

    def get_funding_operation_for_recovery(
        self, *, user_id: str, operation_id: str
    ) -> PolymarketFundingOperation | None: ...

    def compare_and_set_funding_operation(
        self,
        *,
        expected_revision: int,
        expected_status: FundingOperationStatus,
        replacement: PolymarketFundingOperation,
    ) -> PolymarketFundingOperation | None: ...


class SqlAlchemyBridgeRepository:
    def __init__(self, database_url: str) -> None:
        options: dict = {}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 5}
        try:
            self.engine = create_engine(database_url, **options)
        except (SQLAlchemyError, ValueError):
            raise BridgeRepositoryError("bridge database migration failed") from None
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._migrate()

    @staticmethod
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _migrate(self) -> None:
        try:
            connection = self.engine.connect()
        except SQLAlchemyError:
            raise BridgeRepositoryError("bridge database migration failed") from None
        transaction = None
        schema_name = None
        migration_connection = connection
        try:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                schema_name = getattr(
                    self.engine.dialect, "default_schema_name", None
                )
                if not isinstance(schema_name, str) or not schema_name:
                    raise BridgeRepositoryError("bridge database migration failed")
                transaction = connection.begin()
                connection.execute(text("SET LOCAL search_path = pg_catalog"))
                connection.execute(
                    text(
                        "SET LOCAL lock_timeout = "
                        f"'{_POSTGRES_MIGRATION_LOCK_TIMEOUT_MS}ms'"
                    )
                )
                connection.execute(
                    text(
                        "SET LOCAL statement_timeout = "
                        f"'{_POSTGRES_MIGRATION_STATEMENT_TIMEOUT_MS}ms'"
                    )
                )
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": _POSTGRES_MIGRATION_LOCK},
                )
                execution_options = getattr(
                    connection, "execution_options", None
                )
                if callable(execution_options):
                    migration_connection = execution_options(
                        schema_translate_map={None: schema_name}
                    )

            table_names = set(
                inspect(connection).get_table_names(schema=schema_name)
            )
            version_table = BridgeSchemaVersionRow.__tablename__
            if version_table in table_names:
                version = migration_connection.scalar(
                    select(BridgeSchemaVersionRow.version).where(
                        BridgeSchemaVersionRow.singleton == 1
                    )
                )
                if version is None:
                    raise BridgeRepositoryError("bridge database schema version is unavailable")
                if version > BRIDGE_SCHEMA_VERSION:
                    raise BridgeRepositoryError(
                        "bridge database schema is newer than this binary"
                    )
                _validate_table_signature(
                    inspect(connection),
                    _VERSION_TABLE,
                    schema_name=schema_name,
                )
                if version == 1:
                    if (
                        not _V1_MANAGED_TABLES.issubset(table_names)
                        or PolymarketFundingOperationRow.__tablename__ in table_names
                    ):
                        raise BridgeRepositoryError(
                            "bridge database schema is incomplete"
                        )
                    _validate_schema_signature(
                        connection, version=1, schema_name=schema_name
                    )
                    next(
                        index
                        for index in BridgeDepositTargetRow.__table__.indexes
                        if index.name == _TARGET_OPERATION_SCOPE_INDEX_NAME
                    ).create(migration_connection, checkfirst=True)
                    PolymarketFundingOperationRow.__table__.create(
                        migration_connection, checkfirst=False
                    )
                    _install_operation_update_guard(
                        connection,
                        schema_name=schema_name,
                        version=BRIDGE_SCHEMA_VERSION,
                    )
                    _validate_schema_signature(
                        connection,
                        version=BRIDGE_SCHEMA_VERSION,
                        schema_name=schema_name,
                    )
                    migration_connection.execute(
                        BridgeSchemaVersionRow.__table__.update()
                        .where(BridgeSchemaVersionRow.singleton == 1)
                        .values(version=BRIDGE_SCHEMA_VERSION)
                    )
                elif version in {2, 3}:
                    if not _MANAGED_TABLES.issubset(table_names):
                        raise BridgeRepositoryError(
                            "bridge database schema is incomplete"
                        )
                    _validate_schema_signature(
                        connection, version=version, schema_name=schema_name
                    )
                    _add_opc_installation_column(
                        connection,
                        schema_name=schema_name,
                    )
                    _replace_operation_update_guard(
                        connection,
                        schema_name=schema_name,
                        version=BRIDGE_SCHEMA_VERSION,
                    )
                    _validate_schema_signature(
                        connection,
                        version=BRIDGE_SCHEMA_VERSION,
                        schema_name=schema_name,
                    )
                    migration_connection.execute(
                        BridgeSchemaVersionRow.__table__.update()
                        .where(BridgeSchemaVersionRow.singleton == 1)
                        .values(version=BRIDGE_SCHEMA_VERSION)
                    )
                elif version < BRIDGE_SCHEMA_VERSION:
                    raise BridgeRepositoryError(
                        "bridge database schema requires a controlled migration"
                    )
                else:
                    if not _MANAGED_TABLES.issubset(table_names):
                        raise BridgeRepositoryError(
                            "bridge database schema is incomplete"
                        )
                    _validate_schema_signature(
                        connection,
                        version=BRIDGE_SCHEMA_VERSION,
                        schema_name=schema_name,
                    )
            else:
                if table_names & _MANAGED_TABLES:
                    raise BridgeRepositoryError("bridge database schema metadata is missing")
                Base.metadata.create_all(migration_connection)
                _install_operation_update_guard(
                    connection,
                    schema_name=schema_name,
                    version=BRIDGE_SCHEMA_VERSION,
                )
                _validate_schema_signature(
                    connection,
                    version=BRIDGE_SCHEMA_VERSION,
                    schema_name=schema_name,
                )
                migration_connection.execute(
                    BridgeSchemaVersionRow.__table__.insert().values(
                        singleton=1, version=BRIDGE_SCHEMA_VERSION
                    )
                )

            migrated_tables = set(
                inspect(connection).get_table_names(schema=schema_name)
            )
            if not _MANAGED_TABLES.issubset(migrated_tables):
                raise BridgeRepositoryError("bridge database schema is incomplete")
            _validate_schema_signature(
                connection,
                version=BRIDGE_SCHEMA_VERSION,
                schema_name=schema_name,
            )
            if _active_target_conflict_exists(migration_connection):
                raise BridgeRepositoryError(
                    "bridge database contains conflicting active funding operations"
                )

            if self.engine.dialect.name == "sqlite":
                connection.commit()
            elif transaction is not None:
                transaction.commit()
        except BridgeRepositoryError:
            if self.engine.dialect.name == "sqlite":
                connection.rollback()
            elif transaction is not None:
                transaction.rollback()
            raise
        except (SQLAlchemyError, ValueError, TypeError):
            if self.engine.dialect.name == "sqlite":
                connection.rollback()
            elif transaction is not None:
                transaction.rollback()
            raise BridgeRepositoryError("bridge database migration failed") from None
        finally:
            connection.close()

    def save_deposit_target(self, target: PolymarketBridgeDeposit) -> PolymarketBridgeDeposit:
        try:
            with self.sessions.begin() as session:
                existing = session.scalar(
                    select(BridgeDepositTargetRow).where(
                        BridgeDepositTargetRow.user_id == target.user_id,
                        BridgeDepositTargetRow.binding_id == target.binding_id,
                        BridgeDepositTargetRow.venue_wallet_address
                        == target.venue_wallet_address,
                    )
                )
                if existing is not None:
                    stored = self._target_from_row(existing)
                    if self._same_target(stored, target):
                        return stored
                    raise BridgeRepositoryError("bridge target context conflict")
                session.add(
                    BridgeDepositTargetRow(
                        deposit_id=target.deposit_id,
                        user_id=target.user_id,
                        binding_id=target.binding_id,
                        venue_wallet_address=target.venue_wallet_address,
                        bridge_address=target.bridge_address,
                        source_network=target.source_network,
                        source_token_address=target.source_token_address,
                        destination_network=target.destination_network,
                        destination_token_address=target.destination_token_address,
                        status=target.status,
                        created_at=target.created_at,
                    )
                )
            return target
        except BridgeRepositoryError:
            raise
        except IntegrityError:
            replay = self.find_deposit_target(
                user_id=target.user_id,
                binding_id=target.binding_id,
                venue_wallet_address=target.venue_wallet_address,
            )
            if replay is not None and self._same_target(replay, target):
                return replay
            if replay is not None:
                raise BridgeRepositoryError("bridge target context conflict")
            raise BridgeRepositoryError("bridge target could not be persisted")
        except SQLAlchemyError:
            raise BridgeRepositoryError("bridge target could not be persisted") from None

    def find_deposit_target(
        self, *, user_id: str, binding_id: str, venue_wallet_address: str
    ) -> PolymarketBridgeDeposit | None:
        return self._read_one(
            select(BridgeDepositTargetRow).where(
                BridgeDepositTargetRow.user_id == user_id,
                BridgeDepositTargetRow.binding_id == binding_id,
                BridgeDepositTargetRow.venue_wallet_address == venue_wallet_address,
            ),
            self._target_from_row,
        )

    def find_deposit_target_for_binding(
        self, *, user_id: str, binding_id: str
    ) -> PolymarketBridgeDeposit | None:
        return self._read_one(
            select(BridgeDepositTargetRow).where(
                BridgeDepositTargetRow.user_id == user_id,
                BridgeDepositTargetRow.binding_id == binding_id,
            ),
            self._target_from_row,
        )

    def try_claim_deposit_creation(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        claim_token: str,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> str:
        collision = False
        failed = False
        try:
            with self.sessions.begin() as session:
                existing = session.get(
                    BridgeDepositClaimRow, (user_id, binding_id)
                )
                if existing is None:
                    session.add(
                        BridgeDepositClaimRow(
                            user_id=user_id,
                            binding_id=binding_id,
                            venue_wallet_address=venue_wallet_address,
                            claim_token=claim_token,
                            claimed_at=claimed_at,
                            lease_expires_at=lease_expires_at,
                        )
                    )
                    return "acquired"
                if existing.venue_wallet_address != venue_wallet_address:
                    return "context_conflict"
                return "busy"
        except IntegrityError:
            collision = True
        except (SQLAlchemyError, ValidationError):
            failed = True
        if failed:
            raise BridgeRepositoryError("bridge database claim failed")
        if collision:
            existing = self._read_one(
                select(BridgeDepositClaimRow).where(
                    BridgeDepositClaimRow.user_id == user_id,
                    BridgeDepositClaimRow.binding_id == binding_id,
                ),
                lambda row: row,
            )
            if existing is None:
                raise BridgeRepositoryError("bridge database claim failed")
            return (
                "busy"
                if existing.venue_wallet_address == venue_wallet_address
                else "context_conflict"
            )
        raise AssertionError("unreachable")

    def release_deposit_creation_claim(
        self, *, user_id: str, binding_id: str, claim_token: str
    ) -> None:
        failed = False
        try:
            with self.sessions.begin() as session:
                session.execute(
                    delete(BridgeDepositClaimRow).where(
                        BridgeDepositClaimRow.user_id == user_id,
                        BridgeDepositClaimRow.binding_id == binding_id,
                        BridgeDepositClaimRow.claim_token == claim_token,
                    )
                )
            return
        except SQLAlchemyError:
            failed = True
        if failed:
            raise BridgeRepositoryError("bridge database claim release failed")

    def get_deposit_target(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
    ) -> PolymarketBridgeDeposit | None:
        return self._read_one(
            select(BridgeDepositTargetRow).where(
                BridgeDepositTargetRow.user_id == user_id,
                BridgeDepositTargetRow.binding_id == binding_id,
                BridgeDepositTargetRow.venue_wallet_address == venue_wallet_address,
                BridgeDepositTargetRow.bridge_address == bridge_address,
            ),
            self._target_from_row,
        )

    def save_bridge_observation(self, status: PolymarketBridgeStatus) -> PolymarketBridgeStatus:
        target = self.get_deposit_target(
            user_id=status.user_id,
            binding_id=status.binding_id,
            venue_wallet_address=status.venue_wallet_address,
            bridge_address=status.bridge_address,
        )
        if target is None:
            raise BridgeRepositoryError("bridge observation target is not available")
        try:
            with self.sessions.begin() as session:
                existing = session.get(BridgeObservationRow, status.observation_id)
                if existing is not None:
                    stored = self._observation_from_row(existing)
                    if stored == status:
                        return stored
                    raise BridgeRepositoryError("bridge observation context conflict")
                session.add(
                    BridgeObservationRow(
                        observation_id=status.observation_id,
                        user_id=status.user_id,
                        binding_id=status.binding_id,
                        venue_wallet_address=status.venue_wallet_address,
                        bridge_address=status.bridge_address,
                        source_network=status.source_network,
                        source_token_address=status.source_token_address,
                        destination_network=status.destination_network,
                        destination_token_address=status.destination_token_address,
                        status=status.status,
                        tx_hash=status.tx_hash,
                        amount_atomic=status.amount_atomic,
                        checked_at=status.checked_at,
                        bridge_created_time_ms=status.bridge_created_time_ms,
                    )
                )
            return status
        except BridgeRepositoryError:
            raise
        except IntegrityError:
            with self.sessions() as session:
                replay_row = session.get(
                    BridgeObservationRow, status.observation_id
                )
            if replay_row is not None:
                replay = self._observation_from_row(replay_row)
                if replay == status:
                    return replay
                raise BridgeRepositoryError(
                    "bridge observation context conflict"
                ) from None
            raise BridgeRepositoryError("bridge observation could not be persisted") from None
        except SQLAlchemyError:
            raise BridgeRepositoryError("bridge observation could not be persisted") from None

    def get_bridge_observation(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
        expected_tx_hash: str | None = None,
    ) -> PolymarketBridgeStatus | None:
        statement = select(BridgeObservationRow).where(
            BridgeObservationRow.user_id == user_id,
            BridgeObservationRow.binding_id == binding_id,
            BridgeObservationRow.venue_wallet_address == venue_wallet_address,
            BridgeObservationRow.bridge_address == bridge_address,
        )
        if expected_tx_hash is not None:
            statement = statement.where(BridgeObservationRow.tx_hash == expected_tx_hash)
        statement = statement.order_by(
            BridgeObservationRow.checked_at.desc(),
            BridgeObservationRow.observation_id.desc(),
        )
        return self._read_one(statement.limit(1), self._observation_from_row)

    def create_funding_operation(
        self, operation: PolymarketFundingOperation
    ) -> tuple[PolymarketFundingOperation, bool]:
        operation = self._validated_operation(operation)
        self._validate_new_operation(operation)
        replay = self.get_funding_operation_by_idempotency(
            user_id=operation.user_id,
            binding_id=operation.binding_id,
            idempotency_key=operation.idempotency_key,
        )
        if replay is not None:
            if self._same_immutable_operation(replay, operation):
                return replay, False
            raise BridgeRepositoryError("funding operation context conflict")

        try:
            with self.sessions.begin() as session:
                target_lock = session.execute(
                    update(BridgeDepositTargetRow)
                    .where(
                        BridgeDepositTargetRow.user_id == operation.user_id,
                        BridgeDepositTargetRow.binding_id == operation.binding_id,
                        BridgeDepositTargetRow.venue_wallet_address
                        == operation.venue_wallet_address,
                        BridgeDepositTargetRow.bridge_address
                        == operation.bridge_address,
                        BridgeDepositTargetRow.source_network
                        == operation.source_network,
                        BridgeDepositTargetRow.source_token_address
                        == operation.source_token_address,
                        BridgeDepositTargetRow.destination_network
                        == operation.destination_network,
                        BridgeDepositTargetRow.destination_token_address
                        == operation.destination_token_address,
                    )
                    .values(status=BridgeDepositTargetRow.status)
                )
                if target_lock.rowcount != 1:
                    raise BridgeRepositoryError(
                        "funding operation context conflict"
                    )

                active_row = session.scalar(
                    select(PolymarketFundingOperationRow)
                    .where(
                        PolymarketFundingOperationRow.user_id
                        == operation.user_id,
                        PolymarketFundingOperationRow.binding_id
                        == operation.binding_id,
                        PolymarketFundingOperationRow.venue_wallet_address
                        == operation.venue_wallet_address,
                        PolymarketFundingOperationRow.bridge_address
                        == operation.bridge_address,
                        PolymarketFundingOperationRow.source_network
                        == operation.source_network,
                        PolymarketFundingOperationRow.source_token_address
                        == operation.source_token_address,
                        PolymarketFundingOperationRow.destination_network
                        == operation.destination_network,
                        PolymarketFundingOperationRow.destination_token_address
                        == operation.destination_token_address,
                        PolymarketFundingOperationRow.status.not_in(
                            sorted(FUNDING_OPERATION_TERMINAL_STATUSES)
                        ),
                    )
                    .order_by(
                        PolymarketFundingOperationRow.created_at.asc(),
                        PolymarketFundingOperationRow.operation_id.asc(),
                    )
                    .limit(1)
                )
                if active_row is not None:
                    active = self._operation_from_row(active_row)
                    if self._same_immutable_operation(active, operation):
                        return active, False
                    raise BridgeRepositoryError(
                        "funding operation is already in progress"
                    )

                operation_id_collision = session.get(
                    PolymarketFundingOperationRow, operation.operation_id
                )
                if operation_id_collision is not None:
                    existing = self._operation_from_row(operation_id_collision)
                    if self._same_immutable_operation(existing, operation):
                        return existing, False
                    raise BridgeRepositoryError(
                        "funding operation context conflict"
                    )
                session.add(
                    PolymarketFundingOperationRow(
                        **self._operation_values(operation)
                    )
                )
            return operation, True
        except BridgeRepositoryError:
            raise
        except IntegrityError:
            replay = self.get_funding_operation_by_idempotency(
                user_id=operation.user_id,
                binding_id=operation.binding_id,
                idempotency_key=operation.idempotency_key,
            )
            if replay is not None and self._same_immutable_operation(
                replay, operation
            ):
                return replay, False
            raise BridgeRepositoryError(
                "funding operation context conflict"
            ) from None
        except (SQLAlchemyError, ValidationError):
            raise BridgeRepositoryError(
                "funding operation could not be persisted"
            ) from None

    def get_funding_operation(
        self, *, user_id: str, binding_id: str, operation_id: str
    ) -> PolymarketFundingOperation | None:
        return self._read_one(
            select(PolymarketFundingOperationRow).where(
                PolymarketFundingOperationRow.operation_id == operation_id,
                PolymarketFundingOperationRow.user_id == user_id,
                PolymarketFundingOperationRow.binding_id == binding_id,
            ),
            self._operation_from_row,
        )

    def get_funding_operation_by_idempotency(
        self, *, user_id: str, binding_id: str, idempotency_key: str
    ) -> PolymarketFundingOperation | None:
        return self._read_one(
            select(PolymarketFundingOperationRow).where(
                PolymarketFundingOperationRow.user_id == user_id,
                PolymarketFundingOperationRow.binding_id == binding_id,
                PolymarketFundingOperationRow.idempotency_key == idempotency_key,
            ),
            self._operation_from_row,
        )

    def get_funding_operation_for_recovery(
        self, *, user_id: str, operation_id: str
    ) -> PolymarketFundingOperation | None:
        if (
            not isinstance(user_id, str)
            or not _RECOVERY_ID_PATTERN.fullmatch(user_id)
            or not isinstance(operation_id, str)
            or not _RECOVERY_ID_PATTERN.fullmatch(operation_id)
        ):
            raise BridgeRepositoryError(
                "funding operation recovery lookup is invalid"
            )
        return self._read_one(
            select(PolymarketFundingOperationRow).where(
                PolymarketFundingOperationRow.user_id == user_id,
                PolymarketFundingOperationRow.operation_id == operation_id,
            ),
            self._operation_from_row,
        )

    def compare_and_set_funding_operation(
        self,
        *,
        expected_revision: int,
        expected_status: FundingOperationStatus,
        replacement: PolymarketFundingOperation,
    ) -> PolymarketFundingOperation | None:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
            or not isinstance(expected_status, str)
            or expected_status not in FUNDING_OPERATION_STATUSES
        ):
            raise BridgeRepositoryError("funding operation CAS input is invalid")
        if (
            expected_status
            in {"settlement_submitting", "settlement_unknown", "submitted"}
            and replacement.status in {"failed", "released"}
            and not self._has_definite_core_failure_proof(replacement)
            and not self._has_prebroadcast_release_proof(
                expected_status=expected_status,
                replacement=replacement,
            )
        ):
            raise BridgeRepositoryError(
                "funding operation failure proof is required"
            )
        replacement = self._validated_operation(replacement)
        try:
            with self.sessions.begin() as session:
                current_row = session.scalar(
                    select(PolymarketFundingOperationRow).where(
                        PolymarketFundingOperationRow.operation_id
                        == replacement.operation_id,
                        PolymarketFundingOperationRow.user_id
                        == replacement.user_id,
                        PolymarketFundingOperationRow.binding_id
                        == replacement.binding_id,
                    )
                )
                if current_row is None:
                    return None
                current = self._operation_from_row(current_row)
                if (
                    current.revision != expected_revision
                    or current.status != expected_status
                ):
                    return None
                if current.status in FUNDING_OPERATION_TERMINAL_STATUSES:
                    raise BridgeRepositoryError("funding operation is terminal")
                if replacement.revision != expected_revision + 1:
                    raise BridgeRepositoryError(
                        "funding operation revision is invalid"
                    )
                if not self._same_immutable_operation(current, replacement):
                    raise BridgeRepositoryError(
                        "funding operation immutable context conflict"
                    )
                if replacement.created_at != current.created_at:
                    raise BridgeRepositoryError(
                        "funding operation immutable context conflict"
                    )
                if replacement.status == current.status:
                    allowed_same_status_fields = {
                        "action_unknown": set(),
                        "policy_unknown": set(),
                        "settlement_unknown": {"core_tx_hash", "core_state"},
                        "bridge_pending": {
                            "bridge_observation_id",
                            "bridge_status",
                            "venue_buying_power_after_atomic",
                        },
                    }.get(current.status)
                    if allowed_same_status_fields is None:
                        raise BridgeRepositoryError(
                            "funding operation transition is invalid"
                        )
                    mutable_changes = {
                        field_name
                        for field_name in self._mutable_operation_values(replacement)
                        if field_name not in {"status", "revision", "updated_at"}
                        and getattr(replacement, field_name)
                        != getattr(current, field_name)
                    }
                    if not mutable_changes.issubset(allowed_same_status_fields):
                        raise BridgeRepositoryError(
                            "funding operation checkpoint is invalid for status"
                        )
                    if current.status == "settlement_unknown":
                        allowed_core_state_recovery = {
                            None: {None, "spending_reserved", "payment_submitted"},
                            "spending_reserved": {
                                "spending_reserved",
                                "payment_submitted",
                            },
                            "payment_submitted": {"payment_submitted"},
                        }
                        if replacement.core_state not in (
                            allowed_core_state_recovery.get(current.core_state, set())
                        ):
                            raise BridgeRepositoryError(
                                "funding operation checkpoint is invalid for status"
                            )
                for field_name in _WRITE_ONCE_OPERATION_FIELDS:
                    current_value = getattr(current, field_name)
                    if (
                        current_value is not None
                        and getattr(replacement, field_name) != current_value
                    ):
                        raise BridgeRepositoryError(
                            "funding operation checkpoint conflict"
                        )
                if (
                    current.core_replacement_forbidden
                    and not replacement.core_replacement_forbidden
                ):
                    raise BridgeRepositoryError(
                        "funding operation checkpoint conflict"
                    )
                if replacement.updated_at < current.updated_at:
                    raise BridgeRepositoryError(
                        "funding operation timestamp is invalid"
                    )
                if (
                    replacement.status != current.status
                    and replacement.status
                    not in _ALLOWED_OPERATION_TRANSITIONS[current.status]
                ):
                    raise BridgeRepositoryError(
                        "funding operation transition is invalid"
                    )
                result = session.execute(
                    update(PolymarketFundingOperationRow)
                    .where(
                        PolymarketFundingOperationRow.operation_id
                        == current.operation_id,
                        PolymarketFundingOperationRow.user_id == current.user_id,
                        PolymarketFundingOperationRow.binding_id
                        == current.binding_id,
                        PolymarketFundingOperationRow.revision == expected_revision,
                        PolymarketFundingOperationRow.status == expected_status,
                    )
                    .values(**self._mutable_operation_values(replacement))
                )
                if result.rowcount != 1:
                    return None
            return replacement
        except BridgeRepositoryError:
            raise
        except (SQLAlchemyError, ValidationError):
            raise BridgeRepositoryError("funding operation CAS failed") from None

    def _read_one(self, statement, converter):
        failed = False
        try:
            with self.sessions() as session:
                row = session.scalar(statement)
            return converter(row) if row is not None else None
        except (
            SQLAlchemyError,
            ValidationError,
            ValueError,
            TypeError,
            OverflowError,
            AttributeError,
        ):
            failed = True
        if failed:
            raise BridgeRepositoryError("bridge database read failed") from None
        raise AssertionError("unreachable")

    @staticmethod
    def _target_from_row(row: BridgeDepositTargetRow) -> PolymarketBridgeDeposit:
        return PolymarketBridgeDeposit(
            deposit_id=row.deposit_id,
            user_id=row.user_id,
            binding_id=row.binding_id,
            venue_wallet_address=row.venue_wallet_address,
            bridge_address=row.bridge_address,
            source_network=row.source_network,
            source_token_address=row.source_token_address,
            destination_network=row.destination_network,
            destination_token_address=row.destination_token_address,
            status=row.status,
            created_at=_as_utc(row.created_at),
        )

    @staticmethod
    def _same_target(
        left: PolymarketBridgeDeposit, right: PolymarketBridgeDeposit
    ) -> bool:
        return left.model_dump(exclude={"created_at"}) == right.model_dump(
            exclude={"created_at"}
        )

    @staticmethod
    def _observation_from_row(row: BridgeObservationRow) -> PolymarketBridgeStatus:
        return PolymarketBridgeStatus(
            observation_id=row.observation_id,
            user_id=row.user_id,
            binding_id=row.binding_id,
            venue_wallet_address=row.venue_wallet_address,
            bridge_address=row.bridge_address,
            source_network=row.source_network,
            source_token_address=row.source_token_address,
            destination_network=row.destination_network,
            destination_token_address=row.destination_token_address,
            status=row.status,
            tx_hash=row.tx_hash,
            amount_atomic=row.amount_atomic,
            checked_at=_as_utc(row.checked_at),
            bridge_created_time_ms=row.bridge_created_time_ms,
        )

    @staticmethod
    def _operation_from_row(
        row: PolymarketFundingOperationRow,
    ) -> PolymarketFundingOperation:
        return PolymarketFundingOperation(
            operation_id=row.operation_id,
            user_id=row.user_id,
            agent_id=row.agent_id,
            idempotency_key=row.idempotency_key,
            opc_installation_id=row.opc_installation_id,
            binding_id=row.binding_id,
            venue_wallet_address=row.venue_wallet_address,
            bridge_address=row.bridge_address,
            source_network=row.source_network,
            source_token_address=row.source_token_address,
            destination_network=row.destination_network,
            destination_token_address=row.destination_token_address,
            amount_usdc=row.amount_usdc,
            amount_atomic=row.amount_atomic,
            resource=row.resource,
            request_hash=row.request_hash,
            quote_hash=row.quote_hash,
            wallet_identity_id=row.wallet_identity_id,
            spending_grant_id=row.spending_grant_id,
            asset_allowance_id=row.asset_allowance_id,
            spender_address=row.spender_address,
            venue_buying_power_before_atomic=row.venue_buying_power_before_atomic,
            risk_level=row.risk_level,
            risk_score=row.risk_score,
            risk_action=row.risk_action,
            risk_assessment_id=row.risk_assessment_id,
            risk_assessed_at=_as_utc(row.risk_assessed_at),
            status=row.status,
            action_id=row.action_id,
            policy_decision_id=row.policy_decision_id,
            audit_event_id=row.audit_event_id,
            reservation_id=row.reservation_id,
            core_tx_hash=row.core_tx_hash,
            core_state=row.core_state,
            core_replacement_forbidden=row.core_replacement_forbidden,
            core_failure_evidence_kind=row.core_failure_evidence_kind,
            bridge_observation_id=row.bridge_observation_id,
            bridge_status=row.bridge_status,
            venue_buying_power_after_atomic=row.venue_buying_power_after_atomic,
            failure_reason_code=row.failure_reason_code,
            confirmed_at=(
                _as_utc(row.confirmed_at) if row.confirmed_at is not None else None
            ),
            finalized_at=(
                _as_utc(row.finalized_at) if row.finalized_at is not None else None
            ),
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
            revision=row.revision,
        )

    @staticmethod
    def _validated_operation(
        operation: PolymarketFundingOperation,
    ) -> PolymarketFundingOperation:
        invalid = False
        try:
            return PolymarketFundingOperation.model_validate(operation.model_dump())
        except (AttributeError, ValidationError):
            invalid = True
        if invalid:
            raise BridgeRepositoryError("funding operation is invalid") from None
        raise AssertionError("unreachable")

    @staticmethod
    def _validate_new_operation(operation: PolymarketFundingOperation) -> None:
        checkpoint_fields = (
            *_WRITE_ONCE_OPERATION_FIELDS,
            "core_state",
            "core_failure_evidence_kind",
            "bridge_observation_id",
            "bridge_status",
            "venue_buying_power_after_atomic",
        )
        if (
            operation.status != "created"
            or operation.revision != 0
            or operation.core_replacement_forbidden
            or operation.updated_at != operation.created_at
            or any(getattr(operation, field_name) is not None for field_name in checkpoint_fields)
        ):
            raise BridgeRepositoryError(
                "new funding operation state is invalid"
            )

    @staticmethod
    def _same_immutable_operation(
        left: PolymarketFundingOperation, right: PolymarketFundingOperation
    ) -> bool:
        return all(
            getattr(left, field_name) == getattr(right, field_name)
            for field_name in _IMMUTABLE_OPERATION_FIELDS
        )

    @staticmethod
    def _has_definite_core_failure_proof(
        operation: PolymarketFundingOperation,
    ) -> bool:
        return bool(
            operation.core_tx_hash
            and operation.core_replacement_forbidden
            and operation.core_failure_evidence_kind
            in {"definite_rpc_rejection", "failed_receipt"}
            and operation.failure_reason_code
            and operation.core_state in {"spending_reserved", "released"}
        )

    @staticmethod
    def _has_prebroadcast_release_proof(
        *,
        expected_status: FundingOperationStatus,
        replacement: PolymarketFundingOperation,
    ) -> bool:
        return bool(
            expected_status == "settlement_unknown"
            and replacement.status == "released"
            and replacement.core_tx_hash is None
            and replacement.core_state == "released"
            and replacement.core_replacement_forbidden is False
            and replacement.core_failure_evidence_kind is None
            and replacement.failure_reason_code
            == CORE_PREBROADCAST_RELEASE_REASON
        )

    @staticmethod
    def _operation_values(operation: PolymarketFundingOperation) -> dict:
        return operation.model_dump()

    @staticmethod
    def _mutable_operation_values(operation: PolymarketFundingOperation) -> dict:
        values = operation.model_dump()
        return {
            field_name: value
            for field_name, value in values.items()
            if field_name not in _IMMUTABLE_OPERATION_FIELDS
            and field_name not in {"operation_id", "created_at"}
        }


class SQLiteBridgeRepository(SqlAlchemyBridgeRepository):
    def __init__(self, database_path: Path | str) -> None:
        path = Path(database_path)
        if not str(path).strip():
            raise BridgeRepositoryError("personal bridge database path is required")
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(f"sqlite+pysqlite:///{path}")


class PostgresBridgeRepository(SqlAlchemyBridgeRepository):
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("postgresql+psycopg://"):
            raise BridgeRepositoryError(
                "server profile requires a postgresql+psycopg database URL"
            )
        super().__init__(database_url)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
