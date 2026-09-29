from __future__ import annotations

import os
import inspect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression

from models import (
    EnrollmentTokenRecord,
    HostedRotationRecord,
    NodeRegistration,
    PreflightRecord,
)
from repository import (
    ControlPlaneBase,
    InMemoryRepository,
    PostgresRepository,
    PreflightRow,
    RepositoryConflict,
    digest_secret,
    enrollment_binding_digest,
)
from replay import RedisReplayCoordinator, ReplayUnavailable
from shared.hosted_facilitator_protocol import DeviceSigningKey


NOW = 2_000_000_000


def token_record(token: str = "enrollment-secret") -> EnrollmentTokenRecord:
    return EnrollmentTokenRecord(
        tenant_id="tenant_1",
        token_digest=digest_secret(token),
        expires_at=NOW + 300,
    )


def node(token: str = "access-secret", *, epoch: int = 1) -> NodeRegistration:
    key = DeviceSigningKey.generate()
    return NodeRegistration(
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        device_public_jwk=key.public_jwk,
        device_key_id=key.thumbprint,
        access_token_digest=digest_secret(token),
        credential_epoch=epoch,
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def rotation(
    current: NodeRegistration,
    *,
    rotation_id: str = "rotation_1",
    token: str = "rotated-access-secret",
    prepared_at: int = NOW,
) -> HostedRotationRecord:
    key = DeviceSigningKey.generate()
    return HostedRotationRecord(
        rotation_id=rotation_id,
        tenant_id=current.tenant_id,
        node_id=current.node_id,
        wallet_binding_id=current.wallet_binding_id,
        expected_epoch=current.credential_epoch,
        next_epoch=current.credential_epoch + 1,
        pending_public_jwk=key.public_jwk,
        pending_device_key_id=key.thumbprint,
        pending_access_token_digest=digest_secret(token),
        status="prepared",
        prepared_at=prepared_at,
    )


def preflight(**overrides: object) -> PreflightRecord:
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "request_id": "request_1",
        "idempotency_key": "idempotency_1",
        "request_nonce": "0x" + "01" * 32,
        "capability_hash": "0x" + "02" * 32,
        "reservation_id": "reservation_1",
        "request_hash": "0x" + "03" * 32,
        "signed_response_jws": "signed-response",
        "created_at": NOW,
    }
    values.update(overrides)
    return PreflightRecord(**values)


class _FakeResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeNestedTransaction:
    def __init__(self, session) -> None:
        self.session = session

    def __enter__(self):
        if self.session._outer_failed or self.session._nested_depth != 0:
            raise AssertionError("nested transaction cannot start")
        self.session._nested_depth = 1
        self.session.nested_started = True
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if exc_type is not None:
            self.session.nested_rolled_back = True
            self.session.added.clear()
        self.session._nested_depth = 0
        return False


class _FakeSession:
    def __init__(self, collision_row: PreflightRow) -> None:
        self.collision_row = collision_row
        self.added = []
        self.flush_calls = 0
        self.nested_started = False
        self.nested_rolled_back = False
        self.idempotency_queries: list[dict[str, object]] = []
        self.locked_idempotency_queries = 0
        self.queries_after_savepoint = 0
        self._collision_committed = False
        self._nested_depth = 0
        self._outer_failed = False

    def execute(self, statement):
        if self._outer_failed:
            raise AssertionError("outer transaction was not recovered")
        predicates = _statement_predicates(statement)
        expected_keys = {"tenant_id", "node_id", "idempotency_key"}
        if set(predicates) == expected_keys:
            self.idempotency_queries.append(predicates)
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                self.locked_idempotency_queries += 1
            if self.nested_rolled_back:
                self.queries_after_savepoint += 1
                row_scope = {
                    "tenant_id": self.collision_row.tenant_id,
                    "node_id": self.collision_row.node_id,
                    "idempotency_key": self.collision_row.idempotency_key,
                }
                if self._collision_committed and predicates == row_scope:
                    return _FakeResult(self.collision_row)
        return _FakeResult(None)

    def add(self, row) -> None:
        if self._nested_depth != 1:
            self._outer_failed = True
            raise AssertionError("insert must be enclosed by a savepoint")
        self.added.append(row)

    def flush(self) -> None:
        self.flush_calls += 1
        if self._nested_depth != 1:
            self._outer_failed = True
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))
        if len(self.added) != 1:
            raise AssertionError("expected one pending preflight row")
        self._collision_committed = True
        raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    def begin_nested(self):
        return _FakeNestedTransaction(self)


