from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from typing import Any, Callable, Iterator
from unittest.mock import patch

from sqlalchemy import event, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from clink_node.storage import (
    MiniAppActiveRunLease,
    MiniAppBrowserSession,
    MiniAppHermesBinding,
    MiniAppMessageClaim,
    MiniAppMessageClaimResult,
    MiniAppStorageConflict,
    PostgresNodeRepository,
    SQLiteNodeRepository,
)
from clink_node.storage import postgres as postgres_storage
from clink_node.storage.postgres import metadata as postgres_metadata
from clink_node.storage.schema import SQLITE_MIGRATIONS


NOW = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)


def _hash(character: str) -> str:
    return character * 64


def _unique_hash(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


def _raw_browser_session(label: str) -> dict[str, Any]:
    return {
        "session_id": f"browser_{label}",
        "telegram_user_id": "987654321",
        "subject_id": f"telegram:{label}",
        "exchange_hash": _unique_hash(f"{label}:exchange"),
        "client_nonce_hash": _unique_hash(f"{label}:nonce"),
        "session_token_hash": _unique_hash(f"{label}:session"),
        "csrf_token_hash": _unique_hash(f"{label}:csrf"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "revoked_at": None,
    }


def _raw_hermes_binding(label: str) -> dict[str, Any]:
    return {
        "subject_id": f"telegram:{label}",
        "hermes_session_id": f"hermes_{label}",
        "session_key_hash": _unique_hash(f"{label}:session-key"),
        "created_at": NOW,
        "revoked_at": None,
    }


def _raw_message_claim(label: str) -> dict[str, Any]:
    return {
        "subject_id": f"telegram:{label}",
        "client_message_id": f"message_{label}",
        "payload_hash": _unique_hash(f"{label}:payload"),
        "status": "starting",
        "hermes_run_id": None,
        "hermes_run_session_id": f"hermes_effective_{label}",
        "legacy_unreconciled": False,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _raw_active_run_lease(label: str) -> dict[str, Any]:
    return {
        "subject_id": f"telegram:{label}",
        "client_message_id": f"message_{label}",
        "acquired_at": NOW,
        "updated_at": NOW,
    }


def _browser_session(**overrides: Any) -> MiniAppBrowserSession:
    values: dict[str, Any] = {
        "session_id": "browser_session_1",
        "telegram_user_id": "987654321",
        "subject_id": "telegram:987654321",
        "exchange_hash": _hash("a"),
        "client_nonce_hash": _hash("b"),
        "session_token_hash": _hash("c"),
        "csrf_token_hash": _hash("d"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "revoked_at": None,
    }
    values.update(overrides)
    return MiniAppBrowserSession(**values)


def _hermes_binding(**overrides: Any) -> MiniAppHermesBinding:
    values: dict[str, Any] = {
        "subject_id": "telegram:987654321",
        "hermes_session_id": "hermes_session_1",
        "session_key_hash": _hash("e"),
        "created_at": NOW,
        "revoked_at": None,
    }
    values.update(overrides)
    return MiniAppHermesBinding(**values)


def _message_claim(**overrides: Any) -> MiniAppMessageClaim:
    values: dict[str, Any] = {
        "subject_id": "telegram:987654321",
        "client_message_id": "message_1",
        "payload_hash": _hash("f"),
        "status": "starting",
        "hermes_run_id": None,
        "hermes_run_session_id": "hermes_effective_session_1",
        "legacy_unreconciled": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return MiniAppMessageClaim(**values)


def _active_run_lease(**overrides: Any) -> MiniAppActiveRunLease:
    values: dict[str, Any] = {
        "subject_id": "telegram:987654321",
        "client_message_id": "message_1",
        "acquired_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return MiniAppActiveRunLease(**values)


class MiniAppStorageModelTests(unittest.TestCase):
    def test_active_run_lease_is_frozen_bounded_and_normalized(self) -> None:
        offset = datetime.fromisoformat("2026-08-18T18:00:00+08:00")
        lease = _active_run_lease(acquired_at=offset, updated_at=offset)

        self.assertEqual(
            tuple(field.name for field in fields(lease)),
            ("subject_id", "client_message_id", "acquired_at", "updated_at"),
        )
        self.assertEqual(lease.acquired_at, NOW)
        self.assertEqual(lease.updated_at, NOW)
        with self.assertRaises(FrozenInstanceError):
            lease.client_message_id = "changed"  # type: ignore[misc]

        invalid = (
            lambda: _active_run_lease(subject_id=""),
            lambda: _active_run_lease(subject_id="x" * 257),
            lambda: _active_run_lease(client_message_id=""),
            lambda: _active_run_lease(client_message_id="x" * 257),
            lambda: _active_run_lease(
                acquired_at=datetime(2026, 8, 18, 10, 0)
            ),
        )
        for build in invalid:
            with self.subTest(build=build):
                with self.assertRaises(ValueError) as raised:
                    build()
                self.assertEqual(
                    str(raised.exception),
                    "miniapp_storage_invalid",
                )

    def test_records_are_frozen_and_normalize_aware_timestamps_to_utc(
        self,
    ) -> None:
        offset = datetime.fromisoformat("2026-08-18T18:00:00+08:00")
        session = _browser_session(created_at=offset)

        self.assertEqual(session.created_at, NOW)
        with self.assertRaises(FrozenInstanceError):
            session.session_id = "changed"  # type: ignore[misc]

    def test_every_hash_requires_64_lowercase_hex_characters(self) -> None:
        examples = (
            (_browser_session(), "exchange_hash"),
            (_browser_session(), "client_nonce_hash"),
            (_browser_session(), "session_token_hash"),
            (_browser_session(), "csrf_token_hash"),
            (_hermes_binding(), "session_key_hash"),
            (_message_claim(), "payload_hash"),
        )

        for record, field_name in examples:
            for invalid in (_hash("A"), "0" * 63, "g" * 64):
                with self.subTest(field=field_name, invalid=invalid[:2]):
                    with self.assertRaises(ValueError) as raised:
                        replace(record, **{field_name: invalid})
                    self.assertEqual(
                        str(raised.exception),
                        "miniapp_storage_invalid",
                    )
                    self.assertNotIn(invalid, repr(raised.exception))

    def test_ids_and_timestamps_are_nonempty_bounded_and_aware(self) -> None:
        invalid_records: tuple[Callable[[], object], ...] = (
            lambda: _browser_session(session_id=""),
            lambda: _browser_session(subject_id="x" * 257),
            lambda: _hermes_binding(hermes_session_id="x" * 257),
            lambda: _message_claim(client_message_id="x" * 257),
            lambda: _message_claim(hermes_run_session_id=""),
            lambda: _message_claim(hermes_run_session_id="x" * 257),
            lambda: _browser_session(created_at=datetime(2026, 8, 18)),
        )

        for build in invalid_records:
            with self.subTest(build=build):
                with self.assertRaises(ValueError) as raised:
                    build()
                self.assertEqual(
                    str(raised.exception),
                    "miniapp_storage_invalid",
                )

    def test_claim_status_run_and_provenance_invariants_are_validated(
        self,
    ) -> None:
        invalid_records = (
            lambda: _message_claim(status="finished"),
            lambda: _message_claim(
                status="starting",
                hermes_run_id="run_1",
            ),
            lambda: _message_claim(status="unknown", hermes_run_id="run_1"),
            lambda: _message_claim(status="accepted", hermes_run_id=None),
            lambda: _message_claim(
                status="starting",
                hermes_run_session_id=None,
            ),
            lambda: _message_claim(
                status="accepted",
                hermes_run_id="run_1",
                hermes_run_session_id=None,
            ),
            lambda: _message_claim(legacy_unreconciled=True),
            lambda: _message_claim(
                status="unknown",
                legacy_unreconciled=True,
                hermes_run_session_id="hermes_effective_session_1",
            ),
            lambda: _message_claim(
                status="unknown",
                legacy_unreconciled=1,
                hermes_run_session_id=None,
            ),
        )

        for build in invalid_records:
            with self.subTest(build=build):
                with self.assertRaises(ValueError) as raised:
                    build()
                self.assertEqual(
                    str(raised.exception),
                    "miniapp_storage_invalid",
                )

        accepted = _message_claim(
            status="accepted",
            hermes_run_id="run_1",
        )
        unknown = _message_claim(status="unknown")
        legacy = _message_claim(
            status="unknown",
            hermes_run_session_id=None,
            legacy_unreconciled=True,
        )
        self.assertEqual(
            accepted.hermes_run_session_id,
            "hermes_effective_session_1",
        )
        self.assertEqual(
            unknown.hermes_run_session_id,
            "hermes_effective_session_1",
        )
        self.assertIsNone(legacy.hermes_run_session_id)
        self.assertTrue(legacy.legacy_unreconciled)

    def test_message_claim_result_is_frozen_and_adds_only_ownership(
        self,
    ) -> None:
        claim = _message_claim()
        result = MiniAppMessageClaimResult(claim=claim, created=True)

        self.assertEqual(
            tuple(field.name for field in fields(result)),
            ("claim", "created"),
        )
        self.assertIs(result.claim, claim)
        self.assertTrue(result.created)
        with self.assertRaises(FrozenInstanceError):
            result.created = False  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.claim.status = "unknown"  # type: ignore[misc]
        rendered = repr(result)
        for raw_value in (
            "raw message body",
            "telegram initData",
            "credential-value",
            "browser-token-value",
        ):
            self.assertNotIn(raw_value, rendered)


class MiniAppRepositoryContract:
    repository: SQLiteNodeRepository | PostgresNodeRepository
    integrity_error: type[Exception]

    def table_columns(self, table_name: str) -> set[str]:
        raise NotImplementedError

    def raw_insert(
        self,
        table_name: str,
        values: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def assert_conflict(self, action: Callable[[], object]) -> None:
        with self.assertRaises(  # type: ignore[attr-defined]
            MiniAppStorageConflict
        ) as raised:
            action()
        error = raised.exception
        self.assertEqual(  # type: ignore[attr-defined]
            str(error),
            "miniapp_storage_conflict",
        )
        self.assertEqual(  # type: ignore[attr-defined]
            repr(error),
            "MiniAppStorageConflict('miniapp_storage_conflict')",
        )
        self.assertIsNone(error.__cause__)  # type: ignore[attr-defined]
        self.assertIsNone(error.__context__)  # type: ignore[attr-defined]
        rendered = repr(error)
        self.assertNotIn(_hash("a"), rendered)  # type: ignore[attr-defined]
        self.assertNotIn("telegram:987654321", rendered)  # type: ignore[attr-defined]

    def test_session_exchange_replay_returns_original_immutable_row(
        self,
    ) -> None:
        proposed = _browser_session()

        stored = self.repository.exchange_miniapp_session(proposed)
        replay = self.repository.exchange_miniapp_session(
            replace(
                proposed,
                session_id="browser_session_replay",
                session_token_hash=_hash("1"),
                csrf_token_hash=_hash("2"),
                created_at=NOW + timedelta(seconds=1),
            )
        )

        self.assertEqual(stored, proposed)  # type: ignore[attr-defined]
        self.assertEqual(replay, proposed)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_session(
                proposed.session_token_hash,
                NOW + timedelta(seconds=1),
            ),
            proposed,
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_session(
                _hash("1"),
                NOW + timedelta(seconds=1),
            )
        )

    def test_session_exchange_rejects_nonce_or_identity_drift(self) -> None:
        proposed = _browser_session()
        self.repository.exchange_miniapp_session(proposed)

        conflicts = (
            replace(proposed, client_nonce_hash=_hash("0")),
            replace(proposed, telegram_user_id="123456789"),
            replace(proposed, subject_id="telegram:123456789"),
        )
        for conflicting in conflicts:
            with self.subTest(  # type: ignore[attr-defined]
                conflicting=conflicting.subject_id
            ):
                self.assert_conflict(
                    lambda candidate=conflicting: (
                        self.repository.exchange_miniapp_session(candidate)
                    )
                )

    def test_session_token_is_unique_and_expiry_and_revocation_are_enforced(
        self,
    ) -> None:
        first = _browser_session()
        self.repository.exchange_miniapp_session(first)
        token_collision = _browser_session(
            session_id="browser_session_2",
            exchange_hash=_hash("0"),
            session_token_hash=first.session_token_hash,
        )

        self.assert_conflict(
            lambda: self.repository.exchange_miniapp_session(token_collision)
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_session(
                first.session_token_hash,
                first.expires_at - timedelta(microseconds=1),
            ),
            first,
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_session(
                first.session_token_hash,
                first.expires_at,
            )
        )

        second = _browser_session(
            session_id="browser_session_3",
            exchange_hash=_hash("1"),
            client_nonce_hash=_hash("2"),
            session_token_hash=_hash("3"),
            csrf_token_hash=_hash("4"),
        )
        self.repository.exchange_miniapp_session(second)
        self.assertTrue(  # type: ignore[attr-defined]
            self.repository.revoke_miniapp_session(
                second.session_token_hash,
                NOW + timedelta(seconds=1),
            )
        )
        self.assertFalse(  # type: ignore[attr-defined]
            self.repository.revoke_miniapp_session(
                second.session_token_hash,
                NOW + timedelta(seconds=2),
            )
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_session(
                second.session_token_hash,
                NOW + timedelta(seconds=2),
            )
        )

    def test_hermes_binding_is_subject_bound_and_replay_safe(self) -> None:
        proposed = _hermes_binding()

        stored = self.repository.get_or_create_hermes_binding(proposed)
        replay = self.repository.get_or_create_hermes_binding(
            replace(proposed, created_at=NOW + timedelta(seconds=1))
        )

        self.assertEqual(stored, proposed)  # type: ignore[attr-defined]
        self.assertEqual(replay, proposed)  # type: ignore[attr-defined]
        self.assert_conflict(
            lambda: self.repository.get_or_create_hermes_binding(
                replace(proposed, hermes_session_id="hermes_session_2")
            )
        )
        self.assert_conflict(
            lambda: self.repository.get_or_create_hermes_binding(
                replace(proposed, session_key_hash=_hash("0"))
            )
        )
        self.assert_conflict(
            lambda: self.repository.get_or_create_hermes_binding(
                replace(proposed, subject_id="telegram:123456789")
            )
        )

    def test_message_claim_is_atomic_per_subject_and_client_id(self) -> None:
        proposed = _message_claim()

        stored = self.repository.claim_miniapp_message(proposed)
        replay = self.repository.claim_miniapp_message(
            replace(proposed, created_at=NOW + timedelta(seconds=1))
        )
        another_subject = self.repository.claim_miniapp_message(
            replace(proposed, subject_id="telegram:123456789")
        )

        self.assertTrue(stored.created)  # type: ignore[attr-defined]
        self.assertEqual(stored.claim, proposed)  # type: ignore[attr-defined]
        expected_lease = _active_run_lease(
            subject_id=proposed.subject_id,
            client_message_id=proposed.client_message_id,
            acquired_at=proposed.created_at,
            updated_at=proposed.updated_at,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_active_run_lease(
                proposed.subject_id
            ),
            expected_lease,
        )
        self.assertFalse(replay.created)  # type: ignore[attr-defined]
        self.assertEqual(replay.claim, proposed)  # type: ignore[attr-defined]
        self.assertTrue(another_subject.created)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            another_subject.claim.subject_id,
            "telegram:123456789",
        )
        self.assert_conflict(
            lambda: self.repository.claim_miniapp_message(
                replace(proposed, payload_hash=_hash("0"))
            )
        )
        self.assert_conflict(
            lambda: self.repository.claim_miniapp_message(
                replace(
                    proposed,
                    hermes_run_session_id="hermes_effective_session_2",
                )
            )
        )

    def test_subject_lease_blocks_other_client_without_partial_claim(
        self,
    ) -> None:
        owner = _message_claim(client_message_id="lease_owner")
        blocked = _message_claim(
            client_message_id="lease_blocked",
            payload_hash=_hash("0"),
        )

        self.repository.claim_miniapp_message(owner)
        self.assert_conflict(
            lambda: self.repository.claim_miniapp_message(blocked)
        )

        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                blocked.subject_id,
                blocked.client_message_id,
            )
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_active_run_lease(owner.subject_id),
            _active_run_lease(
                subject_id=owner.subject_id,
                client_message_id=owner.client_message_id,
                acquired_at=owner.created_at,
                updated_at=owner.updated_at,
            ),
        )

    def test_active_run_lease_release_is_exact_and_idempotent(self) -> None:
        owner = _message_claim(client_message_id="release_owner")
        successor = _message_claim(
            client_message_id="release_successor",
            payload_hash=_hash("1"),
            created_at=NOW + timedelta(seconds=1),
            updated_at=NOW + timedelta(seconds=1),
        )
        self.repository.claim_miniapp_message(owner)

        self.assert_conflict(
            lambda: self.repository.release_miniapp_active_run_lease(
                owner.subject_id,
                "not_the_owner",
            )
        )
        self.assertIsNotNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_active_run_lease(owner.subject_id)
        )
        self.assertTrue(  # type: ignore[attr-defined]
            self.repository.release_miniapp_active_run_lease(
                owner.subject_id,
                owner.client_message_id,
            )
        )
        self.assertFalse(  # type: ignore[attr-defined]
            self.repository.release_miniapp_active_run_lease(
                owner.subject_id,
                owner.client_message_id,
            )
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_active_run_lease(owner.subject_id)
        )

        created = self.repository.claim_miniapp_message(successor)
        self.assertTrue(created.created)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_active_run_lease(owner.subject_id),
            _active_run_lease(
                subject_id=successor.subject_id,
                client_message_id=successor.client_message_id,
                acquired_at=successor.created_at,
                updated_at=successor.updated_at,
            ),
        )

    def test_active_run_lease_lookups_reject_invalid_ids(self) -> None:
        oversized = "x" * 257
        actions = (
            lambda: self.repository.get_miniapp_active_run_lease(""),
            lambda: self.repository.get_miniapp_active_run_lease(oversized),
            lambda: self.repository.release_miniapp_active_run_lease(
                "",
                "message",
            ),
            lambda: self.repository.release_miniapp_active_run_lease(
                "telegram:987654321",
                oversized,
            ),
        )
        for action in actions:
            with self.subTest(action=action):  # type: ignore[attr-defined]
                with self.assertRaises(ValueError) as raised:  # type: ignore[attr-defined]
                    action()
                self.assertEqual(  # type: ignore[attr-defined]
                    str(raised.exception),
                    "miniapp_storage_invalid",
                )

    def test_message_claim_lookup_is_subject_bound_and_preserves_state(
        self,
    ) -> None:
        starting = _message_claim(client_message_id="lookup_starting")
        accepted_source = _message_claim(
            client_message_id="lookup_accepted",
            payload_hash=_hash("1"),
        )
        unknown_source = _message_claim(
            client_message_id="lookup_unknown",
            payload_hash=_hash("2"),
        )
        other_subject = replace(
            starting,
            subject_id="telegram:123456789",
            payload_hash=_hash("3"),
        )
        for claim in (starting, accepted_source, unknown_source):
            self.repository.claim_miniapp_message(claim)
            self.assertTrue(  # type: ignore[attr-defined]
                self.repository.release_miniapp_active_run_lease(
                    claim.subject_id,
                    claim.client_message_id,
                )
            )
        self.repository.claim_miniapp_message(other_subject)
        accepted = self.repository.complete_miniapp_message(
            accepted_source.subject_id,
            accepted_source.client_message_id,
            status="accepted",
            hermes_run_id="run_lookup_accepted",
            hermes_run_session_id=(
                accepted_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=1),
        )
        unknown = self.repository.complete_miniapp_message(
            unknown_source.subject_id,
            unknown_source.client_message_id,
            status="unknown",
            hermes_run_id=None,
            hermes_run_session_id=(
                unknown_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                starting.subject_id,
                starting.client_message_id,
            ),
            starting,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                accepted.subject_id,
                accepted.client_message_id,
            ),
            accepted,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                unknown.subject_id,
                unknown.client_message_id,
            ),
            unknown,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                other_subject.subject_id,
                other_subject.client_message_id,
            ),
            other_subject,
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                "telegram:not-the-owner",
                starting.client_message_id,
            )
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                starting.subject_id,
                "missing_message",
            )
        )

    def test_latest_message_claim_uses_created_time_then_client_id(
        self,
    ) -> None:
        subject_id = "telegram:latest"
        older = _message_claim(
            subject_id=subject_id,
            client_message_id="older",
            payload_hash=_hash("4"),
            created_at=NOW,
            updated_at=NOW,
        )
        tied_lower_source = _message_claim(
            subject_id=subject_id,
            client_message_id="latest_a",
            payload_hash=_hash("5"),
            created_at=NOW + timedelta(seconds=1),
            updated_at=NOW + timedelta(seconds=1),
        )
        tied_higher_source = _message_claim(
            subject_id=subject_id,
            client_message_id="latest_z",
            payload_hash=_hash("6"),
            created_at=NOW + timedelta(seconds=1),
            updated_at=NOW + timedelta(seconds=1),
        )
        for claim in (older, tied_lower_source, tied_higher_source):
            self.repository.claim_miniapp_message(claim)
            self.assertTrue(  # type: ignore[attr-defined]
                self.repository.release_miniapp_active_run_lease(
                    claim.subject_id,
                    claim.client_message_id,
                )
            )
        tied_lower = self.repository.complete_miniapp_message(
            subject_id,
            tied_lower_source.client_message_id,
            status="accepted",
            hermes_run_id="run_latest_a",
            hermes_run_session_id=(
                tied_lower_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=3),
        )
        tied_higher = self.repository.complete_miniapp_message(
            subject_id,
            tied_higher_source.client_message_id,
            status="unknown",
            hermes_run_id=None,
            hermes_run_session_id=(
                tied_higher_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=2),
        )

        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_latest_miniapp_message_claim(subject_id),
            tied_higher,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                subject_id,
                tied_lower.client_message_id,
            ),
            tied_lower,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.repository.get_miniapp_message_claim(
                subject_id,
                older.client_message_id,
            ),
            older,
        )
        self.assertIsNone(  # type: ignore[attr-defined]
            self.repository.get_latest_miniapp_message_claim(
                "telegram:no-claims"
            )
        )

    def test_message_claim_lookup_rejects_invalid_bounded_ids(self) -> None:
        oversized = "x" * 257
        actions = (
            lambda: self.repository.get_miniapp_message_claim(
                "",
                "message_1",
            ),
            lambda: self.repository.get_miniapp_message_claim(
                oversized,
                "message_1",
            ),
            lambda: self.repository.get_miniapp_message_claim(
                "telegram:987654321",
                "",
            ),
            lambda: self.repository.get_miniapp_message_claim(
                "telegram:987654321",
                oversized,
            ),
            lambda: self.repository.get_latest_miniapp_message_claim(""),
            lambda: self.repository.get_latest_miniapp_message_claim(
                oversized
            ),
        )

        for action in actions:
            with self.subTest(action=action):  # type: ignore[attr-defined]
                with self.assertRaises(ValueError) as raised:  # type: ignore[attr-defined]
                    action()
                self.assertEqual(  # type: ignore[attr-defined]
                    str(raised.exception),
                    "miniapp_storage_invalid",
                )
                self.assertNotIn(oversized, repr(raised.exception))  # type: ignore[attr-defined]

    def test_message_completion_accepts_only_contract_transitions(self) -> None:
        accepted_source = _message_claim(client_message_id="accepted_message")
        self.repository.claim_miniapp_message(accepted_source)

        accepted = self.repository.complete_miniapp_message(
            accepted_source.subject_id,
            accepted_source.client_message_id,
            status="accepted",
            hermes_run_id="run_1",
            hermes_run_session_id=(
                accepted_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=1),
        )
        accepted_replay = self.repository.complete_miniapp_message(
            accepted_source.subject_id,
            accepted_source.client_message_id,
            status="accepted",
            hermes_run_id="run_1",
            hermes_run_session_id=(
                accepted_source.hermes_run_session_id
            ),
            now=NOW + timedelta(seconds=2),
        )
        claim_replay = self.repository.claim_miniapp_message(
            replace(accepted_source, updated_at=NOW + timedelta(seconds=2))
        )

        self.assertEqual(accepted.status, "accepted")  # type: ignore[attr-defined]
        self.assertEqual(accepted.hermes_run_id, "run_1")  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            accepted.hermes_run_session_id,
            accepted_source.hermes_run_session_id,
        )
        self.assertEqual(  # type: ignore[attr-defined]
            accepted.updated_at,
            NOW + timedelta(seconds=1),
        )
        self.assertEqual(accepted_replay, accepted)  # type: ignore[attr-defined]
        self.assertFalse(claim_replay.created)  # type: ignore[attr-defined]
        self.assertEqual(claim_replay.claim, accepted)  # type: ignore[attr-defined]
        self.assert_conflict(
            lambda: self.repository.complete_miniapp_message(
                accepted.subject_id,
                accepted.client_message_id,
                status="accepted",
                hermes_run_id="run_2",
                hermes_run_session_id=(
                    accepted_source.hermes_run_session_id
                ),
                now=NOW + timedelta(seconds=3),
            )
        )
        self.assert_conflict(
            lambda: self.repository.complete_miniapp_message(
                accepted.subject_id,
                accepted.client_message_id,
                status="accepted",
                hermes_run_id="run_1",
                hermes_run_session_id="hermes_effective_session_2",
                now=NOW + timedelta(seconds=3),
            )
        )
        self.assert_conflict(
            lambda: self.repository.complete_miniapp_message(
                accepted.subject_id,
                accepted.client_message_id,
                status="unknown",
                hermes_run_id=None,
                hermes_run_session_id=(
                    accepted_source.hermes_run_session_id
                ),
                now=NOW + timedelta(seconds=3),
            )
        )

        self.assertTrue(  # type: ignore[attr-defined]
            self.repository.release_miniapp_active_run_lease(
                accepted_source.subject_id,
                accepted_source.client_message_id,
            )
        )
        unknown_source = _message_claim(client_message_id="unknown_message")
        self.repository.claim_miniapp_message(unknown_source)
        unknown = self.repository.complete_miniapp_message(
            unknown_source.subject_id,
            unknown_source.client_message_id,
            status="unknown",
            hermes_run_id=None,
            hermes_run_session_id=unknown_source.hermes_run_session_id,
            now=NOW + timedelta(seconds=1),
        )
        unknown_replay = self.repository.claim_miniapp_message(
            replace(unknown_source, updated_at=NOW + timedelta(seconds=2))
        )
        recovered = self.repository.complete_miniapp_message(
            unknown.subject_id,
            unknown.client_message_id,
            status="accepted",
            hermes_run_id="run_recovered",
            hermes_run_session_id=unknown_source.hermes_run_session_id,
            now=NOW + timedelta(seconds=2),
        )

        self.assertEqual(unknown.status, "unknown")  # type: ignore[attr-defined]
        self.assertFalse(unknown_replay.created)  # type: ignore[attr-defined]
        self.assertEqual(unknown_replay.claim, unknown)  # type: ignore[attr-defined]
        self.assertEqual(recovered.status, "accepted")  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            recovered.hermes_run_id,
            "run_recovered",
        )
        self.assertEqual(  # type: ignore[attr-defined]
            recovered.hermes_run_session_id,
            unknown_source.hermes_run_session_id,
        )

    def test_message_completion_rejects_missing_run_and_other_transitions(
        self,
    ) -> None:
        cases = (
            ("missing_accepted", "accepted", None),
            ("run_on_unknown", "unknown", "run_1"),
            ("same_starting", "starting", None),
        )
        for client_message_id, status, run_id in cases:
            with self.subTest(status=status, run_id=run_id):
                claim = _message_claim(client_message_id=client_message_id)
                self.repository.claim_miniapp_message(claim)
                self.assert_conflict(
                    lambda: self.repository.complete_miniapp_message(
                        claim.subject_id,
                        claim.client_message_id,
                        status=status,
                        hermes_run_id=run_id,
                        hermes_run_session_id=(
                            claim.hermes_run_session_id
                        ),
                        now=NOW + timedelta(seconds=1),
                    )
                )
                self.assertTrue(  # type: ignore[attr-defined]
                    self.repository.release_miniapp_active_run_lease(
                        claim.subject_id,
                        claim.client_message_id,
                    )
                )

        unknown_claim = _message_claim(client_message_id="unknown_no_run")
        self.repository.claim_miniapp_message(unknown_claim)
        self.repository.complete_miniapp_message(
            unknown_claim.subject_id,
            unknown_claim.client_message_id,
            status="unknown",
            hermes_run_id=None,
            hermes_run_session_id=unknown_claim.hermes_run_session_id,
            now=NOW + timedelta(seconds=1),
        )
        self.assert_conflict(
            lambda: self.repository.complete_miniapp_message(
                unknown_claim.subject_id,
                unknown_claim.client_message_id,
                status="accepted",
                hermes_run_id=None,
                hermes_run_session_id=(
                    unknown_claim.hermes_run_session_id
                ),
                now=NOW + timedelta(seconds=2),
            )
        )

    def test_message_completion_rejects_provenance_drift(self) -> None:
        source = _message_claim(client_message_id="session_drift")
        self.repository.claim_miniapp_message(source)

        for status, run_id in (("accepted", "run_drift"), ("unknown", None)):
            with self.subTest(status=status):  # type: ignore[attr-defined]
                self.assert_conflict(
                    lambda status=status, run_id=run_id: (
                        self.repository.complete_miniapp_message(
                            source.subject_id,
                            source.client_message_id,
                            status=status,
                            hermes_run_id=run_id,
                            hermes_run_session_id=(
                                "hermes_effective_session_2"
                            ),
                            now=NOW + timedelta(seconds=1),
                        )
                    )
                )

        current = self.repository.get_miniapp_message_claim(
            source.subject_id,
            source.client_message_id,
        )
        self.assertEqual(current, source)  # type: ignore[attr-defined]

    def test_tables_store_only_bounded_identifiers_hashes_and_state(self) -> None:
        self.assertEqual(  # type: ignore[attr-defined]
            self.table_columns("miniapp_browser_session"),
            {
                "session_id",
                "telegram_user_id",
                "subject_id",
                "exchange_hash",
                "client_nonce_hash",
                "session_token_hash",
                "csrf_token_hash",
                "created_at",
                "expires_at",
                "revoked_at",
            },
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.table_columns("miniapp_hermes_binding"),
            {
                "subject_id",
                "hermes_session_id",
                "session_key_hash",
                "created_at",
                "revoked_at",
            },
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.table_columns("miniapp_message_claim"),
            {
                "subject_id",
                "client_message_id",
                "payload_hash",
                "status",
                "hermes_run_id",
                "hermes_run_session_id",
                "legacy_unreconciled",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(  # type: ignore[attr-defined]
            self.table_columns("miniapp_active_run_lease"),
            {
                "subject_id",
                "client_message_id",
                "acquired_at",
                "updated_at",
            },
        )

    def test_database_rejects_non_lowerhex_hashes_in_every_hash_column(
        self,
    ) -> None:
        hash_columns = (
            ("miniapp_browser_session", _raw_browser_session, "exchange_hash"),
            (
                "miniapp_browser_session",
                _raw_browser_session,
                "client_nonce_hash",
            ),
            (
                "miniapp_browser_session",
                _raw_browser_session,
                "session_token_hash",
            ),
            ("miniapp_browser_session", _raw_browser_session, "csrf_token_hash"),
            (
                "miniapp_hermes_binding",
                _raw_hermes_binding,
                "session_key_hash",
            ),
            ("miniapp_message_claim", _raw_message_claim, "payload_hash"),
        )
        invalid_hashes = ("A" * 64, "G" * 64, "!" * 64, "a" * 63)

        for table_name, build_values, field_name in hash_columns:
            for index, invalid_hash in enumerate(invalid_hashes):
                label = f"{field_name}_{index}"
                values = build_values(label)
                values[field_name] = invalid_hash
                with self.subTest(  # type: ignore[attr-defined]
                    table=table_name,
                    field=field_name,
                    invalid=invalid_hash[0],
                ):
                    with self.assertRaises(  # type: ignore[attr-defined]
                        self.integrity_error
                    ):
                        self.raw_insert(table_name, values)

    def test_database_rejects_empty_or_oversized_critical_ids(self) -> None:
        id_columns = (
            ("miniapp_browser_session", _raw_browser_session, "session_id"),
            (
                "miniapp_browser_session",
                _raw_browser_session,
                "telegram_user_id",
            ),
            ("miniapp_browser_session", _raw_browser_session, "subject_id"),
            ("miniapp_hermes_binding", _raw_hermes_binding, "subject_id"),
            (
                "miniapp_hermes_binding",
                _raw_hermes_binding,
                "hermes_session_id",
            ),
            ("miniapp_message_claim", _raw_message_claim, "subject_id"),
            (
                "miniapp_message_claim",
                _raw_message_claim,
                "client_message_id",
            ),
            (
                "miniapp_message_claim",
                _raw_message_claim,
                "hermes_run_session_id",
            ),
        )

        for table_name, build_values, field_name in id_columns:
            for index, invalid_id in enumerate(("", "x" * 257)):
                values = build_values(f"invalid_{field_name}_{index}")
                values[field_name] = invalid_id
                with self.subTest(  # type: ignore[attr-defined]
                    table=table_name,
                    field=field_name,
                    length=len(invalid_id),
                ):
                    with self.assertRaises(  # type: ignore[attr-defined]
                        self.integrity_error
                    ):
                        self.raw_insert(table_name, values)

    def test_database_accepts_critical_id_boundaries(self) -> None:
        id_columns = (
            ("miniapp_browser_session", _raw_browser_session, "session_id"),
            (
                "miniapp_browser_session",
                _raw_browser_session,
                "telegram_user_id",
            ),
            ("miniapp_browser_session", _raw_browser_session, "subject_id"),
            ("miniapp_hermes_binding", _raw_hermes_binding, "subject_id"),
            (
                "miniapp_hermes_binding",
                _raw_hermes_binding,
                "hermes_session_id",
            ),
            ("miniapp_message_claim", _raw_message_claim, "subject_id"),
            (
                "miniapp_message_claim",
                _raw_message_claim,
                "client_message_id",
            ),
            (
                "miniapp_message_claim",
                _raw_message_claim,
                "hermes_run_session_id",
            ),
        )

        for table_name, build_values, field_name in id_columns:
            for index, valid_id in enumerate(("x", "x" * 256)):
                values = build_values(f"valid_{field_name}_{index}")
                values[field_name] = valid_id
                with self.subTest(  # type: ignore[attr-defined]
                    table=table_name,
                    field=field_name,
                    length=len(valid_id),
                ):
                    self.raw_insert(table_name, values)

    def test_database_rejects_invalid_claim_state_provenance_shapes(
        self,
    ) -> None:
        invalid_shapes = (
            ("starting", "run_starting", "session", False),
            ("unknown", "run_unknown", "session", False),
            ("accepted", None, "session", False),
            ("accepted", "", "session", False),
            ("accepted", "r" * 257, "session", False),
            ("starting", None, None, False),
            ("unknown", None, None, False),
            ("accepted", "run", None, False),
            ("starting", None, None, True),
            ("accepted", "run", None, True),
            ("unknown", None, "session", True),
        )

        for index, shape in enumerate(invalid_shapes):
            status, run_id, session_id, legacy = shape
            values = _raw_message_claim(f"invalid_shape_{index}")
            values.update(
                status=status,
                hermes_run_id=run_id,
                hermes_run_session_id=session_id,
                legacy_unreconciled=legacy,
            )
            with self.subTest(  # type: ignore[attr-defined]
                status=status,
                run_length=len(run_id) if run_id is not None else None,
                session_id=session_id,
                legacy=legacy,
            ):
                with self.assertRaises(  # type: ignore[attr-defined]
                    self.integrity_error
                ):
                    self.raw_insert("miniapp_message_claim", values)

    def test_database_accepts_valid_claim_state_provenance_shapes(
        self,
    ) -> None:
        valid_shapes = (
            ("starting", None, "s", False),
            ("unknown", None, "s" * 256, False),
            ("accepted", "r", "s", False),
            ("accepted", "r" * 256, "s" * 256, False),
            ("unknown", None, None, True),
        )

        for index, shape in enumerate(valid_shapes):
            status, run_id, session_id, legacy = shape
            values = _raw_message_claim(f"valid_shape_{index}")
            values.update(
                status=status,
                hermes_run_id=run_id,
                hermes_run_session_id=session_id,
                legacy_unreconciled=legacy,
            )
            with self.subTest(  # type: ignore[attr-defined]
                status=status,
                run_length=len(run_id) if run_id is not None else None,
                session_id=session_id,
                legacy=legacy,
            ):
                self.raw_insert("miniapp_message_claim", values)


class SQLiteMiniAppRepositoryTests(
    MiniAppRepositoryContract,
    unittest.TestCase,
):
    integrity_error = sqlite3.IntegrityError

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "clink.db"
        self.repository = SQLiteNodeRepository(self.path)
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def table_columns(self, table_name: str) -> set[str]:
        with sqlite3.connect(self.path) as connection:
            return {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                )
            }

    def test_active_run_lease_schema_has_subject_pk_and_composite_fk(
        self,
    ) -> None:
        with sqlite3.connect(self.path) as connection:
            columns = connection.execute(
                "PRAGMA table_info(miniapp_active_run_lease)"
            ).fetchall()
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(miniapp_active_run_lease)"
            ).fetchall()
            ddl = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' "
                "AND name = 'miniapp_active_run_lease'"
            ).fetchone()[0]

        self.assertEqual(
            [row[1] for row in columns if row[5]],
            ["subject_id"],
        )
        self.assertEqual(
            {(row[3], row[4]) for row in foreign_keys},
            {
                ("subject_id", "subject_id"),
                ("client_message_id", "client_message_id"),
            },
        )
        self.assertEqual({row[2] for row in foreign_keys}, {
            "miniapp_message_claim"
        })
        self.assertEqual({row[6] for row in foreign_keys}, {"RESTRICT"})
        self.assertIn("length(subject_id) BETWEEN 1 AND 256", ddl)
        self.assertIn("length(client_message_id) BETWEEN 1 AND 256", ddl)

    def raw_insert(
        self,
        table_name: str,
        values: dict[str, Any],
    ) -> None:
        columns = tuple(values)
        stored_values = tuple(
            value.isoformat() if isinstance(value, datetime) else value
            for value in values.values()
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                f"INSERT INTO {table_name} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                stored_values,
            )


