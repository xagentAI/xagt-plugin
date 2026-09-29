from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError

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
from .schema import SCHEMA_VERSION, ensure_supported_schema_versions
from .sqlite import PayloadCipher


metadata = MetaData()
_MIGRATION_ADVISORY_LOCK_ID = 0x434C494E4B4D4947


def _bounded_id_check(column_name: str) -> str:
    return f"length({column_name}) BETWEEN 1 AND 256"


def _lowerhex64_check(column_name: str) -> str:
    remainder = column_name
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return f"length({column_name}) = 64 AND {remainder} = ''"


node_schema_migration = Table(
    "node_schema_migration",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)
node_meta = Table(
    "node_meta",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
module_state = Table(
    "module_state",
    metadata,
    Column("name", String(128), primary_key=True),
    Column("mode", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("pid", Integer),
    Column("endpoint", Text),
    Column("mcp_url", Text),
    Column("detail", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
interaction_session = Table(
    "interaction_session",
    metadata,
    Column("session_id", String(128), primary_key=True),
    Column("kind", String(64), nullable=False),
    Column("user_id", String(256), nullable=False, index=True),
    Column("token_hash", String(128), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("status", String(32), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Column("consumed_at", DateTime(timezone=True)),
)
event_outbox = Table(
    "event_outbox",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("event_type", String(128), nullable=False),
    Column("aggregate_id", String(256), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), index=True),
)
secret_reference = Table(
    "secret_reference",
    metadata,
    Column("name", String(256), primary_key=True),
    Column("backend", String(64), nullable=False),
    Column("reference", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
miniapp_browser_session = Table(
    "miniapp_browser_session",
    metadata,
    Column("session_id", String(256), primary_key=True),
    Column("telegram_user_id", String(256), nullable=False),
    Column("subject_id", String(256), nullable=False, index=True),
    Column("exchange_hash", String(64), nullable=False, unique=True),
    Column("client_nonce_hash", String(64), nullable=False),
    Column("session_token_hash", String(64), nullable=False, unique=True),
    Column("csrf_token_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Column("revoked_at", DateTime(timezone=True), index=True),
    CheckConstraint(
        _bounded_id_check("session_id"),
        name="ck_miniapp_browser_session_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("telegram_user_id"),
        name="ck_miniapp_browser_telegram_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("subject_id"),
        name="ck_miniapp_browser_subject_id_length",
    ),
    CheckConstraint(
        _lowerhex64_check("exchange_hash"),
        name="ck_miniapp_browser_exchange_hash_lowerhex64",
    ),
    CheckConstraint(
        _lowerhex64_check("client_nonce_hash"),
        name="ck_miniapp_browser_nonce_hash_lowerhex64",
    ),
    CheckConstraint(
        _lowerhex64_check("session_token_hash"),
        name="ck_miniapp_browser_token_hash_lowerhex64",
    ),
    CheckConstraint(
        _lowerhex64_check("csrf_token_hash"),
        name="ck_miniapp_browser_csrf_hash_lowerhex64",
    ),
)
miniapp_hermes_binding = Table(
    "miniapp_hermes_binding",
    metadata,
    Column("subject_id", String(256), primary_key=True),
    Column("hermes_session_id", String(256), nullable=False, unique=True),
    Column("session_key_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), index=True),
    CheckConstraint(
        _bounded_id_check("subject_id"),
        name="ck_miniapp_binding_subject_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("hermes_session_id"),
        name="ck_miniapp_binding_session_id_length",
    ),
    CheckConstraint(
        _lowerhex64_check("session_key_hash"),
        name="ck_miniapp_hermes_key_hash_lowerhex64",
    ),
)
miniapp_message_claim = Table(
    "miniapp_message_claim",
    metadata,
    Column("subject_id", String(256), primary_key=True),
    Column("client_message_id", String(256), primary_key=True),
    Column("payload_hash", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("hermes_run_id", String(256)),
    Column("hermes_run_session_id", String(256)),
    Column(
        "legacy_unreconciled",
        Boolean(
            create_constraint=True,
            name="ck_miniapp_claim_legacy_boolean",
        ),
        nullable=False,
        server_default=text("false"),
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        _bounded_id_check("subject_id"),
        name="ck_miniapp_claim_subject_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("client_message_id"),
        name="ck_miniapp_claim_message_id_length",
    ),
    CheckConstraint(
        _lowerhex64_check("payload_hash"),
        name="ck_miniapp_claim_payload_hash_lowerhex64",
    ),
    CheckConstraint(
        """
        (
            legacy_unreconciled IS TRUE
            AND status = 'unknown'
            AND hermes_run_id IS NULL
            AND hermes_run_session_id IS NULL
        ) OR (
            legacy_unreconciled IS FALSE
            AND hermes_run_session_id IS NOT NULL
            AND length(hermes_run_session_id) BETWEEN 1 AND 256
            AND (
                (
                    status IN ('starting', 'unknown')
                    AND hermes_run_id IS NULL
                ) OR (
                    status = 'accepted'
                    AND hermes_run_id IS NOT NULL
                    AND length(hermes_run_id) BETWEEN 1 AND 256
                )
            )
        )
        """,
        name="ck_miniapp_claim_status_provenance",
    ),
)
miniapp_active_run_lease = Table(
    "miniapp_active_run_lease",
    metadata,
    Column("subject_id", String(256), primary_key=True),
    Column("client_message_id", String(256), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("subject_id", "client_message_id"),
        (
            "miniapp_message_claim.subject_id",
            "miniapp_message_claim.client_message_id",
        ),
        name="fk_miniapp_active_run_lease_claim",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        _bounded_id_check("subject_id"),
        name="ck_miniapp_active_run_lease_subject_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("client_message_id"),
        name="ck_miniapp_active_run_lease_client_message_id_length",
    ),
)
agent_binding = Table(
    "agent_binding",
    metadata,
    Column("agent_id", String(256), primary_key=True),
    Column("user_id", String(96), nullable=False, unique=True),
    Column("issuer", String(256), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("external_agent_id", String(256), nullable=False),
    Column("current_credential_id", String(256)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "issuer",
        "subject_id",
        name="uq_agent_binding_issuer_subject",
    ),
    UniqueConstraint(
        "issuer",
        "external_agent_id",
        name="uq_agent_binding_issuer_external_agent",
    ),
    CheckConstraint(
        _bounded_id_check("agent_id"),
        name="ck_agent_binding_agent_id_length",
    ),
    CheckConstraint(
        "length(user_id) BETWEEN 1 AND 96",
        name="ck_agent_binding_user_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("issuer"),
        name="ck_agent_binding_issuer_length",
    ),
    CheckConstraint(
        _bounded_id_check("subject_id"),
        name="ck_agent_binding_subject_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("external_agent_id"),
        name="ck_agent_binding_external_agent_id_length",
    ),
    CheckConstraint(
        "current_credential_id IS NULL OR "
        + _bounded_id_check("current_credential_id"),
        name="ck_agent_binding_current_credential_id_length",
    ),
)
agent_runtime_credential = Table(
    "agent_runtime_credential",
    metadata,
    Column("credential_id", String(256), primary_key=True),
    Column("agent_id", String(256), nullable=False),
    Column("runtime_id", String(256), nullable=False),
    Column("request_id", String(256), nullable=False),
    Column("scope", String(16), nullable=False),
    Column("request_fingerprint", String(64), nullable=False),
    Column("secret_digest", String(64), nullable=False, unique=True),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("replaced_credential_id", String(256)),
    ForeignKeyConstraint(
        ("agent_id",),
        ("agent_binding.agent_id",),
        name="fk_agent_runtime_credential_agent",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "agent_id",
        "request_id",
        name="uq_agent_runtime_credential_request",
    ),
    CheckConstraint(
        _bounded_id_check("credential_id"),
        name="ck_agent_runtime_credential_credential_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("agent_id"),
        name="ck_agent_runtime_credential_agent_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("runtime_id"),
        name="ck_agent_runtime_credential_runtime_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("request_id"),
        name="ck_agent_runtime_credential_request_id_length",
    ),
    CheckConstraint(
        "scope IN ('read', 'payments')",
        name="ck_agent_runtime_credential_scope",
    ),
    CheckConstraint(
        _lowerhex64_check("request_fingerprint"),
        name="ck_agent_runtime_credential_fingerprint_lowerhex64",
    ),
    CheckConstraint(
        _lowerhex64_check("secret_digest"),
        name="ck_agent_runtime_credential_secret_digest_lowerhex64",
    ),
    CheckConstraint(
        "replaced_credential_id IS NULL OR "
        + _bounded_id_check("replaced_credential_id"),
        name="ck_agent_runtime_credential_replaced_id_length",
    ),
)
agent_runtime_revocation = Table(
    "agent_runtime_revocation",
    metadata,
    Column("agent_id", String(256), nullable=False),
    Column("runtime_id", String(256), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("agent_id",),
        ("agent_binding.agent_id",),
        name="fk_agent_runtime_revocation_agent",
        ondelete="RESTRICT",
    ),
    PrimaryKeyConstraint(
        "agent_id",
        "runtime_id",
        name="pk_agent_runtime_revocation",
    ),
    CheckConstraint(
        _bounded_id_check("agent_id"),
        name="ck_agent_runtime_revocation_agent_id_length",
    ),
    CheckConstraint(
        _bounded_id_check("runtime_id"),
        name="ck_agent_runtime_revocation_runtime_id_length",
    ),
)


class PostgresNodeRepository:
    """SQLAlchemy-backed Node state repository for Server Profile.

    The schema intentionally uses portable SQLAlchemy Core primitives so the
    repository contract can be tested without requiring a live PostgreSQL
    server. Production construction always uses the configured PostgreSQL URL.
    """

    def __init__(
        self,
        url: str,
        *,
        cipher: PayloadCipher | None = None,
        engine: Engine | None = None,
    ) -> None:
        self.url = url
        self.cipher = cipher
        self.engine = engine or create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=300,
        )

    def migrate(self) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            dialect_name = connection.dialect.name
            if dialect_name == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": _MIGRATION_ADVISORY_LOCK_ID},
                )
                dialect_insert = postgresql_insert
            elif dialect_name == "sqlite":
                dialect_insert = sqlite_insert
            else:
                raise RuntimeError("unsupported_storage_dialect")

            if dialect_name == "postgresql":
                history_table = connection.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": "node_schema_migration"},
                ).first()
                meta_table = connection.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": "node_meta"},
                ).first()
            else:
                history_table = connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = :table_name"
                    ),
                    {"table_name": "node_schema_migration"},
                ).first()
                meta_table = connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = :table_name"
                    ),
                    {"table_name": "node_meta"},
                ).first()
            history_version = None
            if history_table is not None and history_table[0] is not None:
                row = connection.execute(
                    text(
                        "SELECT MAX(version) AS version "
                        "FROM node_schema_migration"
                    )
                ).first()
                history_version = row[0] if row is not None else None
            meta_version = None
            if meta_table is not None and meta_table[0] is not None:
                row = connection.execute(
                    text(
                        "SELECT value FROM node_meta "
                        "WHERE key = :key"
                    ),
                    {"key": "schema_version"},
                ).first()
                meta_version = row[0] if row is not None else None
            ensure_supported_schema_versions(history_version, meta_version)

            metadata.create_all(connection)
            version_six_applied = connection.execute(
                select(node_schema_migration.c.version).where(
                    node_schema_migration.c.version == 6
                )
            ).first()
            if version_six_applied is None:
                connection.execute(
                    text(
                        "INSERT INTO agent_runtime_revocation("
                        "agent_id, runtime_id, revoked_at) "
                        "SELECT binding.agent_id, credential.runtime_id, "
                        "credential.revoked_at "
                        "FROM agent_binding AS binding "
                        "JOIN agent_runtime_credential AS credential "
                        "ON credential.agent_id = binding.agent_id "
                        "AND credential.credential_id = "
                        "binding.current_credential_id "
                        "WHERE credential.revoked_at IS NOT NULL"
                    )
                )
            version_three_applied = connection.execute(
                select(node_schema_migration.c.version).where(
                    node_schema_migration.c.version == 3
                )
            ).first()
            if (
                dialect_name == "postgresql"
                and version_three_applied is None
            ):
                connection.execute(
                    text(
                        "ALTER TABLE miniapp_message_claim "
                        "ADD COLUMN IF NOT EXISTS "
                        "hermes_run_session_id VARCHAR(256)"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE miniapp_message_claim "
                        "ADD COLUMN IF NOT EXISTS "
                        "legacy_unreconciled BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE miniapp_message_claim "
                        "SET status = 'unknown', hermes_run_id = NULL, "
                        "hermes_run_session_id = NULL, "
                        "legacy_unreconciled = TRUE "
                        "WHERE hermes_run_session_id IS NULL"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE miniapp_message_claim "
                        "DROP CONSTRAINT IF EXISTS "
                        "ck_miniapp_claim_status_run_id"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE miniapp_message_claim "
                        "DROP CONSTRAINT IF EXISTS "
                        "ck_miniapp_claim_status_provenance"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE miniapp_message_claim "
                        "ADD CONSTRAINT "
                        "ck_miniapp_claim_status_provenance CHECK ("
                        "(legacy_unreconciled IS TRUE "
                        "AND status = 'unknown' "
                        "AND hermes_run_id IS NULL "
                        "AND hermes_run_session_id IS NULL) OR ("
                        "legacy_unreconciled IS FALSE "
                        "AND hermes_run_session_id IS NOT NULL "
                        "AND length(hermes_run_session_id) "
                        "BETWEEN 1 AND 256 AND (("
                        "status IN ('starting', 'unknown') "
                        "AND hermes_run_id IS NULL) OR ("
                        "status = 'accepted' "
                        "AND hermes_run_id IS NOT NULL "
                        "AND length(hermes_run_id) BETWEEN 1 AND 256))))"
                    )
                )
                connection.execute(
                    dialect_insert(node_schema_migration)
                    .values(version=3, applied_at=now)
                    .on_conflict_do_nothing(
                        index_elements=[node_schema_migration.c.version]
                    )
                )

            version_four_applied = connection.execute(
                select(node_schema_migration.c.version).where(
                    node_schema_migration.c.version == 4
                )
            ).first()
            if version_four_applied is None:
                connection.execute(delete(miniapp_active_run_lease))
                connection.execute(
                    text(
                        "INSERT INTO miniapp_active_run_lease("
                        "subject_id, client_message_id, "
                        "acquired_at, updated_at) "
                        "SELECT claim.subject_id, "
                        "claim.client_message_id, "
                        "claim.created_at, claim.updated_at "
                        "FROM miniapp_message_claim AS claim "
                        "WHERE claim.legacy_unreconciled IS FALSE "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM miniapp_message_claim AS newer "
                        "WHERE newer.subject_id = claim.subject_id "
                        "AND newer.legacy_unreconciled IS FALSE "
                        "AND (newer.created_at > claim.created_at "
                        "OR (newer.created_at = claim.created_at "
                        "AND newer.client_message_id "
                        "> claim.client_message_id)))"
                    )
                )
                connection.execute(
                    dialect_insert(node_schema_migration)
                    .values(version=4, applied_at=now)
                    .on_conflict_do_nothing(
                        index_elements=[node_schema_migration.c.version]
                    )
                )
            connection.execute(
                dialect_insert(node_schema_migration)
                .values(version=SCHEMA_VERSION, applied_at=now)
                .on_conflict_do_nothing(
                    index_elements=[node_schema_migration.c.version]
                )
            )
            connection.execute(
                dialect_insert(node_meta)
                .values(
                    key="schema_version",
                    value=str(SCHEMA_VERSION),
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[node_meta.c.key],
                    set_={
                        "value": str(SCHEMA_VERSION),
                        "updated_at": now,
                    },
                )
            )

    def schema_version(self) -> int:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(node_meta.c.value).where(
                    node_meta.c.key == "schema_version"
                )
            ).first()
        return int(row[0]) if row else 0

    def exchange_miniapp_session(
        self,
        proposed: MiniAppBrowserSession,
    ) -> MiniAppBrowserSession:
        inserted = True
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(miniapp_browser_session).values(
                        session_id=proposed.session_id,
                        telegram_user_id=proposed.telegram_user_id,
                        subject_id=proposed.subject_id,
                        exchange_hash=proposed.exchange_hash,
                        client_nonce_hash=proposed.client_nonce_hash,
                        session_token_hash=proposed.session_token_hash,
                        csrf_token_hash=proposed.csrf_token_hash,
                        created_at=_utc(proposed.created_at),
                        expires_at=_utc(proposed.expires_at),
                        revoked_at=(
                            _utc(proposed.revoked_at)
                            if proposed.revoked_at is not None
                            else None
                        ),
                    )
                )
        except IntegrityError:
            inserted = False
        if inserted:
            return proposed

        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_browser_session).where(
                    miniapp_browser_session.c.exchange_hash
                    == proposed.exchange_hash
                )
            ).mappings().first()
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
        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_browser_session).where(
                    and_(
                        miniapp_browser_session.c.session_token_hash
                        == token_hash,
                        miniapp_browser_session.c.revoked_at.is_(None),
                        miniapp_browser_session.c.expires_at > current_time,
                    )
                )
            ).mappings().first()
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
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(miniapp_browser_session)
                .where(
                    and_(
                        miniapp_browser_session.c.session_token_hash
                        == token_hash,
                        miniapp_browser_session.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=revoked_at)
            )
            return changed.rowcount == 1

    def get_or_create_hermes_binding(
        self,
        proposed: MiniAppHermesBinding,
    ) -> MiniAppHermesBinding:
        inserted = True
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(miniapp_hermes_binding).values(
                        subject_id=proposed.subject_id,
                        hermes_session_id=proposed.hermes_session_id,
                        session_key_hash=proposed.session_key_hash,
                        created_at=_utc(proposed.created_at),
                        revoked_at=(
                            _utc(proposed.revoked_at)
                            if proposed.revoked_at is not None
                            else None
                        ),
                    )
                )
        except IntegrityError:
            inserted = False
        if inserted:
            return proposed

        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_hermes_binding).where(
                    miniapp_hermes_binding.c.subject_id
                    == proposed.subject_id
                )
            ).mappings().first()
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
            with self.engine.begin() as connection:
                connection.execute(
                    insert(miniapp_message_claim).values(
                        subject_id=proposed.subject_id,
                        client_message_id=proposed.client_message_id,
                        payload_hash=proposed.payload_hash,
                        status=proposed.status,
                        hermes_run_id=proposed.hermes_run_id,
                        hermes_run_session_id=(
                            proposed.hermes_run_session_id
                        ),
                        legacy_unreconciled=(
                            proposed.legacy_unreconciled
                        ),
                        created_at=_utc(proposed.created_at),
                        updated_at=_utc(proposed.updated_at),
                    )
                )
                connection.execute(
                    insert(miniapp_active_run_lease).values(
                        subject_id=proposed.subject_id,
                        client_message_id=proposed.client_message_id,
                        acquired_at=_utc(proposed.created_at),
                        updated_at=_utc(proposed.updated_at),
                    )
                )
        except IntegrityError:
            inserted = False
        if inserted:
            return MiniAppMessageClaimResult(claim=proposed, created=True)

        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_message_claim).where(
                    and_(
                        miniapp_message_claim.c.subject_id
                        == proposed.subject_id,
                        miniapp_message_claim.c.client_message_id
                        == proposed.client_message_id,
                    )
                )
            ).mappings().first()
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
        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_message_claim).where(
                    and_(
                        miniapp_message_claim.c.subject_id
                        == normalized_subject_id,
                        miniapp_message_claim.c.client_message_id
                        == normalized_message_id,
                    )
                )
            ).mappings().first()
        return _miniapp_message_claim_from_row(row) if row is not None else None

    def get_latest_miniapp_message_claim(
        self,
        subject_id: str,
    ) -> MiniAppMessageClaim | None:
        normalized_subject_id = _validate_id(subject_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_message_claim)
                .where(
                    miniapp_message_claim.c.subject_id
                    == normalized_subject_id
                )
                .order_by(
                    miniapp_message_claim.c.created_at.desc(),
                    miniapp_message_claim.c.client_message_id.desc(),
                )
                .limit(1)
            ).mappings().first()
        return _miniapp_message_claim_from_row(row) if row is not None else None

    def get_miniapp_active_run_lease(
        self,
        subject_id: str,
    ) -> MiniAppActiveRunLease | None:
        normalized_subject_id = _validate_id(subject_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(miniapp_active_run_lease).where(
                    miniapp_active_run_lease.c.subject_id
                    == normalized_subject_id
                )
            ).mappings().first()
        return _miniapp_active_run_lease_from_row(row) if row else None

    def release_miniapp_active_run_lease(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> bool:
        normalized_subject_id = _validate_id(subject_id)
        normalized_message_id = _validate_id(client_message_id)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(miniapp_active_run_lease)
                .where(
                    miniapp_active_run_lease.c.subject_id
                    == normalized_subject_id
                )
                .with_for_update()
            ).mappings().first()
            if row is None:
                return False
            current = _miniapp_active_run_lease_from_row(row)
            if current.client_message_id != normalized_message_id:
                raise MiniAppStorageConflict()
            changed = connection.execute(
                delete(miniapp_active_run_lease).where(
                    and_(
                        miniapp_active_run_lease.c.subject_id
                        == normalized_subject_id,
                        miniapp_active_run_lease.c.client_message_id
                        == normalized_message_id,
                    )
                )
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

        with self.engine.begin() as connection:
            row = connection.execute(
                select(miniapp_message_claim)
                .where(
                    and_(
                        miniapp_message_claim.c.subject_id
                        == normalized_subject_id,
                        miniapp_message_claim.c.client_message_id
                        == normalized_message_id,
                    )
                )
                .with_for_update()
            ).mappings().first()
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
            changed = connection.execute(
                update(miniapp_message_claim)
                .where(
                    and_(
                        miniapp_message_claim.c.subject_id
                        == normalized_subject_id,
                        miniapp_message_claim.c.client_message_id
                        == normalized_message_id,
                        miniapp_message_claim.c.status == current.status,
                    )
                )
                .values(
                    status=status,
                    hermes_run_id=normalized_run_id,
                    updated_at=updated_at,
                )
            )
            if changed.rowcount != 1:
                raise MiniAppStorageConflict()
            completed = connection.execute(
                select(miniapp_message_claim).where(
                    and_(
                        miniapp_message_claim.c.subject_id
                        == normalized_subject_id,
                        miniapp_message_claim.c.client_message_id
                        == normalized_message_id,
                    )
                )
            ).mappings().one()
        return _miniapp_message_claim_from_row(completed)

    def set_module(self, record: ModuleRecord) -> None:
        values = {
            "mode": record.mode,
            "status": record.status,
            "pid": record.pid,
            "endpoint": record.endpoint,
            "mcp_url": record.mcp_url,
            "detail": record.detail,
            "updated_at": _utc(record.updated_at),
        }
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(module_state)
                .where(module_state.c.name == record.name)
                .values(**values)
            )
            if changed.rowcount == 0:
                connection.execute(
                    insert(module_state).values(name=record.name, **values)
                )

    def get_module(self, name: str) -> ModuleRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(module_state).where(module_state.c.name == name)
            ).mappings().first()
        return _module_from_row(row) if row else None

    def list_modules(self) -> list[ModuleRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(module_state).order_by(module_state.c.name)
            ).mappings()
            return [_module_from_row(row) for row in rows]

    def create_interaction(self, session: InteractionSession) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(interaction_session).values(
                    session_id=session.session_id,
                    kind=session.kind,
                    user_id=session.user_id,
                    token_hash=session.token_hash,
                    payload_json=self._encode_payload(
                        session.payload,
                        purpose=f"interaction:{session.session_id}",
                    ),
                    status=session.status,
                    created_at=_utc(session.created_at),
                    expires_at=_utc(session.expires_at),
                    consumed_at=(
                        _utc(session.consumed_at)
                        if session.consumed_at
                        else None
                    ),
                )
            )

    def get_interaction(
        self,
        session_id: str,
    ) -> InteractionSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(interaction_session).where(
                    interaction_session.c.session_id == session_id
                )
            ).mappings().first()
        return self._interaction_from_row(row) if row else None

    def consume_interaction(
        self,
        session_id: str,
        token_hash: str,
        *,
        now: datetime,
    ) -> InteractionSession | None:
        current_time = _utc(now)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(interaction_session).where(
                    interaction_session.c.session_id == session_id
                )
            ).mappings().first()
            if row is None:
                return None
            current = self._interaction_from_row(row)
            if current.status != "pending":
                return None
            if current.token_hash != token_hash:
                return None
            if current.expires_at <= current_time:
                connection.execute(
                    update(interaction_session)
                    .where(
                        interaction_session.c.session_id == session_id
                    )
                    .values(status="expired")
                )
                return None
            changed = connection.execute(
                update(interaction_session)
                .where(
                    and_(
                        interaction_session.c.session_id == session_id,
                        interaction_session.c.status == "pending",
                        interaction_session.c.token_hash == token_hash,
                    )
                )
                .values(status="consumed", consumed_at=current_time)
            )
            if changed.rowcount != 1:
                return None
            consumed = connection.execute(
                select(interaction_session).where(
                    interaction_session.c.session_id == session_id
                )
            ).mappings().one()
        return self._interaction_from_row(consumed)

    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(event_outbox).values(
                    event_type=event_type,
                    aggregate_id=aggregate_id,
                    payload_json=json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            return int(result.inserted_primary_key[0])

    def pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(event_outbox)
                .where(event_outbox.c.published_at.is_(None))
                .order_by(event_outbox.c.event_id)
                .limit(limit)
            ).mappings()
            return [
                {
                    "event_id": int(row["event_id"]),
                    "event_type": row["event_type"],
                    "aggregate_id": row["aggregate_id"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": _utc(row["created_at"]).isoformat(),
                }
                for row in rows
            ]

    def mark_event_published(self, event_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(event_outbox)
                .where(event_outbox.c.event_id == event_id)
                .values(published_at=datetime.now(UTC))
            )

    def put_secret_reference(
        self,
        name: str,
        backend: str,
        reference: str,
    ) -> None:
        values = {
            "backend": backend,
            "reference": reference,
            "updated_at": datetime.now(UTC),
        }
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(secret_reference)
                .where(secret_reference.c.name == name)
                .values(**values)
            )
            if changed.rowcount == 0:
                connection.execute(
                    insert(secret_reference).values(name=name, **values)
                )

    def get_secret_reference(self, name: str) -> dict[str, str] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    secret_reference.c.name,
                    secret_reference.c.backend,
                    secret_reference.c.reference,
                ).where(secret_reference.c.name == name)
            ).mappings().first()
        return dict(row) if row else None

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
        row: RowMapping,
    ) -> InteractionSession:
        session_id = str(row["session_id"])
        return InteractionSession(
            session_id=session_id,
            kind=str(row["kind"]),
            user_id=str(row["user_id"]),
            token_hash=str(row["token_hash"]),
            payload=self._decode_payload(
                str(row["payload_json"]),
                purpose=f"interaction:{session_id}",
            ),
            status=str(row["status"]),
            created_at=_utc(row["created_at"]),
            expires_at=_utc(row["expires_at"]),
            consumed_at=(
                _utc(row["consumed_at"])
                if row["consumed_at"] is not None
                else None
            ),
        )


