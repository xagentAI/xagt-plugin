from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import importlib
from pathlib import Path
import sqlite3
from threading import Barrier
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError

from services.account_service import (
    AccountRepository,
    AssetAllowance,
    SpendingGrant,
    WalletIdentity,
)
from services.account_service.repository import SpendingGrantRow
from services.account_service.schemas import MAX_UINT256


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
WALLET = "0x" + "Ab" * 20
TOKEN = "0x" + "Cd" * 20
SPENDER = "0x" + "Ef" * 20


def wallet_identity(
    wallet_identity_id: str = "wallet_1",
    user_id: str = "u",
    status: str = "active",
) -> WalletIdentity:
    return WalletIdentity(
        wallet_identity_id=wallet_identity_id,
        user_id=user_id,
        wallet_address=WALLET,
        status=status,
        proof_hash="proof",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def asset_allowance(
    wallet_identity_id: str, allowance_id: str = "allowance_1", network: str = "eip155:137"
) -> AssetAllowance:
    return AssetAllowance(
        asset_allowance_id=allowance_id,
        wallet_identity_id=wallet_identity_id,
        network=network,
        token_address=TOKEN,
        token_symbol="USDC",
        token_decimals=6,
        spender_address=SPENDER,
        approved_amount_atomic=1_000_000,
        observed_allowance_atomic=900_000,
        allowance_tx_hash="0x" + "12" * 32,
        status="active",
        confirmed_block=123,
        last_chain_check_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def spending_grant(
    wallet_identity_id: str,
    product_scopes: list[str] | None = None,
    spending_grant_id: str = "grant_1",
    status: str = "active",
    status_reason: str | None = None,
    updated_at: datetime = NOW,
) -> SpendingGrant:
    return SpendingGrant(
        spending_grant_id=spending_grant_id,
        wallet_identity_id=wallet_identity_id,
        user_id="u",
        agent_id="hermes",
        status=status,
        status_reason=status_reason,
        max_amount_usdc=Decimal("12.345678"),
        per_transaction_limit_usdc=Decimal("2.000001"),
        daily_limit_usdc=Decimal("5.000001"),
        product_scopes=product_scopes if product_scopes is not None else ["prediction_markets", "marketplace"],
        network_scopes=["eip155:137", "eip155:8453"],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
        updated_at=updated_at,
    )


def test_wallet_identity_and_allowance_uniqueness(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()

    repo.save_wallet_identity(identity)

    assert identity.wallet_address == WALLET.lower()
    assert repo.active_wallet_identities("u") == [identity]

    allowance = asset_allowance(identity.wallet_identity_id)
    repo.save_asset_allowance(allowance)

    assert allowance.token_address == TOKEN.lower()
    assert allowance.spender_address == SPENDER.lower()
    assert repo.asset_allowances(identity.wallet_identity_id) == [allowance]
    with pytest.raises(ValueError, match="asset allowance already exists"):
        repo.save_asset_allowance(
            asset_allowance(identity.wallet_identity_id, allowance_id="other")
        )


def test_sqlite_round_trips_max_uint256_allowance_as_exact_text(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'uint256.db'}")
    identity = wallet_identity()
    allowance = asset_allowance(identity.wallet_identity_id).model_copy(
        update={
            "approved_amount_atomic": MAX_UINT256,
            "observed_allowance_atomic": MAX_UINT256,
        }
    )
    repo.save_wallet_identity(identity)

    repo.save_asset_allowance(allowance)

    assert repo.asset_allowances(identity.wallet_identity_id) == [allowance]
    with repo.engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT approved_amount_atomic, observed_allowance_atomic FROM asset_allowances"
        ).one()
        storage_types = connection.exec_driver_sql(
            "SELECT typeof(approved_amount_atomic), typeof(observed_allowance_atomic) "
            "FROM asset_allowances"
        ).one()
    assert stored == (str(MAX_UINT256), str(MAX_UINT256))
    assert storage_types == ("text", "text")


def test_active_spending_grants_round_trip_decimal_and_utc_timestamps(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()
    grant = spending_grant(identity.wallet_identity_id)

    repo.save_wallet_identity(identity)
    repo.save_spending_grant(grant)

    assert repo.active_spending_grants("u", at=NOW) == [grant]


def test_active_grant_requires_an_active_matching_wallet_identity(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity(status="revoked")
    repo.save_wallet_identity(identity)

    with pytest.raises(ValueError, match="wallet identity is not active"):
        repo.save_spending_grant(spending_grant(identity.wallet_identity_id))


def test_revoke_then_active_grant_creation_cannot_restore_spending(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()
    repo.save_wallet_identity(identity)
    repo.revoke_wallet_identity_and_pause_active_grants(identity.wallet_identity_id, NOW)

    with pytest.raises(ValueError, match="wallet identity is not active"):
        repo.save_spending_grant(spending_grant(identity.wallet_identity_id))


def test_disconnect_wallet_identity_atomically_revokes_all_open_grants(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'disconnect.db'}")
    selected = wallet_identity("wallet_selected")
    other = wallet_identity("wallet_other", user_id="other_user").model_copy(
        update={"wallet_address": "0x" + "12" * 20}
    )
    repo.save_wallet_identity(selected)
    repo.save_wallet_identity(other)
    selected_grants = [
        spending_grant(
            selected.wallet_identity_id,
            spending_grant_id=f"grant_{status}",
            status=status,
            status_reason="user_paused" if status == "paused" else None,
        )
        for status in ("active", "pending", "paused", "revoked")
    ]
    for item in selected_grants:
        repo.save_spending_grant(item)
    other_grant = spending_grant(
        other.wallet_identity_id,
        spending_grant_id="grant_other",
    ).model_copy(update={"user_id": other.user_id})
    repo.save_spending_grant(other_grant)

    disconnected = repo.disconnect_wallet_identity(
        selected.wallet_identity_id, NOW
    )
    repeated = repo.disconnect_wallet_identity(selected.wallet_identity_id, NOW)

    assert disconnected.status == repeated.status == "revoked"
    for status in ("active", "pending", "paused"):
        stored = repo.spending_grant(f"grant_{status}")
        assert stored.status == "revoked"
        assert stored.status_reason == "wallet_identity_disconnected"
    assert repo.spending_grant("grant_revoked").status == "revoked"
    assert repo.spending_grant("grant_other").status == "active"
    assert repo.wallet_identity(other.wallet_identity_id).status == "active"


def test_active_grant_create_and_revoke_competition_never_leaves_active_grant(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()
    grant = spending_grant(identity.wallet_identity_id)
    repo.save_wallet_identity(identity)

    outcomes = _concurrent_outcomes(
        lambda: repo.save_spending_grant(grant),
        lambda: repo.revoke_wallet_identity_and_pause_active_grants(identity.wallet_identity_id, NOW),
    )

    assert [outcome for outcome, _ in outcomes].count("success") >= 1
    assert repo.active_spending_grants(identity.user_id) == []
    with repo.sessions() as session:
        row = session.get(SpendingGrantRow, grant.spending_grant_id)
    if row is not None:
        assert row.status == "paused"
        assert row.status_reason == "wallet_identity_revoked"


@pytest.mark.parametrize("product_scopes", [[], ["all"], [""]])
def test_spending_grant_requires_explicit_product_scopes(product_scopes):
    with pytest.raises(ValueError, match="product scopes must be explicit"):
        spending_grant("wallet_1", product_scopes)


def test_asset_allowances_are_independent_per_network(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()
    polygon = asset_allowance(identity.wallet_identity_id, "polygon", "eip155:137")
    base = asset_allowance(identity.wallet_identity_id, "base", "eip155:8453")

    repo.save_wallet_identity(identity)
    repo.save_asset_allowance(polygon)
    repo.save_asset_allowance(base)

    assert {
        allowance.network for allowance in repo.asset_allowances(identity.wallet_identity_id)
    } == {"eip155:137", "eip155:8453"}


def test_sqlite_rejects_orphan_grants_and_allowances(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")

    with pytest.raises(ValueError, match="spending grant could not be saved"):
        repo.save_spending_grant(spending_grant("missing_wallet"))
    with pytest.raises(ValueError, match="asset allowance persistence failed"):
        repo.save_asset_allowance(asset_allowance("missing_wallet"))


def _concurrent_outcomes(*operations):
    barrier = Barrier(len(operations))

    def execute(operation):
        barrier.wait()
        try:
            return "success", operation()
        except ValueError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return [future.result() for future in [executor.submit(execute, op) for op in operations]]


def test_sqlite_concurrent_identical_identity_saves_are_idempotent(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()

    outcomes = _concurrent_outcomes(
        lambda: repo.save_wallet_identity(identity),
        lambda: repo.save_wallet_identity(identity),
    )

    assert [outcome for outcome, _ in outcomes] == ["success", "success"]
    assert repo.active_wallet_identities(identity.user_id) == [identity]


def test_sqlite_concurrent_conflicting_identity_saves_have_one_winner(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    first = wallet_identity("wallet_1")
    conflict = wallet_identity("wallet_2")

    outcomes = _concurrent_outcomes(
        lambda: repo.save_wallet_identity(first),
        lambda: repo.save_wallet_identity(conflict),
    )

    assert [outcome for outcome, _ in outcomes].count("success") == 1
    assert [outcome for outcome, _ in outcomes].count("error") == 1
    assert len(repo.active_wallet_identities(first.user_id)) == 1


def test_sqlite_existing_grant_save_is_serialized_and_idempotent(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    identity = wallet_identity()
    grant = spending_grant(identity.wallet_identity_id)
    paused = spending_grant(
        identity.wallet_identity_id,
        status="paused",
        updated_at=NOW + timedelta(seconds=1),
    )
    repo.save_wallet_identity(identity)
    repo.save_spending_grant(grant)

    outcomes = _concurrent_outcomes(
        lambda: repo.save_spending_grant(paused),
        lambda: repo.save_spending_grant(paused),
    )

    assert [outcome for outcome, _ in outcomes] == ["success", "success"]
    with repo.sessions() as session:
        row = session.get(SpendingGrantRow, paused.spending_grant_id)
    assert row is not None
    assert row.status == "paused"


def test_postgresql_grant_lookup_compiles_with_for_update():
    repo = object.__new__(AccountRepository)
    repo.engine = SimpleNamespace(dialect=postgresql.dialect())

    class CapturingSession:
        statement = None

        def scalar(self, statement):
            self.statement = statement
            return None

    session = CapturingSession()
    assert repo._locked_grant(session, "grant_1") is None
    assert "FOR UPDATE" in str(session.statement.compile(dialect=postgresql.dialect()))


def test_postgresql_active_grant_lifecycle_query_compiles_with_for_update():
    repo = object.__new__(AccountRepository)
    repo.engine = SimpleNamespace(dialect=postgresql.dialect())

    class CapturingSession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return SimpleNamespace(all=lambda: [])

    session = CapturingSession()

    @contextmanager
    def write_session():
        yield session

    repo._write_session = write_session

    assert repo.active_spending_grants("u", at=NOW) == []
    assert "FOR UPDATE" in str(session.statement.compile(dialect=postgresql.dialect()))


def test_grant_integrity_error_recovers_only_equivalent_persisted_row():
    repo = object.__new__(AccountRepository)
    grant = spending_grant("wallet_1")

    @contextmanager
    def failed_write_session():
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))
        yield None

    repo._write_session = failed_write_session
    repo._spending_grant_by_id = lambda _: grant

    assert repo.save_spending_grant(grant) == grant

    repo._spending_grant_by_id = lambda _: spending_grant("wallet_1", status="paused")
    with pytest.raises(ValueError, match="spending grant could not be saved"):
        repo.save_spending_grant(grant)


def _migration_config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    return config


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _unique_index_columns(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    return {
        tuple(
            row[2]
            for row in connection.execute(f"PRAGMA index_info('{index_name}')")
        )
        for _, index_name, unique, *_ in connection.execute(
            f"PRAGMA index_list('{table}')"
        )
        if unique
    }


def test_account_migration_creates_exact_domain_tables_and_downgrades(tmp_path):
    database = tmp_path / "account-migration.db"
    config = _migration_config(database)
    post_funding_v2_tables = {
        "allowance_recovery_attempts",
        "account_wallet_bootstrap_states",
        "action_approvals",
        "action_intents",
        "wallet_identities",
        "account_sessions",
        "spending_grants",
        "asset_allowances",
        "spending_grant_daily_usage",
        "spending_grant_rolling_usage",
        "public_account_sessions",
        "policy_decisions",
        "audit_events",
        "funding_relayer_nonces",
        "funding_payment_capabilities",
        "opc_installations",
        "opc_pairings",
        "opc_access_credentials",
    }

    command.upgrade(config, "20260713_0002")
    connection = sqlite3.connect(database)
    baseline_tables = _table_names(connection)
    connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(database)
    assert _table_names(connection) - baseline_tables == post_funding_v2_tables
    grant_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info('spending_grants')")
    }
    session_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info('account_sessions')")
    }
    allowance_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info('asset_allowances')")
    }
    public_session_columns = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info('public_account_sessions')")
    }
    assert grant_columns["status_reason"][3] == 0
    assert grant_columns["hourly_limit_usdc"][3] == 1
    assert grant_columns["merchant_trust_scopes"][3] == 1
    assert grant_columns["notification_mode"][3] == 1
    assert {
        "purpose",
        "wallet_identity_id",
        "payload",
        "payload_hash",
        "created_by_public_account_session_id",
    } <= session_columns.keys()
    assert allowance_columns["approved_amount_atomic"][2].upper() == "VARCHAR(78)"
    assert allowance_columns["observed_allowance_atomic"][2].upper() == "VARCHAR(78)"
    assert "token_digest" in public_session_columns
    assert "session_id" not in public_session_columns
    assert {
        "purpose",
        "status",
        "expires_at",
        "revoked_at",
        "browser_session_digest",
        "csrf_token_digest",
        "exchanged_at",
    } <= public_session_columns.keys()

    wallet_indexes = {
        row[1] for row in connection.execute("PRAGMA index_list('wallet_identities')")
    }
    grant_indexes = {
        row[1] for row in connection.execute("PRAGMA index_list('spending_grants')")
    }
    allowance_indexes = {
        row[1] for row in connection.execute("PRAGMA index_list('asset_allowances')")
    }
    session_indexes = {
        row[1] for row in connection.execute("PRAGMA index_list('account_sessions')")
    }
    daily_usage_indexes = {
        row[1]
        for row in connection.execute("PRAGMA index_list('spending_grant_daily_usage')")
    }
    public_session_indexes = {
        row[1]
        for row in connection.execute("PRAGMA index_list('public_account_sessions')")
    }
    assert ("user_id", "chain_family", "wallet_address") in _unique_index_columns(
        connection, "wallet_identities"
    )
    assert {"ix_wallet_identities_user_id", "ix_wallet_identities_status"} <= wallet_indexes
    assert {"ix_spending_grants_user_id", "ix_spending_grants_status", "ix_spending_grants_expires_at"} <= grant_indexes
    assert (
        "wallet_identity_id",
        "network",
        "token_address",
        "spender_address",
    ) in _unique_index_columns(connection, "asset_allowances")
    assert {"ix_asset_allowances_wallet_status"} <= allowance_indexes
    assert {
        "ix_account_sessions_user_id",
        "ix_account_sessions_expires_at",
        "ix_account_sessions_created_by_public_account_session_id",
    } <= session_indexes
    assert {"ix_spending_grant_daily_usage_spending_grant_id"} <= daily_usage_indexes
    assert ("token_digest",) in _unique_index_columns(
        connection, "public_account_sessions"
    )
    assert ("browser_session_digest",) in _unique_index_columns(
        connection, "public_account_sessions"
    )
    assert {
        "ix_public_account_sessions_user_id",
        "ix_public_account_sessions_status",
        "ix_public_account_sessions_expires_at",
    } <= public_session_indexes
    public_session_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'public_account_sessions'"
    ).fetchone()[0]
    assert "ck_public_account_session_digest" in public_session_sql
    assert "ck_public_account_browser_session_digest" in public_session_sql
    assert "ck_public_account_csrf_token_digest" in public_session_sql
    assert "ck_public_account_session_purpose" in public_session_sql
    assert "ck_public_account_session_status" in public_session_sql
    assert connection.execute("PRAGMA foreign_key_list('spending_grants')").fetchall()
    assert connection.execute("PRAGMA foreign_key_list('asset_allowances')").fetchall()
    assert connection.execute("PRAGMA foreign_key_list('spending_grant_daily_usage')").fetchall()
    assert (
        "public_account_sessions",
        "created_by_public_account_session_id",
        "public_account_session_id",
    ) in {
        (row[2], row[3], row[4])
        for row in connection.execute("PRAGMA foreign_key_list('account_sessions')")
    }
    connection.close()

    command.downgrade(config, "20260713_0002")
    connection = sqlite3.connect(database)
    assert _table_names(connection) == baseline_tables
    connection.close()


def test_account_migration_declares_json_numeric_and_timezone_columns(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.20260715_0003_unified_wallet_authorization"
    )
    created_tables = {}

    class RecordingOperations:
        def create_table(self, name, *elements):
            created_tables[name] = {
                element.name: element
                for element in elements
                if isinstance(element, sa.Column)
            }

        def create_index(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(migration, "op", RecordingOperations())
    migration.upgrade()

    grants = created_tables["spending_grants"]
    daily_usage = created_tables["spending_grant_daily_usage"]
    sessions = created_tables["account_sessions"]
    allowances = created_tables["asset_allowances"]
    assert isinstance(grants["product_scopes"].type, sa.JSON)
    assert isinstance(grants["status_reason"].type, sa.String)
    assert grants["status_reason"].nullable is True
    assert isinstance(grants["max_amount_usdc"].type, sa.Numeric)
    assert grants["max_amount_usdc"].type.precision == 38
    assert grants["max_amount_usdc"].type.scale == 6
    assert isinstance(daily_usage["used_amount_usdc"].type, sa.Numeric)
    assert daily_usage["used_amount_usdc"].type.precision == 38
    assert daily_usage["used_amount_usdc"].type.scale == 6
    assert grants["expires_at"].type.timezone is True
    assert sessions["expires_at"].type.timezone is True
    assert isinstance(sessions["payload"].type, sa.JSON)
    assert isinstance(sessions["payload_hash"].type, sa.String)
    approved_type = allowances["approved_amount_atomic"].type
    sqlite_type = approved_type.dialect_impl(sqlite.dialect())
    postgres_type = approved_type.dialect_impl(postgresql.dialect())
    assert isinstance(sqlite_type, sa.String)
    assert sqlite_type.length == 78
    assert isinstance(postgres_type, sa.Numeric)
    assert postgres_type.precision == 78
    assert postgres_type.scale == 0
    assert allowances["created_at"].type.timezone is True