def _statement_predicates(statement) -> dict[str, object]:
    predicates: dict[str, object] = {}
    for item in visitors.iterate(statement):
        if not isinstance(item, BinaryExpression) or item.operator is not operators.eq:
            continue
        column_name = getattr(item.left, "key", None)
        if column_name in {"tenant_id", "node_id", "idempotency_key"}:
            predicates[column_name] = item.right.value
    return predicates


class _FakeSessionTransaction:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.committed = False

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        self.committed = exc_type is None
        return False


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.transaction = None

    def begin(self):
        self.transaction = _FakeSessionTransaction(self.session)
        return self.transaction


def stored_preflight_row(record: PreflightRecord) -> PreflightRow:
    return PreflightRow(
        record_id="preflight_stored",
        tenant_id=record.tenant_id,
        node_id=record.node_id,
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        request_nonce=record.request_nonce,
        capability_hash=record.capability_hash,
        reservation_id=record.reservation_id,
        request_hash=record.request_hash,
        signed_response_jws="stored-signed-response",
        created_at=record.created_at,
    )


def test_postgres_metadata_declares_control_plane_tables_and_constraints() -> None:
    names = set(ControlPlaneBase.metadata.tables)
    assert {
        "hosted_tenants",
        "hosted_enrollment_tokens",
        "hosted_node_registrations",
        "hosted_dpop_replays",
        "hosted_preflight_records",
    } <= names

    ddl = "\n".join(
        str(
            CreateTable(ControlPlaneBase.metadata.tables[name]).compile(
                dialect=postgresql.dialect()
            )
        )
        for name in names
    )
    assert "UNIQUE" in ddl
    assert "token_digest" in ddl
    assert "access_token_digest" in ddl
    assert "request_nonce" in ddl
    assert "idempotency_key" in ddl
    assert "hosted_node_rotations" in names
    assert "pending_public_jwk" in ddl
    assert "pending_access_token_digest" in ddl
    assert "revocation_id" in ddl
    assert "enrollment_binding_digest" in ddl
    assert "uq_hosted_enrollment_node_binding" in ddl
    assert "uq_hosted_node_revocation_id" in ddl
    assert "uq_hosted_rotation_node_expected_epoch" in ddl
    assert "uq_hosted_rotation_pending_access_digest" in ddl
    assert "ck_hosted_rotation_commit_timestamp" in ddl
    rotations = ControlPlaneBase.metadata.tables["hosted_node_rotations"]
    assert any(
        index.name == "ix_hosted_node_rotations_scope_status"
        and tuple(column.name for column in index.columns)
        == ("tenant_id", "node_id", "status")
        for index in rotations.indexes
    )


def test_postgres_exact_collision_returns_stored_response_and_commits_outer_transaction() -> None:
    incoming = preflight(signed_response_jws="new-signed-response")
    stored = stored_preflight_row(incoming)
    session = _FakeSession(stored)
    sessions = _FakeSessionFactory(session)
    repository = object.__new__(PostgresRepository)
    repository.sessions = sessions

    result = repository.bind_preflight(incoming)

    assert result.signed_response_jws == "stored-signed-response"
    assert session.flush_calls == 1
    assert session.nested_started is True
    assert session.nested_rolled_back is True
    assert session.added == []
    assert sessions.transaction is not None
    assert sessions.transaction.committed is True
    assert session.idempotency_queries == [
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
    ]
    assert session.locked_idempotency_queries == 1
    assert session.queries_after_savepoint == 1


def test_postgres_collision_with_changed_hash_conflicts_after_savepoint_rollback() -> None:
    incoming = preflight(signed_response_jws="new-signed-response")
    stored = stored_preflight_row(incoming)
    stored.request_hash = "0x" + "04" * 32
    session = _FakeSession(stored)
    sessions = _FakeSessionFactory(session)
    repository = object.__new__(PostgresRepository)
    repository.sessions = sessions

    with pytest.raises(RepositoryConflict, match="idempotency"):
        repository.bind_preflight(incoming)

    assert session.flush_calls == 1
    assert session.nested_started is True
    assert session.nested_rolled_back is True
    assert session.added == []
    assert sessions.transaction is not None
    assert sessions.transaction.committed is False
    assert session.idempotency_queries == [
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
    ]
    assert session.locked_idempotency_queries == 1
    assert session.queries_after_savepoint == 1