class SQLAlchemyMiniAppRepositoryContractTests(
    MiniAppRepositoryContract,
    unittest.TestCase,
):
    integrity_error = SQLAlchemyIntegrityError

    def setUp(self) -> None:
        from sqlalchemy import create_engine

        self.repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=create_engine("sqlite+pysqlite:///:memory:"),
        )
        self.repository.migrate()

    def tearDown(self) -> None:
        self.repository.engine.dispose()

    def table_columns(self, table_name: str) -> set[str]:
        from sqlalchemy import inspect

        return {
            str(column["name"])
            for column in inspect(self.repository.engine).get_columns(
                table_name
            )
        }

    def raw_insert(
        self,
        table_name: str,
        values: dict[str, Any],
    ) -> None:
        table = postgres_metadata.tables[table_name]
        with self.repository.engine.begin() as connection:
            connection.execute(insert(table).values(**values))

    def test_active_run_lease_metadata_has_subject_pk_and_composite_fk(
        self,
    ) -> None:
        table = postgres_metadata.tables["miniapp_active_run_lease"]
        self.assertEqual(
            tuple(column.name for column in table.primary_key.columns),
            ("subject_id",),
        )
        self.assertEqual(len(table.foreign_key_constraints), 1)
        foreign_key = next(iter(table.foreign_key_constraints))
        self.assertEqual(
            tuple(element.parent.name for element in foreign_key.elements),
            ("subject_id", "client_message_id"),
        )
        self.assertEqual(
            tuple(element.column.name for element in foreign_key.elements),
            ("subject_id", "client_message_id"),
        )
        self.assertEqual(foreign_key.ondelete, "RESTRICT")
        self.assertEqual(
            {
                constraint.name
                for constraint in table.constraints
                if constraint.name and constraint.name.startswith("ck_")
            },
            {
                "ck_miniapp_active_run_lease_subject_id_length",
                "ck_miniapp_active_run_lease_client_message_id_length",
            },
        )

    def test_message_claim_database_rejects_non_boolean_legacy_marker(
        self,
    ) -> None:
        values = _raw_message_claim("non_boolean_legacy")
        values.update(
            status="unknown",
            hermes_run_id=None,
            hermes_run_session_id=None,
            legacy_unreconciled=2,
        )
        columns = tuple(values)
        parameters = tuple(
            value.isoformat() if isinstance(value, datetime) else value
            for value in (values[column] for column in columns)
        )

        with self.assertRaises(SQLAlchemyIntegrityError):
            with self.repository.engine.begin() as connection:
                connection.exec_driver_sql(
                    f"INSERT INTO miniapp_message_claim "
                    f"({', '.join(columns)}) VALUES "
                    f"({', '.join('?' for _ in columns)})",
                    parameters,
                )

    def test_message_claim_attempts_insert_before_conflict_lookup(self) -> None:
        statements: list[str] = []

        def record_statement(
            connection: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            del connection, cursor, parameters, context, executemany
            statements.append(statement.strip().upper())

        event.listen(
            self.repository.engine,
            "before_cursor_execute",
            record_statement,
        )
        self.addCleanup(
            event.remove,
            self.repository.engine,
            "before_cursor_execute",
            record_statement,
        )
        proposed = _message_claim(client_message_id="insert_first")

        created = self.repository.claim_miniapp_message(proposed)
        self.assertTrue(created.created)
        self.assertTrue(
            statements[0].startswith("INSERT INTO MINIAPP_MESSAGE_CLAIM")
        )

        statements.clear()
        replay = self.repository.claim_miniapp_message(proposed)
        self.assertFalse(replay.created)
        self.assertTrue(
            statements[0].startswith("INSERT INTO MINIAPP_MESSAGE_CLAIM")
        )
        self.assertTrue(
            any(
                statement.startswith("SELECT")
                and "MINIAPP_MESSAGE_CLAIM" in statement
                for statement in statements[1:]
            )
        )


class SQLiteMiniAppMigrationTests(unittest.TestCase):
    def test_version_one_database_upgrades_without_losing_existing_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clink-v1.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE node_schema_migration (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                connection.executescript(SQLITE_MIGRATIONS[0][1])
                connection.execute(
                    "INSERT INTO node_schema_migration VALUES (1, ?)",
                    (NOW.isoformat(),),
                )
                connection.execute(
                    "INSERT INTO node_meta VALUES ('schema_version', '1', ?)",
                    (NOW.isoformat(),),
                )
                connection.execute(
                    """
                    INSERT INTO module_state(
                        name, mode, status, pid, endpoint, mcp_url,
                        detail, updated_at
                    ) VALUES ('core', 'managed', 'ready', 42, NULL, NULL,
                              NULL, ?)
                    """,
                    (NOW.isoformat(),),
                )
                connection.execute(
                    """
                    INSERT INTO interaction_session(
                        session_id, kind, user_id, token_hash, payload_json,
                        status, created_at, expires_at, consumed_at
                    ) VALUES ('interaction_1', 'approval', 'user_1',
                              'legacy-token-hash', '{"request_id":"request_1"}',
                              'pending', ?, ?, NULL)
                    """,
                    (NOW.isoformat(), (NOW + timedelta(minutes=5)).isoformat()),
                )
                connection.execute(
                    """
                    INSERT INTO event_outbox(
                        event_type, aggregate_id, payload_json, created_at
                    ) VALUES ('node.started', 'node', '{}', ?)
                    """,
                    (NOW.isoformat(),),
                )
                connection.execute(
                    """
                    INSERT INTO secret_reference(
                        name, backend, reference, updated_at
                    ) VALUES ('miniapp-key', 'keychain', 'ref:miniapp', ?)
                    """,
                    (NOW.isoformat(),),
                )

            repository = SQLiteNodeRepository(path)
            repository.migrate()

            self.assertEqual(repository.schema_version(), 6)
            self.assertEqual(repository.get_module("core").pid, 42)
            self.assertEqual(
                repository.get_interaction("interaction_1").payload,
                {"request_id": "request_1"},
            )
            self.assertEqual(
                repository.pending_events()[0]["event_type"],
                "node.started",
            )
            self.assertEqual(
                repository.get_secret_reference("miniapp-key"),
                {
                    "name": "miniapp-key",
                    "backend": "keychain",
                    "reference": "ref:miniapp",
                },
            )
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    {
                        row[0]
                        for row in connection.execute(
                            "SELECT version FROM node_schema_migration"
                        )
                    },
                    {1, 2, 3, 4, 5, 6},
                )

    def test_version_two_claims_are_preserved_but_fail_closed_without_provenance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clink-v2.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE node_schema_migration (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                connection.executescript(SQLITE_MIGRATIONS[0][1])
                connection.executescript(SQLITE_MIGRATIONS[1][1])
                connection.executemany(
                    "INSERT INTO node_schema_migration VALUES (?, ?)",
                    ((1, NOW.isoformat()), (2, NOW.isoformat())),
                )
                connection.execute(
                    "UPDATE node_meta SET value = '2' "
                    "WHERE key = 'schema_version'"
                )
                legacy_rows = (
                    (
                        "legacy_starting",
                        _unique_hash("legacy-starting"),
                        "starting",
                        None,
                    ),
                    (
                        "legacy_unknown",
                        _unique_hash("legacy-unknown"),
                        "unknown",
                        None,
                    ),
                    (
                        "legacy_accepted",
                        _unique_hash("legacy-accepted"),
                        "accepted",
                        "legacy_run",
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO miniapp_message_claim(
                        subject_id, client_message_id, payload_hash,
                        status, hermes_run_id, created_at, updated_at
                    ) VALUES ('telegram:legacy', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            message_id,
                            payload_hash,
                            status,
                            run_id,
                            NOW.isoformat(),
                            (NOW + timedelta(seconds=index)).isoformat(),
                        )
                        for index, (
                            message_id,
                            payload_hash,
                            status,
                            run_id,
                        ) in enumerate(legacy_rows)
                    ),
                )

            repository = SQLiteNodeRepository(path)
            repository.migrate()

            self.assertEqual(repository.schema_version(), 6)
            self.assertIsNone(
                repository.get_miniapp_active_run_lease("telegram:legacy")
            )
            for index, (message_id, payload_hash, _, _) in enumerate(
                legacy_rows
            ):
                with self.subTest(message_id=message_id):
                    claim = repository.get_miniapp_message_claim(
                        "telegram:legacy",
                        message_id,
                    )
                    self.assertIsNotNone(claim)
                    assert claim is not None
                    self.assertEqual(claim.payload_hash, payload_hash)
                    self.assertEqual(claim.status, "unknown")
                    self.assertIsNone(claim.hermes_run_id)
                    self.assertIsNone(claim.hermes_run_session_id)
                    self.assertTrue(claim.legacy_unreconciled)
                    self.assertEqual(claim.created_at, NOW)
                    self.assertEqual(
                        claim.updated_at,
                        NOW + timedelta(seconds=index),
                    )
                    with self.assertRaises(MiniAppStorageConflict):
                        repository.complete_miniapp_message(
                            claim.subject_id,
                            claim.client_message_id,
                            status="accepted",
                            hermes_run_id="recovered_run",
                            hermes_run_session_id="guessed_session",
                            now=NOW + timedelta(minutes=1),
                        )

            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    {
                        row[0]
                        for row in connection.execute(
                            "SELECT version FROM node_schema_migration"
                        )
                    },
                    {1, 2, 3, 4, 5, 6},
                )

    def test_version_three_keeps_provenance_and_leases_only_latest_claim(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clink-v3.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE node_schema_migration (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                for _, script in SQLITE_MIGRATIONS[:3]:
                    connection.executescript(script)
                connection.executemany(
                    "INSERT INTO node_schema_migration VALUES (?, ?)",
                    (
                        (1, NOW.isoformat()),
                        (2, NOW.isoformat()),
                        (3, NOW.isoformat()),
                    ),
                )
                connection.execute(
                    "UPDATE node_meta SET value = '3' "
                    "WHERE key = 'schema_version'"
                )
                claims = (
                    (
                        "starting_v3",
                        _unique_hash("starting-v3"),
                        "starting",
                        None,
                    ),
                    (
                        "unknown_v3",
                        _unique_hash("unknown-v3"),
                        "unknown",
                        None,
                    ),
                    (
                        "accepted_v3",
                        _unique_hash("accepted-v3"),
                        "accepted",
                        "run_v3",
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO miniapp_message_claim(
                        subject_id, client_message_id, payload_hash,
                        status, hermes_run_id, hermes_run_session_id,
                        legacy_unreconciled, created_at, updated_at
                    ) VALUES (
                        'telegram:v3', ?, ?, ?, ?, 'hermes_v3',
                        0, ?, ?
                    )
                    """,
                    (
                        (
                            message_id,
                            payload_hash,
                            status,
                            run_id,
                            (NOW + timedelta(seconds=index)).isoformat(),
                            (NOW + timedelta(seconds=index + 10)).isoformat(),
                        )
                        for index, (
                            message_id,
                            payload_hash,
                            status,
                            run_id,
                        ) in enumerate(claims)
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO miniapp_message_claim(
                        subject_id, client_message_id, payload_hash,
                        status, hermes_run_id, hermes_run_session_id,
                        legacy_unreconciled, created_at, updated_at
                    ) VALUES (
                        'telegram:v3-legacy', 'legacy_v3', ?,
                        'unknown', NULL, NULL, 1, ?, ?
                    )
                    """,
                    (
                        _unique_hash("legacy-v3"),
                        NOW.isoformat(),
                        NOW.isoformat(),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO miniapp_message_claim(
                        subject_id, client_message_id, payload_hash,
                        status, hermes_run_id, hermes_run_session_id,
                        legacy_unreconciled, created_at, updated_at
                    ) VALUES (
                        'telegram:v3-tie', ?, ?, ?, NULL, 'hermes_tie',
                        0, ?, ?
                    )
                    """,
                    (
                        (
                            "tie_a",
                            _unique_hash("tie-a"),
                            "starting",
                            (NOW + timedelta(seconds=5)).isoformat(),
                            (NOW + timedelta(seconds=5)).isoformat(),
                        ),
                        (
                            "tie_z",
                            _unique_hash("tie-z"),
                            "unknown",
                            (NOW + timedelta(seconds=5)).isoformat(),
                            (NOW + timedelta(seconds=6)).isoformat(),
                        ),
                    ),
                )

            repository = SQLiteNodeRepository(path)
            repository.migrate()

            self.assertEqual(repository.schema_version(), 6)
            latest = repository.get_miniapp_active_run_lease("telegram:v3")
            self.assertEqual(
                latest,
                _active_run_lease(
                    subject_id="telegram:v3",
                    client_message_id="accepted_v3",
                    acquired_at=NOW + timedelta(seconds=2),
                    updated_at=NOW + timedelta(seconds=12),
                ),
            )
            self.assertIsNone(
                repository.get_miniapp_active_run_lease(
                    "telegram:v3-legacy"
                )
            )
            self.assertEqual(
                repository.get_miniapp_active_run_lease(
                    "telegram:v3-tie"
                ),
                _active_run_lease(
                    subject_id="telegram:v3-tie",
                    client_message_id="tie_z",
                    acquired_at=NOW + timedelta(seconds=5),
                    updated_at=NOW + timedelta(seconds=6),
                ),
            )
            for index, (
                message_id,
                payload_hash,
                status,
                run_id,
            ) in enumerate(claims):
                with self.subTest(message_id=message_id):
                    claim = repository.get_miniapp_message_claim(
                        "telegram:v3",
                        message_id,
                    )
                    self.assertIsNotNone(claim)
                    assert claim is not None
                    self.assertEqual(claim.payload_hash, payload_hash)
                    self.assertEqual(claim.status, status)
                    self.assertEqual(claim.hermes_run_id, run_id)
                    self.assertEqual(
                        claim.hermes_run_session_id,
                        "hermes_v3",
                    )
                    self.assertFalse(claim.legacy_unreconciled)
                    self.assertEqual(
                        claim.created_at,
                        NOW + timedelta(seconds=index),
                    )
                    self.assertEqual(
                        claim.updated_at,
                        NOW + timedelta(seconds=index + 10),
                    )
            legacy = repository.get_miniapp_message_claim(
                "telegram:v3-legacy",
                "legacy_v3",
            )
            self.assertIsNotNone(legacy)
            assert legacy is not None
            self.assertTrue(legacy.legacy_unreconciled)

            self.assertTrue(
                repository.release_miniapp_active_run_lease(
                    "telegram:v3",
                    "accepted_v3",
                )
            )
            successor = _message_claim(
                subject_id="telegram:v3",
                client_message_id="successor_v4",
                payload_hash=_unique_hash("successor-v4"),
                created_at=NOW + timedelta(seconds=20),
                updated_at=NOW + timedelta(seconds=20),
            )
            self.assertTrue(
                repository.claim_miniapp_message(successor).created
            )
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    {
                        row[0]
                        for row in connection.execute(
                            "SELECT version FROM node_schema_migration"
                        )
                    },
                    {1, 2, 3, 4, 5, 6},
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM miniapp_active_run_lease"
                    ).fetchone()[0],
                    2,
                )


class _MigrationResult:
    rowcount = 0

    def __init__(self, first_row: tuple[int] | None = None) -> None:
        self.first_row = first_row

    def first(self) -> tuple[int] | None:
        return self.first_row


class _MigrationConnection:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()

    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        applied_versions: frozenset[int],
        history_version: int | None,
        meta_version: int | None,
    ) -> None:
        self.events = events
        self.applied_versions = applied_versions
        self.history_version = history_version
        self.meta_version = meta_version

    def execute(
        self,
        statement: Any,
        parameters: dict[str, Any] | None = None,
    ) -> _MigrationResult:
        compiled = statement.compile(dialect=postgresql.dialect())
        rendered = str(compiled)
        self.events.append(
            ("execute", id(self), rendered, parameters, compiled.params)
        )
        if "to_regclass" in rendered:
            return _MigrationResult((1,))
        if (
            "max(version)" in rendered.lower()
            and "node_schema_migration" in rendered
        ):
            return _MigrationResult((self.history_version,))
        if (
            "SELECT value FROM node_meta" in rendered
            and parameters == {"key": "schema_version"}
        ):
            return _MigrationResult(
                (
                    str(self.meta_version)
                    if self.meta_version is not None
                    else None,
                )
            )
        if "SELECT node_schema_migration.version" in rendered:
            requested_versions = {
                value
                for value in compiled.params.values()
                if isinstance(value, int)
            }
            applied = requested_versions & self.applied_versions
            if applied:
                return _MigrationResult((next(iter(applied)),))
        return _MigrationResult()


class _MigrationEngine:
    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        applied_versions: frozenset[int] = frozenset({3}),
        history_version: int | None = 3,
        meta_version: int | None = 3,
    ) -> None:
        self.events = events
        self.connection = _MigrationConnection(
            events,
            applied_versions=applied_versions,
            history_version=history_version,
            meta_version=meta_version,
        )

    @contextmanager
    def begin(self) -> Iterator[_MigrationConnection]:
        self.events.append(("begin", id(self.connection)))
        yield self.connection
        self.events.append(("commit", id(self.connection)))


class PostgresMiniAppMigrationTests(unittest.TestCase):
    def test_future_schema_fails_after_lock_but_before_ddl_or_writes(
        self,
    ) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(
            events,
            history_version=7,
            meta_version=7,
        )
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        with patch.object(postgres_storage.metadata, "create_all") as ddl:
            with self.assertRaises(RuntimeError) as raised:
                repository.migrate()

        self.assertEqual(
            str(raised.exception),
            "storage_schema_newer_than_binary",
        )
        ddl.assert_not_called()
        statements = [
            event[2]
            for event in events
            if event[0] == "execute"
        ]
        self.assertIn("pg_advisory_xact_lock", statements[0])
        self.assertTrue(
            any(
                "max(version)" in statement.lower()
                and "node_schema_migration" in statement
                for statement in statements
            )
        )
        self.assertFalse(
            any(
                keyword in statement.upper()
                for statement in statements
                for keyword in (
                    "ALTER TABLE",
                    "CREATE TABLE",
                    "DROP TABLE",
                    "INSERT INTO",
                    "UPDATE ",
                    "DELETE FROM",
                )
            )
        )

    def test_future_schema_uses_max_of_inconsistent_history_and_meta(
        self,
    ) -> None:
        for history_version, meta_version in ((7, 6), (6, 7)):
            with self.subTest(
                history_version=history_version,
                meta_version=meta_version,
            ):
                events: list[tuple[Any, ...]] = []
                engine = _MigrationEngine(
                    events,
                    history_version=history_version,
                    meta_version=meta_version,
                )
                repository = PostgresNodeRepository(
                    "postgresql+psycopg://unused",
                    engine=engine,  # type: ignore[arg-type]
                )

                with patch.object(
                    postgres_storage.metadata,
                    "create_all",
                ) as ddl:
                    with self.assertRaises(RuntimeError) as raised:
                        repository.migrate()

                self.assertEqual(
                    str(raised.exception),
                    "storage_schema_newer_than_binary",
                )
                ddl.assert_not_called()

    def test_migration_locks_before_ddl_and_uses_atomic_upserts(self) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(events, applied_versions=frozenset({3}))
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        def record_create_all(bind: object) -> None:
            events.append(("ddl", id(bind)))

        with patch.object(
            postgres_storage.metadata,
            "create_all",
            side_effect=record_create_all,
        ):
            repository.migrate()

        self.assertEqual([event[0] for event in events[:2]], ["begin", "execute"])
        self.assertEqual(events[-1][0], "commit")
        self.assertEqual(events[0], ("begin", id(engine.connection)))
        self.assertEqual(events[1][0:2], ("execute", id(engine.connection)))
        self.assertIn("pg_advisory_xact_lock", events[1][2])
        self.assertEqual(
            events[1][3],
            {"lock_id": postgres_storage._MIGRATION_ADVISORY_LOCK_ID},
        )
        ddl_index = next(
            index for index, event in enumerate(events) if event[0] == "ddl"
        )
        self.assertGreater(ddl_index, 1)
        self.assertEqual(events[ddl_index], ("ddl", id(engine.connection)))
        self.assertEqual(events[-1], ("commit", id(engine.connection)))

        writes = [
            event[2]
            for event in events
            if event[0] == "execute"
            and (
                "INSERT INTO node_schema_migration" in event[2]
                or "INSERT INTO node_meta" in event[2]
            )
        ]
        self.assertEqual(len(writes), 3)
        self.assertIn("INSERT INTO node_schema_migration", writes[0])
        self.assertIn("ON CONFLICT", writes[0])
        self.assertIn("INSERT INTO node_schema_migration", writes[1])
        self.assertIn("ON CONFLICT", writes[1])
        self.assertIn("INSERT INTO node_meta", writes[2])
        self.assertIn("ON CONFLICT", writes[2])

    def test_version_three_migration_quarantines_unproven_claims_before_constraint(
        self,
    ) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(events, applied_versions=frozenset())
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        with patch.object(postgres_storage.metadata, "create_all"):
            repository.migrate()

        statements = [
            event[2]
            for event in events
            if event[0] == "execute"
        ]

        def statement_index(*fragments: str) -> int:
            matching = [
                index
                for index, statement in enumerate(statements)
                if all(fragment in statement for fragment in fragments)
            ]
            self.assertTrue(matching, msg=f"missing SQL fragments: {fragments}")
            return matching[0]

        add_session = statement_index(
            "ADD COLUMN IF NOT EXISTS hermes_run_session_id"
        )
        add_legacy = statement_index(
            "ADD COLUMN IF NOT EXISTS legacy_unreconciled"
        )
        quarantine = statement_index(
            "UPDATE miniapp_message_claim",
            "legacy_unreconciled",
            "unknown",
        )
        add_constraint = statement_index(
            "ADD CONSTRAINT ck_miniapp_claim_status_provenance"
        )
        version_write = statement_index("INSERT INTO node_schema_migration")
        self.assertLess(add_session, quarantine)
        self.assertLess(add_legacy, quarantine)
        self.assertLess(quarantine, add_constraint)
        self.assertLess(add_constraint, version_write)

    def test_completed_version_three_skips_claim_table_ddl(self) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(events, applied_versions=frozenset({3}))
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        with patch.object(postgres_storage.metadata, "create_all"):
            repository.migrate()

        statements = [
            event[2]
            for event in events
            if event[0] == "execute"
        ]
        self.assertTrue(
            any(
                "SELECT node_schema_migration.version" in statement
                for statement in statements
            )
        )
        self.assertFalse(
            any(
                "ALTER TABLE miniapp_message_claim" in statement
                for statement in statements
            )
        )

    def test_version_four_leases_latest_claim_without_rewriting_history(
        self,
    ) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(
            events,
            applied_versions=frozenset({3}),
        )
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        with patch.object(postgres_storage.metadata, "create_all"):
            repository.migrate()

        statements = [
            event[2]
            for event in events
            if event[0] == "execute"
        ]
        delete_index = next(
            index
            for index, statement in enumerate(statements)
            if "DELETE FROM miniapp_active_run_lease" in statement
        )
        lease_insert_index = next(
            index
            for index, statement in enumerate(statements)
            if "INSERT INTO miniapp_active_run_lease" in statement
            and "miniapp_message_claim" in statement
        )
        version_four_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "execute"
            and "INSERT INTO node_schema_migration" in event[2]
            and 4 in event[4].values()
        )
        meta_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "execute"
            and "INSERT INTO node_meta" in event[2]
        )
        statement_event_indexes = [
            index for index, event in enumerate(events) if event[0] == "execute"
        ]
        self.assertLess(
            statement_event_indexes[delete_index],
            statement_event_indexes[lease_insert_index],
        )
        self.assertLess(
            statement_event_indexes[lease_insert_index],
            version_four_index,
        )
        self.assertLess(version_four_index, meta_index)
        self.assertFalse(
            any(
                "UPDATE miniapp_message_claim" in statement
                for statement in statements
            )
        )

    def test_completed_version_four_skips_lease_quarantine(self) -> None:
        events: list[tuple[Any, ...]] = []
        engine = _MigrationEngine(
            events,
            applied_versions=frozenset({3, 4}),
            history_version=4,
            meta_version=4,
        )
        repository = PostgresNodeRepository(
            "postgresql+psycopg://unused",
            engine=engine,  # type: ignore[arg-type]
        )

        with patch.object(postgres_storage.metadata, "create_all"):
            repository.migrate()

        statements = [
            event[2]
            for event in events
            if event[0] == "execute"
        ]
        self.assertFalse(
            any(
                "DELETE FROM miniapp_active_run_lease" in statement
                or "INSERT INTO miniapp_active_run_lease" in statement
                or "UPDATE miniapp_message_claim" in statement
                for statement in statements
            )
        )


class SQLiteMiniAppConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "clink.db"
        self.first_repository = SQLiteNodeRepository(self.path)
        self.second_repository = SQLiteNodeRepository(self.path)
        self.first_repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_competing_session_exchanges_have_one_winner(self) -> None:
        barrier = Barrier(2)
        exchange_hash = _unique_hash("competing-exchange")
        candidates = (
            _browser_session(exchange_hash=exchange_hash),
            _browser_session(
                session_id="browser_session_2",
                telegram_user_id="123456789",
                subject_id="telegram:123456789",
                exchange_hash=exchange_hash,
                client_nonce_hash=_hash("0"),
                session_token_hash=_hash("1"),
                csrf_token_hash=_hash("2"),
            ),
        )

        def exchange(
            repository: SQLiteNodeRepository,
            candidate: MiniAppBrowserSession,
        ) -> tuple[str, MiniAppBrowserSession | None]:
            barrier.wait()
            try:
                return "stored", repository.exchange_miniapp_session(candidate)
            except MiniAppStorageConflict:
                return "conflict", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(exchange, self.first_repository, candidates[0]),
                executor.submit(exchange, self.second_repository, candidates[1]),
            )
            outcomes = tuple(future.result() for future in futures)

        self.assertEqual(
            sorted(outcome[0] for outcome in outcomes),
            ["conflict", "stored"],
        )
        winner = next(outcome[1] for outcome in outcomes if outcome[1])
        loser = next(
            candidate
            for candidate in candidates
            if candidate.session_id != winner.session_id
        )
        self.assertEqual(
            self.first_repository.get_miniapp_session(
                winner.session_token_hash,
                NOW + timedelta(seconds=1),
            ),
            winner,
        )
        self.assertIsNone(
            self.first_repository.get_miniapp_session(
                loser.session_token_hash,
                NOW + timedelta(seconds=1),
            )
        )

    def test_competing_terminal_completions_cannot_replace_winner(self) -> None:
        proposed = _message_claim(client_message_id="competing_message")
        self.first_repository.claim_miniapp_message(proposed)
        barrier = Barrier(2)

        def complete(
            repository: SQLiteNodeRepository,
            run_id: str,
        ) -> tuple[str, MiniAppMessageClaim | None]:
            barrier.wait()
            try:
                return (
                    "accepted",
                    repository.complete_miniapp_message(
                        proposed.subject_id,
                        proposed.client_message_id,
                        status="accepted",
                        hermes_run_id=run_id,
                        hermes_run_session_id=(
                            proposed.hermes_run_session_id
                        ),
                        now=NOW + timedelta(seconds=1),
                    ),
                )
            except MiniAppStorageConflict:
                return "conflict", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(complete, self.first_repository, "run_1"),
                executor.submit(complete, self.second_repository, "run_2"),
            )
            outcomes = tuple(future.result() for future in futures)

        self.assertEqual(
            sorted(outcome[0] for outcome in outcomes),
            ["accepted", "conflict"],
        )
        winner = next(outcome[1] for outcome in outcomes if outcome[1])
        replay = self.first_repository.claim_miniapp_message(proposed)
        self.assertFalse(replay.created)
        self.assertEqual(replay.claim, winner)
        with self.assertRaises(MiniAppStorageConflict):
            self.second_repository.complete_miniapp_message(
                proposed.subject_id,
                proposed.client_message_id,
                status="unknown",
                hermes_run_id=None,
                hermes_run_session_id=(
                    proposed.hermes_run_session_id
                ),
                now=NOW + timedelta(seconds=2),
            )

    def test_competing_exact_claims_have_one_atomic_owner(self) -> None:
        proposed = _message_claim(client_message_id="competing_claim")
        barrier = Barrier(2)

        def claim(
            repository: SQLiteNodeRepository,
        ) -> MiniAppMessageClaimResult:
            barrier.wait()
            return repository.claim_miniapp_message(proposed)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(claim, self.first_repository),
                executor.submit(claim, self.second_repository),
            )
            results = tuple(future.result() for future in futures)

        self.assertEqual(
            sorted(result.created for result in results),
            [False, True],
        )
        self.assertEqual(
            tuple(result.claim for result in results),
            (proposed, proposed),
        )
        self.assertEqual(
            self.first_repository.get_miniapp_active_run_lease(
                proposed.subject_id
            ),
            _active_run_lease(
                subject_id=proposed.subject_id,
                client_message_id=proposed.client_message_id,
                acquired_at=proposed.created_at,
                updated_at=proposed.updated_at,
            ),
        )

    def test_competing_different_clients_share_one_subject_lease(self) -> None:
        candidates = (
            _message_claim(
                client_message_id="competing_a",
                payload_hash=_hash("a"),
            ),
            _message_claim(
                client_message_id="competing_b",
                payload_hash=_hash("b"),
            ),
        )
        barrier = Barrier(2)

        def claim(
            repository: SQLiteNodeRepository,
            candidate: MiniAppMessageClaim,
        ) -> tuple[str, MiniAppMessageClaim | None]:
            barrier.wait()
            try:
                result = repository.claim_miniapp_message(candidate)
                return "created", result.claim
            except MiniAppStorageConflict:
                return "conflict", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(claim, self.first_repository, candidates[0]),
                executor.submit(claim, self.second_repository, candidates[1]),
            )
            outcomes = tuple(future.result() for future in futures)

        self.assertEqual(
            sorted(outcome[0] for outcome in outcomes),
            ["conflict", "created"],
        )
        winner = next(outcome[1] for outcome in outcomes if outcome[1])
        assert winner is not None
        loser = next(
            candidate
            for candidate in candidates
            if candidate.client_message_id != winner.client_message_id
        )
        self.assertEqual(
            self.first_repository.get_miniapp_active_run_lease(
                winner.subject_id
            ),
            _active_run_lease(
                subject_id=winner.subject_id,
                client_message_id=winner.client_message_id,
                acquired_at=winner.created_at,
                updated_at=winner.updated_at,
            ),
        )
        self.assertIsNone(
            self.first_repository.get_miniapp_message_claim(
                loser.subject_id,
                loser.client_message_id,
            )
        )


if __name__ == "__main__":
    unittest.main()
