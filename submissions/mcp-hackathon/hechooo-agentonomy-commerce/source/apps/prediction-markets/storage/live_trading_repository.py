from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ORDER_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_PROJECTION_HASH = re.compile(r"^[0-9a-f]{64}$")
_SUBMISSION_STATUSES = {
    "intent_recorded",
    "submitting",
    "unknown",
    "submitted",
    "rejected",
}
_EXPECTED_COLUMNS = {
    "signing_session_id",
    "user_id",
    "binding_id",
    "wallet_address",
    "client_order_id",
    "projection_hash",
    "funding_operation_id",
    "submission_status",
    "order_id",
    "revision",
    "created_at",
    "updated_at",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS polymarket_live_submissions (
  signing_session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  binding_id TEXT NOT NULL,
  wallet_address TEXT NOT NULL,
  client_order_id TEXT NOT NULL UNIQUE,
  projection_hash TEXT NOT NULL,
  funding_operation_id TEXT NOT NULL,
  submission_status TEXT NOT NULL
    CHECK (
      submission_status IN (
        'intent_recorded',
        'submitting',
        'unknown',
        'submitted',
        'rejected'
      )
    ),
  order_id TEXT,
  revision INTEGER NOT NULL CHECK (revision >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (submission_status = 'submitted' AND order_id = client_order_id)
    OR
    (submission_status != 'submitted' AND order_id IS NULL)
  )
);
"""


class LiveTradingRepositoryError(RuntimeError):
    """A fixed, redacted live-submission persistence failure."""


@dataclass(frozen=True, slots=True)
class LiveSubmissionRecord:
    signing_session_id: str
    user_id: str
    binding_id: str
    wallet_address: str
    client_order_id: str
    projection_hash: str
    funding_operation_id: str
    submission_status: str
    order_id: str | None
    revision: int
    created_at: str
    updated_at: str


class SQLiteLiveTradingRepository:
    """Single-node SQLite authority for one-shot Polymarket submission state."""

    def __init__(self, database_path: Path | str) -> None:
        path = Path(database_path)
        if not str(path).strip():
            raise LiveTradingRepositoryError(
                "personal live trading database path is required"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = path
        self._initialize()

    def _initialize(self) -> None:
        try:
            with self._transaction() as connection:
                connection.executescript(_SCHEMA)
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(polymarket_live_submissions)"
                    ).fetchall()
                }
                if columns != _EXPECTED_COLUMNS:
                    raise LiveTradingRepositoryError(
                        "live trading database schema is incompatible"
                    )
        except LiveTradingRepositoryError:
            raise
        except sqlite3.Error:
            raise LiveTradingRepositoryError(
                "live trading database initialization failed"
            ) from None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_submission_intent(
        self,
        *,
        signing_session_id: str,
        user_id: str,
        binding_id: str,
        wallet_address: str,
        client_order_id: str,
        projection_hash: str,
        funding_operation_id: str,
    ) -> LiveSubmissionRecord:
        session_id = self._validate_identifier(signing_session_id)
        scoped_user_id = self._validate_identifier(user_id)
        scoped_binding_id = self._validate_identifier(binding_id)
        funding_id = self._validate_identifier(funding_operation_id)
        if funding_id == "unassigned":
            raise LiveTradingRepositoryError(
                "live trading funding provenance is required"
            )
        wallet = self._validate_address(wallet_address)
        recovery_id = self._validate_order_hash(client_order_id)
        projection = self._validate_projection_hash(projection_hash)
        now = self._utc_now()
        proposed = LiveSubmissionRecord(
            signing_session_id=session_id,
            user_id=scoped_user_id,
            binding_id=scoped_binding_id,
            wallet_address=wallet,
            client_order_id=recovery_id,
            projection_hash=projection,
            funding_operation_id=funding_id,
            submission_status="intent_recorded",
            order_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM polymarket_live_submissions
                    WHERE signing_session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row is not None:
                    current = self._record(row)
                    immutable = (
                        "user_id",
                        "binding_id",
                        "wallet_address",
                        "client_order_id",
                        "projection_hash",
                        "funding_operation_id",
                    )
                    if any(
                        getattr(current, field) != getattr(proposed, field)
                        for field in immutable
                    ):
                        raise LiveTradingRepositoryError(
                            "live trading idempotency payload conflicts"
                        )
                    return current
                connection.execute(
                    """
                    INSERT INTO polymarket_live_submissions (
                      signing_session_id,
                      user_id,
                      binding_id,
                      wallet_address,
                      client_order_id,
                      projection_hash,
                      funding_operation_id,
                      submission_status,
                      order_id,
                      revision,
                      created_at,
                      updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposed.signing_session_id,
                        proposed.user_id,
                        proposed.binding_id,
                        proposed.wallet_address,
                        proposed.client_order_id,
                        proposed.projection_hash,
                        proposed.funding_operation_id,
                        proposed.submission_status,
                        proposed.order_id,
                        proposed.revision,
                        proposed.created_at,
                        proposed.updated_at,
                    ),
                )
        except LiveTradingRepositoryError:
            raise
        except sqlite3.IntegrityError:
            raise LiveTradingRepositoryError(
                "live trading idempotency payload conflicts"
            ) from None
        except sqlite3.Error:
            raise LiveTradingRepositoryError(
                "live trading database operation failed"
            ) from None
        return proposed

    def claim_submission(
        self,
        *,
        signing_session_id: str,
        expected_revision: int,
    ) -> LiveSubmissionRecord | None:
        return self._compare_and_set(
            signing_session_id=signing_session_id,
            expected_revision=expected_revision,
            expected_statuses={"intent_recorded"},
            submission_status="submitting",
            order_id=None,
        )

    def record_submission_result(
        self,
        *,
        signing_session_id: str,
        expected_revision: int,
        submission_status: str,
        order_id: str | None,
    ) -> LiveSubmissionRecord | None:
        if submission_status not in {"unknown", "submitted", "rejected"}:
            raise LiveTradingRepositoryError("live trading status is invalid")
        normalized_order_id = (
            self._validate_order_hash(order_id)
            if order_id is not None
            else None
        )
        if submission_status == "submitted" and normalized_order_id is None:
            raise LiveTradingRepositoryError("live trading order ID is required")
        if submission_status != "submitted" and normalized_order_id is not None:
            raise LiveTradingRepositoryError(
                "live trading order ID is invalid for status"
            )
        expected_statuses = (
            {"submitting", "unknown"}
            if submission_status == "submitted"
            else {"submitting"}
        )
        return self._compare_and_set(
            signing_session_id=signing_session_id,
            expected_revision=expected_revision,
            expected_statuses=expected_statuses,
            submission_status=submission_status,
            order_id=normalized_order_id,
        )

    def _compare_and_set(
        self,
        *,
        signing_session_id: str,
        expected_revision: int,
        expected_statuses: set[str],
        submission_status: str,
        order_id: str | None,
    ) -> LiveSubmissionRecord | None:
        session_id = self._validate_identifier(signing_session_id)
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
            or submission_status not in _SUBMISSION_STATUSES
        ):
            raise LiveTradingRepositoryError("live trading status is invalid")
        placeholders = ",".join("?" for _ in expected_statuses)
        now = self._utc_now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM polymarket_live_submissions
                    WHERE signing_session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if (
                    row is None
                    or row["revision"] != expected_revision
                    or row["submission_status"] not in expected_statuses
                ):
                    return None
                current = self._record(row)
                if order_id is not None and order_id != current.client_order_id:
                    raise LiveTradingRepositoryError(
                        "live trading order ID does not match recovery ID"
                    )
                replacement = replace(
                    current,
                    submission_status=submission_status,
                    order_id=order_id,
                    revision=expected_revision + 1,
                    updated_at=now,
                )
                result = connection.execute(
                    f"""
                    UPDATE polymarket_live_submissions
                    SET
                      submission_status = ?,
                      order_id = ?,
                      revision = ?,
                      updated_at = ?
                    WHERE signing_session_id = ?
                      AND revision = ?
                      AND submission_status IN ({placeholders})
                    """,
                    (
                        replacement.submission_status,
                        replacement.order_id,
                        replacement.revision,
                        replacement.updated_at,
                        replacement.signing_session_id,
                        expected_revision,
                        *sorted(expected_statuses),
                    ),
                )
                return replacement if result.rowcount == 1 else None
        except LiveTradingRepositoryError:
            raise
        except sqlite3.Error:
            raise LiveTradingRepositoryError(
                "live trading database operation failed"
            ) from None

    def get_submission(
        self,
        *,
        signing_session_id: str,
        user_id: str,
        binding_id: str,
        wallet_address: str,
    ) -> LiveSubmissionRecord | None:
        session_id = self._validate_identifier(signing_session_id)
        scoped_user_id = self._validate_identifier(user_id)
        scoped_binding_id = self._validate_identifier(binding_id)
        wallet = self._validate_address(wallet_address)
        try:
            with sqlite3.connect(self.database_path, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT *
                    FROM polymarket_live_submissions
                    WHERE signing_session_id = ?
                      AND user_id = ?
                      AND binding_id = ?
                      AND wallet_address = ?
                    """,
                    (
                        session_id,
                        scoped_user_id,
                        scoped_binding_id,
                        wallet,
                    ),
                ).fetchone()
        except sqlite3.Error:
            raise LiveTradingRepositoryError(
                "live trading database operation failed"
            ) from None
        return self._record(row) if row is not None else None

    @staticmethod
    def _record(row: sqlite3.Row) -> LiveSubmissionRecord:
        return LiveSubmissionRecord(
            **{
                field: row[field]
                for field in LiveSubmissionRecord.__dataclass_fields__
            }
        )

    @staticmethod
    def _validate_identifier(value: str) -> str:
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise LiveTradingRepositoryError("live trading identifier is invalid")
        return value

    @staticmethod
    def _validate_address(value: str) -> str:
        if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
            raise LiveTradingRepositoryError(
                "live trading wallet scope is invalid"
            )
        normalized = value.lower()
        if normalized == "0x" + "0" * 40:
            raise LiveTradingRepositoryError(
                "live trading wallet scope is invalid"
            )
        return normalized

    @staticmethod
    def _validate_order_hash(value: str | None) -> str:
        if not isinstance(value, str) or not _ORDER_HASH.fullmatch(value):
            raise LiveTradingRepositoryError(
                "live trading order hash is invalid"
            )
        return value

    @staticmethod
    def _validate_projection_hash(value: str) -> str:
        if not isinstance(value, str) or not _PROJECTION_HASH.fullmatch(value):
            raise LiveTradingRepositoryError(
                "live trading projection hash is invalid"
            )
        return value

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_live_trading_repository(config):
    profile = str(getattr(config, "profile", "")).strip().lower()
    if profile != "personal":
        raise LiveTradingRepositoryError(
            "MVP live trading repository supports personal SQLite only"
        )
    database_path = str(getattr(config, "ledger_db_file", "") or "").strip()
    if not database_path:
        raise LiveTradingRepositoryError(
            "personal live trading database path is required"
        )
    return SQLiteLiveTradingRepository(database_path)
