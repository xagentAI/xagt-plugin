from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import FacilitatorConfig, HostedWatcherConfig
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


BASE_PROFILE = HOSTED_CHAIN_PROFILES["eip155:8453"]


def watcher_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "test",
        "postgres_url": "postgresql+psycopg://watcher:watcher@localhost/hosted",
        "chain_id": BASE_PROFILE.chain_id,
        "asset_contract": BASE_PROFILE.token,
        "watcher_rpc_url": "http://127.0.0.1:9545",
        "executor_address": "0x" + "11" * 20,
        "executor_admin_address": "0x" + "44" * 20,
        "executor_code_hash": "0x" + "22" * 32,
        "execution_signer_address": "0x" + "33" * 20,
        "signer_epoch": 7,
        "confirmation_depth": BASE_PROFILE.min_confirmation_depth,
        "rpc_timeout_seconds": 20,
        "watcher_rpc_min_interval_ms": 0,
        "watch_batch_size": 100,
        "watch_poll_seconds": 5,
        "native_asset_usd_price_ceiling_micros": 4_000_000_000,
        "max_in_flight_per_node": 10,
        "max_accepted_per_node_utc_day": 50,
        "max_accepted_per_node_lifetime": 250,
        "max_gas_usd_micros_per_node_utc_day": 1_000_000,
        "max_gas_usd_micros_platform_utc_day": 100_000_000,
    }
    values.update(overrides)
    return values


def production_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "production",
        "public_origin": "https://hosted.example.com",
        "postgres_url": "postgresql+psycopg://hosted:secret@db/hosted?sslmode=verify-full",
        "redis_url": "rediss://redis.example.com:6380/0",
        "response_key_ref": "alias/hosted-response",
        "core_authority_origin": "https://core.example.com",
        "core_internal_token": "internal-test-token",
        "chain_id": BASE_PROFILE.chain_id,
        "asset_contract": BASE_PROFILE.token,
        "enrollment_ttl_seconds": 300,
        "dpop_ttl_seconds": 60,
        "max_request_body_bytes": 128 * 1024,
    }
    values.update(overrides)
    return values


def test_production_config_requires_persistent_postgres_redis_and_key_reference() -> None:
    config = FacilitatorConfig(**production_values())

    assert config.environment == "production"
    assert config.public_origin == "https://hosted.example.com"
    assert config.postgres_url.startswith("postgresql")
    assert config.redis_url.startswith("rediss://")

    with pytest.raises((ValidationError, ValueError), match="TLS"):
        FacilitatorConfig(
            **production_values(
                postgres_url="postgresql+psycopg://hosted:secret@db/hosted"
            )
        )
    with pytest.raises((ValidationError, ValueError), match="TLS"):
        FacilitatorConfig(
            **production_values(redis_url="redis://redis.example.com:6379/0")
        )

    for field, value in (
        ("postgres_url", "sqlite:///hosted.db"),
        ("postgres_url", "memory://"),
        ("redis_url", ""),
        ("response_key_ref", "-----BEGIN " + "PRIVATE KEY-----"),
        ("response_key_ref", "secret://clink/hosted/response-key"),
    ):
        with pytest.raises((ValidationError, ValueError), match=field.split("_")[0]):
            FacilitatorConfig(**production_values(**{field: value}))

    for field in ("core_authority_origin", "core_internal_token"):
        with pytest.raises((ValidationError, ValueError), match="Core authority"):
            FacilitatorConfig(**production_values(**{field: ""}))


@pytest.mark.parametrize(
    "origin",
    [
        "http://hosted.example.com",
        "https://hosted.example.com/",
        "https://user:password@hosted.example.com",
        "https://hosted.example.com/path",
        "https://hosted.example.com?query=1",
    ],
)
def test_production_public_origin_is_canonical_https_without_credentials_or_path(
    origin: str,
) -> None:
    with pytest.raises((ValidationError, ValueError), match="public origin"):
        FacilitatorConfig(**production_values(public_origin=origin))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enrollment_ttl_seconds", 29),
        ("enrollment_ttl_seconds", 901),
        ("dpop_ttl_seconds", 0),
        ("dpop_ttl_seconds", 61),
        ("max_request_body_bytes", 1023),
        ("max_request_body_bytes", 1024 * 1024 + 1),
    ],
)
def test_production_config_rejects_unsafe_ttls_and_body_limits(
    field: str,
    value: int,
) -> None:
    with pytest.raises((ValidationError, ValueError), match=field.split("_")[0]):
        FacilitatorConfig(**production_values(**{field: value}))


def test_test_config_may_use_explicit_loopback_http_but_never_memory_fallback() -> None:
    config = FacilitatorConfig(
        environment="test",
        public_origin="http://127.0.0.1:8080",
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="redis://127.0.0.1:6379/0",
        response_key_ref="test://injected-response-signer",
        chain_id=BASE_PROFILE.chain_id,
        asset_contract=BASE_PROFILE.token,
        enrollment_ttl_seconds=300,
        dpop_ttl_seconds=60,
        max_request_body_bytes=128 * 1024,
    )

    assert config.public_origin == "http://127.0.0.1:8080"

    with pytest.raises((ValidationError, ValueError), match="public origin"):
        FacilitatorConfig(
            environment="test",
            public_origin="http://not-loopback.example.com",
            postgres_url=config.postgres_url,
            redis_url=config.redis_url,
            response_key_ref=config.response_key_ref,
            chain_id=config.chain_id,
            asset_contract=config.asset_contract,
            enrollment_ttl_seconds=300,
            dpop_ttl_seconds=60,
            max_request_body_bytes=128 * 1024,
        )


