from __future__ import annotations

import hashlib
import os
from io import StringIO
from pathlib import Path
from runpy import run_path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
import pytest


_MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations"
_MIGRATION_POSTGRES_URL_ENV = "TEST_HOSTED_MIGRATION_POSTGRES_URL"
_ORIGINAL_MULTICHAIN_SHA256 = (
    "78ba225767a6251288c47412f58c35d700e1e272359208c32e563523a777c8b7"
)
_FINALITY_CONSTRAINT = "ck_hosted_execution_terminal_finality_evidence"


def test_hosted_alembic_configuration_discovers_existing_revision_chain() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260901_0008"]
    assert script.get_revision("20260825_0002").down_revision == "20260825_0001"
    assert script.get_revision("20260825_0003").down_revision == "20260825_0002"
    assert script.get_revision("20260827_0004").down_revision == "20260825_0003"
    assert script.get_revision("20260827_0005").down_revision == "20260827_0004"
    assert script.get_revision("20260827_0006").down_revision == "20260827_0005"
    assert script.get_revision("20260827_0007").down_revision == "20260827_0006"
    assert script.get_revision("20260901_0008").down_revision == "20260827_0007"


def test_original_multichain_migration_is_immutable() -> None:
    source = _MIGRATIONS_DIR / "20260827_0004_hosted_multichain.py"

    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        _ORIGINAL_MULTICHAIN_SHA256
    )


def _require_migration_postgres_url() -> str:
    database_url = os.getenv(_MIGRATION_POSTGRES_URL_ENV)
    if not database_url:
        pytest.skip(
            f"{_MIGRATION_POSTGRES_URL_ENV} is not configured; "
            "live migration tests require an explicit test PostgreSQL URL"
        )
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        pytest.fail(
            f"{_MIGRATION_POSTGRES_URL_ENV} must be a PostgreSQL SQLAlchemy URL"
        )
    return database_url


def _scoped_migration_url(database_url: str, schema: str) -> str:
    return (
        make_url(database_url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )


def _with_migration_schema(database_url: str, callback) -> None:
    schema = f"hosted_migration_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = create_engine(_scoped_migration_url(database_url, schema))
        try:
            callback(scoped_engine, schema)
        finally:
            scoped_engine.dispose()
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _run_migration(scoped_engine, target: str, *, direction: str = "upgrade") -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    with scoped_engine.connect() as connection:
        config.attributes["connection"] = connection
        if direction == "upgrade":
            command.upgrade(config, target)
        elif direction == "downgrade":
            command.downgrade(config, target)
        else:  # pragma: no cover - test helper misuse
            raise ValueError(f"unsupported migration direction: {direction}")
        connection.commit()


def _seed_terminal_execution(
    scoped_engine,
    execution_id: str,
    *,
    chain: str = "eip155:8453",
    confirmations: int = 2,
    finality_boundary: str | None = None,
    safe_block_number: int | None = 123,
    safe_block_hash: str | None = "0x" + "11" * 32,
) -> None:
    hashes = {
        "capability_hash": "0x" + "22" * 32,
        "reservation_hash": "0x" + "33" * 32,
        "execution_scope_hash": "0x" + "44" * 32,
        "execution_digest": "0x" + "55" * 32,
        "canonical_hash": "0x" + "66" * 32,
    }
    with scoped_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO hosted_executions ("
                "execution_id, tenant_id, node_id, wallet_binding_id, capability_id, "
                "reservation_id, purchase_id, idempotency_key, chain, owner, payee, "
                "token, amount_atomic, executor, signer_epoch, owner_nonce, deadline, "
                "capability_hash, reservation_hash, execution_scope_hash, execution_digest, "
                "canonical_payload, canonical_hash, relayer_address, relayer_nonce, status, "
                "confirmations, safe_block_number, safe_block_hash, finality_boundary, "
                "created_at, updated_at) VALUES ("
                ":execution_id, 'tenant_1', 'node_1', 'binding_1', :capability_id, "
                ":reservation_id, :purchase_id, :idempotency_key, :chain, "
                "'0x" + "aa" * 20 + "', '0x" + "bb" * 20 + "', '0x" + "cc" * 20 + "', "
                "'1', '0x" + "dd" * 20 + "', 1, :owner_nonce, 2000000000, "
                ":capability_hash, :reservation_hash, :execution_scope_hash, :execution_digest, "
                "'{}'::json, :canonical_hash, '0x" + "ee" * 20 + "', :relayer_nonce, "
                "'finalized', :confirmations, :safe_block_number, :safe_block_hash, "
                ":finality_boundary, 2000000000, 2000000001)"
            ),
            {
                "execution_id": execution_id,
                "capability_id": f"cap_{execution_id}",
                "reservation_id": f"reservation_{execution_id}",
                "purchase_id": f"purchase_{execution_id}",
                "idempotency_key": f"idempotency_{execution_id}",
                "chain": chain,
                "owner_nonce": execution_id,
                "relayer_nonce": 1,
                "confirmations": confirmations,
                "safe_block_number": safe_block_number,
                "safe_block_hash": safe_block_hash,
                "finality_boundary": finality_boundary,
                **hashes,
            },
        )


