from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from scripts.check_runtime_schema import check_runtime_schema


ROOT = Path(__file__).resolve().parents[1]


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    return config


def test_opc_migration_creates_required_authority_tables_and_runtime_contract(tmp_path):
    database = tmp_path / "opc-migration.sqlite3"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    schema = inspect(engine)

    assert {
        "opc_installations",
        "opc_pairings",
        "opc_access_credentials",
    } <= set(schema.get_table_names())
    assert {
        "installation_id",
        "public_jwk",
        "public_jwk_thumbprint",
        "status",
        "user_id",
        "wallet_identity_id",
        "spending_grant_id",
        "consent_expires_at",
        "consent_hash",
        "revoked_at",
    } <= {
        column["name"] for column in schema.get_columns("opc_installations")
    }
    assert check_runtime_schema(f"sqlite+pysqlite:///{database}") == []


def test_opc_migration_is_reversible_without_touching_account_rows(tmp_path):
    database = tmp_path / "opc-downgrade.sqlite3"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallet_identities "
                "(wallet_identity_id,user_id,chain_family,wallet_address,status,"
                "proof_scheme,proof_hash,verified_at,created_at,updated_at) VALUES "
                "('wallet-opc','user-opc','eip155',:wallet,'active','eip191',"
                "'proof',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"wallet": "0x" + "11" * 20},
        )

    command.downgrade(config, "20260901_0019")
    schema = inspect(engine)
    assert "opc_installations" not in schema.get_table_names()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT user_id FROM wallet_identities WHERE wallet_identity_id='wallet-opc'")
        ).scalar_one() == "user-opc"