def test_watcher_config_is_strict_frozen_and_has_no_api_or_private_signing_inputs() -> None:
    config = HostedWatcherConfig(**watcher_values())

    assert config.chain_id == BASE_PROFILE.chain_id
    assert config.watcher_rpc_url == "http://127.0.0.1:9545"
    assert config.execution_signer_address == "0x" + "33" * 20
    assert config.signer_epoch == 7
    with pytest.raises((TypeError, ValidationError), match="frozen"):
        config.chain_id = 137  # type: ignore[misc]

    with pytest.raises((ValidationError, ValueError), match="extra"):
        HostedWatcherConfig(**watcher_values(public_origin="https://example.com"))


def test_watcher_config_from_env_requires_only_watcher_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = watcher_values()
    env = {
        "CLINK_FACILITATOR_ENV": values["environment"],
        "CLINK_HOSTED_POSTGRES_URL": values["postgres_url"],
        "CLINK_HOSTED_CHAIN_ID": values["chain_id"],
        "CLINK_HOSTED_ASSET_CONTRACT": values["asset_contract"],
        "CLINK_HOSTED_WATCHER_RPC_URL": values["watcher_rpc_url"],
        "CLINK_HOSTED_WATCHER_RPC_MIN_INTERVAL_MS": "250",
        "CLINK_HOSTED_EXECUTOR_ADDRESS": values["executor_address"],
        "CLINK_HOSTED_EXECUTOR_ADMIN_ADDRESS": values["executor_admin_address"],
        "CLINK_HOSTED_EXECUTOR_CODE_HASH": values["executor_code_hash"],
        "CLINK_HOSTED_EXECUTION_SIGNER_ADDRESS": values["execution_signer_address"],
        "CLINK_HOSTED_SIGNER_EPOCH": values["signer_epoch"],
        "CLINK_HOSTED_NATIVE_ASSET_USD_PRICE_CEILING_MICROS": values[
            "native_asset_usd_price_ceiling_micros"
        ],
    }
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    for key in (
        "CLINK_HOSTED_PUBLIC_ORIGIN",
        "CLINK_HOSTED_REDIS_URL",
        "CLINK_HOSTED_RESPONSE_KEY_REF",
        "CLINK_HOSTED_RESPONSE_KMS_KEY_ID",
        "CLINK_CORE_AUTHORITY_ORIGIN",
        "CLINK_CORE_INTERNAL_API_TOKEN",
        "CLINK_HOSTED_SUBMISSION_RPC_URL",
        "CLINK_HOSTED_EXECUTION_RPC_URL",
        "CLINK_HOSTED_EXECUTION_KMS_KEY_ID",
        "CLINK_HOSTED_GAS_KMS_KEY_ID",
        "CLINK_HOSTED_RELAYER_ADDRESS",
        "CLINK_HOSTED_MAX_GAS_LIMIT",
        "CLINK_HOSTED_MAX_FEE_PER_GAS_WEI",
        "CLINK_HOSTED_MAX_PRIORITY_FEE_PER_GAS_WEI",
    ):
        monkeypatch.delenv(key, raising=False)

    config = HostedWatcherConfig.from_env()

    assert config.postgres_url == values["postgres_url"]
    assert config.executor_address == values["executor_address"]
    assert config.executor_admin_address == values["executor_admin_address"]
    assert config.execution_signer_address == values["execution_signer_address"]
    assert config.signer_epoch == values["signer_epoch"]
    assert config.watcher_rpc_min_interval_ms == 250
    assert config.pilot_gate_policy.native_asset_usd_price_ceiling_micros == 4_000_000_000


@pytest.mark.parametrize("value", [-1, 10_001, True])
def test_watcher_config_rejects_invalid_rpc_pacing(value: object) -> None:
    with pytest.raises((ValidationError, ValueError), match="watcher_rpc_min_interval_ms"):
        HostedWatcherConfig(**watcher_values(watcher_rpc_min_interval_ms=value))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_signer_address", "not-an-address"),
        ("execution_signer_address", "0x" + "00" * 20),
        ("executor_admin_address", "not-an-address"),
        ("executor_admin_address", "0x" + "00" * 20),
        ("signer_epoch", 0),
        ("signer_epoch", True),
    ],
)
def test_watcher_config_validates_public_contract_identity(
    field: str,
    value: object,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        HostedWatcherConfig(**watcher_values(**{field: value}))


def test_watcher_test_config_allows_remote_https_but_rejects_remote_http() -> None:
    config = HostedWatcherConfig(
        **watcher_values(watcher_rpc_url="https://watcher.example.com")
    )
    assert config.watcher_rpc_url == "https://watcher.example.com"

    with pytest.raises((ValidationError, ValueError), match="loopback HTTP"):
        HostedWatcherConfig(**watcher_values(watcher_rpc_url="http://watcher.example.com"))


@pytest.mark.parametrize("chain_name", ["eip155:84532", "eip155:80002"])
def test_watcher_production_rejects_testnet_chain(chain_name: str) -> None:
    profile = HOSTED_CHAIN_PROFILES[chain_name]

    with pytest.raises((ValidationError, ValueError), match="production"):
        HostedWatcherConfig(
            **watcher_values(
                environment="production",
                watcher_rpc_url="https://watcher.example.com",
                chain_id=profile.chain_id,
                asset_contract=profile.token,
                confirmation_depth=profile.min_confirmation_depth,
            )
        )
