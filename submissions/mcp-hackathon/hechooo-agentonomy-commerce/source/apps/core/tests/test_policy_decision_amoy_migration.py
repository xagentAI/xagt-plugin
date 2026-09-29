from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from services.action_policy_repository import ActionPolicyRepository


ROOT = Path(__file__).resolve().parents[1]
AMOY_NETWORK = "eip155:80002"
POLYGON_NETWORK = "eip155:137"
UNSUPPORTED_NETWORK = "eip155:1"


def _policy_payload(*, policy_decision_id: str, chain: str) -> dict:
    return {
        "policy_decision_id": policy_decision_id,
        "action_id": "act_amoy_rehearsal",
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "marketplace_purchase",
        "decision": "approved",
        "target_address": "0x" + "1" * 40,
        "chain": chain,
        "evaluated_at": "2026-09-01T00:00:00Z",
    }


def _migration_config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    return config


def _insert_policy(connection, *, policy_decision_id: str, chain: str) -> None:
    payload = _policy_payload(
        policy_decision_id=policy_decision_id,
        chain=chain,
    )
    connection.execute(
        text(
            "INSERT INTO policy_decisions "
            "(policy_decision_id, action_id, user_id, agent_id, action_type, "
            "decision, target_address, chain, payload, evaluated_at) "
            "VALUES (:policy_decision_id, :action_id, :user_id, :agent_id, "
            ":action_type, :decision, :target_address, :chain, :payload, "
            ":evaluated_at)"
        ),
        {**payload, "payload": json.dumps(payload)},
    )


def test_policy_repository_persists_amoy_rehearsal_without_relaxing_other_chains(
    tmp_path,
):
    repository = ActionPolicyRepository(
        f"sqlite+pysqlite:///{tmp_path / 'repository.sqlite3'}"
    )
    amoy = _policy_payload(
        policy_decision_id="policy_amoy",
        chain=AMOY_NETWORK,
    )

    assert repository.create_policy_decision(amoy) == amoy
    assert repository.policy_decision("policy_amoy") == amoy

    unsupported = deepcopy(amoy)
    unsupported.update(
        policy_decision_id="policy_unsupported",
        chain=UNSUPPORTED_NETWORK,
    )
    with pytest.raises(ValueError, match="policy decision could not be persisted"):
        repository.create_policy_decision(unsupported)


def test_amoy_policy_constraint_migration_preserves_rows_and_is_reversible(tmp_path):
    database = tmp_path / "migration.sqlite3"
    config = _migration_config(database)
    command.upgrade(config, "20260825_0018")
    engine = create_engine(f"sqlite+pysqlite:///{database}")

    with engine.begin() as connection:
        _insert_policy(
            connection,
            policy_decision_id="policy_polygon_before",
            chain=POLYGON_NETWORK,
        )

    command.upgrade(config, "head")

    with engine.begin() as connection:
        _insert_policy(
            connection,
            policy_decision_id="policy_amoy_after",
            chain=AMOY_NETWORK,
        )
        with pytest.raises(IntegrityError):
            _insert_policy(
                connection,
                policy_decision_id="policy_unsupported_after",
                chain=UNSUPPORTED_NETWORK,
            )
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT policy_decision_id FROM policy_decisions "
                "ORDER BY policy_decision_id"
            )
        ).scalars().all() == ["policy_amoy_after", "policy_polygon_before"]

    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM policy_decisions "
                "WHERE policy_decision_id = 'policy_amoy_after'"
            )
        )
    command.downgrade(config, "20260825_0018")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT policy_decision_id FROM policy_decisions")
        ).scalar_one() == "policy_polygon_before"
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            _insert_policy(
                connection,
                policy_decision_id="policy_amoy_downgraded",
                chain=AMOY_NETWORK,
            )