def test_postgres_collision_does_not_return_existing_row_from_another_scope() -> None:
    incoming = preflight()
    stored = stored_preflight_row(preflight(tenant_id="tenant_2", node_id="node_2"))
    session = _FakeSession(stored)
    sessions = _FakeSessionFactory(session)
    repository = object.__new__(PostgresRepository)
    repository.sessions = sessions

    with pytest.raises(RepositoryConflict, match="uniqueness"):
        repository.bind_preflight(incoming)

    assert session.added == []
    assert session.nested_rolled_back is True
    assert sessions.transaction is not None
    assert sessions.transaction.committed is False
    assert session.idempotency_queries == [
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
        {
            "tenant_id": incoming.tenant_id,
            "node_id": incoming.node_id,
            "idempotency_key": incoming.idempotency_key,
        },
    ]
    assert session.locked_idempotency_queries == 1
    assert session.queries_after_savepoint == 1


def test_postgres_concurrent_exact_retry_returns_committed_response_when_configured() -> (
    None
):
    postgres_url = os.getenv("TEST_HOSTED_FACILITATOR_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_HOSTED_FACILITATOR_POSTGRES_URL is not configured")

    schema = f"hosted_facilitator_{uuid4().hex}"
    admin_engine = create_engine(postgres_url)
    repositories: list[PostgresRepository] = []
    listeners = []
    initial_selects = Barrier(2)
    incoming = preflight()

    def scoped_url() -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )

    def pause_until_both_initial_selects(
        connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = statement.lower()
        if (
            "from hosted_preflight_records" in normalized
            and "idempotency_key" in normalized
            and "for update" not in normalized
            and not connection.info.get("hosted_initial_select_seen")
        ):
            connection.info["hosted_initial_select_seen"] = True
            initial_selects.wait(timeout=15)

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        repositories = [
            PostgresRepository(scoped_url()),
            PostgresRepository(scoped_url()),
        ]
        ControlPlaneBase.metadata.create_all(repositories[0].engine)
        for repository in repositories:
            event.listen(
                repository.engine,
                "before_cursor_execute",
                pause_until_both_initial_selects,
            )
            listeners.append(repository.engine)

        def bind(repository: PostgresRepository) -> PreflightRecord:
            return repository.bind_preflight(incoming)

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(bind, repositories))

        assert results == [incoming, incoming]
        changed = replace(incoming, request_hash="0x" + "04" * 32)
        with pytest.raises(RepositoryConflict, match="idempotency"):
            repositories[0].bind_preflight(changed)
    finally:
        for engine in listeners:
            event.remove(
                engine, "before_cursor_execute", pause_until_both_initial_selects
            )
        for repository in repositories:
            repository.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_enrollment_token_is_digest_only_and_consumed_once() -> None:
    repo = InMemoryRepository()
    repo.put_enrollment_token(token_record())

    stored = repo.get_enrollment_token(digest_secret("enrollment-secret"))
    assert stored is not None
    assert stored.token_digest == digest_secret("enrollment-secret")
    assert "enrollment-secret" not in repr(stored)

    consumed = repo.consume_enrollment_token(
        digest_secret("enrollment-secret"), now=NOW
    )
    assert consumed is not None
    assert repo.consume_enrollment_token(digest_secret("enrollment-secret"), now=NOW) is None


def test_enrollment_token_expiry_and_concurrent_consumption_are_fail_closed() -> None:
    repo = InMemoryRepository()
    repo.put_enrollment_token(token_record("race-secret"))

    with pytest.raises(RepositoryConflict, match="expired"):
        expired = EnrollmentTokenRecord(
            tenant_id="tenant_1",
            token_digest=digest_secret("expired-secret"),
            expires_at=NOW,
        )
        repo.put_enrollment_token(expired)
        repo.consume_enrollment_token(digest_secret("expired-secret"), now=NOW)

    def consume() -> bool:
        return repo.consume_enrollment_token(
            digest_secret("race-secret"), now=NOW
        ) is not None

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: consume(), range(8)))
    assert sum(results) == 1


