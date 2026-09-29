from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from clink_node.agent_access import (
    AgentAccessConflictError,
    AgentAccessNotFoundError,
    AgentAccessService,
    AgentAccessUnauthorizedError,
)
from clink_node.storage.agent_access import AgentAccessRepository
from clink_node.storage.postgres import PostgresNodeRepository
from clink_node.storage.sqlite import SQLiteNodeRepository


def _service(path, *, issuer="issuer-a", key=b"k" * 32, now=None):
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    clock = now if now is not None else [datetime(2026, 9, 3, tzinfo=UTC)]
    service = AgentAccessService(
        AgentAccessRepository(engine),
        issuer=issuer,
        token_key=key,
        clock=lambda: clock[0],
    )
    return service, engine, clock


def test_revoked_runtime_cannot_reissue_but_replay_and_new_runtime_cas_work(
    tmp_path,
):
    path = tmp_path / "node.sqlite3"
    SQLiteNodeRepository(path).migrate()
    service, engine, clock = _service(path)
    try:
        binding = service.register(
            subject_id="subject-a",
            external_agent_id="agent-a",
        )
        first = service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
            request_id="request-a",
        )
        renewed = service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
            request_id="request-a-renewal",
            replaces_credential_id=first.credential_id,
        )

        service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
        )
        with pytest.raises(AgentAccessConflictError):
            service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
                request_id="request-a-after-stop",
                replaces_credential_id=renewed.credential_id,
            )

        replay = service.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
            request_id="request-a-renewal",
            replaces_credential_id=first.credential_id,
        )
        assert replay.access_token == renewed.access_token
        assert replay.expires_at == renewed.expires_at
        with pytest.raises(AgentAccessUnauthorizedError):
            service.authenticate(replay.access_token)

        restarted = AgentAccessService(
            AgentAccessRepository(
                create_engine(
                    f"sqlite+pysqlite:///{path}",
                    connect_args={"check_same_thread": False},
                )
            ),
            issuer="issuer-a",
            token_key=b"k" * 32,
            clock=lambda: clock[0],
        )
        with pytest.raises(AgentAccessConflictError):
            restarted.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
                request_id="request-a-after-reopen",
                replaces_credential_id=renewed.credential_id,
            )

        fresh = restarted.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-c",
            request_id="request-c",
            replaces_credential_id=renewed.credential_id,
        )
        restarted.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
        )
        assert restarted.authenticate(fresh.access_token).runtime_id == "runtime-c"
    finally:
        engine.dispose()


def test_revoke_before_issue_and_cross_agent_issuer_isolation(tmp_path):
    path = tmp_path / "node.sqlite3"
    SQLiteNodeRepository(path).migrate()
    service, engine, _ = _service(path)
    other, other_engine, _ = _service(
        path,
        issuer="issuer-b",
        key=b"o" * 32,
    )
    try:
        binding = service.register(
            subject_id="subject-a",
            external_agent_id="agent-a",
        )
        other_binding = service.register(
            subject_id="subject-b",
            external_agent_id="agent-b",
        )

        service.revoke_runtime(
            agent_id=binding.agent_id,
            runtime_id="runtime-stopped-before-issue",
        )
        with pytest.raises(AgentAccessConflictError):
            service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-stopped-before-issue",
                request_id="delayed-request",
            )

        other_agent_credential = service.issue_credential(
            agent_id=other_binding.agent_id,
            runtime_id="runtime-stopped-before-issue",
            request_id="other-agent-request",
        )
        assert other_agent_credential.runtime_id == "runtime-stopped-before-issue"

        with pytest.raises(AgentAccessNotFoundError):
            other.revoke_runtime(
                agent_id=binding.agent_id,
                runtime_id="runtime-stopped-before-issue",
            )
        assert service.authenticate(other_agent_credential.access_token).agent_id == other_binding.agent_id
    finally:
        engine.dispose()
        other_engine.dispose()


def test_issue_and_revoke_with_independent_sqlite_connections_leave_no_active_credential(
    tmp_path,
):
    path = tmp_path / "node.sqlite3"
    SQLiteNodeRepository(path).migrate()
    setup, setup_engine, clock = _service(path)
    binding = setup.register(subject_id="subject-a", external_agent_id="agent-a")
    first = setup.issue_credential(
        agent_id=binding.agent_id,
        runtime_id="runtime-a",
        request_id="request-a",
    )
    barrier = threading.Barrier(2)

    def issue():
        service, engine, _ = _service(path, now=clock)
        try:
            barrier.wait(timeout=10)
            return service.issue_credential(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
                request_id="race-issue",
                replaces_credential_id=first.credential_id,
            )
        except AgentAccessConflictError:
            return None
        finally:
            engine.dispose()

    def revoke():
        service, engine, _ = _service(path, now=clock)
        try:
            barrier.wait(timeout=10)
            service.revoke_runtime(
                agent_id=binding.agent_id,
                runtime_id="runtime-a",
            )
            return True
        finally:
            engine.dispose()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            issued, revoked = executor.map(lambda fn: fn(), (issue, revoke))
        assert revoked is True

        verifier, verifier_engine, _ = _service(path, now=clock)
        try:
            status = verifier.get_runtime_status(binding.agent_id)
            assert status["runtime"]["status"] == "revoked"
            if issued is not None:
                with pytest.raises(AgentAccessUnauthorizedError):
                    verifier.authenticate(issued.access_token)
        finally:
            verifier_engine.dispose()
    finally:
        setup_engine.dispose()