def _constraint_info(connection) -> tuple[str, bool]:
    row = connection.execute(
        text(
            "SELECT pg_get_constraintdef(constraint_oid), convalidated "
            "FROM ("
            "SELECT c.oid AS constraint_oid, c.convalidated "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = current_schema() "
            "AND t.relname = 'hosted_executions' "
            "AND c.conname = 'ck_hosted_execution_terminal_finality_evidence'"
            ") constraints"
        )
    ).one()
    return str(row[0]), bool(row[1])


def _migration_version(connection) -> str:
    return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def test_postgres_finality_compensation_backfills_inferable_base_row() -> None:
    database_url = _require_migration_postgres_url()

    def exercise(scoped_engine, _schema: str) -> None:
        _run_migration(scoped_engine, "20260827_0007")
        _seed_terminal_execution(scoped_engine, "exec_inferable")

        _run_migration(scoped_engine, "20260901_0008")

        with scoped_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT finality_boundary FROM hosted_executions "
                    "WHERE execution_id = 'exec_inferable'"
                )
            ).scalar_one()
            constraint, validated = _constraint_info(connection)
            assert row == "safe"
            assert _migration_version(connection) == "20260901_0008"
            assert "finality_boundary IS NOT NULL" in constraint
            assert validated is True

    _with_migration_schema(database_url, exercise)


def test_postgres_finality_upgrade_guard_rolls_back_to_0007() -> None:
    database_url = _require_migration_postgres_url()

    def exercise(scoped_engine, _schema: str) -> None:
        _run_migration(scoped_engine, "20260827_0007")
        _seed_terminal_execution(
            scoped_engine,
            "exec_unrecoverable",
            chain="eip155:137",
            confirmations=3,
        )

        with pytest.raises(Exception, match="cannot upgrade hosted finality evidence"):
            _run_migration(scoped_engine, "20260901_0008")

        with scoped_engine.connect() as connection:
            constraint, validated = _constraint_info(connection)
            assert _migration_version(connection) == "20260827_0007"
            assert "finality_boundary IS NOT NULL" not in constraint
            assert validated is True
            assert connection.execute(
                text(
                    "SELECT finality_boundary, safe_block_number, safe_block_hash "
                    "FROM hosted_executions WHERE execution_id = 'exec_unrecoverable'"
                )
            ).one() == (None, 123, "0x" + "11" * 32)

    _with_migration_schema(database_url, exercise)


