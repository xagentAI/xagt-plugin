"""Durable, non-authoritative allowance transaction recovery metadata.

This store deliberately sits beside the verified ``asset_allowances`` table.  A
recovery row can remember a wallet transaction that still needs independent
chain verification, but it can never itself make an allowance usable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import re
from typing import Mapping
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .repository import (
    Base,
    UInt256Storage,
    _utc_timestamp,
)
from .schemas import (
    MAX_UINT256,
    canonicalize_evm_address,
    canonicalize_transaction_hash,
)


KNOWN_EVM_NETWORKS = frozenset(
    {
        "eip155:137",
        "eip155:8453",
        "eip155:80002",
    }
)
OPEN_STATUSES = frozenset({"awaiting_wallet", "pending", "attention_required"})
RECOVERY_STATUSES = frozenset(
    {
        "awaiting_wallet",
        "pending",
        "verified",
        "rejected",
        "attention_required",
        "confirmed_mismatch",
    }
)
RECOVERY_RESULT_STATUSES = frozenset(
    {"pending", "verified", "rejected", "attention_required"}
)
RECOVERY_REASON_CODES = frozenset(
    {
        "rpc_unavailable",
        "chain_pending",
        "invalid_evidence",
        "wallet_unavailable",
        "amount_mismatch",
    }
)
REQUEST_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_AMOUNT_PATTERN = re.compile(r"^[1-9][0-9]*$")
MAX_DUE_ATTEMPTS = 10
LEASE_SECONDS = 120
MAX_RETRY_DELAY_SECONDS = 300


class AllowanceRecoveryRow(Base):
    """SQLAlchemy representation of one allowance transaction attempt."""

    __tablename__ = "allowance_recovery_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_wallet', 'pending', 'verified', 'rejected', "
            "'attention_required', 'confirmed_mismatch')",
            name="ck_allowance_recovery_status",
        ),
        CheckConstraint(
            "network IN ('eip155:137', 'eip155:8453', 'eip155:80002')",
            name="ck_allowance_recovery_network",
        ),
        CheckConstraint(
            "length(token_address) = 42 AND substr(token_address, 1, 2) = '0x' "
            "AND token_address = lower(token_address)",
            name="ck_allowance_recovery_token_address",
        ),
        CheckConstraint(
            "length(spender_address) = 42 AND substr(spender_address, 1, 2) = '0x' "
            "AND spender_address = lower(spender_address)",
            name="ck_allowance_recovery_spender_address",
        ),
        CheckConstraint(
            "amount_atomic IS NULL OR amount_atomic > 0",
            name="ck_allowance_recovery_amount_atomic_positive",
        ),
        CheckConstraint(
            "allowance_tx_hash IS NULL OR "
            "(length(allowance_tx_hash) = 66 AND "
            "substr(allowance_tx_hash, 1, 2) = '0x' AND "
            "allowance_tx_hash = lower(allowance_tx_hash))",
            name="ck_allowance_recovery_tx_hash",
        ),
        CheckConstraint(
            "request_key_digest IS NULL OR "
            "(length(request_key_digest) = 64 AND "
            "request_key_digest = lower(request_key_digest))",
            name="ck_allowance_recovery_request_key_digest",
        ),
        CheckConstraint(
            "reason_code IS NULL OR reason_code IN "
            "('rpc_unavailable', 'chain_pending', 'invalid_evidence', "
            "'wallet_unavailable', 'amount_mismatch')",
            name="ck_allowance_recovery_reason_code",
        ),
        CheckConstraint(
            "check_count >= 0",
            name="ck_allowance_recovery_check_count_nonnegative",
        ),
        CheckConstraint(
            "actual_approved_amount_atomic IS NULL OR "
            "actual_approved_amount_atomic > 0",
            name="ck_allowance_recovery_actual_amount_positive",
        ),
        CheckConstraint(
            "confirmed_block IS NULL OR confirmed_block >= 0",
            name="ck_allowance_recovery_confirmed_block_nonnegative",
        ),
        CheckConstraint(
            "confirmed_block_hash IS NULL OR "
            "(length(confirmed_block_hash) = 66 AND "
            "substr(confirmed_block_hash, 1, 2) = '0x' AND "
            "confirmed_block_hash = lower(confirmed_block_hash))",
            name="ck_allowance_recovery_confirmed_block_hash",
        ),
        CheckConstraint(
            "((status = 'confirmed_mismatch' AND allowance_tx_hash IS NOT NULL "
            "AND reason_code IS NOT NULL AND reason_code = 'amount_mismatch' "
            "AND next_check_at IS NULL "
            "AND amount_atomic IS NOT NULL "
            "AND actual_approved_amount_atomic IS NOT NULL "
            "AND observed_allowance_atomic IS NOT NULL "
            "AND confirmed_block IS NOT NULL "
            "AND confirmed_block_hash IS NOT NULL AND verified_at IS NOT NULL "
            "AND actual_approved_amount_atomic <> amount_atomic) OR "
            "(status <> 'confirmed_mismatch' "
            "AND actual_approved_amount_atomic IS NULL "
            "AND observed_allowance_atomic IS NULL "
            "AND confirmed_block IS NULL "
            "AND confirmed_block_hash IS NULL AND verified_at IS NULL))",
            name="ck_allowance_recovery_mismatch_evidence_complete",
        ),
        Index(
            "uq_allowance_recovery_open_scope",
            "wallet_identity_id",
            "network",
            "token_address",
            "spender_address",
            unique=True,
            sqlite_where=text(
                "status IN ('awaiting_wallet', 'pending', 'attention_required')"
            ),
            postgresql_where=text(
                "status IN ('awaiting_wallet', 'pending', 'attention_required')"
            ),
        ),
        Index(
            "uq_allowance_recovery_wallet_network_hash",
            "wallet_identity_id",
            "network",
            "allowance_tx_hash",
            unique=True,
            sqlite_where=text("allowance_tx_hash IS NOT NULL"),
            postgresql_where=text("allowance_tx_hash IS NOT NULL"),
        ),
        Index(
            "uq_allowance_recovery_request_key_digest",
            "request_key_digest",
            unique=True,
            sqlite_where=text("request_key_digest IS NOT NULL"),
            postgresql_where=text("request_key_digest IS NOT NULL"),
        ),
        Index(
            "ix_allowance_recovery_wallet_created",
            "wallet_identity_id",
            "created_at",
            "attempt_id",
        ),
        Index(
            "ix_allowance_recovery_due",
            "status",
            "next_check_at",
            "attempt_id",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True, nullable=False)
    wallet_identity_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"),
        index=True,
        nullable=False,
    )
    network: Mapped[str] = mapped_column(String(64), nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    spender_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_atomic: Mapped[Decimal | None] = mapped_column(
        UInt256Storage(), nullable=True
    )
    allowance_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    request_key_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    check_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    actual_approved_amount_atomic: Mapped[Decimal | None] = mapped_column(
        UInt256Storage(), nullable=True
    )
    observed_allowance_atomic: Mapped[Decimal | None] = mapped_column(
        UInt256Storage(), nullable=True
    )
    confirmed_block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_block_hash: Mapped[str | None] = mapped_column(
        String(66), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def _required_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = _utc_timestamp(value)
    assert normalized is not None
    return normalized.isoformat()


def _canonical_network(value: str) -> str:
    if not isinstance(value, str) or value not in KNOWN_EVM_NETWORKS:
        raise ValueError("network is not a canonical EVM network")
    return value


def _canonical_amount(value: str) -> str:
    if not isinstance(value, str) or CANONICAL_AMOUNT_PATTERN.fullmatch(value) is None:
        raise ValueError("amount_atomic must be a positive uint256 decimal string")
    if len(value) > 78 or int(value) > MAX_UINT256:
        raise ValueError("amount_atomic must be a positive uint256 decimal string")
    return value


def _canonical_uint256(value, *, positive: bool, field_name: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a canonical uint256 decimal string")
    if isinstance(value, int):
        rendered = str(value)
    elif isinstance(value, Decimal):
        try:
            integer_value = int(value)
        except (ValueError, OverflowError) as exc:
            raise ValueError(
                f"{field_name} must be a canonical uint256 decimal string"
            ) from exc
        if value != integer_value:
            raise ValueError(
                f"{field_name} must be a canonical uint256 decimal string"
            )
        rendered = str(integer_value)
    elif isinstance(value, str):
        rendered = value
    else:
        raise ValueError(f"{field_name} must be a canonical uint256 decimal string")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)", rendered):
        raise ValueError(f"{field_name} must be a canonical uint256 decimal string")
    number = int(rendered)
    if number > MAX_UINT256 or (positive and number == 0):
        raise ValueError(f"{field_name} must be a canonical uint256 decimal string")
    return rendered


def _request_digest(value: str) -> str:
    if not isinstance(value, str) or REQUEST_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("request key is not canonical")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _canonical_identifier(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 96
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def _public_amount(value: Decimal | int | str | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value), "f")


def _evidence_timestamp(value) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("verified_at must be timezone-aware") from exc
    return _required_utc(value)


class AllowanceRecoveryStore:
    """Persist and reconcile allowance transaction attempts.

    ``repository`` must be an existing :class:`AccountRepository`.  The model
    is registered on that repository's ``Base`` at module import time, so the
    module must be imported before a new SQLite repository is constructed.
    The store intentionally does not perform PostgreSQL DDL.
    """

    def __init__(self, repository):
        self.repository = repository

    @property
    def _is_sqlite(self) -> bool:
        return self.repository.engine.dialect.name == "sqlite"

    def _locked_identity(self, session, wallet_identity_id: str, user_id: str, *, require_active: bool = True):
        identity = self.repository._locked_wallet_identity(session, wallet_identity_id)
        if identity is None or identity.user_id != user_id:
            raise ValueError("wallet identity is unavailable")
        if require_active and identity.status != "active":
            raise ValueError("wallet identity is not active")
        return identity

    def _attempt(self, session, attempt_id: str, *, lock: bool = False):
        statement = select(AllowanceRecoveryRow).where(
            AllowanceRecoveryRow.attempt_id == attempt_id
        )
        if lock:
            # The first read is intentionally performed before locking the
            # wallet identity so we can discover which identity to lock.  A
            # PostgreSQL lock may wait behind another tab; force SQLAlchemy
            # to refresh its identity-map entry after that wait.
            statement = statement.execution_options(populate_existing=True)
            if not self._is_sqlite:
                statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _scope_matches(row: AllowanceRecoveryRow, values: dict[str, str]) -> bool:
        return all(
            getattr(row, field) == values[field]
            for field in ("user_id", "wallet_identity_id", "network", "token_address", "spender_address")
        ) and _public_amount(row.amount_atomic) == values["amount_atomic"]

    @staticmethod
    def _public(row: AllowanceRecoveryRow) -> dict[str, object]:
        record = {
            "attempt_id": row.attempt_id,
            "user_id": row.user_id,
            "wallet_identity_id": row.wallet_identity_id,
            "network": row.network,
            "token_address": row.token_address,
            "spender_address": row.spender_address,
            "amount_atomic": _public_amount(row.amount_atomic),
            "allowance_tx_hash": row.allowance_tx_hash,
            "status": row.status,
            "reason_code": row.reason_code,
            "created_at": _iso_utc(row.created_at),
            "updated_at": _iso_utc(row.updated_at),
            "next_check_at": _iso_utc(row.next_check_at),
        }
        if row.status == "confirmed_mismatch":
            record.update(
                {
                    "actual_approved_amount_atomic": _public_amount(
                        row.actual_approved_amount_atomic
                    ),
                    "observed_allowance_atomic": _public_amount(
                        row.observed_allowance_atomic
                    ),
                    "confirmed_block": row.confirmed_block,
                    "confirmed_block_hash": row.confirmed_block_hash,
                    "verified_at": _iso_utc(row.verified_at),
                }
            )
        return record

    @staticmethod
    def _normalized_mismatch_evidence(evidence: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(evidence, Mapping):
            raise ValueError("allowance mismatch evidence is invalid")

        expected_value = evidence.get("expected_amount_atomic")
        amount_value = evidence.get("amount_atomic")
        if expected_value is not None and amount_value is not None:
            canonical_expected = _canonical_uint256(
                expected_value,
                positive=True,
                field_name="expected_amount_atomic",
            )
            canonical_amount = _canonical_uint256(
                amount_value,
                positive=True,
                field_name="amount_atomic",
            )
            if canonical_expected != canonical_amount:
                raise ValueError("allowance mismatch prepared amount is inconsistent")
            expected_value = canonical_expected
        if expected_value is None:
            expected_value = amount_value

        try:
            normalized = {
                "wallet_identity_id": _canonical_identifier(
                    evidence["wallet_identity_id"],
                    field_name="wallet_identity_id",
                ),
                "network": _canonical_network(evidence["network"]),
                "token_address": canonicalize_evm_address(
                    evidence["token_address"]
                ),
                "spender_address": canonicalize_evm_address(
                    evidence["spender_address"]
                ),
                "allowance_tx_hash": canonicalize_transaction_hash(
                    evidence["allowance_tx_hash"]
                ),
                "amount_atomic": _canonical_uint256(
                    expected_value,
                    positive=True,
                    field_name="expected_amount_atomic",
                ),
                "actual_approved_amount_atomic": _canonical_uint256(
                    evidence["actual_approved_amount_atomic"],
                    positive=True,
                    field_name="actual_approved_amount_atomic",
                ),
                "observed_allowance_atomic": _canonical_uint256(
                    evidence["observed_allowance_atomic"],
                    positive=False,
                    field_name="observed_allowance_atomic",
                ),
                "confirmed_block": evidence["confirmed_block"],
                "confirmed_block_hash": canonicalize_transaction_hash(
                    evidence["confirmed_block_hash"]
                ),
                "verified_at": _evidence_timestamp(evidence["verified_at"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("allowance mismatch evidence is incomplete") from exc

        if (
            isinstance(normalized["confirmed_block"], bool)
            or not isinstance(normalized["confirmed_block"], int)
            or normalized["confirmed_block"] < 0
        ):
            raise ValueError("confirmed_block must be a non-negative integer")
        if normalized["actual_approved_amount_atomic"] == normalized["amount_atomic"]:
            raise ValueError("allowance mismatch amounts must differ")
        if "user_id" in evidence:
            normalized["user_id"] = _canonical_identifier(
                evidence["user_id"], field_name="user_id"
            )
        if "attempt_id" in evidence:
            normalized["attempt_id"] = _canonical_identifier(
                evidence["attempt_id"], field_name="attempt_id"
            )
        return normalized

    @staticmethod
    def _mismatch_scope_matches(
        row: AllowanceRecoveryRow, evidence: Mapping[str, object]
    ) -> bool:
        return (
            row.wallet_identity_id == evidence["wallet_identity_id"]
            and row.network == evidence["network"]
            and row.token_address == evidence["token_address"]
            and row.spender_address == evidence["spender_address"]
            and row.allowance_tx_hash == evidence["allowance_tx_hash"]
            and _public_amount(row.amount_atomic) == evidence["amount_atomic"]
        )

    def begin(
        self,
        *,
        user_id: str,
        wallet_identity_id: str,
        network: str,
        token_address: str,
        spender_address: str,
        amount_atomic: str,
        request_key: str,
        now: datetime,
    ) -> dict[str, object]:
        user_id = _canonical_identifier(user_id, field_name="user_id")
        wallet_identity_id = _canonical_identifier(
            wallet_identity_id, field_name="wallet_identity_id"
        )
        network = _canonical_network(network)
        token_address = canonicalize_evm_address(token_address)
        spender_address = canonicalize_evm_address(spender_address)
        amount_atomic = _canonical_amount(amount_atomic)
        request_key_digest = _request_digest(request_key)
        now = _required_utc(now)
        scope = {
            "user_id": user_id,
            "wallet_identity_id": wallet_identity_id,
            "network": network,
            "token_address": token_address,
            "spender_address": spender_address,
            "amount_atomic": amount_atomic,
        }

        try:
            with self.repository._write_session() as session:
                # This is deliberately the first database lock.  Wallet
                # revocation and competing browser tabs use this same lock.
                self._locked_identity(session, wallet_identity_id, user_id)
                request_statement = select(AllowanceRecoveryRow).where(
                    AllowanceRecoveryRow.request_key_digest == request_key_digest
                )
                if not self._is_sqlite:
                    request_statement = request_statement.with_for_update()
                existing = session.scalar(request_statement)
                if existing is not None:
                    if self._scope_matches(existing, scope):
                        return {"created": False, "attempt": self._public(existing)}
                    raise ValueError("allowance recovery request conflicts with an existing attempt")

                open_statement = select(AllowanceRecoveryRow).where(
                    AllowanceRecoveryRow.wallet_identity_id == wallet_identity_id,
                    AllowanceRecoveryRow.network == network,
                    AllowanceRecoveryRow.token_address == token_address,
                    AllowanceRecoveryRow.spender_address == spender_address,
                    AllowanceRecoveryRow.status.in_(tuple(OPEN_STATUSES)),
                )
                if not self._is_sqlite:
                    open_statement = open_statement.with_for_update()
                if session.scalar(open_statement) is not None:
                    raise ValueError("allowance recovery scope conflicts with an existing attempt")

                row = AllowanceRecoveryRow(
                    attempt_id=uuid4().hex,
                    user_id=user_id,
                    wallet_identity_id=wallet_identity_id,
                    network=network,
                    token_address=token_address,
                    spender_address=spender_address,
                    amount_atomic=amount_atomic,
                    allowance_tx_hash=None,
                    status="awaiting_wallet",
                    reason_code=None,
                    created_at=now,
                    updated_at=now,
                    next_check_at=None,
                    request_key_digest=request_key_digest,
                    check_count=0,
                )
                session.add(row)
                return {"created": True, "attempt": self._public(row)}
        except IntegrityError as exc:
            raise ValueError("allowance recovery attempt conflicts with an existing record") from exc

    def submitted(
        self,
        *,
        user_id: str,
        attempt_id: str,
        request_key: str,
        allowance_tx_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        user_id = _canonical_identifier(user_id, field_name="user_id")
        attempt_id = _canonical_identifier(attempt_id, field_name="attempt_id")
        request_key_digest = _request_digest(request_key)
        allowance_tx_hash = canonicalize_transaction_hash(allowance_tx_hash)
        now = _required_utc(now)

        try:
            with self.repository._write_session() as session:
                snapshot = self._attempt(session, attempt_id)
                if snapshot is None:
                    raise ValueError("allowance attempt is unavailable")
                # Look up the identity from the durable attempt, then lock it
                # before locking or changing the attempt itself.
                self._locked_identity(session, snapshot.wallet_identity_id, user_id)
                row = self._attempt(session, attempt_id, lock=True)
                if (
                    row is None
                    or row.user_id != user_id
                    or row.request_key_digest is None
                    or not hmac.compare_digest(row.request_key_digest, request_key_digest)
                ):
                    raise ValueError("allowance attempt is unavailable")

                if row.allowance_tx_hash is not None:
                    if hmac.compare_digest(row.allowance_tx_hash, allowance_tx_hash):
                        return self._public(row)
                    raise ValueError("allowance attempt conflicts with an existing transaction")
                if row.status != "awaiting_wallet":
                    raise ValueError("allowance attempt cannot accept a transaction")

                duplicate_hash = session.scalar(
                    select(AllowanceRecoveryRow).where(
                        AllowanceRecoveryRow.wallet_identity_id == row.wallet_identity_id,
                        AllowanceRecoveryRow.network == row.network,
                        AllowanceRecoveryRow.allowance_tx_hash == allowance_tx_hash,
                        AllowanceRecoveryRow.attempt_id != row.attempt_id,
                    )
                )
                if duplicate_hash is not None:
                    raise ValueError("allowance transaction conflicts with an existing attempt")

                row.allowance_tx_hash = allowance_tx_hash
                row.status = "pending"
                row.reason_code = None
                row.next_check_at = now
                row.updated_at = now
                return self._public(row)
        except IntegrityError as exc:
            raise ValueError("allowance transaction conflicts with an existing attempt") from exc

    def rejected(
        self,
        *,
        user_id: str,
        attempt_id: str,
        request_key: str,
        now: datetime,
    ) -> dict[str, object]:
        user_id = _canonical_identifier(user_id, field_name="user_id")
        attempt_id = _canonical_identifier(attempt_id, field_name="attempt_id")
        request_key_digest = _request_digest(request_key)
        now = _required_utc(now)

        with self.repository._write_session() as session:
            snapshot = self._attempt(session, attempt_id)
            if snapshot is None:
                raise ValueError("allowance attempt is unavailable")
            self._locked_identity(session, snapshot.wallet_identity_id, user_id)
            row = self._attempt(session, attempt_id, lock=True)
            if (
                row is None
                or row.user_id != user_id
                or row.request_key_digest is None
                or not hmac.compare_digest(row.request_key_digest, request_key_digest)
            ):
                raise ValueError("allowance attempt is unavailable")
            if row.status == "rejected" and row.allowance_tx_hash is None:
                return self._public(row)
            if row.allowance_tx_hash is not None or row.status != "awaiting_wallet":
                raise ValueError("allowance attempt cannot be rejected")
            row.status = "rejected"
            row.reason_code = None
            row.next_check_at = None
            row.updated_at = now
            return self._public(row)

    def register_proof(
        self,
        *,
        user_id: str,
        wallet_identity_id: str,
        network: str,
        token_address: str,
        spender_address: str,
        allowance_tx_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        user_id = _canonical_identifier(user_id, field_name="user_id")
        wallet_identity_id = _canonical_identifier(
            wallet_identity_id, field_name="wallet_identity_id"
        )
        network = _canonical_network(network)
        token_address = canonicalize_evm_address(token_address)
        spender_address = canonicalize_evm_address(spender_address)
        allowance_tx_hash = canonicalize_transaction_hash(allowance_tx_hash)
        now = _required_utc(now)

        try:
            with self.repository._write_session() as session:
                self._locked_identity(session, wallet_identity_id, user_id)
                exact = session.scalar(
                    select(AllowanceRecoveryRow).where(
                        AllowanceRecoveryRow.wallet_identity_id == wallet_identity_id,
                        AllowanceRecoveryRow.network == network,
                        AllowanceRecoveryRow.token_address == token_address,
                        AllowanceRecoveryRow.spender_address == spender_address,
                        AllowanceRecoveryRow.allowance_tx_hash == allowance_tx_hash,
                    )
                )
                if exact is not None:
                    return self._public(exact)

                duplicate_hash = session.scalar(
                    select(AllowanceRecoveryRow).where(
                        AllowanceRecoveryRow.wallet_identity_id == wallet_identity_id,
                        AllowanceRecoveryRow.network == network,
                        AllowanceRecoveryRow.allowance_tx_hash == allowance_tx_hash,
                    )
                )
                if duplicate_hash is not None:
                    raise ValueError("allowance transaction conflicts with an existing attempt")

                open_statement = select(AllowanceRecoveryRow).where(
                    AllowanceRecoveryRow.wallet_identity_id == wallet_identity_id,
                    AllowanceRecoveryRow.network == network,
                    AllowanceRecoveryRow.token_address == token_address,
                    AllowanceRecoveryRow.spender_address == spender_address,
                    AllowanceRecoveryRow.status.in_(tuple(OPEN_STATUSES)),
                )
                if not self._is_sqlite:
                    open_statement = open_statement.with_for_update()
                if session.scalar(open_statement) is not None:
                    raise ValueError("allowance recovery scope conflicts with an existing attempt")

                row = AllowanceRecoveryRow(
                    attempt_id=uuid4().hex,
                    user_id=user_id,
                    wallet_identity_id=wallet_identity_id,
                    network=network,
                    token_address=token_address,
                    spender_address=spender_address,
                    amount_atomic=None,
                    allowance_tx_hash=allowance_tx_hash,
                    status="pending",
                    reason_code=None,
                    created_at=now,
                    updated_at=now,
                    next_check_at=now,
                    request_key_digest=None,
                    check_count=0,
                )
                session.add(row)
                return self._public(row)
        except IntegrityError as exc:
            raise ValueError("allowance transaction conflicts with an existing attempt") from exc

    def confirm_mismatch(
        self,
        *,
        attempt_id: str,
        evidence: Mapping[str, object],
        now: datetime,
    ) -> dict[str, object]:
        """Atomically record a fully independently verified amount mismatch.

        This is the sole path that can create the terminal mismatch status.
        It intentionally never writes ``asset_allowances`` or any spending
        authority; the row and its audit event commit together.
        """
        attempt_id = _canonical_identifier(attempt_id, field_name="attempt_id")
        normalized = self._normalized_mismatch_evidence(evidence)
        now = _required_utc(now)

        with self.repository._write_session() as session:
            snapshot = self._attempt(session, attempt_id)
            if snapshot is None:
                raise ValueError("allowance attempt is unavailable")
            identity = self._locked_identity(
                session,
                snapshot.wallet_identity_id,
                snapshot.user_id,
                require_active=True,
            )
            row = self._attempt(session, attempt_id, lock=True)
            if (
                row is None
                or row.user_id != snapshot.user_id
                or normalized.get("attempt_id", attempt_id) != attempt_id
                or normalized.get("user_id", row.user_id) != row.user_id
                or not self._mismatch_scope_matches(row, normalized)
            ):
                raise ValueError("allowance mismatch evidence does not match attempt")
            if identity.status != "active":
                raise ValueError("wallet identity is not active")

            # A terminal row is immutable.  A repeated read of the same proof
            # returns the original evidence and cannot create another audit.
            if row.status == "confirmed_mismatch":
                return self._public(row)
            # ``attention_required`` is an unresolved proof produced by an
            # earlier failed independent check.  A later authenticated
            # request with the same transaction hash may complete the full
            # check and terminally record a mismatch.  Hashless attempts and
            # all other terminal states remain ineligible.
            if row.status not in {"pending", "attention_required"} or row.allowance_tx_hash is None:
                raise ValueError("allowance attempt is not awaiting mismatch confirmation")
            if row.amount_atomic is None:
                raise ValueError("allowance attempt has no prepared amount")

            row.actual_approved_amount_atomic = normalized[
                "actual_approved_amount_atomic"
            ]
            row.observed_allowance_atomic = normalized["observed_allowance_atomic"]
            row.confirmed_block = normalized["confirmed_block"]
            row.confirmed_block_hash = normalized["confirmed_block_hash"]
            row.verified_at = normalized["verified_at"]
            row.status = "confirmed_mismatch"
            row.reason_code = "amount_mismatch"
            row.next_check_at = None
            row.updated_at = now
            self.repository._append_account_audit(
                session,
                event_type="allowance_confirmed_mismatch",
                user_id=row.user_id,
                created_at=now,
                payload={
                    "attempt_id": row.attempt_id,
                    "wallet_identity_id": row.wallet_identity_id,
                    "network": row.network,
                    "token_address": row.token_address,
                    "spender_address": row.spender_address,
                    "allowance_tx_hash": row.allowance_tx_hash,
                    "amount_atomic": _public_amount(row.amount_atomic),
                    "actual_approved_amount_atomic": _public_amount(
                        row.actual_approved_amount_atomic
                    ),
                    "observed_allowance_atomic": _public_amount(
                        row.observed_allowance_atomic
                    ),
                    "confirmed_block": row.confirmed_block,
                    "confirmed_block_hash": row.confirmed_block_hash,
                    "verified_at": _iso_utc(row.verified_at),
                    "status": row.status,
                    "reason_code": row.reason_code,
                },
            )
            return self._public(row)

    def records(
        self, *, user_id: str, wallet_identity_id: str
    ) -> list[dict[str, object]]:
        user_id = _canonical_identifier(user_id, field_name="user_id")
        wallet_identity_id = _canonical_identifier(
            wallet_identity_id, field_name="wallet_identity_id"
        )
        with self.repository.sessions() as session:
            base_filter = (
                AllowanceRecoveryRow.user_id == user_id,
                AllowanceRecoveryRow.wallet_identity_id == wallet_identity_id,
            )
            open_rows = session.scalars(
                select(AllowanceRecoveryRow)
                .where(*base_filter, AllowanceRecoveryRow.status.in_(tuple(OPEN_STATUSES)))
                .order_by(
                    AllowanceRecoveryRow.created_at.desc(),
                    AllowanceRecoveryRow.attempt_id.desc(),
                )
            ).all()
            terminal_rows = session.scalars(
                select(AllowanceRecoveryRow)
                .where(*base_filter, ~AllowanceRecoveryRow.status.in_(tuple(OPEN_STATUSES)))
                .order_by(
                    AllowanceRecoveryRow.created_at.desc(),
                    AllowanceRecoveryRow.attempt_id.desc(),
                )
                .limit(20)
            ).all()
        # Never hide an unresolved attempt behind terminal history.  The
        # terminal portion remains bounded to keep account projections small.
        return [self._public(row) for row in [*open_rows, *terminal_rows]]

    def get(self, *, user_id: str, attempt_id: str) -> dict[str, object] | None:
        """Return one public attempt only when it belongs to ``user_id``."""

        user_id = _canonical_identifier(user_id, field_name="user_id")
        attempt_id = _canonical_identifier(attempt_id, field_name="attempt_id")
        with self.repository.sessions() as session:
            row = session.scalar(
                select(AllowanceRecoveryRow).where(
                    AllowanceRecoveryRow.user_id == user_id,
                    AllowanceRecoveryRow.attempt_id == attempt_id,
                )
            )
        return self._public(row) if row is not None else None

    def due(
        self, *, now: datetime, limit: int = MAX_DUE_ATTEMPTS
    ) -> list[dict[str, object]]:
        now = _required_utc(now)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("due limit is invalid")
        limit = min(limit, MAX_DUE_ATTEMPTS)
        if limit == 0:
            return []

        with self.repository._write_session() as session:
            statement = (
                select(AllowanceRecoveryRow)
                .where(
                    AllowanceRecoveryRow.status == "pending",
                    AllowanceRecoveryRow.allowance_tx_hash.is_not(None),
                    AllowanceRecoveryRow.next_check_at.is_not(None),
                    AllowanceRecoveryRow.next_check_at <= now,
                )
                .order_by(
                    AllowanceRecoveryRow.next_check_at.asc(),
                    AllowanceRecoveryRow.attempt_id.asc(),
                )
                .limit(limit)
            )
            if not self._is_sqlite:
                statement = statement.with_for_update(skip_locked=True)
            rows = session.scalars(statement).all()
            lease_until = now + timedelta(seconds=LEASE_SECONDS)
            for row in rows:
                row.next_check_at = lease_until
                row.updated_at = now
            return [self._public(row) for row in rows]

    def result(
        self,
        *,
        attempt_id: str,
        status: str,
        reason_code: str | None,
        now: datetime,
    ) -> dict[str, object]:
        attempt_id = _canonical_identifier(attempt_id, field_name="attempt_id")
        if status not in RECOVERY_RESULT_STATUSES:
            raise ValueError("allowance recovery result status is invalid")
        if reason_code is not None and reason_code not in RECOVERY_REASON_CODES:
            raise ValueError("allowance recovery reason code is invalid")
        now = _required_utc(now)

        with self.repository._write_session() as session:
            snapshot = self._attempt(session, attempt_id)
            if snapshot is None:
                raise ValueError("allowance attempt is unavailable")
            identity = self._locked_identity(
                session, snapshot.wallet_identity_id, snapshot.user_id,
                require_active=False,
            )
            row = self._attempt(session, attempt_id, lock=True)
            if row is None:
                raise ValueError("allowance attempt is unavailable")
            if row.status in {"verified", "rejected", "confirmed_mismatch"}:
                return self._public(row)
            if row.allowance_tx_hash is None:
                raise ValueError("allowance attempt has no transaction proof")
            if status == "rejected":
                raise ValueError("known allowance transaction cannot be rejected")

            # Revocation must stop retries without reviving allowance authority.
            # Only this internal metadata result path can lock an inactive wallet;
            # all browser-originated writes still require an active identity.
            if identity.status != "active":
                row.status = "attention_required"
                row.reason_code = "wallet_unavailable"
                row.next_check_at = None
            elif status == "verified":
                row.status = "verified"
                row.reason_code = None
                row.next_check_at = None
            elif status == "attention_required":
                row.status = "attention_required"
                row.reason_code = reason_code
                row.next_check_at = None
            else:
                row.status = "pending"
                row.reason_code = reason_code
                # Cap the exponent before calculating it.  This keeps a row
                # with a very large persisted retry count inexpensive to
                # reconcile while retaining the five-minute delay cap.
                retry_exponent = min(max(int(row.check_count or 0), 0), 7)
                delay = min(
                    3 * (2**retry_exponent),
                    MAX_RETRY_DELAY_SECONDS,
                )
                row.check_count = int(row.check_count or 0) + 1
                row.next_check_at = now + timedelta(seconds=delay)
            row.updated_at = now
            return self._public(row)


__all__ = [
    "AllowanceRecoveryRow",
    "AllowanceRecoveryStore",
    "KNOWN_EVM_NETWORKS",
    "OPEN_STATUSES",
    "RECOVERY_REASON_CODES",
    "RECOVERY_STATUSES",
]