def test_node_rotation_retires_old_token_and_revoke_is_irreversible() -> None:
    repo = InMemoryRepository()
    first = node()
    repo.put_node(first)

    rotated = node("new-access-secret", epoch=2)
    repo.rotate_node(
        tenant_id="tenant_1",
        node_id="node_1",
        expected_epoch=1,
        replacement=rotated,
    )
    assert repo.get_node_by_access_digest(first.access_token_digest) is None
    assert repo.get_node_by_access_digest(rotated.access_token_digest) == rotated

    revoked = repo.revoke_node(
        tenant_id="tenant_1", node_id="node_1", expected_epoch=2
    )
    assert revoked.status == "revoked"
    assert repo.get_node_by_access_digest(rotated.access_token_digest) is None
    with pytest.raises(RepositoryConflict, match="revoked"):
        repo.rotate_node(
            tenant_id="tenant_1",
            node_id="node_1",
            expected_epoch=3,
            replacement=node("third-secret", epoch=4),
        )


def test_enrollment_replay_binds_one_node_even_after_consumption_and_expiry() -> None:
    repo = InMemoryRepository()
    token = "replay-enrollment-secret"
    repo.put_enrollment_token(
        EnrollmentTokenRecord(
            tenant_id="tenant_1",
            token_digest=digest_secret(token),
            expires_at=NOW + 1,
        )
    )
    first = node("enrollment-access")
    enrolled = repo.enroll_node(
        digest_secret(token), first, now=NOW, binding_digest=enrollment_binding_digest(first)
    )

    stored_token = repo.get_enrollment_token(digest_secret(token))
    assert stored_token is not None
    assert stored_token.enrolled_node_id == enrolled.node_id
    assert stored_token.enrollment_binding_digest == enrollment_binding_digest(first)

    # A response-loss retry can have a newly generated server-side node id, but
    # must carry exactly the same client credential binding and return the
    # original registration even after the invite's nominal expiry.
    retry = replace(first, node_id="node_retry", created_at=NOW + 1, updated_at=NOW + 1)
    assert repo.enroll_node(
        digest_secret(token), retry, now=NOW + 2,
        binding_digest=enrollment_binding_digest(retry),
    ) == enrolled

    with pytest.raises(RepositoryConflict, match="binding"):
        repo.enroll_node(
            digest_secret(token),
            replace(retry, wallet_binding_id="binding_changed"),
            now=NOW + 2,
            binding_digest=enrollment_binding_digest(
                replace(retry, wallet_binding_id="binding_changed")
            ),
        )


def test_enrollment_binding_node_id_is_unique_across_invites() -> None:
    repo = InMemoryRepository()
    bound = EnrollmentTokenRecord(
        tenant_id="tenant_1",
        token_digest=digest_secret("bound-enrollment-1"),
        expires_at=NOW + 300,
        consumed_at=NOW,
        enrolled_node_id="node_1",
        enrollment_binding_digest=b"\x01" * 32,
    )
    repo.put_enrollment_token(bound)

    with pytest.raises(RepositoryConflict, match="enrollment"):
        repo.put_enrollment_token(
            replace(
                bound,
                token_digest=digest_secret("bound-enrollment-2"),
            )
        )


def test_concurrent_exact_enrollment_retries_return_the_same_registration() -> None:
    repo = InMemoryRepository()
    token = "concurrent-enrollment-secret"
    repo.put_enrollment_token(
        EnrollmentTokenRecord(
            tenant_id="tenant_1",
            token_digest=digest_secret(token),
            expires_at=NOW + 300,
        )
    )
    incoming = node("concurrent-access")

    def enroll_once(_: int) -> NodeRegistration:
        return repo.enroll_node(
            digest_secret(token), incoming, now=NOW,
            binding_digest=enrollment_binding_digest(incoming),
        )

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(enroll_once, range(8)))
    assert {result.node_id for result in results} == {incoming.node_id}
    assert repo.get_node("tenant_1", incoming.node_id) == incoming


