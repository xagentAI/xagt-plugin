from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine

from clink_node.agent_access import (
    AgentAccessConflictError,
    AgentAccessNotFoundError,
    AgentAccessService,
    AgentAccessUnauthorizedError,
)
from clink_node.storage.agent_access import AgentAccessRepository
from clink_node.storage.sqlite import SQLiteNodeRepository


class AgentAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "clink.db"
        SQLiteNodeRepository(self.path).migrate()
        self.engine = create_engine(f"sqlite+pysqlite:///{self.path}")
        self.repository = AgentAccessRepository(self.engine)
        self.now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        self.service = AgentAccessService(
            self.repository,
            issuer="service-agent",
            token_key=b"k" * 32,
            clock=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def test_registration_is_durable_idempotent_and_issuer_scoped(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        replay = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )

        self.assertEqual(replay, binding)
        self.assertEqual(self.service.get_agent(binding.agent_id), binding)
        self.assertLessEqual(len(binding.user_id), 96)
        self.assertTrue(binding.user_id.startswith("agent:"))

        with self.assertRaises(AgentAccessConflictError) as changed_subject:
            self.service.register(
                subject_id="wallet-user-1",
                external_agent_id="agent-2",
            )
        self.assertEqual(changed_subject.exception.code, "conflict")

        with self.assertRaises(AgentAccessConflictError):
            self.service.register(
                subject_id="wallet-user-2",
                external_agent_id="agent-1",
            )

        other_issuer = AgentAccessService(
            self.repository,
            issuer="other-service",
            token_key=b"o" * 32,
            clock=lambda: self.now,
        )
        other = other_issuer.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        self.assertNotEqual(other.agent_id, binding.agent_id)
        self.assertNotEqual(other.user_id, binding.user_id)

        restarted = AgentAccessService(
            AgentAccessRepository(self.engine),
            issuer="service-agent",
            token_key=b"k" * 32,
            clock=lambda: self.now,
        )
        self.assertEqual(restarted.get_agent(binding.agent_id), binding)

        with self.assertRaises(AgentAccessNotFoundError):
            self.service.get_agent("missing-agent")

    def test_registration_rejects_control_characters(self) -> None:
        for field, value in (
            ("subject_id", "wallet\nuser"),
            ("external_agent_id", "agent\x00id"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.service.register(
                        subject_id=(
                            value if field == "subject_id" else "wallet-user"
                        ),
                        external_agent_id=(
                            value if field == "external_agent_id" else "agent"
                        ),
                    )

    def test_non_ascii_subject_gets_bounded_ascii_opaque_user_id(self) -> None:
        binding = self.service.register(
            subject_id="用户/agent+1",
            external_agent_id="agent-unicode",
        )

        self.assertLessEqual(len(binding.user_id), 96)
        self.assertTrue(binding.user_id.isascii())
        self.assertNotIn("用户", binding.user_id)
        self.assertNotIn("/", binding.user_id)
        self.assertNotIn("+", binding.user_id)

        replay = self.service.register(
            subject_id="用户/agent+1",
            external_agent_id="agent-unicode",
        )
        self.assertEqual(replay.user_id, binding.user_id)

    def test_issue_authenticates_current_credential_and_hides_secrets(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        issued = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
            scope="payments",
            ttl_seconds=300,
        )

        self.assertEqual(issued.agent_id, binding.agent_id)
        self.assertEqual(issued.runtime_id, "runtime-1")
        self.assertEqual(issued.scope, "payments")
        self.assertEqual(issued.expires_at, self.now + timedelta(seconds=300))
        self.assertNotIn(issued.access_token, repr(issued))
        self.assertNotIn(b"clink_rt", self.path.read_bytes())

        principal = self.service.authenticate(issued.access_token)
        self.assertEqual(principal.user_id, binding.user_id)
        self.assertEqual(principal.agent_id, binding.agent_id)
        self.assertEqual(principal.runtime_id, "runtime-1")
        self.assertEqual(principal.credential_id, issued.credential_id)
        self.assertEqual(principal.issuer, "service-agent")
        self.assertEqual(principal.scope, "payments")
        self.assertEqual(principal.expires_at, issued.expires_at)

        with self.assertRaises(AgentAccessUnauthorizedError):
            self.service.authenticate("malformed-token")

        self.now += timedelta(seconds=300)
        with self.assertRaises(AgentAccessUnauthorizedError) as expired:
            self.service.authenticate(issued.access_token)
        self.assertEqual(expired.exception.code, "unauthorized")

    def test_issue_exact_replay_is_deterministic_but_conflicts_do_not_mutate(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        request = dict(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
            scope="read",
            ttl_seconds=300,
        )
        first = self.service.issue_credential(**request)
        replay = self.service.issue_credential(**request)

        self.assertEqual(replay, first)
        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(**{**request, "scope": "payments"})
        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(**{**request, "runtime_id": "runtime-2"})
        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                **{**request, "ttl_seconds": 301}
            )

        with sqlite3.connect(self.path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM agent_runtime_credential"
            ).fetchone()[0]
        self.assertEqual(count, 1)

        self.now += timedelta(seconds=300)
        expired_replay = self.service.issue_credential(**request)
        self.assertEqual(expired_replay, first)
        with self.assertRaises(AgentAccessUnauthorizedError):
            self.service.authenticate(expired_replay.access_token)

    def test_runtime_status_is_scoped_read_only_and_hides_credential_secrets(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )

        empty = self.service.get_runtime_status(binding.agent_id)
        self.assertEqual(empty, {"agent_id": binding.agent_id, "runtime": None})

        issued = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
            scope="read",
            ttl_seconds=300,
        )
        status = self.service.get_runtime_status(binding.agent_id)
        self.assertEqual(set(status), {"agent_id", "runtime"})
        self.assertEqual(status["agent_id"], binding.agent_id)
        self.assertIsInstance(status["runtime"], dict)
        runtime = status["runtime"]
        self.assertEqual(
            set(runtime),
            {
                "credential_id",
                "runtime_id",
                "scope",
                "issued_at",
                "expires_at",
                "status",
            },
        )
        self.assertEqual(runtime["credential_id"], issued.credential_id)
        self.assertEqual(runtime["runtime_id"], "runtime-1")
        self.assertEqual(runtime["scope"], "read")
        self.assertEqual(runtime["issued_at"], issued.issued_at)
        self.assertEqual(runtime["expires_at"], issued.expires_at)
        self.assertEqual(runtime["status"], "active")
        self.assertNotIn(issued.access_token, repr(status))

        self.now = issued.expires_at
        self.assertEqual(
            self.service.get_runtime_status(binding.agent_id)["runtime"]["status"],
            "expired",
        )

        other_issuer = AgentAccessService(
            self.repository,
            issuer="other-service",
            token_key=b"o" * 32,
            clock=lambda: self.now,
        )
        with self.assertRaises(AgentAccessNotFoundError):
            other_issuer.get_runtime_status(binding.agent_id)

    def test_runtime_status_reports_revoked_current_credential(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        issued = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
        )

        self.service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
        )
        status = self.service.get_runtime_status(binding.agent_id)
        self.assertEqual(status["runtime"]["credential_id"], issued.credential_id)
        self.assertEqual(status["runtime"]["status"], "revoked")

    def test_rotation_requires_compare_and_swap_and_old_runtime_stop_is_safe(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        first = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
        )

        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-2",
                request_id="request-2",
            )
        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-2",
                request_id="request-2",
                replaces_credential_id="wrong-credential",
            )

        second = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-2",
            request_id="request-2",
            replaces_credential_id=first.credential_id,
        )
        with self.assertRaises(AgentAccessUnauthorizedError):
            self.service.authenticate(first.access_token)
        self.assertEqual(
            self.service.authenticate(second.access_token).runtime_id,
            "runtime-2",
        )

        self.service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
        )
        self.assertEqual(
            self.service.authenticate(second.access_token).runtime_id,
            "runtime-2",
        )
        self.service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-2",
        )
        with self.assertRaises(AgentAccessUnauthorizedError):
            self.service.authenticate(second.access_token)

        revoked_replay = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-2",
            request_id="request-2",
            replaces_credential_id=first.credential_id,
        )
        self.assertEqual(revoked_replay, second)

    def test_runtime_generation_cannot_reenter_after_aba_rotation(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        first = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
            request_id="request-a",
        )
        second = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-b",
            request_id="request-b",
            replaces_credential_id=first.credential_id,
        )

        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
                request_id="request-a-refresh",
                replaces_credential_id=second.credential_id,
            )

        self.service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-b",
        )
        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
                request_id="request-a-after-current-revoked",
                replaces_credential_id=second.credential_id,
            )

        with self.assertRaises(AgentAccessConflictError):
            self.service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-b",
                request_id="request-b-refresh",
                replaces_credential_id=second.credential_id,
            )

    def test_scope_and_ttl_are_strictly_validated(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        for scope in ("admin", "Payments", True):
            with self.subTest(scope=scope):
                with self.assertRaises(ValueError):
                    self.service.issue_credential(
                        agent_id=binding.agent_id,
                        runtime_id="runtime",
                        request_id=f"request-{scope}",
                        scope=scope,
                    )
        for ttl in (59, 901, True, 300.0, "300"):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ValueError):
                    self.service.issue_credential(
                        agent_id=binding.agent_id,
                        runtime_id="runtime",
                        request_id=f"request-{ttl}",
                        ttl_seconds=ttl,
                    )

    def test_sqlite_concurrent_rotation_has_one_winner(self) -> None:
        binding = self.service.register(
            subject_id="wallet-user-1",
            external_agent_id="agent-1",
        )
        first = self.service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-1",
            request_id="request-1",
        )

        def rotate(request_id: str) -> str:
            service = AgentAccessService(
                AgentAccessRepository(
                    create_engine(f"sqlite+pysqlite:///{self.path}")
                ),
                issuer="service-agent",
                token_key=b"k" * 32,
                clock=lambda: self.now,
            )
            try:
                return service.issue_credential(
                    agent_id=binding.agent_id,
                    runtime_id=request_id,
                    request_id=request_id,
                    replaces_credential_id=first.credential_id,
                ).credential_id
            except AgentAccessConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(rotate, ("runtime-2", "runtime-3")))

        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(len({item for item in results if item != "conflict"}), 1)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_runtime_credential"
                ).fetchone()[0],
                2,
            )


if __name__ == "__main__":
    unittest.main()
