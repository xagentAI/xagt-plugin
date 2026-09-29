from __future__ import annotations

import json

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import scripts.check_runtime_schema as runtime_schema
from scripts.check_runtime_schema import check_runtime_schema


def test_runtime_schema_check_uses_node_managed_version_table(
    tmp_path,
    monkeypatch,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'managed.sqlite3'}"
    monkeypatch.setenv("CLINK_NODE_MANAGED", "1")
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    assert check_runtime_schema(database_url) == []


def test_runtime_schema_check_rejects_partial_head_schema(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    assert check_runtime_schema(database_url) == []

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE asset_allowances"))

    problems = check_runtime_schema(database_url)
    assert problems == ["missing required table: asset_allowances"]


def test_runtime_schema_check_requires_payment_capability_table_and_columns(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'capability-schema.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    schema = inspect(engine)
    columns = {
        column["name"]
        for column in schema.get_columns("funding_payment_capabilities")
    }
    assert {
        "capability_id",
        "capability_version",
        "capability_hash",
        "reservation_id",
        "idempotency_key",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "wallet_identity_id",
        "canonical_payload",
        "issued_at",
        "expires_at",
        "created_at",
    } <= columns
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE funding_payment_capabilities"))

    problems = check_runtime_schema(database_url)
    assert problems[0] == "missing required table: funding_payment_capabilities"


def test_runtime_schema_check_rejects_payment_capability_without_integrity_constraints(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'capability-constraints.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE funding_payment_capabilities"))
        connection.execute(
            text(
                """
                CREATE TABLE funding_payment_capabilities (
                    capability_id VARCHAR(96) NOT NULL,
                    capability_version VARCHAR(64) NOT NULL,
                    capability_hash VARCHAR(66) NOT NULL,
                    reservation_id VARCHAR(96) NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    tenant_id VARCHAR(256) NOT NULL,
                    node_id VARCHAR(256) NOT NULL,
                    wallet_binding_id VARCHAR(256) NOT NULL,
                    wallet_identity_id VARCHAR(96) NOT NULL,
                    canonical_payload JSON NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )

    assert set(check_runtime_schema(database_url)) == {
        "missing required primary key: funding_payment_capabilities.capability_id",
        "missing required check constraint: funding_payment_capabilities.ck_payment_capability_hash_canonical",
        "missing required check constraint: funding_payment_capabilities.ck_payment_capability_lifetime",
        "missing required check constraint: funding_payment_capabilities.ck_payment_capability_version",
        "missing required unique constraint: funding_payment_capabilities.uq_payment_capability_hash",
        "missing required unique constraint: funding_payment_capabilities.uq_payment_capability_idempotency",
        "missing required unique constraint: funding_payment_capabilities.uq_payment_capability_reservation",
    }


def test_payment_capability_migration_downgrade_removes_dedicated_table(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'capability-downgrade.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "20260725_0017")

    assert "funding_payment_capabilities" not in inspect(
        create_engine(database_url)
    ).get_table_names()


def test_runtime_schema_check_requires_wallet_bootstrap_state(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE account_wallet_bootstrap_states"))

    assert check_runtime_schema(database_url) == [
        "missing required table: account_wallet_bootstrap_states",
        "missing required column: "
        "account_wallet_bootstrap_states.binding_generation",
        "missing required column: "
        "account_wallet_bootstrap_states.binding_state",
        "missing required column: account_wallet_bootstrap_states.unbound_at",
        "missing required check constraint: "
        "account_wallet_bootstrap_states."
        "ck_account_wallet_bootstrap_binding_state",
        "missing required check constraint: "
        "account_wallet_bootstrap_states."
        "ck_account_wallet_bootstrap_unbound_at",
    ]


def test_runtime_schema_check_requires_wallet_rebind_generation_state(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    assert runtime_schema.REQUIRED_COLUMNS[
        "account_wallet_bootstrap_states"
    ] == {
        "binding_state",
        "binding_generation",
        "unbound_at",
    }
    assert runtime_schema.REQUIRED_CHECK_CONSTRAINTS[
        "account_wallet_bootstrap_states"
    ] == {
        "ck_account_wallet_bootstrap_binding_state",
        "ck_account_wallet_bootstrap_unbound_at",
    }
    assert runtime_schema.REQUIRED_INDEXES["wallet_identities"] == {
        "uq_wallet_identity_open_scope",
        "uq_wallet_identity_open_user",
    }

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_wallet_identity_open_scope"))

    assert check_runtime_schema(database_url) == [
        "missing required index: "
        "wallet_identities.uq_wallet_identity_open_scope"
    ]


def test_runtime_schema_check_requires_wallet_challenge_creator_browser_session(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    columns = {
        column["name"] for column in inspect(engine).get_columns("account_sessions")
    }
    assert "created_by_public_account_session_id" in columns
    assert runtime_schema.REQUIRED_COLUMNS["account_sessions"] == {
        "created_by_public_account_session_id"
    }

    command.downgrade(config, "20260716_0011")

    problems = check_runtime_schema(database_url)
    assert problems[0] == (
        "migration revision is not at head "
        "(current=['20260716_0011'], expected=['20260916_0022'])"
    )
    assert "missing required column: account_sessions.created_by_public_account_session_id" in problems
    assert "missing required table: action_approvals" in problems
    assert "missing required table: action_intents" in problems
    assert "missing required table: policy_decisions" in problems


def test_runtime_schema_check_requires_agent_spending_mandate_state(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    schema = inspect(engine)
    assert runtime_schema.REQUIRED_COLUMNS["spending_grants"] == {
        "hourly_limit_usdc",
        "merchant_trust_scopes",
        "notification_mode",
    }
    assert runtime_schema.REQUIRED_INDEXES["spending_grant_rolling_usage"] == {
        "ix_spending_grant_rolling_usage_spending_grant_id",
        "ix_spending_grant_rolling_usage_state",
        "ix_spending_grant_rolling_usage_occurred_at",
        "ix_grant_rolling_usage_window",
    }
    assert "spending_grant_rolling_usage" in schema.get_table_names()

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE spending_grant_rolling_usage"))

    assert check_runtime_schema(database_url) == [
        "missing required table: spending_grant_rolling_usage",
        "missing required index: spending_grant_rolling_usage.ix_grant_rolling_usage_window",
        "missing required index: spending_grant_rolling_usage.ix_spending_grant_rolling_usage_occurred_at",
        "missing required index: spending_grant_rolling_usage.ix_spending_grant_rolling_usage_spending_grant_id",
        "missing required index: spending_grant_rolling_usage.ix_spending_grant_rolling_usage_state",
        "missing required foreign key: spending_grant_rolling_usage.spending_grant_id->spending_grants",
    ]


def test_runtime_schema_check_requires_action_policy_constraints_and_indexes(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    schema = inspect(engine)
    assert runtime_schema.REQUIRED_CHECK_CONSTRAINTS["account_sessions"] == {
        "ck_wallet_challenge_creating_public_session"
    }
    for table, required in runtime_schema.REQUIRED_CHECK_CONSTRAINTS.items():
        names = {constraint["name"] for constraint in schema.get_check_constraints(table)}
        assert required <= names
    for table, required in runtime_schema.REQUIRED_INDEXES.items():
        names = {index["name"] for index in schema.get_indexes(table)}
        assert required <= names
    assert runtime_schema.REQUIRED_UNIQUE_CONSTRAINTS["funding_payment_capabilities"] == {
        "uq_payment_capability_hash",
        "uq_payment_capability_reservation",
        "uq_payment_capability_idempotency",
    }
    assert runtime_schema.REQUIRED_PRIMARY_KEYS["funding_payment_capabilities"] == {
        "capability_id"
    }


def test_fresh_action_policy_migration_round_trip_restores_runtime_schema(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'round-trip.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.downgrade(config, "20260716_0013")
    schema = inspect(create_engine(database_url))
    assert schema.has_table("action_intents") is False
    assert schema.has_table("action_approvals") is False
    assert schema.has_table("policy_decisions") is False

    command.upgrade(config, "head")
    assert check_runtime_schema(database_url) == []


def test_fresh_migration_seeds_exactly_one_global_funding_lock(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'fresh.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        lock_ids = connection.execute(
            text("SELECT lock_id FROM funding_locks ORDER BY lock_id")
        ).scalars().all()
    assert lock_ids == [1]


def test_fresh_migration_adds_durable_per_network_relayer_nonce_allocator(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nonces.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "20260715_0005")
    engine = create_engine(database_url)
    assert inspect(engine).has_table("funding_relayer_nonces") is False

    command.upgrade(config, "head")

    schema = inspect(engine)
    columns = {
        column["name"]: column for column in schema.get_columns("funding_relayer_nonces")
    }
    primary_key = schema.get_pk_constraint("funding_relayer_nonces")
    assert set(columns) == {
        "network",
        "relayer_address",
        "next_nonce",
        "updated_at",
    }
    assert primary_key["constrained_columns"] == ["network", "relayer_address"]
    assert columns["next_nonce"]["nullable"] is False


def test_fresh_migration_persists_nullable_receipt_token_address(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'receipt-token.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    columns = {
        column["name"]: column
        for column in inspect(create_engine(database_url)).get_columns(
            "funding_ledger_records"
        )
    }
    assert columns["token_address"]["nullable"] is True


def test_security_migration_adds_audit_idempotency_and_scrubs_signed_transactions(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'security-wave.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260716_0010")
    engine = create_engine(database_url)
    raw_transaction = "0x" + "ab" * 100
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO funding_ledger_records "
                "(record_id, record_type, payload, updated_at) "
                "VALUES (:record_id, 'reservation', :payload, CURRENT_TIMESTAMP)"
            ),
            {
                "record_id": "reserve_legacy_signed",
                "payload": json.dumps(
                    {
                        "reservation_id": "reserve_legacy_signed",
                        "settlement_raw_transaction": raw_transaction,
                        "tx_hash": "0x" + "1" * 64,
                    }
                ),
            },
        )

    command.upgrade(config, "head")

    audit_columns = {
        column["name"]
        for column in inspect(engine).get_columns("audit_events")
    }
    with engine.connect() as connection:
        payload = connection.execute(
            text(
                "SELECT payload FROM funding_ledger_records "
                "WHERE record_id = 'reserve_legacy_signed'"
            )
        ).scalar_one()
    assert "idempotency_key" in audit_columns
    assert "settlement_raw_transaction" not in json.loads(payload)
    assert raw_transaction not in payload