def test_staged_rotation_is_exactly_idempotent_and_hides_pending_credential() -> None:
    repo = InMemoryRepository()
    current = node()
    repo.put_node(current)
    pending = rotation(current)

    with pytest.raises(RepositoryConflict, match="status"):
        repo.prepare_rotation(replace(pending, status="cancelled"))
    assert repo.prepare_rotation(pending) == pending
    assert repo.prepare_rotation(pending) == pending
    assert (
        repo.get_pending_rotation_by_access_digest(
            pending.pending_access_token_digest,
            tenant_id=current.tenant_id,
            node_id=current.node_id,
        )
        == pending
    )
    assert repo.get_node_by_access_digest(pending.pending_access_token_digest) is None

    changed = replace(
        pending,
        pending_access_token_digest=digest_secret("different-pending-access"),
    )
    with pytest.raises(RepositoryConflict, match="rotation"):
        repo.prepare_rotation(changed)

    other = rotation(current, rotation_id="rotation_2", token="other-pending-access")
    with pytest.raises(RepositoryConflict, match="rotation"):
        repo.prepare_rotation(other)

    committed = repo.commit_rotation(
        rotation_id=pending.rotation_id,
        tenant_id=pending.tenant_id,
        node_id=pending.node_id,
        expected_epoch=pending.expected_epoch,
        pending_access_token_digest=pending.pending_access_token_digest,
        now=NOW + 1,
    )
    assert committed.credential_epoch == 2
    assert committed.device_public_jwk == pending.pending_public_jwk
    assert committed.device_key_id == pending.pending_device_key_id
    assert committed.access_token_digest == pending.pending_access_token_digest
    assert repo.get_node_by_access_digest(current.access_token_digest) is None
    assert repo.get_node_by_access_digest(pending.pending_access_token_digest) == committed
    assert (
        repo.get_pending_rotation_by_access_digest(
            pending.pending_access_token_digest,
            tenant_id=current.tenant_id,
            node_id=current.node_id,
        )
        is None
    )
    assert repo.commit_rotation(
        rotation_id=pending.rotation_id,
        tenant_id=pending.tenant_id,
        node_id=pending.node_id,
        expected_epoch=pending.expected_epoch,
        pending_access_token_digest=pending.pending_access_token_digest,
        now=NOW + 2,
    ) == committed


def test_prepare_rotation_exact_retry_ignores_service_timestamps_but_rejects_mutation() -> None:
    repo = InMemoryRepository()
    current = node()
    repo.put_node(current)
    pending = rotation(current)
    first = repo.prepare_rotation(pending)

    # A retry may be reconstructed after the process clock advanced.  These
    # timestamps are service metadata, not part of the client request binding.
    retry = replace(pending, prepared_at=NOW + 99)
    assert repo.prepare_rotation(retry) == first

    changed = replace(
        retry,
        expected_epoch=2,
        next_epoch=3,
    )
    with pytest.raises(RepositoryConflict, match="rotation"):
        repo.prepare_rotation(changed)


def _sqlite_backed_postgres_repository() -> PostgresRepository:
    engine = create_engine("sqlite://")
    ControlPlaneBase.metadata.create_all(engine)
    repository = object.__new__(PostgresRepository)
    repository.engine = engine
    repository.sessions = sessionmaker(engine, expire_on_commit=False)
    return repository


def test_postgres_prepare_rotation_exact_retry_returns_persisted_record() -> None:
    repo = _sqlite_backed_postgres_repository()
    current = node()
    repo.put_node(current)
    pending = rotation(current)
    first = repo.prepare_rotation(pending)

    retry = replace(pending, prepared_at=NOW + 99)
    assert repo.prepare_rotation(retry) == first

    changed = replace(
        retry,
        expected_epoch=2,
        next_epoch=3,
    )
    with pytest.raises(RepositoryConflict, match="rotation"):
        repo.prepare_rotation(changed)


def test_postgres_commit_locks_node_before_rotation() -> None:
    source = inspect.getsource(PostgresRepository.commit_rotation)
    assert source.index("select(NodeRegistrationRow)") < source.index(
        "select(HostedRotationRow)"
    )


def test_committed_rotation_replay_rejects_current_credential_drift() -> None:
    repo = InMemoryRepository()
    current = node()
    repo.put_node(current)
    pending = rotation(current)
    repo.prepare_rotation(pending)
    committed = repo.commit_rotation(
        rotation_id=pending.rotation_id,
        tenant_id=pending.tenant_id,
        node_id=pending.node_id,
        expected_epoch=pending.expected_epoch,
        pending_access_token_digest=pending.pending_access_token_digest,
        now=NOW + 1,
    )

    drifted = node("drifted-access", epoch=committed.credential_epoch)
    repo._nodes[(committed.tenant_id, committed.node_id)] = replace(
        drifted,
        wallet_binding_id=committed.wallet_binding_id,
        updated_at=committed.updated_at,
    )
    with pytest.raises(RepositoryConflict, match="rotation state"):
        repo.commit_rotation(
            rotation_id=pending.rotation_id,
            tenant_id=pending.tenant_id,
            node_id=pending.node_id,
            expected_epoch=pending.expected_epoch,
            pending_access_token_digest=pending.pending_access_token_digest,
            now=NOW + 2,
        )