def _module_from_row(row: RowMapping) -> ModuleRecord:
    return ModuleRecord(
        name=str(row["name"]),
        mode=str(row["mode"]),
        status=str(row["status"]),
        pid=int(row["pid"]) if row["pid"] is not None else None,
        endpoint=(
            str(row["endpoint"]) if row["endpoint"] is not None else None
        ),
        mcp_url=(
            str(row["mcp_url"]) if row["mcp_url"] is not None else None
        ),
        detail=str(row["detail"]) if row["detail"] is not None else None,
        updated_at=_utc(row["updated_at"]),
    )


def _miniapp_browser_session_from_row(
    row: RowMapping,
) -> MiniAppBrowserSession:
    return MiniAppBrowserSession(
        session_id=str(row["session_id"]),
        telegram_user_id=str(row["telegram_user_id"]),
        subject_id=str(row["subject_id"]),
        exchange_hash=str(row["exchange_hash"]),
        client_nonce_hash=str(row["client_nonce_hash"]),
        session_token_hash=str(row["session_token_hash"]),
        csrf_token_hash=str(row["csrf_token_hash"]),
        created_at=_utc(row["created_at"]),
        expires_at=_utc(row["expires_at"]),
        revoked_at=(
            _utc(row["revoked_at"])
            if row["revoked_at"] is not None
            else None
        ),
    )


def _miniapp_hermes_binding_from_row(
    row: RowMapping,
) -> MiniAppHermesBinding:
    return MiniAppHermesBinding(
        subject_id=str(row["subject_id"]),
        hermes_session_id=str(row["hermes_session_id"]),
        session_key_hash=str(row["session_key_hash"]),
        created_at=_utc(row["created_at"]),
        revoked_at=(
            _utc(row["revoked_at"])
            if row["revoked_at"] is not None
            else None
        ),
    )


def _miniapp_message_claim_from_row(
    row: RowMapping,
) -> MiniAppMessageClaim:
    return MiniAppMessageClaim(
        subject_id=str(row["subject_id"]),
        client_message_id=str(row["client_message_id"]),
        payload_hash=str(row["payload_hash"]),
        status=str(row["status"]),
        hermes_run_id=(
            str(row["hermes_run_id"])
            if row["hermes_run_id"] is not None
            else None
        ),
        hermes_run_session_id=(
            str(row["hermes_run_session_id"])
            if row["hermes_run_session_id"] is not None
            else None
        ),
        legacy_unreconciled=bool(row["legacy_unreconciled"]),
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
    )


def _miniapp_active_run_lease_from_row(
    row: RowMapping,
) -> MiniAppActiveRunLease:
    return MiniAppActiveRunLease(
        subject_id=str(row["subject_id"]),
        client_message_id=str(row["client_message_id"]),
        acquired_at=_utc(row["acquired_at"]),
        updated_at=_utc(row["updated_at"]),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
