from __future__ import annotations

import sqlite3
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

from clink_node.interactions import InteractionService
from clink_node.schema_contract import validate_sqlite_artifacts
from clink_node.secrets import EnvelopeCipher, MemorySecretStore
from clink_node.storage import (
    InteractionSession,
    ModuleRecord,
    PostgresNodeRepository,
    SQLiteNodeRepository,
)
from clink_node.storage.schema import SQLITE_MIGRATIONS


class SQLiteNodeRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "clink.db"
        self.repository = SQLiteNodeRepository(self.path)
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_migration_is_idempotent_and_enables_safety_pragmas(self) -> None:
        self.repository.migrate()

        self.assertEqual(self.repository.schema_version(), 6)
        self.assertEqual(
            self.repository.pragmas(),
            {"foreign_keys": 1, "journal_mode": "wal"},
        )

    def test_sqlite_artifacts_are_no_follow_and_private(self) -> None:
        os.chmod(self.path, 0o600)
        validate_sqlite_artifacts(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

        wal = Path(str(self.path) + "-wal")
        wal.write_bytes(b"wal")
        os.chmod(wal, 0o600)
        validate_sqlite_artifacts(self.path)

        target = self.path.parent / "outside-wal"
        target.write_bytes(b"outside")
        wal.unlink()
        wal.symlink_to(target)
        with self.assertRaises(PermissionError):
            validate_sqlite_artifacts(self.path)

    def test_upgrade_preflight_checkpoints_and_validates_schema_contract(self) -> None:
        os.chmod(self.path, 0o600)

        report = self.repository.checkpoint_and_validate()

        self.assertEqual(report["integrity"], "ok")
        self.assertEqual(report["foreign_keys"], [])
        self.assertEqual(report["schema_version"], 6)

    def test_upgrade_backup_is_atomic_private_and_reopenable(self) -> None:
        os.chmod(self.path, 0o600)
        backup = self.path.parent / "upgrade-backup.db"

        result = self.repository.create_upgrade_backup(backup)

        self.assertEqual(result, backup)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        validate_sqlite_artifacts(backup)
        reopened = SQLiteNodeRepository(backup)
        self.assertEqual(reopened.schema_version(), 6)

    def test_v5_upgrade_backfills_only_current_revoked_runtime_and_repeats(self) -> None:
        path = Path(self.temporary.name) / "v5.db"
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE node_schema_migration ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            for version, script in SQLITE_MIGRATIONS:
                if version > 5:
                    continue
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO node_schema_migration(version, applied_at) "
                    "VALUES (?, ?)",
                    (version, now),
                )
            connection.execute(
                "INSERT INTO node_meta(key, value, updated_at) "
                "VALUES ('schema_version', '5', ?)",
                (now,),
            )
            connection.executemany(
                "INSERT INTO agent_binding("
                "agent_id, user_id, issuer, subject_id, external_agent_id, "
                "current_credential_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        "agent-current", "user-current", "issuer", "subject-current",
                        "external-current", "credential-current", now,
                    ),
                    (
                        "agent-active", "user-active", "issuer", "subject-active",
                        "external-active", "credential-active", now,
                    ),
                ),
            )
            connection.executemany(
                "INSERT INTO agent_runtime_credential("
                "credential_id, agent_id, runtime_id, request_id, scope, "
                "request_fingerprint, secret_digest, issued_at, expires_at, "
                "revoked_at, replaced_credential_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        "credential-historical", "agent-current", "runtime-historical",
                        "request-historical", "read", "a" * 64, "b" * 64,
                        now, now, now, None,
                    ),
                    (
                        "credential-current", "agent-current", "runtime-current",
                        "request-current", "read", "c" * 64, "d" * 64,
                        now, now, now, None,
                    ),
                    (
                        "credential-old", "agent-active", "runtime-old",
                        "request-old", "read", "e" * 64, "f" * 64,
                        now, now, now, None,
                    ),
                    (
                        "credential-active", "agent-active", "runtime-active",
                        "request-active", "read", "1" * 64, "2" * 64,
                        now, now, None, None,
                    ),
                ),
            )

        repository = SQLiteNodeRepository(path)
        repository.migrate()
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                "SELECT agent_id, runtime_id FROM agent_runtime_revocation "
                "ORDER BY agent_id, runtime_id"
            ).fetchall()
        self.assertEqual(rows, [("agent-current", "runtime-current")])
        repository.migrate()
        with sqlite3.connect(path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_runtime_revocation"
                ).fetchone()[0],
                1,
            )

    def test_migration_rejects_future_schema_before_any_write(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO node_schema_migration(version, applied_at) "
                "VALUES (7, ?)",
                (datetime.now(UTC).isoformat(),),
            )
            connection.execute(
                "UPDATE node_meta SET value = '7' "
                "WHERE key = 'schema_version'"
            )

        statements: list[str] = []
        original_connect = self.repository._connect

        def traced_connect() -> sqlite3.Connection:
            connection = original_connect()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(
            self.repository,
            "_connect",
            side_effect=traced_connect,
        ):
            with self.assertRaises(RuntimeError) as raised:
                self.repository.migrate()

        self.assertEqual(
            str(raised.exception),
            "storage_schema_newer_than_binary",
        )
        writes = tuple(
            statement
            for statement in statements
            if statement.lstrip().upper().startswith(
                ("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE")
            )
        )
        self.assertEqual(writes, ())
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT MAX(version) FROM node_schema_migration"
                ).fetchone()[0],
                7,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM node_meta "
                    "WHERE key = 'schema_version'"
                ).fetchone()[0],
                "7",
            )

    def test_migration_uses_max_of_inconsistent_history_and_meta(self) -> None:
        for history_version, meta_version in ((7, 6), (6, 7)):
            with self.subTest(
                history_version=history_version,
                meta_version=meta_version,
            ), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "future.db"
                repository = SQLiteNodeRepository(path)
                repository.migrate()
                with sqlite3.connect(path) as connection:
                    if history_version > 6:
                        connection.execute(
                            "INSERT INTO node_schema_migration("
                            "version, applied_at) VALUES (?, ?)",
                            (history_version, datetime.now(UTC).isoformat()),
                        )
                    connection.execute(
                        "UPDATE node_meta SET value = ? "
                        "WHERE key = 'schema_version'",
                        (str(meta_version),),
                    )

                with self.assertRaises(RuntimeError) as raised:
                    repository.migrate()

                self.assertEqual(
                    str(raised.exception),
                    "storage_schema_newer_than_binary",
                )
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT MAX(version) "
                            "FROM node_schema_migration"
                        ).fetchone()[0],
                        history_version,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM node_meta "
                            "WHERE key = 'schema_version'"
                        ).fetchone()[0],
                        str(meta_version),
                    )

    def test_module_state_survives_repository_restart(self) -> None:
        now = datetime.now(UTC)
        self.repository.set_module(
            ModuleRecord(
                name="core",
                mode="managed",
                status="ready",
                pid=123,
                endpoint="http://127.0.0.1:8019",
                mcp_url=None,
                detail=None,
                updated_at=now,
            )
        )

        reopened = SQLiteNodeRepository(self.path)
        reopened.migrate()
        record = reopened.get_module("core")

        self.assertIsNotNone(record)
        self.assertEqual(record.status, "ready")
        self.assertEqual(record.pid, 123)

    def test_interaction_token_is_one_time_and_not_stored_in_plaintext(
        self,
    ) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        service = InteractionService(
            self.repository,
            base_url="http://127.0.0.1:8170",
            ttl_seconds=60,
        )
        link = service.create(
            "wallet_binding",
            "user_1",
            {"request_id": "req_1"},
            now=now,
        )
        stored = self.repository.get_interaction(link.session_id)

        self.assertIsNotNone(stored)
        self.assertNotEqual(stored.token_hash, link.token)
        self.assertNotIn(link.token, link.url.split("#", 1)[0])
        first = service.consume(
            link.session_id,
            link.token,
            now=now + timedelta(seconds=1),
        )
        second = service.consume(
            link.session_id,
            link.token,
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(first)
        self.assertEqual(first.status, "consumed")
        self.assertIsNone(second)

    def test_sensitive_interaction_payload_is_encrypted_at_rest(self) -> None:
        encrypted_path = Path(self.temporary.name) / "encrypted.db"
        cipher = EnvelopeCipher(MemorySecretStore({}))
        repository = SQLiteNodeRepository(
            encrypted_path,
            cipher=cipher,
        )
        repository.migrate()
        service = InteractionService(
            repository,
            base_url="http://127.0.0.1:8170",
        )

        link = service.create(
            "spending_mandate",
            "user_1",
            {"wallet": "0x1234567890sensitive"},
        )

        database_bytes = encrypted_path.read_bytes()
        self.assertNotIn(b"0x1234567890sensitive", database_bytes)
        self.assertEqual(
            repository.get_interaction(link.session_id).payload["wallet"],
            "0x1234567890sensitive",
        )

    def test_expired_interaction_cannot_be_consumed(self) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        service = InteractionService(
            self.repository,
            base_url="http://127.0.0.1:8170",
            ttl_seconds=10,
        )
        link = service.create("approval", "user_1", {}, now=now)

        consumed = service.consume(
            link.session_id,
            link.token,
            now=now + timedelta(seconds=11),
        )

        self.assertIsNone(consumed)
        self.assertEqual(
            self.repository.get_interaction(link.session_id).status,
            "expired",
        )

    def test_event_outbox_is_durable_and_acknowledged_once(self) -> None:
        event_id = self.repository.append_event(
            "node.started",
            "node",
            {"profile": "personal"},
        )

        self.assertEqual(
            self.repository.pending_events(),
            [
                {
                    "event_id": event_id,
                    "event_type": "node.started",
                    "aggregate_id": "node",
                    "payload": {"profile": "personal"},
                    "created_at": self.repository.pending_events()[0][
                        "created_at"
                    ],
                }
            ],
        )

        self.repository.mark_event_published(event_id)
        self.assertEqual(self.repository.pending_events(), [])


class PostgresNodeRepositoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine

        self.repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=create_engine("sqlite+pysqlite:///:memory:"),
        )
        self.repository.migrate()

    def tearDown(self) -> None:
        self.repository.engine.dispose()

    def test_server_repository_implements_node_state_contract(self) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        module = ModuleRecord(
            name="marketplace",
            mode="external",
            status="ready",
            pid=None,
            endpoint="https://marketplace.example",
            mcp_url="https://marketplace.example/mcp",
            detail=None,
            updated_at=now,
        )
        self.repository.set_module(module)

        stored = self.repository.get_module("marketplace")

        self.assertEqual(self.repository.schema_version(), 6)
        self.assertEqual(stored, module)
        self.assertEqual(self.repository.list_modules(), [module])

    def test_server_v5_upgrade_backfills_only_current_revoked_runtime(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self.repository.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agent_binding("
                    "agent_id, user_id, issuer, subject_id, external_agent_id, "
                    "current_credential_id, created_at) VALUES ("
                    ":agent_id, :user_id, :issuer, :subject_id, :external_agent_id, "
                    ":current_credential_id, :created_at)"
                ),
                {
                    "agent_id": "migration-agent",
                    "user_id": "migration-user",
                    "issuer": "migration-issuer",
                    "subject_id": "migration-subject",
                    "external_agent_id": "migration-external",
                    "current_credential_id": "migration-current",
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agent_runtime_credential("
                    "credential_id, agent_id, runtime_id, request_id, scope, "
                    "request_fingerprint, secret_digest, issued_at, expires_at, "
                    "revoked_at, replaced_credential_id) VALUES ("
                    ":credential_id, :agent_id, :runtime_id, :request_id, :scope, "
                    ":request_fingerprint, :secret_digest, :issued_at, :expires_at, "
                    ":revoked_at, NULL)"
                ),
                {
                    "credential_id": "migration-historical",
                    "agent_id": "migration-agent",
                    "runtime_id": "migration-historical-runtime",
                    "request_id": "migration-historical-request",
                    "scope": "read",
                    "request_fingerprint": "a" * 64,
                    "secret_digest": "b" * 64,
                    "issued_at": now,
                    "expires_at": now,
                    "revoked_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agent_runtime_credential("
                    "credential_id, agent_id, runtime_id, request_id, scope, "
                    "request_fingerprint, secret_digest, issued_at, expires_at, "
                    "revoked_at, replaced_credential_id) VALUES ("
                    ":credential_id, :agent_id, :runtime_id, :request_id, :scope, "
                    ":request_fingerprint, :secret_digest, :issued_at, :expires_at, "
                    ":revoked_at, NULL)"
                ),
                {
                    "credential_id": "migration-current",
                    "agent_id": "migration-agent",
                    "runtime_id": "migration-current-runtime",
                    "request_id": "migration-current-request",
                    "scope": "read",
                    "request_fingerprint": "c" * 64,
                    "secret_digest": "d" * 64,
                    "issued_at": now,
                    "expires_at": now,
                    "revoked_at": now,
                },
            )
            connection.execute(
                text("DELETE FROM node_schema_migration WHERE version = 6")
            )
            connection.execute(
                text(
                    "UPDATE node_meta SET value = '5' "
                    "WHERE key = 'schema_version'"
                )
            )

        self.repository.migrate()
        with self.repository.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT agent_id, runtime_id "
                        "FROM agent_runtime_revocation"
                    )
                ).all(),
                [("migration-agent", "migration-current-runtime")],
            )
        self.repository.migrate()
        with self.repository.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT COUNT(*) FROM agent_runtime_revocation")
                ).scalar_one(),
                1,
            )

    def test_server_repository_consumes_interaction_once(self) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        session = InteractionSession(
            session_id="interaction_1",
            kind="wallet_binding",
            user_id="user_1",
            token_hash="token-hash",
            payload={"request_id": "request_1"},
            status="pending",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            consumed_at=None,
        )
        self.repository.create_interaction(session)

        first = self.repository.consume_interaction(
            session.session_id,
            session.token_hash,
            now=now + timedelta(seconds=1),
        )
        second = self.repository.consume_interaction(
            session.session_id,
            session.token_hash,
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(first)
        self.assertEqual(first.status, "consumed")
        self.assertIsNone(second)

    def test_server_repository_persists_outbox_and_secret_references(
        self,
    ) -> None:
        event_id = self.repository.append_event(
            "purchase.delivered",
            "purchase_1",
            {"receipt_id": "receipt_1"},
        )
        self.repository.put_secret_reference(
            "receipt-signing-key",
            "vault",
            "kv/clink/receipt-signing-key",
        )

        self.assertEqual(
            self.repository.pending_events()[0]["event_id"],
            event_id,
        )
        self.assertEqual(
            self.repository.get_secret_reference(
                "receipt-signing-key"
            ),
            {
                "name": "receipt-signing-key",
                "backend": "vault",
                "reference": "kv/clink/receipt-signing-key",
            },
        )

        self.repository.mark_event_published(event_id)
        self.assertEqual(self.repository.pending_events(), [])


if __name__ == "__main__":
    unittest.main()