POSTGRES_URL_ENV = "CLINK_NODE_AGENT_ACCESS_POSTGRES_URL"


@pytest.fixture
def postgres_agent_access_repository():
    url = os.getenv(POSTGRES_URL_ENV)
    if not url:
        pytest.skip(f"set {POSTGRES_URL_ENV} for PostgreSQL integration tests")

    admin_engine = create_engine(url, pool_pre_ping=True)
    schema_name = f"clink_agent_access_{uuid.uuid4().hex}"
    quoted_schema = '"' + schema_name.replace('"', '""') + '"'
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
        schema_created = True
        engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema_name}"},
        )
        repository = PostgresNodeRepository(url, engine=engine)
        repository.migrate()
        yield repository, schema_name
    finally:
        if "engine" in locals():
            engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        admin_engine.dispose()


def test_postgresql_runtime_tombstone_migration_is_repeatable_and_race_safe(
    postgres_agent_access_repository,
):
    repository, schema_name = postgres_agent_access_repository
    assert repository.schema_version() == 6

    clock = [datetime(2026, 9, 3, tzinfo=UTC)]
    service = AgentAccessService(
        AgentAccessRepository(repository.engine),
        issuer="issuer-a",
        token_key=b"k" * 32,
        clock=lambda: clock[0],
    )
    binding = service.register(
        subject_id="postgres-subject",
        external_agent_id="postgres-agent",
    )
    first = service.issue_credential(
        agent_id=binding.agent_id,
        runtime_id="runtime-a",
        request_id="request-a",
    )

    with repository.engine.begin() as connection:
        connection.execute(text("DROP TABLE agent_runtime_revocation"))
        connection.execute(
            text(
                "DELETE FROM node_schema_migration WHERE version = 6"
            )
        )
        connection.execute(
            text(
                "UPDATE node_meta SET value = '5' "
                "WHERE key = 'schema_version'"
            )
        )
        connection.execute(
            text(
                "UPDATE agent_runtime_credential SET revoked_at = :revoked_at "
                "WHERE credential_id = :credential_id"
            ),
            {"revoked_at": clock[0], "credential_id": first.credential_id},
        )

    repository.migrate()
    with repository.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT agent_id, runtime_id FROM agent_runtime_revocation"
            )
        ).one() == (binding.agent_id, "runtime-a")
    repository.migrate()
    with repository.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM agent_runtime_revocation"
            )
        ).scalar_one() == 1

    restarted = AgentAccessService(
        AgentAccessRepository(repository.engine),
        issuer="issuer-a",
        token_key=b"k" * 32,
        clock=lambda: clock[0],
    )
    with pytest.raises(AgentAccessConflictError):
        restarted.issue_credential(
            agent_id=binding.agent_id,
            runtime_id="runtime-a",
            request_id="request-a-after-migration",
            replaces_credential_id=first.credential_id,
        )

    fresh = restarted.issue_credential(
        agent_id=binding.agent_id,
        runtime_id="runtime-b",
        request_id="request-b",
        replaces_credential_id=first.credential_id,
    )
    barrier = threading.Barrier(2)

    def issue_refresh():
        engine = create_engine(
            repository.url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema_name}"},
        )
        try:
            access = AgentAccessService(
                AgentAccessRepository(engine),
                issuer="issuer-a",
                token_key=b"k" * 32,
                clock=lambda: clock[0],
            )
            barrier.wait(timeout=10)
            try:
                return access.issue_credential(
                    agent_id=binding.agent_id,
                    runtime_id="runtime-b",
                    request_id="race-refresh",
                    replaces_credential_id=fresh.credential_id,
                )
            except AgentAccessConflictError:
                return None
        finally:
            engine.dispose()

    def revoke():
        engine = create_engine(
            repository.url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema_name}"},
        )
        try:
            access = AgentAccessService(
                AgentAccessRepository(engine),
                issuer="issuer-a",
                token_key=b"k" * 32,
                clock=lambda: clock[0],
            )
            barrier.wait(timeout=10)
            access.revoke_runtime(
                agent_id=binding.agent_id,
                runtime_id="runtime-b",
            )
            return True
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        raced, revoked = executor.map(
            lambda operation: operation(),
            (issue_refresh, revoke),
        )
    assert revoked is True
    if raced is not None:
        with pytest.raises(AgentAccessUnauthorizedError):
            restarted.authenticate(raced.access_token)
    assert restarted.get_runtime_status(binding.agent_id)["runtime"]["status"] == "revoked"
