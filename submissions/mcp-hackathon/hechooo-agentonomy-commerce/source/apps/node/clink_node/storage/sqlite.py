from __future__ import annotations

import hmac
import json
import os
import sqlite3
import stat
import threading
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

from .base import (
    InteractionSession,
    MiniAppActiveRunLease,
    MiniAppBrowserSession,
    MiniAppHermesBinding,
    MiniAppMessageClaim,
    MiniAppMessageClaimResult,
    MiniAppStorageConflict,
    ModuleRecord,
    _normalize_datetime,
    _validate_hash,
    _validate_id,
)
from .schema import (
    SCHEMA_VERSION,
    SQLITE_MIGRATIONS,
    ensure_supported_schema_versions,
)
from ..schema_contract import prepare_sqlite_path, validate_sqlite_artifacts


class PayloadCipher(Protocol):
    def encrypt(self, plaintext: bytes, *, purpose: str) -> str: ...

    def decrypt(self, encoded: str, *, purpose: str) -> bytes: ...


def _iso(value: datetime) -> str:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SQLiteNodeRepository:
    def __init__(
        self,
        path: Path,
        *,
        cipher: PayloadCipher | None = None,
    ) -> None:
        self.path = path.expanduser().resolve()
        self.cipher = cipher
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def migrate(self) -> None:
        with self.transaction() as connection:
            existing_tables = {
                str(row["name"])
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table'
                      AND name IN ('node_schema_migration', 'node_meta')
                    """
                )
            }
            history_version = None
            if "node_schema_migration" in existing_tables:
                row = connection.execute(
                    "SELECT MAX(version) AS version "
                    "FROM node_schema_migration"
                ).fetchone()
                history_version = row["version"] if row is not None else None
            meta_version = None
            if "node_meta" in existing_tables:
                row = connection.execute(
                    "SELECT value FROM node_meta "
                    "WHERE key = 'schema_version'"
                ).fetchone()
                meta_version = row["value"] if row is not None else None
            ensure_supported_schema_versions(history_version, meta_version)

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS node_schema_migration (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM node_schema_migration"
                )
            }
            for version, script in SQLITE_MIGRATIONS:
                if version in applied:
                    continue
                for statement in script.split(";"):
                    sql = statement.strip()
                    if sql:
                        connection.execute(sql)
                connection.execute(
                    """
                    INSERT INTO node_schema_migration(version, applied_at)
                    VALUES (?, ?)
                    """,
                    (version, _iso(datetime.now(UTC))),
                )
            connection.execute(
                """
                INSERT INTO node_meta(key, value, updated_at)
                VALUES ('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    str(SCHEMA_VERSION),
                    _iso(datetime.now(UTC)),
                ),
            )
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")

    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM node_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"]) if row else 0

    def exchange_miniapp_session(
        self,
        proposed: MiniAppBrowserSession,
    ) -> MiniAppBrowserSession:
        inserted = True
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO miniapp_browser_session(
                        session_id, telegram_user_id, subject_id,
                        exchange_hash, client_nonce_hash,
                        session_token_hash, csrf_token_hash,
                        created_at, expires_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposed.session_id,
                        proposed.telegram_user_id,
                        proposed.subject_id,
                        proposed.exchange_hash,
                        proposed.client_nonce_hash,
                        proposed.session_token_hash,
                        proposed.csrf_token_hash,
                        _iso(proposed.created_at),
                        _iso(proposed.expires_at),
                        (
                            _iso(proposed.revoked_at)
                            if proposed.revoked_at is not None
                            else None
                        ),
                    ),
                )
        except sqlite3.IntegrityError:
            inserted = False
        if inserted:
            return proposed

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_browser_session
                WHERE exchange_hash = ?
                """,
                (proposed.exchange_hash,),
            ).fetchone()
        if row is not None:
            current = _miniapp_browser_session_from_row(row)
            if (
                hmac.compare_digest(
                    current.exchange_hash,
                    proposed.exchange_hash,
                )
                and hmac.compare_digest(
                    current.client_nonce_hash,
                    proposed.client_nonce_hash,
                )
                and current.telegram_user_id == proposed.telegram_user_id
                and current.subject_id == proposed.subject_id
            ):
                return current
        raise MiniAppStorageConflict()

    def get_miniapp_session(
        self,
        session_token_hash: str,
        now: datetime,
    ) -> MiniAppBrowserSession | None:
        token_hash = _validate_hash(session_token_hash)
        current_time = _normalize_datetime(now)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_browser_session
                WHERE session_token_hash = ?
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (token_hash, _iso(current_time)),
            ).fetchone()
        if row is None:
            return None
        current = _miniapp_browser_session_from_row(row)
        if not hmac.compare_digest(current.session_token_hash, token_hash):
            return None
        return current

    def revoke_miniapp_session(
        self,
        session_token_hash: str,
        now: datetime,
    ) -> bool:
        token_hash = _validate_hash(session_token_hash)
        revoked_at = _normalize_datetime(now)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE miniapp_browser_session
                SET revoked_at = ?
                WHERE session_token_hash = ? AND revoked_at IS NULL
                """,
                (_iso(revoked_at), token_hash),
            )
            return cursor.rowcount == 1

    def get_or_create_hermes_binding(
        self,
        proposed: MiniAppHermesBinding,
    ) -> MiniAppHermesBinding:
        inserted = True
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO miniapp_hermes_binding(
                        subject_id, hermes_session_id, session_key_hash,
                        created_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        proposed.subject_id,
                        proposed.hermes_session_id,
                        proposed.session_key_hash,
                        _iso(proposed.created_at),
                        (
                            _iso(proposed.revoked_at)
                            if proposed.revoked_at is not None
                            else None
                        ),
                    ),
                )
        except sqlite3.IntegrityError:
            inserted = False
        if inserted:
            return proposed

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_hermes_binding
                WHERE subject_id = ?
                """,
                (proposed.subject_id,),
            ).fetchone()
        if row is not None:
            current = _miniapp_hermes_binding_from_row(row)
            if (
                current.hermes_session_id == proposed.hermes_session_id
                and hmac.compare_digest(
                    current.session_key_hash,
                    proposed.session_key_hash,
                )
            ):
                return current
        raise MiniAppStorageConflict()

    def claim_miniapp_message(
        self,
        proposed: MiniAppMessageClaim,
    ) -> MiniAppMessageClaimResult:
        if (
            proposed.status != "starting"
            or proposed.hermes_run_id is not None
            or proposed.hermes_run_session_id is None
            or proposed.legacy_unreconciled
        ):
            raise MiniAppStorageConflict()
        inserted = True
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO miniapp_message_claim(
                        subject_id, client_message_id, payload_hash,
                        status, hermes_run_id, hermes_run_session_id,
                        legacy_unreconciled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposed.subject_id,
                        proposed.client_message_id,
                        proposed.payload_hash,
                        proposed.status,
                        proposed.hermes_run_id,
                        proposed.hermes_run_session_id,
                        int(proposed.legacy_unreconciled),
                        _iso(proposed.created_at),
                        _iso(proposed.updated_at),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO miniapp_active_run_lease(
                        subject_id, client_message_id,
                        acquired_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        proposed.subject_id,
                        proposed.client_message_id,
                        _iso(proposed.created_at),
                        _iso(proposed.updated_at),
                    ),
                )
        except sqlite3.IntegrityError:
            inserted = False
        if inserted:
            return MiniAppMessageClaimResult(claim=proposed, created=True)

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_message_claim
                WHERE subject_id = ? AND client_message_id = ?
                """,
                (proposed.subject_id, proposed.client_message_id),
            ).fetchone()
        if row is not None:
            current = _miniapp_message_claim_from_row(row)
            if hmac.compare_digest(
                current.payload_hash,
                proposed.payload_hash,
            ) and (
                current.hermes_run_session_id
                == proposed.hermes_run_session_id
                and not current.legacy_unreconciled
            ):
                return MiniAppMessageClaimResult(
                    claim=current,
                    created=False,
                )
        raise MiniAppStorageConflict()

    def get_miniapp_message_claim(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> MiniAppMessageClaim | None:
        normalized_subject_id = _validate_id(subject_id)
        normalized_message_id = _validate_id(client_message_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_message_claim
                WHERE subject_id = ? AND client_message_id = ?
                """,
                (normalized_subject_id, normalized_message_id),
            ).fetchone()
        return _miniapp_message_claim_from_row(row) if row is not None else None

    def get_latest_miniapp_message_claim(
        self,
        subject_id: str,
    ) -> MiniAppMessageClaim | None:
        normalized_subject_id = _validate_id(subject_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_message_claim
                WHERE subject_id = ?
                ORDER BY created_at DESC, client_message_id DESC
                LIMIT 1
                """,
                (normalized_subject_id,),
            ).fetchone()
        return _miniapp_message_claim_from_row(row) if row is not None else None

    def get_miniapp_active_run_lease(
        self,
        subject_id: str,
    ) -> MiniAppActiveRunLease | None:
        normalized_subject_id = _validate_id(subject_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_active_run_lease
                WHERE subject_id = ?
                """,
                (normalized_subject_id,),
            ).fetchone()
        return _miniapp_active_run_lease_from_row(row) if row else None

    def release_miniapp_active_run_lease(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> bool:
        normalized_subject_id = _validate_id(subject_id)
        normalized_message_id = _validate_id(client_message_id)
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_active_run_lease
                WHERE subject_id = ?
                """,
                (normalized_subject_id,),
            ).fetchone()
            if row is None:
                return False
            current = _miniapp_active_run_lease_from_row(row)
            if current.client_message_id != normalized_message_id:
                raise MiniAppStorageConflict()
            changed = connection.execute(
                """
                DELETE FROM miniapp_active_run_lease
                WHERE subject_id = ? AND client_message_id = ?
                """,
                (normalized_subject_id, normalized_message_id),
            )
            if changed.rowcount != 1:
                raise MiniAppStorageConflict()
        return True

    def complete_miniapp_message(
        self,
        subject_id: str,
        client_message_id: str,
        *,
        status: str,
        hermes_run_id: str | None,
        hermes_run_session_id: str | None,
        now: datetime,
    ) -> MiniAppMessageClaim:
        normalized_subject_id = _validate_id(subject_id)
        normalized_message_id = _validate_id(client_message_id)
        updated_at = _normalize_datetime(now)
        if hermes_run_session_id is None:
            raise MiniAppStorageConflict()
        normalized_run_session_id = _validate_id(hermes_run_session_id)
        if status == "accepted":
            if hermes_run_id is None:
                raise MiniAppStorageConflict()
            normalized_run_id = _validate_id(hermes_run_id)
        elif status == "unknown":
            if hermes_run_id is not None:
                raise MiniAppStorageConflict()
            normalized_run_id = None
        else:
            raise MiniAppStorageConflict()

        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM miniapp_message_claim
                WHERE subject_id = ? AND client_message_id = ?
                """,
                (normalized_subject_id, normalized_message_id),
            ).fetchone()
            if row is None:
                raise MiniAppStorageConflict()
            current = _miniapp_message_claim_from_row(row)
            if (
                current.legacy_unreconciled
                or current.hermes_run_session_id
                != normalized_run_session_id
            ):
                raise MiniAppStorageConflict()
            if current.status == "accepted":
                if (
                    status == "accepted"
                    and current.hermes_run_id == normalized_run_id
                    and current.hermes_run_session_id
                    == normalized_run_session_id
                ):
                    return current
                raise MiniAppStorageConflict()
            allowed = (
                current.status == "starting"
                and status in ("accepted", "unknown")
            ) or (current.status == "unknown" and status == "accepted")
            if not allowed:
                raise MiniAppStorageConflict()
            cursor = connection.execute(
                """
                UPDATE miniapp_message_claim
                SET status = ?, hermes_run_id = ?, updated_at = ?
                WHERE subject_id = ? AND client_message_id = ?
                  AND status = ?
                """,
                (
                    status,
                    normalized_run_id,
                    _iso(updated_at),
                    normalized_subject_id,
                    normalized_message_id,
                    current.status,
                ),
            )
            if cursor.rowcount != 1:
                raise MiniAppStorageConflict()
            completed = connection.execute(
                """
                SELECT * FROM miniapp_message_claim
                WHERE subject_id = ? AND client_message_id = ?
                """,
                (normalized_subject_id, normalized_message_id),
            ).fetchone()
        return _miniapp_message_claim_from_row(completed)

    def set_module(self, record: ModuleRecord) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO module_state(
                    name, mode, status, pid, endpoint, mcp_url,
                    detail, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    mode = excluded.mode,
                    status = excluded.status,
                    pid = excluded.pid,
                    endpoint = excluded.endpoint,
                    mcp_url = excluded.mcp_url,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (
                    record.name,
                    record.mode,
                    record.status,
                    record.pid,
                    record.endpoint,
                    record.mcp_url,
                    record.detail,
                    _iso(record.updated_at),
                ),
            )

    def get_module(self, name: str) -> ModuleRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM module_state WHERE name = ?",
                (name,),
            ).fetchone()
        return _module_from_row(row) if row else None

    def list_modules(self) -> list[ModuleRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM module_state ORDER BY name"
            ).fetchall()
        return [_module_from_row(row) for row in rows]

    def create_interaction(self, session: InteractionSession) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO interaction_session(
                    session_id, kind, user_id, token_hash, payload_json,
                    status, created_at, expires_at, consumed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.kind,
                    session.user_id,
                    session.token_hash,
                    self._encode_payload(
                        session.payload,
                        purpose=f"interaction:{session.session_id}",
                    ),
                    session.status,
                    _iso(session.created_at),
                    _iso(session.expires_at),
                    _iso(session.consumed_at)
                    if session.consumed_at
                    else None,
                ),
            )

    def get_interaction(
        self,
        session_id: str,
    ) -> InteractionSession | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM interaction_session
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._interaction_from_row(row) if row else None

    def consume_interaction(
        self,
        session_id: str,
        token_hash: str,
        *,
        now: datetime,
    ) -> InteractionSession | None:
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM interaction_session
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            current = self._interaction_from_row(row)
            if current.status != "pending":
                return None
            if current.token_hash != token_hash:
                return None
            if current.expires_at <= now.astimezone(UTC):
                connection.execute(
                    """
                    UPDATE interaction_session
                    SET status = 'expired'
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                return None
            consumed_at = _iso(now)
            cursor = connection.execute(
                """
                UPDATE interaction_session
                SET status = 'consumed', consumed_at = ?
                WHERE session_id = ? AND status = 'pending'
                """,
                (consumed_at, session_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                """
                SELECT * FROM interaction_session
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._interaction_from_row(row)

    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO event_outbox(
                    event_type, aggregate_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_type,
                    aggregate_id,
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    _iso(datetime.now(UTC)),
                ),
            )
            return int(cursor.lastrowid)

    def pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_outbox
                WHERE published_at IS NULL
                ORDER BY event_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "event_id": int(row["event_id"]),
                "event_type": row["event_type"],
                "aggregate_id": row["aggregate_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def mark_event_published(self, event_id: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE event_outbox
                SET published_at = ?
                WHERE event_id = ?
                """,
                (_iso(datetime.now(UTC)), event_id),
            )

    def put_secret_reference(
        self,
        name: str,
        backend: str,
        reference: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO secret_reference(
                    name, backend, reference, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    backend = excluded.backend,
                    reference = excluded.reference,
                    updated_at = excluded.updated_at
                """,
                (name, backend, reference, _iso(datetime.now(UTC))),
            )

    def get_secret_reference(self, name: str) -> dict[str, str] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT name, backend, reference
                FROM secret_reference
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def pragmas(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            return {
                "foreign_keys": int(
                    connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                ),
                "journal_mode": str(
                    connection.execute(
                        "PRAGMA journal_mode"
                    ).fetchone()[0]
                ).lower(),
            }

    def checkpoint_and_validate(self) -> dict[str, object]:
        """Checkpoint WAL and fail closed on storage or schema corruption."""

        prepare_sqlite_path(self.path)
        with closing(self._connect()) as connection:
            checkpoint = tuple(
                connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                or ()
            )
            integrity = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            ).lower()
            foreign_keys = [
                tuple(row)
                for row in connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            ]
            schema_version_row = connection.execute(
                "SELECT value FROM node_meta WHERE key = 'schema_version'"
            ).fetchone()
            schema_version = (
                int(schema_version_row[0])
                if schema_version_row is not None
                else 0
            )
        if integrity != "ok":
            raise RuntimeError("sqlite integrity check failed")
        if foreign_keys:
            raise RuntimeError("sqlite foreign key check failed")
        validate_sqlite_artifacts(self.path)
        return {
            "checkpoint": checkpoint,
            "integrity": integrity,
            "foreign_keys": foreign_keys,
            "schema_version": schema_version,
        }

    def validate_for_upgrade(self) -> dict[str, object]:
        return self.checkpoint_and_validate()

    def create_upgrade_backup(self, destination: Path) -> Path:
        """Create a private, atomic SQLite backup after storage preflight."""

        self.checkpoint_and_validate()
        target = Path(destination).expanduser()
        if target.absolute() == self.path.absolute():
            raise ValueError("SQLite backup destination must differ from source")
        validate_sqlite_artifacts(target)
        if target.exists() or target.is_symlink():
            metadata = os.lstat(target)
            if not stat.S_ISREG(metadata.st_mode):
                raise PermissionError("SQLite backup destination is unsafe")
        temporary = target.with_name(
            f".{target.name}.tmp-{os.getpid()}-{os.urandom(6).hex()}"
        )
        descriptor = -1
        source: sqlite3.Connection | None = None
        backup: sqlite3.Connection | None = None
        try:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            descriptor = os.open(temporary, flags, 0o600)
            os.close(descriptor)
            descriptor = -1
            source = self._connect()
            backup = sqlite3.connect(temporary, isolation_level=None)
            source.backup(backup)
            backup.execute("PRAGMA journal_mode = DELETE")
            backup.commit()
            backup.close()
            backup = None
            source.close()
            source = None
            descriptor = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, target)
            directory = os.open(
                target.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | os.O_NOFOLLOW,
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            prepare_sqlite_path(target)
            reopened = SQLiteNodeRepository(target)
            if reopened.schema_version() != self.schema_version():
                raise RuntimeError("SQLite backup schema contract mismatch")
            return target
        finally:
            if backup is not None:
                backup.close()
            if source is not None:
                source.close()
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def backup_for_upgrade(self, destination: Path) -> Path:
        return self.create_upgrade_backup(destination)

    def _encode_payload(
        self,
        payload: dict[str, Any],
        *,
        purpose: str,
    ) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        if self.cipher is None:
            return serialized
        return "enc:v1:" + self.cipher.encrypt(
            serialized.encode("utf-8"),
            purpose=purpose,
        )

    def _decode_payload(
        self,
        encoded: str,
        *,
        purpose: str,
    ) -> dict[str, Any]:
        if not encoded.startswith("enc:v1:"):
            return json.loads(encoded)
        if self.cipher is None:
            raise RuntimeError(
                "encrypted Node payload requires the configured cipher"
            )
        plaintext = self.cipher.decrypt(
            encoded.removeprefix("enc:v1:"),
            purpose=purpose,
        )
        return json.loads(plaintext)

    def _interaction_from_row(
        self,
        row: sqlite3.Row,
    ) -> InteractionSession:
        session_id = row["session_id"]
        return InteractionSession(
            session_id=session_id,
            kind=row["kind"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            payload=self._decode_payload(
                row["payload_json"],
                purpose=f"interaction:{session_id}",
            ),
            status=row["status"],
            created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
            expires_at=_datetime(row["expires_at"]),  # type: ignore[arg-type]
            consumed_at=_datetime(row["consumed_at"]),
        )


def _module_from_row(row: sqlite3.Row) -> ModuleRecord:
    return ModuleRecord(
        name=row["name"],
        mode=row["mode"],
        status=row["status"],
        pid=row["pid"],
        endpoint=row["endpoint"],
        mcp_url=row["mcp_url"],
        detail=row["detail"],
        updated_at=_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


def _miniapp_browser_session_from_row(
    row: sqlite3.Row,
) -> MiniAppBrowserSession:
    return MiniAppBrowserSession(
        session_id=row["session_id"],
        telegram_user_id=row["telegram_user_id"],
        subject_id=row["subject_id"],
        exchange_hash=row["exchange_hash"],
        client_nonce_hash=row["client_nonce_hash"],
        session_token_hash=row["session_token_hash"],
        csrf_token_hash=row["csrf_token_hash"],
        created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
        expires_at=_datetime(row["expires_at"]),  # type: ignore[arg-type]
        revoked_at=_datetime(row["revoked_at"]),
    )


def _miniapp_hermes_binding_from_row(
    row: sqlite3.Row,
) -> MiniAppHermesBinding:
    return MiniAppHermesBinding(
        subject_id=row["subject_id"],
        hermes_session_id=row["hermes_session_id"],
        session_key_hash=row["session_key_hash"],
        created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
        revoked_at=_datetime(row["revoked_at"]),
    )


def _miniapp_message_claim_from_row(
    row: sqlite3.Row,
) -> MiniAppMessageClaim:
    return MiniAppMessageClaim(
        subject_id=row["subject_id"],
        client_message_id=row["client_message_id"],
        payload_hash=row["payload_hash"],
        status=row["status"],
        hermes_run_id=row["hermes_run_id"],
        hermes_run_session_id=row["hermes_run_session_id"],
        legacy_unreconciled=bool(row["legacy_unreconciled"]),
        created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


def _miniapp_active_run_lease_from_row(
    row: sqlite3.Row,
) -> MiniAppActiveRunLease:
    return MiniAppActiveRunLease(
        subject_id=row["subject_id"],
        client_message_id=row["client_message_id"],
        acquired_at=_datetime(row["acquired_at"]),  # type: ignore[arg-type]
        updated_at=_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )
