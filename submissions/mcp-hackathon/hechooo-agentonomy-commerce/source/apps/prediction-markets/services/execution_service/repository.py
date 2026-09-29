from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    inspect,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from shared.schemas import PolymarketOrderSigningSession


ORDER_SIGNING_SESSION_SCHEMA_VERSION = 2
_POSTGRES_MIGRATION_LOCK = 7_385_013_464_228_091_127
_ALLOWED_STATUSES = {
    "blocked",
    "expired",
    "failed",
    "pending_browser_signature",
    "submitted",
    "submitting",
    "unknown",
}

_METADATA = MetaData()
_SCHEMA_VERSION = Table(
    "polymarket_order_signing_schema_version",
    _METADATA,
    Column("singleton", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    CheckConstraint("singleton = 1", name="ck_pm_order_signing_schema_singleton"),
    CheckConstraint("version >= 0", name="ck_pm_order_signing_schema_version"),
)
_SESSIONS = Table(
    "polymarket_order_signing_sessions",
    _METADATA,
    Column("session_id", String(128), primary_key=True),
    Column("user_id", String(256), nullable=True),
    Column("binding_id", String(256), nullable=True),
    Column("projection_hash", String(64), nullable=True),
    Column("status", String(64), nullable=False),
    Column("expires_at", String(64), nullable=True),
    Column("revision", Integer, nullable=False),
    Column("capability_hash", String(64), nullable=True),
    Column("capability_origin", String(2048), nullable=True),
    Column("record_json", Text, nullable=False),
    CheckConstraint("revision >= 0", name="ck_pm_order_signing_revision"),
)


class OrderSigningSessionRepositoryError(RuntimeError):
    """A fixed, redacted signing-session persistence failure."""


class SqlAlchemyOrderSigningSessionRepository:
    def __init__(self, database_url: str) -> None:
        options: dict = {}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 5}
        try:
            self.engine = create_engine(database_url, **options)
        except (SQLAlchemyError, ValueError):
            raise OrderSigningSessionRepositoryError(
                "order signing session database migration failed"
            ) from None
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._configure_sqlite)
        self._migrate()

    @staticmethod
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _migrate(self) -> None:
        try:
            with self._transaction(migration=True) as connection:
                table_names = set(inspect(connection).get_table_names())
                version_table = _SCHEMA_VERSION.name
                sessions_table = _SESSIONS.name
                if version_table not in table_names:
                    if sessions_table in table_names:
                        raise OrderSigningSessionRepositoryError(
                            "order signing session database schema is incomplete"
                        )
                    _METADATA.create_all(connection)
                    connection.execute(
                        insert(_SCHEMA_VERSION).values(
                            singleton=1,
                            version=ORDER_SIGNING_SESSION_SCHEMA_VERSION,
                        )
                    )
                    return

                version = connection.scalar(
                    select(_SCHEMA_VERSION.c.version).where(
                        _SCHEMA_VERSION.c.singleton == 1
                    )
                )
                if version is None:
                    raise OrderSigningSessionRepositoryError(
                        "order signing session database schema version is unavailable"
                    )
                if int(version) > ORDER_SIGNING_SESSION_SCHEMA_VERSION:
                    raise OrderSigningSessionRepositoryError(
                        "order signing session database schema is newer than this binary"
                    )
                if int(version) == 1:
                    columns = {
                        column["name"]
                        for column in inspect(connection).get_columns(sessions_table)
                    }
                    if "capability_origin" not in columns:
                        connection.exec_driver_sql(
                            "ALTER TABLE polymarket_order_signing_sessions "
                            "ADD COLUMN capability_origin VARCHAR(2048)"
                        )
                    connection.execute(
                        update(_SCHEMA_VERSION)
                        .where(_SCHEMA_VERSION.c.singleton == 1)
                        .values(version=ORDER_SIGNING_SESSION_SCHEMA_VERSION)
                    )
                    version = ORDER_SIGNING_SESSION_SCHEMA_VERSION
                if int(version) != ORDER_SIGNING_SESSION_SCHEMA_VERSION:
                    raise OrderSigningSessionRepositoryError(
                        "order signing session database schema is incomplete"
                    )
                if sessions_table not in table_names:
                    raise OrderSigningSessionRepositoryError(
                        "order signing session database schema is incomplete"
                    )
                columns = {
                    column["name"]
                    for column in inspect(connection).get_columns(sessions_table)
                }
                required = {column.name for column in _SESSIONS.columns}
                if not required.issubset(columns):
                    raise OrderSigningSessionRepositoryError(
                        "order signing session database schema is incomplete"
                    )
        except OrderSigningSessionRepositoryError:
            raise
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database migration failed"
            ) from None

    @contextmanager
    def _transaction(
        self,
        *,
        session_id: str | None = None,
        migration: bool = False,
    ) -> Iterator[Connection]:
        connection = self.engine.connect()
        transaction = None
        try:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                transaction = connection.begin()
                lock_id = (
                    _POSTGRES_MIGRATION_LOCK
                    if migration
                    else self._advisory_lock_id(session_id or "")
                )
                connection.execute(
                    text("SELECT pg_catalog.pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            yield connection
            if transaction is not None:
                transaction.commit()
            else:
                connection.commit()
        except BaseException:
            if transaction is not None:
                transaction.rollback()
            else:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _advisory_lock_id(value: str) -> int:
        raw = int.from_bytes(
            hashlib.sha256(value.encode("utf-8")).digest()[:8], "big", signed=False
        )
        return raw - (1 << 64) if raw >= (1 << 63) else raw

    def create(
        self,
        session: PolymarketOrderSigningSession,
        *,
        capability_hash: str | None = None,
        capability_origin: str | None = None,
    ) -> PolymarketOrderSigningSession:
        if session.status not in _ALLOWED_STATUSES or session.revision != 0:
            raise OrderSigningSessionRepositoryError(
                "order signing session record is invalid"
            )
        if (capability_hash is None) != (capability_origin is None):
            raise OrderSigningSessionRepositoryError(
                "order signing session capability is invalid"
            )
        if capability_hash is not None and (
            len(capability_hash) != 64
            or capability_hash.lower() != capability_hash
            or any(character not in "0123456789abcdef" for character in capability_hash)
            or not capability_origin
            or len(capability_origin) > 2048
        ):
            raise OrderSigningSessionRepositoryError(
                "order signing session capability is invalid"
            )
        values = self._row_values(
            session,
            capability_hash=capability_hash,
            capability_origin=capability_origin,
        )
        try:
            with self._transaction(session_id=session.session_id) as connection:
                connection.execute(insert(_SESSIONS).values(**values))
        except IntegrityError:
            raise OrderSigningSessionRepositoryError(
                "order signing session already exists"
            ) from None
        except OrderSigningSessionRepositoryError:
            raise
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database operation failed"
            ) from None
        return session

    def get(self, session_id: str) -> PolymarketOrderSigningSession | None:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(_SESSIONS).where(_SESSIONS.c.session_id == session_id)
                ).mappings().one_or_none()
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database operation failed"
            ) from None
        return None if row is None else self._session_from_row(row)

    def get_by_capability(
        self,
        *,
        capability_hash: str,
        origin: str,
    ) -> PolymarketOrderSigningSession | None:
        if (
            len(capability_hash) != 64
            or capability_hash.lower() != capability_hash
            or any(character not in "0123456789abcdef" for character in capability_hash)
            or not origin
            or len(origin) > 2048
        ):
            return None
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    select(_SESSIONS).where(
                        _SESSIONS.c.capability_hash == capability_hash
                    )
                ).mappings().all()
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database operation failed"
            ) from None
        if len(rows) != 1 or rows[0]["capability_origin"] != origin:
            return None
        return self._session_from_row(rows[0])

    def claim_for_submission(
        self,
        *,
        session_id: str,
        expected_revision: int,
        replacement: PolymarketOrderSigningSession,
    ) -> PolymarketOrderSigningSession | None:
        if replacement.session_id != session_id or replacement.status != "submitting":
            raise OrderSigningSessionRepositoryError(
                "order signing session claim is invalid"
            )
        try:
            with self._transaction(session_id=session_id) as connection:
                row = connection.execute(
                    select(_SESSIONS).where(_SESSIONS.c.session_id == session_id)
                ).mappings().one_or_none()
                if (
                    row is None
                    or row["status"] != "pending_browser_signature"
                    or row["revision"] != expected_revision
                ):
                    return None
                self._assert_immutable_fields(row, replacement)
                claimed = replacement.model_copy(
                    update={"revision": expected_revision + 1}
                )
                result = connection.execute(
                    update(_SESSIONS)
                    .where(
                        _SESSIONS.c.session_id == session_id,
                        _SESSIONS.c.status == "pending_browser_signature",
                        _SESSIONS.c.revision == expected_revision,
                    )
                    .values(
                        **self._row_values(
                            claimed,
                            capability_hash=row["capability_hash"],
                            capability_origin=row["capability_origin"],
                        )
                    )
                )
                return claimed if result.rowcount == 1 else None
        except OrderSigningSessionRepositoryError:
            raise
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database operation failed"
            ) from None

    def compare_and_set_terminal(
        self,
        *,
        session_id: str,
        expected_revision: int,
        replacement: PolymarketOrderSigningSession,
    ) -> PolymarketOrderSigningSession | None:
        if replacement.session_id != session_id or replacement.status not in {
            "blocked",
            "expired",
            "failed",
            "submitted",
            "unknown",
        }:
            raise OrderSigningSessionRepositoryError(
                "order signing session terminal update is invalid"
            )
        try:
            with self._transaction(session_id=session_id) as connection:
                row = connection.execute(
                    select(_SESSIONS).where(_SESSIONS.c.session_id == session_id)
                ).mappings().one_or_none()
                expected_current_statuses = (
                    {"pending_browser_signature"}
                    if replacement.status in {"blocked", "expired"}
                    else (
                        {"pending_browser_signature", "submitting"}
                        if replacement.status == "failed"
                        else (
                            {"submitting", "unknown"}
                            if replacement.status == "submitted"
                            else {"submitting"}
                        )
                    )
                )
                if (
                    row is None
                    or row["status"] not in expected_current_statuses
                    or row["revision"] != expected_revision
                ):
                    return None
                self._assert_immutable_fields(row, replacement)
                terminal = replacement.model_copy(
                    update={"revision": expected_revision + 1}
                )
                result = connection.execute(
                    update(_SESSIONS)
                    .where(
                        _SESSIONS.c.session_id == session_id,
                        _SESSIONS.c.status.in_(expected_current_statuses),
                        _SESSIONS.c.revision == expected_revision,
                    )
                    .values(
                        **self._row_values(
                            terminal,
                            capability_hash=row["capability_hash"],
                            capability_origin=row["capability_origin"],
                        )
                    )
                )
                return terminal if result.rowcount == 1 else None
        except OrderSigningSessionRepositoryError:
            raise
        except SQLAlchemyError:
            raise OrderSigningSessionRepositoryError(
                "order signing session database operation failed"
            ) from None

    @staticmethod
    def _assert_immutable_fields(
        row, replacement: PolymarketOrderSigningSession
    ) -> None:
        locked = {
            "session_id": replacement.session_id,
            "user_id": replacement.user_id,
            "binding_id": replacement.binding_id,
            "projection_hash": replacement.projection_hash,
            "expires_at": replacement.expires_at,
        }
        if any(row[name] != value for name, value in locked.items()):
            raise OrderSigningSessionRepositoryError(
                "order signing session immutable fields changed"
            )

    @staticmethod
    def _row_values(
        session: PolymarketOrderSigningSession,
        *,
        capability_hash: str | None = None,
        capability_origin: str | None = None,
    ) -> dict:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "binding_id": session.binding_id,
            "projection_hash": session.projection_hash,
            "status": session.status,
            "expires_at": session.expires_at,
            "revision": session.revision,
            "capability_hash": capability_hash,
            "capability_origin": capability_origin,
            "record_json": json.dumps(
                session.model_dump(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        }

    @staticmethod
    def _session_from_row(row) -> PolymarketOrderSigningSession:
        try:
            session = PolymarketOrderSigningSession(**json.loads(row["record_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            raise OrderSigningSessionRepositoryError(
                "order signing session record is invalid"
            ) from None
        locked = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "binding_id": session.binding_id,
            "projection_hash": session.projection_hash,
            "status": session.status,
            "expires_at": session.expires_at,
            "revision": session.revision,
        }
        if any(row[name] != value for name, value in locked.items()):
            raise OrderSigningSessionRepositoryError(
                "order signing session record is invalid"
            )
        return session


class SQLiteOrderSigningSessionRepository(
    SqlAlchemyOrderSigningSessionRepository
):
    def __init__(self, database_path: Path | str) -> None:
        path = Path(database_path)
        if not str(path).strip():
            raise OrderSigningSessionRepositoryError(
                "personal order signing session database path is required"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(f"sqlite+pysqlite:///{path}")


class PostgresOrderSigningSessionRepository(
    SqlAlchemyOrderSigningSessionRepository
):
    def __init__(self, database_url: str) -> None:
        if not str(database_url).startswith("postgresql+psycopg://"):
            raise OrderSigningSessionRepositoryError(
                "server profile requires a postgresql+psycopg database URL"
            )
        super().__init__(database_url)


def build_order_signing_session_repository(config):
    profile = str(getattr(config, "profile", "")).strip().lower()
    if profile == "personal":
        configured = Path(str(config.order_signing_session_file))
        database_path = (
            configured
            if configured.suffix == ".sqlite3"
            else configured.with_suffix(".sqlite3")
        )
        return SQLiteOrderSigningSessionRepository(database_path)
    if profile == "server":
        database_url = str(
            getattr(config, "prediction_markets_database_url", "") or ""
        ).strip()
        if not database_url.startswith("postgresql+psycopg://"):
            raise OrderSigningSessionRepositoryError(
                "server profile requires a postgresql+psycopg database URL"
            )
        return PostgresOrderSigningSessionRepository(database_url)
    raise OrderSigningSessionRepositoryError(
        "order signing session repository profile is invalid"
    )