def test_revocation_is_exactly_idempotent_and_has_narrow_revoked_lookup() -> None:
    repo = InMemoryRepository()
    current = node()
    repo.put_node(current)

    revoked = repo.revoke_node(
        tenant_id=current.tenant_id,
        node_id=current.node_id,
        expected_epoch=current.credential_epoch,
        revocation_id="revocation_1",
    )
    assert revoked.status == "revoked"
    assert revoked.revocation_id == "revocation_1"
    assert repo.get_node_by_access_digest(current.access_token_digest) is None
    assert (
        repo.get_revoked_node_by_access_digest(
            current.access_token_digest,
            tenant_id=current.tenant_id,
            node_id=current.node_id,
            revocation_id="revocation_1",
            expected_epoch=current.credential_epoch,
        )
        == revoked
    )
    assert repo.revoke_node(
        tenant_id=current.tenant_id,
        node_id=current.node_id,
        expected_epoch=current.credential_epoch,
        revocation_id="revocation_1",
    ) == revoked
    with pytest.raises(RepositoryConflict, match="revocation"):
        repo.revoke_node(
            tenant_id=current.tenant_id,
            node_id=current.node_id,
            expected_epoch=current.credential_epoch,
            revocation_id="revocation_other",
        )


def test_revocation_id_cannot_be_reused_by_another_node() -> None:
    repo = InMemoryRepository()
    first = node("first-access")
    second = replace(node("second-access"), node_id="node_2")
    repo.put_node(first)
    repo.put_node(second)

    repo.revoke_node(
        tenant_id=first.tenant_id,
        node_id=first.node_id,
        expected_epoch=first.credential_epoch,
        revocation_id="revocation_shared",
    )
    with pytest.raises(RepositoryConflict, match="revocation"):
        repo.revoke_node(
            tenant_id=second.tenant_id,
            node_id=second.node_id,
            expected_epoch=second.credential_epoch,
            revocation_id="revocation_shared",
        )


def test_dpop_jti_and_preflight_bindings_are_scoped_and_exactly_idempotent() -> None:
    repo = InMemoryRepository()
    registration = node()
    repo.put_node(registration)

    assert repo.consume_dpop_jti(
        tenant_id="tenant_1",
        node_id="node_1",
        credential_epoch=1,
        jti="jti-1",
        expires_at=NOW + 60,
        now=NOW,
    )
    assert not repo.consume_dpop_jti(
        tenant_id="tenant_1",
        node_id="node_1",
        credential_epoch=1,
        jti="jti-1",
        expires_at=NOW + 60,
        now=NOW,
    )
    assert repo.consume_dpop_jti(
        tenant_id="tenant_2",
        node_id="node_1",
        credential_epoch=1,
        jti="jti-1",
        expires_at=NOW + 60,
        now=NOW,
    )

    first = preflight()
    assert repo.bind_preflight(first) == first
    assert repo.bind_preflight(first) == first
    with pytest.raises(RepositoryConflict, match="idempotency"):
        repo.bind_preflight(preflight(request_hash="0x" + "04" * 32))
    with pytest.raises(RepositoryConflict, match="request nonce"):
        repo.bind_preflight(
            preflight(
                idempotency_key="idempotency_2",
                request_id="request_2",
            )
        )


def test_redis_replay_keys_hash_scope_components_without_delimiter_aliases() -> None:
    class Client:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def set(self, key, value, *, nx, ex):
            self.keys.append(key)
            return True

    client = Client()
    replay = RedisReplayCoordinator("redis://localhost/0", client=client)
    assert replay.consume_dpop_jti(
        tenant_id="a:b",
        node_id="c",
        credential_epoch=1,
        jti="same-jti",
        ttl_seconds=60,
    )
    assert replay.consume_dpop_jti(
        tenant_id="a",
        node_id="b:c",
        credential_epoch=1,
        jti="same-jti",
        ttl_seconds=60,
    )
    assert client.keys[0] != client.keys[1]


def test_redis_replay_invalid_set_response_fails_closed() -> None:
    class Client:
        def set(self, key, value, *, nx, ex):
            return "unexpected"

    replay = RedisReplayCoordinator("redis://localhost/0", client=Client())
    with pytest.raises(ReplayUnavailable):
        replay.consume_dpop_jti(
            tenant_id="tenant_1",
            node_id="node_1",
            credential_epoch=1,
            jti="jti-1",
            ttl_seconds=60,
        )