def test_postgres_finality_downgrade_guard_preserves_strict_constraint() -> None:
    database_url = _require_migration_postgres_url()

    def exercise(scoped_engine, _schema: str) -> None:
        _run_migration(scoped_engine, "20260827_0007")
        _seed_terminal_execution(
            scoped_engine,
            "exec_drift",
            finality_boundary="safe",
        )
        _run_migration(scoped_engine, "20260901_0008")

        strict_expression = run_path(
            str(_MIGRATIONS_DIR / "20260901_0008_hosted_finality_compensation.py")
        )["_TERMINAL_FINALITY"]
        with scoped_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE hosted_executions DROP CONSTRAINT "
                    "ck_hosted_execution_terminal_finality_evidence"
                )
            )
            connection.execute(
                text(
                    "UPDATE hosted_executions SET finality_boundary = NULL, "
                    "safe_block_number = NULL, safe_block_hash = NULL "
                    "WHERE execution_id = 'exec_drift'"
                )
            )
            connection.exec_driver_sql(
                "ALTER TABLE hosted_executions ADD CONSTRAINT "
                "ck_hosted_execution_terminal_finality_evidence CHECK ("
                f"{strict_expression}) NOT VALID"
            )

        with pytest.raises(Exception, match="cannot downgrade hosted finality evidence"):
            _run_migration(
                scoped_engine,
                "20260827_0007",
                direction="downgrade",
            )

        with scoped_engine.connect() as connection:
            constraint, validated = _constraint_info(connection)
            assert _migration_version(connection) == "20260901_0008"
            assert "finality_boundary IS NOT NULL" in constraint
            assert validated is False

    _with_migration_schema(database_url, exercise)


def _render_multichain_migration(direction: str) -> str:
    namespace = run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "20260827_0004_hosted_multichain.py"
        )
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = namespace[direction]
    migration.__globals__["op"] = Operations(context)
    migration()
    return output.getvalue()


def test_original_multichain_upgrade_has_no_late_compensation_logic() -> None:
    sql = _render_multichain_migration("upgrade")

    assert "UPDATE hosted_executions" not in sql
    assert "finality_boundary IS NOT NULL" not in sql
    assert "ADD CONSTRAINT ck_hosted_execution_terminal_finality_evidence" in sql


def _render_finality_compensation_migration(direction: str) -> str:
    namespace = run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "20260901_0008_hosted_finality_compensation.py"
        )
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = namespace[direction]
    migration.__globals__["op"] = Operations(context)
    migration()
    return output.getvalue()


def test_finality_compensation_repairs_an_already_applied_original_0004() -> None:
    sql = _render_finality_compensation_migration("upgrade")

    drop = sql.index("DROP CONSTRAINT ck_hosted_execution_terminal_finality_evidence")
    backfill = sql.index("UPDATE hosted_executions")
    guard = sql.index("cannot upgrade hosted finality evidence with unrecoverable rows")
    constraint = sql.index(
        "ADD CONSTRAINT ck_hosted_execution_terminal_finality_evidence"
    )
    assert drop < backfill < guard < constraint
    assert "SET finality_boundary = 'safe'" in sql
    assert "chain = 'eip155:8453'" in sql
    assert "status IN ('confirmed', 'finalized', 'reverted', 'reorg_review')" in sql
    assert "finality_boundary IS NULL" in sql
    assert "safe_block_number IS NOT NULL" in sql
    assert "safe_block_hash IS NOT NULL" in sql
    assert "finality_boundary IS NOT NULL" in sql


def test_finality_compensation_downgrade_fails_closed_before_weakening_constraint() -> None:
    sql = _render_finality_compensation_migration("downgrade")

    guard = sql.index("cannot downgrade hosted finality evidence with invalid rows")
    first_ddl = sql.index("DROP CONSTRAINT")
    assert guard < first_ddl
    assert "status IN ('confirmed', 'finalized', 'reverted', 'reorg_review')" in sql[:first_ddl]
    assert "safe_block_number IS NOT NULL" in sql[:first_ddl]
    assert "safe_block_hash IS NOT NULL" in sql[:first_ddl]
    assert "ADD CONSTRAINT ck_hosted_execution_terminal_finality_evidence" in sql


def _render_enrollment_lifecycle_migration(direction: str) -> str:
    namespace = run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "20260827_0005_hosted_enrollment_lifecycle.py"
        )
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = namespace[direction]
    migration.__globals__["op"] = Operations(context)
    migration()
    return output.getvalue()


