"""Schema contract tests for allowance recovery migrations 0021 and 0022."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from scripts.check_runtime_schema import check_runtime_schema


ROOT = Path(__file__).resolve().parents[1]


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    return config


def test_allowance_recovery_migration_round_trip_has_additive_schema_and_runtime_contract(
    tmp_path,
):
    database = tmp_path / "allowance-recovery.sqlite3"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    schema = inspect(engine)

    assert "allowance_recovery_attempts" in schema.get_table_names()
    assert {
        "attempt_id",
        "user_id",
        "wallet_identity_id",
        "network",
        "token_address",
        "spender_address",
        "amount_atomic",
        "allowance_tx_hash",
        "status",
        "reason_code",
        "created_at",
        "updated_at",
        "next_check_at",
        "request_key_digest",
        "check_count",
        "actual_approved_amount_atomic",
        "observed_allowance_atomic",
        "confirmed_block",
        "confirmed_block_hash",
        "verified_at",
    } <= {
        column["name"]
        for column in schema.get_columns("allowance_recovery_attempts")
    }
    assert schema.get_pk_constraint("allowance_recovery_attempts")[
        "constrained_columns"
    ] == ["attempt_id"]
    assert {
        "uq_allowance_recovery_open_scope",
        "uq_allowance_recovery_wallet_network_hash",
        "uq_allowance_recovery_request_key_digest",
    } <= {
        index["name"] for index in schema.get_indexes("allowance_recovery_attempts")
    }
    assert schema.get_foreign_keys("allowance_recovery_attempts")
    assert {
        "ck_allowance_recovery_actual_amount_positive",
        "ck_allowance_recovery_confirmed_block_nonnegative",
        "ck_allowance_recovery_confirmed_block_hash",
        "ck_allowance_recovery_mismatch_evidence_complete",
    } <= {
        check["name"]
        for check in schema.get_check_constraints("allowance_recovery_attempts")
    }
    assert check_runtime_schema(f"sqlite+pysqlite:///{database}") == []

    command.downgrade(config, "20260904_0020")
    assert "allowance_recovery_attempts" not in inspect(engine).get_table_names()


def test_allowance_recovery_downgrade_refuses_open_attempts_without_touching_identity(
    tmp_path,
):
    database = tmp_path / "allowance-recovery-blocked.sqlite3"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallet_identities "
                "(wallet_identity_id,user_id,chain_family,wallet_address,status," \
                "proof_scheme,proof_hash,verified_at,created_at,updated_at) VALUES " \
                "(:wallet_id,:user_id,'eip155',:address,'active','eip191','proof'," \
                ":now,:now,:now)"
            ),
            {
                "wallet_id": "wallet-migration",
                "user_id": "user-migration",
                "address": "0x" + "11" * 20,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO allowance_recovery_attempts "
                "(attempt_id,user_id,wallet_identity_id,network,token_address,"
                "spender_address,amount_atomic,status,created_at,updated_at,"
                "request_key_digest,check_count) VALUES "
                "('attempt-migration','user-migration','wallet-migration',"
                "'eip155:137',:token,:spender,'2000000','awaiting_wallet',"
                ":now,:now,:digest,0)"
            ),
            {
                "token": "0x" + "22" * 20,
                "spender": "0x" + "33" * 20,
                "now": now,
                "digest": "aa" * 32,
            },
        )

    with pytest.raises(RuntimeError, match="open"):
        command.downgrade(config, "20260904_0020")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT user_id FROM wallet_identities "
                "WHERE wallet_identity_id='wallet-migration'"
            )
        ).scalar_one() == "user-migration"
        assert connection.execute(
            text(
                "SELECT attempt_id FROM allowance_recovery_attempts "
                "WHERE attempt_id='attempt-migration'"
            )
        ).scalar_one() == "attempt-migration"


def test_allowance_mismatch_upgrade_from_0021_preserves_open_attempt_and_safe_downgrade(
    tmp_path,
):
    database = tmp_path / "allowance-recovery-upgrade.sqlite3"
    config = _config(database)
    command.upgrade(config, "20260916_0021")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallet_identities "
                "(wallet_identity_id,user_id,chain_family,wallet_address,status,"
                "proof_scheme,proof_hash,verified_at,created_at,updated_at) VALUES "
                "(:wallet_id,:user_id,'eip155',:address,'active','eip191','proof',"
                ":now,:now,:now)"
            ),
            {
                "wallet_id": "wallet-upgrade",
                "user_id": "user-upgrade",
                "address": "0x" + "44" * 20,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO allowance_recovery_attempts "
                "(attempt_id,user_id,wallet_identity_id,network,token_address,"
                "spender_address,amount_atomic,status,created_at,updated_at,"
                "request_key_digest,check_count) VALUES "
                "('attempt-upgrade','user-upgrade','wallet-upgrade',"
                "'eip155:137',:token,:spender,'2000000','awaiting_wallet',"
                ":now,:now,:digest,0)"
            ),
            {
                "token": "0x" + "55" * 20,
                "spender": "0x" + "66" * 20,
                "now": now,
                "digest": "bb" * 32,
            },
        )

    command.upgrade(config, "head")
    schema = inspect(engine)
    assert {
        "actual_approved_amount_atomic",
        "observed_allowance_atomic",
        "confirmed_block",
        "confirmed_block_hash",
        "verified_at",
    } <= {
        column["name"]
        for column in schema.get_columns("allowance_recovery_attempts")
    }
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT amount_atomic,status,allowance_tx_hash "
                "FROM allowance_recovery_attempts WHERE attempt_id='attempt-upgrade'"
            )
        ).mappings().one()
    assert dict(row) == {
        "amount_atomic": "2000000",
        "status": "awaiting_wallet",
        "allowance_tx_hash": None,
    }

    command.downgrade(config, "20260916_0021")
    schema = inspect(engine)
    assert not {
        "actual_approved_amount_atomic",
        "observed_allowance_atomic",
        "confirmed_block",
        "confirmed_block_hash",
        "verified_at",
    } & {
        column["name"]
        for column in schema.get_columns("allowance_recovery_attempts")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT status FROM allowance_recovery_attempts "
                "WHERE attempt_id='attempt-upgrade'"
            )
        ).scalar_one() == "awaiting_wallet"


def test_allowance_mismatch_downgrade_refuses_evidence_loss_and_constraints_reject_bad_terminal_state(
    tmp_path,
):
    database = tmp_path / "allowance-recovery-evidence.sqlite3"
    config = _config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    evidence = {
        "wallet_id": "wallet-evidence",
        "user_id": "user-evidence",
        "address": "0x" + "77" * 20,
        "token": "0x" + "88" * 20,
        "spender": "0x" + "99" * 20,
        "tx_hash": "0x" + "12" * 32,
        "block_hash": "0x" + "ab" * 32,
        "now": now,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallet_identities "
                "(wallet_identity_id,user_id,chain_family,wallet_address,status,"
                "proof_scheme,proof_hash,verified_at,created_at,updated_at) VALUES "
                "(:wallet_id,:user_id,'eip155',:address,'active','eip191','proof',"
                ":now,:now,:now)"
            ),
            evidence,
        )
        connection.execute(
            text(
                "INSERT INTO allowance_recovery_attempts "
                "(attempt_id,user_id,wallet_identity_id,network,token_address,"
                "spender_address,amount_atomic,allowance_tx_hash,status,reason_code,"
                "created_at,updated_at,next_check_at,check_count,"
                "actual_approved_amount_atomic,observed_allowance_atomic,"
                "confirmed_block,confirmed_block_hash,verified_at) VALUES "
                "('attempt-evidence','user-evidence','wallet-evidence','eip155:137',"
                ":token,:spender,'20000000',:tx_hash,'confirmed_mismatch',"
                "'amount_mismatch',:now,:now,NULL,0,'5000000','5000000',100,"
                ":block_hash,:now)"
            ),
            evidence,
        )

    with pytest.raises(RuntimeError, match="confirmed allowance mismatch evidence"):
        command.downgrade(config, "20260916_0021")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT status FROM allowance_recovery_attempts "
                "WHERE attempt_id='attempt-evidence'"
            )
        ).scalar_one() == "confirmed_mismatch"

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE allowance_recovery_attempts "
                    "SET next_check_at=:now WHERE attempt_id='attempt-evidence'"
                ),
                {"now": now},
            )

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE allowance_recovery_attempts "
                    "SET reason_code=NULL WHERE attempt_id='attempt-evidence'"
                )
            )
