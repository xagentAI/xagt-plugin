from __future__ import annotations

from pathlib import Path

import pytest

from app import _configured_chain_token
from config import HostedProductionConfig
from execution_models import ExecutionIntent
from execution_repository import ExecutionRepository
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


BASE_VALUES: dict[str, object] = {
    "environment": "test",
    "public_origin": "http://127.0.0.1:8080",
    "postgres_url": "postgresql+psycopg://test:test@localhost/test",
    "redis_url": "redis://127.0.0.1:6379/0",
    "response_key_ref": "test://response",
    "core_authority_origin": "http://127.0.0.1:8090",
    "core_internal_token": "test-token",
    "chain_id": 8453,
    "asset_contract": HOSTED_CHAIN_PROFILES["eip155:8453"].token,
    "executor_address": "0x" + "11" * 20,
    "executor_admin_address": "0x" + "55" * 20,
    "executor_code_hash": "0x" + "22" * 32,
    "execution_kms_key_id": "kms://execution",
    "execution_signer_address": "0x" + "33" * 20,
    "gas_kms_key_id": "kms://gas",
    "relayer_address": "0x" + "44" * 20,
    "submission_rpc_url": "http://127.0.0.1:8545",
    "watcher_rpc_url": "http://127.0.0.1:9545",
    "max_gas_limit": 500_000,
    "max_fee_per_gas_wei": 100,
    "max_priority_fee_per_gas_wei": 10,
    "native_asset_usd_price_ceiling_micros": 4_000_000_000,
}


def _config(**overrides: object) -> HostedProductionConfig:
    values = {**BASE_VALUES, **overrides}
    return HostedProductionConfig(**values)


def test_hosted_runtime_builds_strict_pilot_gate_policy() -> None:
    config = _config()

    assert config.pilot_gate_policy.max_in_flight_per_node == 10
    assert config.pilot_gate_policy.max_accepted_per_node_utc_day == 50
    assert config.pilot_gate_policy.max_accepted_per_node_lifetime == 250
    assert config.pilot_gate_policy.max_gas_usd_micros_per_node_utc_day == 1_000_000
    assert config.pilot_gate_policy.max_gas_usd_micros_platform_utc_day == 100_000_000
    assert config.pilot_gate_policy.native_asset_usd_price_ceiling_micros == 4_000_000_000


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -1, 1.5],
)
def test_hosted_runtime_requires_safe_native_asset_price_ceiling(value: object) -> None:
    values = dict(BASE_VALUES)
    if value is None:
        values.pop("native_asset_usd_price_ceiling_micros")
    else:
        values["native_asset_usd_price_ceiling_micros"] = value

    with pytest.raises(ValueError, match="native.*price|price.*ceiling"):
        HostedProductionConfig(**values)


@pytest.mark.parametrize("missing", ["chain_id", "asset_contract"])
def test_hosted_runtime_requires_an_explicit_profile(missing: str) -> None:
    values = {
        **BASE_VALUES,
        "chain_id": 8453,
        "asset_contract": HOSTED_CHAIN_PROFILES["eip155:8453"].token,
    }
    values.pop(missing)

    with pytest.raises(ValueError, match=missing):
        HostedProductionConfig(**values)


def test_app_composition_rejects_a_config_without_an_explicit_profile() -> None:
    with pytest.raises(AttributeError):
        _configured_chain_token(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("chain_id", "token", "boundary", "depth"),
    [
        (8453, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "safe", 2),
        (137, "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", "finalized", 3),
        (84532, "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "safe", 2),
        (80002, "0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582", "finalized", 3),
    ],
)
def test_hosted_profile_matrix_binds_exact_token_and_finality(
    chain_id: int, token: str, boundary: str, depth: int
) -> None:
    config = _config(chain_id=chain_id, asset_contract=token, confirmation_depth=depth)

    assert config.chain == f"eip155:{chain_id}"
    assert config.asset_contract == token.lower()
    assert config.finality_boundary == boundary
    assert config.confirmation_depth == depth
    assert HOSTED_CHAIN_PROFILES[config.chain].token == token.lower()


def test_profile_default_depth_follows_polygon_finality_requirement() -> None:
    values = {
        **BASE_VALUES,
        "chain_id": 137,
        "asset_contract": HOSTED_CHAIN_PROFILES["eip155:137"].token,
    }
    values.pop("confirmation_depth", None)

    config = HostedProductionConfig(**values)

    assert config.confirmation_depth == 3
    assert config.finality_boundary == "finalized"


@pytest.mark.parametrize("chain_id", [84532, 80002])
def test_production_profile_rejects_testnets(chain_id: int) -> None:
    token = HOSTED_CHAIN_PROFILES[f"eip155:{chain_id}"].token

    with pytest.raises(ValueError, match="production.*chain|chain.*production"):
        _config(
            environment="production",
            public_origin="https://hosted.example.com",
            core_authority_origin="https://core.example.com",
            core_internal_token="internal-token",
            response_key_ref="alias/hosted-response",
            chain_id=chain_id,
            asset_contract=token,
            confirmation_depth=HOSTED_CHAIN_PROFILES[f"eip155:{chain_id}"].min_confirmation_depth,
        )


def test_execution_intent_requires_explicit_chain_and_token() -> None:
    fields = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "capability_id": "capability_1",
        "reservation_id": "reservation_1",
        "purchase_id": "purchase_1",
        "request_id": "request_1",
        "request_hash": "0x" + "11" * 32,
        "idempotency_key": "idempotency_1",
        "owner": "0x" + "22" * 20,
        "payee": "0x" + "33" * 20,
        "amount_atomic": "1",
        "executor": "0x" + "44" * 20,
        "signer_epoch": 1,
        "owner_nonce": 0,
        "deadline": 100,
        "capability_hash": "0x" + "55" * 32,
        "reservation_hash": "0x" + "66" * 32,
        "execution_scope_hash": "0x" + "77" * 32,
        "execution_digest": "0x" + "88" * 32,
        "relayer_address": "0x" + "99" * 20,
    }

    with pytest.raises(ValueError, match="chain"):
        ExecutionIntent(**fields)
    with pytest.raises(ValueError, match="token"):
        ExecutionIntent(**{**fields, "chain": "eip155:8453"})


def test_watch_query_requires_and_filters_bound_chain(tmp_path: Path) -> None:
    repository = ExecutionRepository(f"sqlite+pysqlite:///{tmp_path / 'watch.sqlite3'}")

    with pytest.raises(TypeError, match="chain"):
        repository.list_watchable_ids(after_execution_id=None, limit=10)  # type: ignore[call-arg]