def test_enrollment_lifecycle_upgrade_declares_binding_rotation_and_revocation_contract() -> None:
    sql = _render_enrollment_lifecycle_migration("upgrade")

    assert "ADD COLUMN enrolled_node_id" in sql
    assert "ADD COLUMN enrollment_binding_digest" in sql
    assert "ck_hosted_enrollment_binding" in sql
    assert "uq_hosted_enrollment_node_binding" in sql
    assert "ADD COLUMN revocation_id" in sql
    assert "CREATE TABLE hosted_node_rotations" in sql
    assert "uq_hosted_rotation_node_expected_epoch" in sql
    assert "uq_hosted_rotation_pending_access_digest" in sql
    assert "next_epoch = expected_epoch + 1" in sql
    assert "status IN ('prepared', 'committed', 'cancelled')" in sql
    assert "ck_hosted_rotation_commit_timestamp" in sql
    assert "CREATE INDEX ix_hosted_node_rotations_scope_status" in sql
    assert "(tenant_id, node_id, status)" in sql


def test_enrollment_lifecycle_downgrade_removes_new_contract() -> None:
    sql = _render_enrollment_lifecycle_migration("downgrade")

    assert "DROP TABLE hosted_node_rotations" in sql
    assert "DROP COLUMN revocation_id" in sql
    assert "DROP CONSTRAINT uq_hosted_enrollment_node_binding" in sql
    assert "DROP COLUMN enrollment_binding_digest" in sql
    assert "DROP COLUMN enrolled_node_id" in sql


def _render_pilot_gate_migration(direction: str) -> str:
    namespace = run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "20260827_0006_hosted_pilot_gate.py"
        )
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = namespace[direction]
    migration.__globals__["op"] = Operations(context)
    migration()
    return output.getvalue()


def test_pilot_gate_upgrade_declares_scopes_reservations_and_audit_events() -> None:
    sql = _render_pilot_gate_migration("upgrade")

    assert "CREATE TABLE hosted_gate_controls" in sql
    assert "scope_type" in sql
    assert "PRIMARY KEY (scope_type, tenant_id, node_id)" in sql
    assert "scope_type IN ('platform', 'tenant', 'node')" in sql
    assert "CREATE TABLE hosted_gate_reservations" in sql
    assert "FOREIGN KEY(execution_id)" in sql
    assert "state IN ('reserved', 'settled', 'released')" in sql
    assert "gas_cost_usd_micros BIGINT DEFAULT 0 NOT NULL" in sql
    assert "gas_utc_day INTEGER" in sql
    assert "ck_hosted_gate_reservation_gas_day" in sql
    assert "CREATE TABLE hosted_gate_events" in sql
    assert "event_id" in sql
    assert "event_type IN ('allowed', 'denied', 'gas_reserved', 'settled', 'released', 'pause_changed')" in sql
    assert "ix_hosted_gate_reservations_tenant_node_day_state" in sql
    assert "ix_hosted_gate_reservations_platform_day_state" in sql
    assert "ix_hosted_gate_events_execution_created" in sql
    assert "ix_hosted_gate_events_tenant_node_created" in sql
    assert sql.index("INSERT INTO hosted_gate_reservations") > sql.index(
        "CREATE TABLE hosted_gate_reservations"
    )


def test_pilot_gate_downgrade_removes_indexes_before_tables() -> None:
    sql = _render_pilot_gate_migration("downgrade")

    assert sql.index("DROP INDEX ix_hosted_gate_events_tenant_node_created") < sql.index(
        "DROP TABLE hosted_gate_events"
    )
    assert sql.index("DROP INDEX ix_hosted_gate_reservations_platform_day_state") < sql.index(
        "DROP TABLE hosted_gate_reservations"
    )
    assert "DROP TABLE hosted_gate_controls" in sql


def test_pilot_gate_upgrade_and_downgrade_are_sqlite_compatible() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE hosted_executions ("
                "execution_id VARCHAR(96) PRIMARY KEY, "
                "tenant_id VARCHAR(256) NOT NULL, "
                "node_id VARCHAR(256) NOT NULL, "
                "idempotency_key VARCHAR(256) NOT NULL, "
                "status VARCHAR(32) NOT NULL, "
                "created_at BIGINT NOT NULL, "
                "updated_at BIGINT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO hosted_executions "
                "(execution_id, tenant_id, node_id, idempotency_key, status, created_at, updated_at) "
                "VALUES "
                "('exec_reserved', 'tenant_1', 'node_1', 'idem_1', 'signed', 172801, 172802), "
                "('exec_settled', 'tenant_1', 'node_1', 'idem_2', 'finalized', 172801, 172803), "
                "('exec_released', 'tenant_1', 'node_1', 'idem_3', 'released', 172801, 172804)"
            )
        )
        namespace = run_path(
            str(
                Path(__file__).parents[1]
                / "migrations"
                / "20260827_0006_hosted_pilot_gate.py"
            )
        )
        operations = Operations(MigrationContext.configure(connection))
        namespace["upgrade"].__globals__["op"] = operations
        namespace["upgrade"]()

        assert {
            "hosted_gate_controls",
            "hosted_gate_reservations",
            "hosted_gate_events",
        }.issubset(set(inspect(connection).get_table_names()))
        rows = connection.execute(
            text(
                "SELECT execution_id, utc_day, state, gas_cost_usd_micros, gas_utc_day "
                "FROM hosted_gate_reservations ORDER BY execution_id"
            )
        ).all()
        assert rows == [
            ("exec_released", 2, "released", 0, None),
            ("exec_reserved", 2, "reserved", 0, None),
            ("exec_settled", 2, "settled", 0, None),
        ]
        controls = connection.execute(
            text(
                "SELECT scope_type, tenant_id, node_id, paused, reason_code "
                "FROM hosted_gate_controls"
            )
        ).all()
        assert controls == [
            ("platform", "", "", True, "migration_review_required")
        ]
        pause_events = connection.execute(
            text(
                "SELECT event_type, reason_code FROM hosted_gate_events "
                "WHERE execution_id IS NULL"
            )
        ).all()
        assert pause_events == [
            ("pause_changed", "migration_review_required")
        ]

        namespace["downgrade"].__globals__["op"] = operations
        namespace["downgrade"]()
        assert not {
            "hosted_gate_controls",
            "hosted_gate_reservations",
            "hosted_gate_events",
        }.intersection(set(inspect(connection).get_table_names()))


def _render_signing_claim_migration(direction: str) -> str:
    namespace = run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "20260827_0007_hosted_signing_claims.py"
        )
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = namespace[direction]
    migration.__globals__["op"] = Operations(context)
    migration()
    return output.getvalue()


def test_signing_claim_upgrade_adds_fencing_and_recyclable_nonce_contract() -> None:
    sql = _render_signing_claim_migration("upgrade")

    assert "ADD COLUMN signing_claim_generation" in sql
    assert "ADD COLUMN signing_claim_expires_at" in sql
    assert "status = 'signing'" in sql
    assert "signing_claim_generation = 1" in sql
    assert "signing_claim_expires_at = LEAST(deadline, updated_at + 15)" in sql
    assert "DROP CONSTRAINT uq_hosted_execution_chain_relayer_nonce" in sql
    assert "CREATE UNIQUE INDEX uq_hosted_execution_active_chain_relayer_nonce" in sql
    assert "WHERE status NOT IN ('expired', 'released')" in sql


def test_signing_claim_downgrade_guards_reused_nonce_before_restoring_constraint() -> None:
    sql = _render_signing_claim_migration("downgrade")

    guard = sql.index("cannot downgrade hosted signing claims with recycled nonces")
    drop_index = sql.index("DROP INDEX uq_hosted_execution_active_chain_relayer_nonce")
    assert guard < drop_index
    assert "ADD CONSTRAINT uq_hosted_execution_chain_relayer_nonce" in sql
    assert "DROP COLUMN signing_claim_expires_at" in sql
    assert "DROP COLUMN signing_claim_generation" in sql
