from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys

import httpx
import pytest
from eth_account import Account

from services.account_service.app import create_app
from services.funding_service.service import FundingService
from services.policy_service.app import APP_CONFIG, create_app as create_policy_app
from shared.config import AppConfig


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
POLYGON = "eip155:137"
BASE = "eip155:8453"


def run_bounded(args, *, timeout, check=False, capture_output=False, **kwargs):
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    process = subprocess.Popen(args, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=2)
        raise

    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def test_account_runtime_config_parses_urls_products_ttl_and_redacts_secrets(
    monkeypatch,
):
    monkeypatch.setenv("ACCOUNT_SERVICE_HOST", "127.0.0.9")
    monkeypatch.setenv("ACCOUNT_SERVICE_PORT", "8119")
    monkeypatch.setenv(
        "CLINK_ACCOUNT_PUBLIC_BASE_URL", "https://account.example.com/core/"
    )
    monkeypatch.setenv("CLINK_ACCOUNT_SESSION_TTL_SECONDS", "600")
    monkeypatch.setenv(
        "CLINK_ACCOUNT_ALLOWED_PRODUCTS", "prediction_markets, marketplace"
    )
    monkeypatch.setenv("CLINK_AUDIT_SERVICE_URL", "http://audit.internal:8117/")
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "internal-secret")
    monkeypatch.setenv("CLINK_RECEIPT_SIGNING_KEY", "receipt-secret")
    monkeypatch.setenv("MISTTRACK_API_KEY", "misttrack-secret")
    monkeypatch.setenv(
        "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY", "relayer-secret"
    )
    monkeypatch.setenv(
        "CLINK_POLYGON_RPC_URL", "https://polygon-rpc.example/v1/polygon-secret"
    )
    monkeypatch.setenv(
        "CLINK_BASE_RPC_URL", "https://base-rpc.example/v1/base-secret"
    )

    config = AppConfig.from_env()

    assert config.account_service_url == "http://127.0.0.9:8119"
    assert config.account_public_base_url == "https://account.example.com/core"
    assert config.account_session_ttl_seconds == 600
    assert config.account_allowed_products == (
        "prediction_markets",
        "marketplace",
    )
    assert config.audit_service_url == "http://audit.internal:8117"
    assert config.clink_receipt_signing_key == "receipt-secret"
    assert config.rpc_url_for(POLYGON).endswith("/v1/polygon-secret")
    assert config.rpc_url_for(BASE).endswith("/v1/base-secret")
    description = json.dumps(config.describe(), sort_keys=True)
    assert "internal-secret" not in description
    assert "receipt-secret" not in description
    assert "misttrack-secret" not in description
    assert "relayer-secret" not in description
    assert "polygon-secret" not in description
    assert "base-secret" not in description


def test_rpc_configuration_is_canonical_and_fails_closed_for_missing_network():
    config = AppConfig(
        polygon_rpc_url="https://polygon-rpc.example/v1/key",
        base_rpc_url="https://base-rpc.example/v1/key",
    )

    assert config.rpc_url_for(POLYGON) == "https://polygon-rpc.example/v1/key"
    assert config.rpc_url_for(BASE) == "https://base-rpc.example/v1/key"
    with pytest.raises(ValueError, match="unsupported canonical EVM network"):
        config.rpc_url_for("eip155:1")

    missing = AppConfig(polygon_rpc_url="https://polygon-rpc.example/v1/key")
    with pytest.raises(RuntimeError, match="CLINK_BASE_RPC_URL"):
        missing.rpc_url_for(BASE)


def test_live_funding_requires_enforced_configured_misttrack():
    with pytest.raises(ValueError, match="CLINK_RISK_MODE=enforce"):
        AppConfig(clink_live_funding=True, risk_mode="shadow")
    with pytest.raises(ValueError, match="CLINK_RISK_PROVIDER=misttrack"):
        AppConfig(
            clink_live_funding=True,
            risk_provider="other",
            risk_mode="enforce",
            misttrack_api_key="test-key",
        )
    with pytest.raises(ValueError, match="MISTTRACK_API_KEY"):
        AppConfig(clink_live_funding=True, risk_mode="enforce", misttrack_api_key="")

    config = AppConfig(
        clink_live_funding=True,
        risk_provider="misttrack",
        risk_mode="enforce",
        misttrack_api_key="test-key",
    )
    assert config.risk_mode == "enforce"


def test_config_description_never_exposes_misttrack_key():
    description = AppConfig(misttrack_api_key="secret").describe()

    assert description["misttrack_api_key"] == "<redacted>"
    assert "secret" not in json.dumps(description)


def test_core_profile_defaults_to_personal_without_redis():
    config = AppConfig()

    assert config.clink_profile == "personal"
    assert config.clink_redis_url == ""
    assert config.misttrack_rate_limit_requests_per_window is None
    assert config.misttrack_rate_limit_window_seconds is None
    assert config.clink_redis_operation_timeout_seconds == 1.0


def test_server_profile_requires_a_valid_nonempty_redis_url():
    with pytest.raises(ValueError, match="CLINK_REDIS_URL"):
        AppConfig(clink_profile="server")
    with pytest.raises(ValueError, match="CLINK_REDIS_URL"):
        AppConfig(clink_profile="server", clink_redis_url="https://redis.example")


def test_from_env_reads_server_profile_and_redacts_redis_url(monkeypatch):
    redis_url = "rediss://user:test-password@redis.example:6380/0"
    monkeypatch.setenv("CLINK_PROFILE", "server")
    monkeypatch.setenv("CLINK_REDIS_URL", redis_url)

    config = AppConfig.from_env()
    description = json.dumps(config.describe(), sort_keys=True)

    assert config.clink_profile == "server"
    assert config.clink_redis_url == redis_url
    assert config.describe()["clink_redis_url"] == "<redacted>"
    assert redis_url not in description
    assert "test-password" not in description


def test_personal_profile_does_not_require_a_misttrack_rate_limit():
    config = AppConfig(
        clink_profile="personal",
        misttrack_api_key="test-key",
    )

    assert config.misttrack_rate_limit_requests_per_window is None
    assert config.misttrack_rate_limit_window_seconds is None


def test_server_with_misttrack_key_requires_a_complete_positive_rate_limit():
    base = {
        "clink_profile": "server",
        "clink_redis_url": "redis://redis.example:6379/0",
        "misttrack_api_key": "test-key",
    }

    with pytest.raises(ValueError, match="MISTTRACK_RATE_LIMIT"):
        AppConfig(**base)
    with pytest.raises(ValueError, match="MISTTRACK_RATE_LIMIT"):
        AppConfig(
            **base,
            misttrack_rate_limit_requests_per_window=10,
        )
    with pytest.raises(ValueError, match="MISTTRACK_RATE_LIMIT"):
        AppConfig(
            **base,
            misttrack_rate_limit_requests_per_window=10,
            misttrack_rate_limit_window_seconds=0,
        )

    config = AppConfig(
        **base,
        misttrack_rate_limit_requests_per_window=10,
        misttrack_rate_limit_window_seconds=60,
    )
    assert config.misttrack_rate_limit_requests_per_window == 10
    assert config.misttrack_rate_limit_window_seconds == 60


def test_optional_rate_limit_values_are_paired_when_configured():
    with pytest.raises(ValueError, match="MISTTRACK_RATE_LIMIT"):
        AppConfig(misttrack_rate_limit_window_seconds=60)
    with pytest.raises(ValueError, match="MISTTRACK_RATE_LIMIT"):
        AppConfig(
            misttrack_rate_limit_requests_per_window=True,
            misttrack_rate_limit_window_seconds=60,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("misttrack_timeout_seconds", 31.0, "MISTTRACK_TIMEOUT_SECONDS"),
        ("misttrack_max_attempts", 6, "MISTTRACK_MAX_ATTEMPTS"),
        (
            "misttrack_rate_limit_requests_per_window",
            1001,
            "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW",
        ),
        (
            "misttrack_rate_limit_window_seconds",
            3601,
            "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS",
        ),
        ("risk_cache_ttl_seconds", 86401, "CLINK_RISK_CACHE_TTL_SECONDS"),
    ],
)
def test_misttrack_runtime_values_have_conservative_maxima(field, value, message):
    values = {field: value}
    if field.startswith("misttrack_rate_limit_"):
        values.setdefault("misttrack_rate_limit_requests_per_window", 10)
        values.setdefault("misttrack_rate_limit_window_seconds", 60)
    with pytest.raises(ValueError, match=message):
        AppConfig(**values)


@pytest.mark.parametrize(
    "timeout",
    [0, -1, True, float("nan"), float("inf"), float("-inf")],
)
def test_redis_operation_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="CLINK_REDIS_OPERATION_TIMEOUT_SECONDS"):
        AppConfig(clink_redis_operation_timeout_seconds=timeout)


def test_redis_operation_timeout_has_a_conservative_hard_maximum():
    with pytest.raises(
        ValueError,
        match="CLINK_REDIS_OPERATION_TIMEOUT_SECONDS.*at most",
    ):
        AppConfig(clink_redis_operation_timeout_seconds=5.1)


def test_from_env_parses_server_rate_limit_and_redis_timeout(monkeypatch):
    monkeypatch.setenv("CLINK_PROFILE", "server")
    monkeypatch.setenv("CLINK_REDIS_URL", "redis://redis.example:6379/0")
    monkeypatch.setenv("MISTTRACK_API_KEY", "test-key")
    monkeypatch.setenv("MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW", "12")
    monkeypatch.setenv("MISTTRACK_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("CLINK_REDIS_OPERATION_TIMEOUT_SECONDS", "0.75")

    config = AppConfig.from_env()

    assert config.misttrack_rate_limit_requests_per_window == 12
    assert config.misttrack_rate_limit_window_seconds == 60
    assert config.clink_redis_operation_timeout_seconds == 0.75


def test_core_requirements_include_supported_redis_client():
    requirements = (ROOT / "requirements.txt").read_text().splitlines()

    assert "redis>=5,<8" in requirements


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("risk_provider", "other", "CLINK_RISK_PROVIDER"),
        ("risk_provider", None, "CLINK_RISK_PROVIDER"),
        ("risk_mode", "observe", "CLINK_RISK_MODE"),
        ("risk_mode", None, "CLINK_RISK_MODE"),
        ("misttrack_api_key", None, "MISTTRACK_API_KEY"),
        ("misttrack_base_url", None, "MISTTRACK_BASE_URL"),
        (
            "misttrack_base_url",
            "http://openapi.misttrack.io",
            "official HTTPS host",
        ),
        (
            "misttrack_base_url",
            "https://openapi.misttrack.io.evil.example",
            "official HTTPS host",
        ),
        ("misttrack_timeout_seconds", 0, "MISTTRACK_TIMEOUT_SECONDS"),
        ("misttrack_timeout_seconds", float("inf"), "MISTTRACK_TIMEOUT_SECONDS"),
        ("misttrack_timeout_seconds", float("nan"), "MISTTRACK_TIMEOUT_SECONDS"),
        ("misttrack_max_attempts", 0, "MISTTRACK_MAX_ATTEMPTS"),
        ("misttrack_max_attempts", True, "MISTTRACK_MAX_ATTEMPTS"),
        ("risk_max_age_seconds", 0, "CLINK_RISK_MAX_AGE_SECONDS"),
        ("risk_cache_ttl_seconds", False, "CLINK_RISK_CACHE_TTL_SECONDS"),
        ("risk_hold_score", True, "CLINK_RISK_HOLD_SCORE"),
        ("risk_deny_score", "71", "CLINK_RISK_DENY_SCORE"),
    ],
)
def test_risk_configuration_is_strict(field, value, message):
    with pytest.raises(ValueError, match=message):
        AppConfig(**{field: value})


def test_risk_score_thresholds_must_be_ordered():
    with pytest.raises(ValueError, match="CLINK_RISK_HOLD_SCORE"):
        AppConfig(risk_hold_score=0, risk_deny_score=71)
    with pytest.raises(ValueError, match="CLINK_RISK_HOLD_SCORE"):
        AppConfig(risk_hold_score=71, risk_deny_score=71)
    with pytest.raises(ValueError, match="CLINK_RISK_DENY_SCORE"):
        AppConfig(risk_hold_score=31, risk_deny_score=101)


@pytest.mark.parametrize(
    ("hold_score", "deny_score"),
    [(32, 71), (31, 72), (40, 90)],
)
def test_enforce_rejects_thresholds_weaker_than_misttrack_policy_v1(
    hold_score, deny_score
):
    with pytest.raises(ValueError, match="misttrack-policy-v1"):
        AppConfig(
            risk_mode="enforce",
            risk_hold_score=hold_score,
            risk_deny_score=deny_score,
        )


def test_enforce_allows_conservative_thresholds():
    config = AppConfig(
        risk_mode="enforce",
        risk_hold_score=20,
        risk_deny_score=70,
    )

    assert config.risk_hold_score == 20
    assert config.risk_deny_score == 70


def test_shadow_allows_threshold_experiments():
    config = AppConfig(
        risk_mode="shadow",
        risk_hold_score=40,
        risk_deny_score=90,
    )

    assert config.risk_hold_score == 40
    assert config.risk_deny_score == 90


def test_from_env_uses_only_new_risk_names(monkeypatch):
    monkeypatch.setenv("CREDITMODEL_BASE_URL", "https://legacy.example")
    monkeypatch.setenv("CREDITMODEL_API_KEY", "legacy-secret")
    monkeypatch.setenv("CREDITMODEL_MODE", "enforce")
    monkeypatch.setenv("CLINK_RISK_MODE", "shadow")

    config = AppConfig.from_env()
    serialized = json.dumps(config.describe(), sort_keys=True)

    assert config.risk_provider == "misttrack"
    assert config.risk_mode == "shadow"
    assert "legacy-secret" not in serialized
    assert not hasattr(config, "credit_model_api_key")


def test_from_env_parses_exact_misttrack_risk_settings(monkeypatch):
    monkeypatch.setenv("CLINK_RISK_PROVIDER", "misttrack")
    monkeypatch.setenv("CLINK_RISK_MODE", "shadow")
    monkeypatch.setenv("MISTTRACK_API_KEY", "test-key")
    monkeypatch.setenv("MISTTRACK_BASE_URL", "https://openapi.misttrack.io")
    monkeypatch.setenv("MISTTRACK_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("MISTTRACK_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CLINK_RISK_HOLD_SCORE", "20")
    monkeypatch.setenv("CLINK_RISK_DENY_SCORE", "80")
    monkeypatch.setenv("CLINK_RISK_MAX_AGE_SECONDS", "120")
    monkeypatch.setenv("CLINK_RISK_CACHE_TTL_SECONDS", "60")

    config = AppConfig.from_env()

    assert config.risk_provider == "misttrack"
    assert config.risk_mode == "shadow"
    assert config.misttrack_api_key == "test-key"
    assert config.misttrack_base_url == "https://openapi.misttrack.io"
    assert config.misttrack_timeout_seconds == 3.5
    assert config.misttrack_max_attempts == 3
    assert config.risk_hold_score == 20
    assert config.risk_deny_score == 80
    assert config.risk_max_age_seconds == 120
    assert config.risk_cache_ttl_seconds == 60


@pytest.mark.parametrize(
    "spender_field",
    [
        "clink_funding_spender_address",
        "clink_polygon_spender_address",
        "clink_base_spender_address",
    ],
)
def test_native_readiness_fails_closed_when_approval_spender_differs_from_relayer(
    tmp_path, spender_field
):
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    values = {
        "funding_database_url": f"sqlite+pysqlite:///{tmp_path / 'readiness.sqlite3'}",
        "clink_live_funding": True,
        "risk_mode": "enforce",
        "misttrack_api_key": "test-key",
        "clink_native_facilitator_enabled": True,
        "polygon_rpc_url": "https://polygon-rpc.example",
        "base_rpc_url": "https://base-rpc.example",
        "clink_native_facilitator_relayer_private_key": relayer_key,
        "clink_polygon_usdc_address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        "clink_base_usdc_address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "clink_funding_spender_address": relayer,
        "clink_polygon_spender_address": relayer,
        "clink_base_spender_address": relayer,
    }
    values[spender_field] = "0x" + "9" * 40
    service = FundingService(config=AppConfig(**values))

    readiness = service.get_funding_readiness()

    assert readiness["status"] == "not_ready"
    assert readiness["native_facilitator_ready"] is False
    assert any("must match the relayer address" in item for item in readiness["missing"])


@pytest.mark.parametrize(
    ("receipt_key", "internal_token", "message"),
    [
        ("", "internal-api-token-" + "1" * 32, "is required"),
        (
            "short-receipt-key",
            "internal-api-token-" + "1" * 32,
            "at least 32 bytes",
        ),
        (
            "replace-with-a-different-long-random-secret",
            "internal-api-token-" + "1" * 32,
            "non-placeholder",
        ),
        (
            "shared-authority-secret-" + "2" * 32,
            "shared-authority-secret-" + "2" * 32,
            "independent from CLINK_CORE_INTERNAL_API_TOKEN",
        ),
    ],
    ids=("missing", "weak", "placeholder", "internal-token-reuse"),
)
def test_native_readiness_requires_independent_receipt_signing_key(
    tmp_path, receipt_key, internal_token, message
):
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'receipt-readiness.sqlite3'}",
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            polygon_rpc_url="https://polygon-rpc.example",
            base_rpc_url="https://base-rpc.example",
            clink_native_facilitator_relayer_private_key=relayer_key,
            clink_funding_spender_address=relayer,
            clink_polygon_spender_address=relayer,
            clink_base_spender_address=relayer,
            clink_internal_api_token=internal_token,
            clink_receipt_signing_key=receipt_key,
        )
    )

    readiness = service.get_funding_readiness()

    assert readiness["status"] == "not_ready"
    assert readiness["native_facilitator_ready"] is False
    assert any(message in item for item in readiness["missing"])


def test_funding_readiness_advertises_universal_payer_contract(tmp_path):
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    polygon_usdc = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
    base_usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'payer-readiness.sqlite3'}",
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            polygon_rpc_url="https://polygon-rpc.example",
            base_rpc_url="https://base-rpc.example",
            clink_native_facilitator_relayer_private_key=relayer_key,
            clink_funding_spender_address=relayer,
            clink_polygon_spender_address=relayer,
            clink_base_spender_address=relayer,
            clink_polygon_usdc_address=polygon_usdc,
            clink_base_usdc_address=base_usdc,
            clink_internal_api_token="internal-api-token-" + "1" * 32,
            clink_receipt_signing_key="independent-receipt-signing-key-" + "2" * 32,
        )
    )

    readiness = service.get_funding_readiness()

    assert readiness["status"] == "ready"
    assert readiness["universal_payer_ready"] is True
    assert readiness["payer_address"] == relayer
    assert readiness["automatic_payment_rail"] == "clink_payer_proxy"
    assert readiness["supported_assets"] == {
        "eip155:137": polygon_usdc,
        "eip155:8453": base_usdc,
    }
    assert readiness["mandate_limits_enforced"] == [
        "per_transaction",
        "rolling_hour",
        "daily",
        "total",
    ]


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("CLINK_ACCOUNT_SESSION_TTL_SECONDS", "0", "TTL must be positive"),
        ("CLINK_ACCOUNT_ALLOWED_PRODUCTS", "", "allowed products"),
        (
            "CLINK_ACCOUNT_PUBLIC_BASE_URL",
            "https://user:password@account.example.com",
            "must not contain credentials",
        ),
    ],
)
def test_account_runtime_config_fails_closed(monkeypatch, name, value, message):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        AppConfig.from_env()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8019",
        "http://127.0.0.9:8019",
        "http://[::1]:8019",
    ],
)
def test_loopback_account_urls_keep_local_development_ergonomics(url):
    config = AppConfig(
        account_public_base_url=url,
        clink_internal_api_token="replace-with-a-long-random-secret",
    )
    assert config.account_public_base_url == url


def test_non_loopback_account_http_url_is_rejected():
    with pytest.raises(ValueError, match="HTTPS"):
        AppConfig(
            account_public_base_url="http://account.example.com",
            clink_internal_api_token="production-token-value",
        )


@pytest.mark.parametrize(
    "token", ["", "replace-with-a-long-random-secret", "changeme"]
)
def test_production_account_url_rejects_placeholder_internal_tokens(token):
    with pytest.raises(ValueError, match="CLINK_CORE_INTERNAL_API_TOKEN"):
        AppConfig(
            account_public_base_url="https://account.example.com",
            clink_internal_api_token=token,
        )


def test_production_account_url_accepts_non_placeholder_internal_token():
    config = AppConfig(
        account_public_base_url="https://account.example.com",
        clink_internal_api_token="4d42e8fd19ea47df824ef58bf9ff30c8",
    )
    assert config.account_public_base_url == "https://account.example.com"


def test_account_session_uses_configured_public_url_and_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
    )
    monkeypatch.setenv("CLINK_ACCOUNT_PUBLIC_BASE_URL", "https://account.example.com")
    monkeypatch.setenv("CLINK_ACCOUNT_SESSION_TTL_SECONDS", "90")
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "internal-token")
    app = create_app(clock=lambda: NOW, approval_targets={})

    async def create_session():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://account.internal"
        ) as client:
            return await client.post(
                "/internal/account-sessions",
                headers={"Authorization": "Bearer internal-token"},
                json={"user_id": "user_1"},
            )

    response = asyncio.run(create_session())

    assert response.status_code == 201
    payload = response.json()
    assert payload["account_url"] == (
        f"https://account.example.com/account/{payload['session_id']}"
    )
    assert datetime.fromisoformat(payload["expires_at"]) == NOW + timedelta(seconds=90)


def test_account_service_exposes_healthz_without_internal_auth(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
    )
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "internal-token")
    app = create_app(clock=lambda: NOW, approval_targets={})

    async def health():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://account.internal"
        ) as client:
            return await client.get("/healthz")

    response = asyncio.run(health())

    assert response.status_code == 200
    assert response.json() == {"service": "account_service", "status": "ok"}


def test_policy_service_exposes_standard_health_contract():
    app = create_policy_app()

    async def health():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://policy.internal"
        ) as client:
            return await client.get("/healthz")

    response = asyncio.run(health())

    assert response.status_code == 200
    assert response.json() == {
        "service": "policy_service",
        "status": "ok",
        "risk_provider": {
            "provider": APP_CONFIG.risk_provider,
            "mode": APP_CONFIG.risk_mode,
            "configured": bool(APP_CONFIG.misttrack_api_key),
        },
    }


def test_explicit_zero_account_session_ttl_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
    )
    with pytest.raises(ValueError, match="TTL must be positive"):
        create_app(
            clock=lambda: NOW,
            session_ttl=timedelta(0),
            approval_targets={},
        )


def test_runtime_scripts_cover_account_service_migrations_and_safe_status(tmp_path):
    run_text = (ROOT / "run_demo.sh").read_text()
    stop_text = (ROOT / "run_demo_stop.sh").read_text()
    assert run_text.index("\nensure_runtime_is_available\n\n") < run_text.index(
        'if [ ! -f ".env" ]; then'
    )
    assert run_text.index("alembic upgrade head") < run_text.index(
        'start_service "account_service"'
    )
    assert (
        'start_service "account_service" '
        'python3 -m services.account_service.app'
    ) in run_text
    assert run_text.index("check_runtime_schema.py") < run_text.index(
        'start_service "account_service"'
    )
    assert run_text.index("check_runtime_schema.py") < run_text.index(
        "import_legacy_action_policy_jsonl.py"
    )
    assert run_text.index("import_legacy_action_policy_jsonl.py") < run_text.index(
        'start_service "action_service"'
    )
    assert "${ACCOUNT_SERVICE_PORT:-8019}" in stop_text

    status_script = tmp_path / "run_demo_status.sh"
    shutil.copy(ROOT / "run_demo_status.sh", status_script)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(ROOT / "scripts/runtime_process_identity.sh", scripts_dir)
    runtime = tmp_path / ".demo_runtime"
    runtime.mkdir()
    (runtime / "pids.tsv").write_text(
        "account_service\t999999\t/tmp/account-service.log\n"
    )
    (tmp_path / ".env").write_text(
        "ACCOUNT_SERVICE_HOST=127.0.0.9\n"
        "ACCOUNT_SERVICE_PORT=8119\n"
        "CLINK_CORE_INTERNAL_API_TOKEN=must-not-print\n"
        "CLINK_RECEIPT_SIGNING_KEY=receipt-key-must-not-print\n"
    )
    result = run_bounded(
        ["bash", str(status_script)],
        timeout=5,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "account_service" in result.stdout
    assert "stale" in result.stdout
    assert "http://127.0.0.9:8119" in result.stdout
    assert "must-not-print" not in result.stdout
    assert "receipt-key-must-not-print" not in result.stdout


def test_runtime_config_guard_rejects_placeholder_without_leaking_it():
    secret = "replace-with-a-long-random-secret"
    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/check_runtime_config.py")],
        timeout=5,
        cwd=ROOT,
        env={
            **os.environ,
            "CLINK_ACCOUNT_PUBLIC_BASE_URL": "https://account.example.com",
            "CLINK_CORE_INTERNAL_API_TOKEN": secret,
            "PYTHONPATH": ".",
        },
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "runtime configuration is invalid" in output
    assert secret not in output


def test_runtime_config_guard_requires_both_native_network_rpcs_without_leaking_urls():
    polygon_url = "https://polygon-rpc.example/private-key"
    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/check_runtime_config.py")],
        timeout=5,
        cwd=ROOT,
        env={
            **os.environ,
            "CLINK_ACCOUNT_PUBLIC_BASE_URL": "https://account.example.com",
            "CLINK_CORE_INTERNAL_API_TOKEN": "runtime-secret-not-a-placeholder",
            "CLINK_NATIVE_FACILITATOR_ENABLED": "true",
            "CLINK_POLYGON_RPC_URL": polygon_url,
            "CLINK_BASE_RPC_URL": "",
            "PYTHONPATH": ".",
        },
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "runtime configuration is invalid" in output
    assert polygon_url not in output


def test_readme_describes_semantic_legacy_product_coverage():
    readme = (ROOT / "README.md").read_text().lower()

    operator_report = next(
        paragraph
        for paragraph in readme.split("\n\n")
        if "operator report" in paragraph and "legacy" in paragraph
    )
    assert "product" in operator_report
    assert "active or pending unified grant" in operator_report
    assert "not covered" in operator_report


@pytest.mark.parametrize(
    "script",
    [
        "run_demo.sh",
        "run_demo_stop.sh",
        "run_demo_status.sh",
        "scripts/runtime_process_identity.sh",
        "scripts/run_core_runtime_lifecycle_smoke.sh",
    ],
)
def test_runtime_scripts_have_valid_shell_syntax(script):
    run_bounded(["bash", "-n", str(ROOT / script)], timeout=5, check=True)


def test_executable_runtime_lifecycle_harness():
    result = run_bounded(
        ["bash", str(ROOT / "scripts/run_core_runtime_lifecycle_smoke.sh")],
        timeout=35,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "configuration failure prefix: config only" in result.stdout
    assert "migration failure prefix: config, migration" in result.stdout
    assert "schema failure prefix: config, migration, schema" in result.stdout
    assert (
        "already-running runtime: exited before config, migration, schema, and legacy import"
        in result.stdout
    )
    assert (
        "legacy import failure prefix: config, migration, schema, legacy import"
        in result.stdout
    )
    assert "already-running runtime: skipped unreadable .env files" in result.stdout
    assert "reused pid metadata: stale in status" in result.stdout
    assert "account_service: running" in result.stdout
    assert "successful lifecycle: ordered prefix and account service stopped" in result.stdout
    assert "identity changed after TERM: SIGKILL skipped" in result.stdout


def test_runtime_lifecycle_reaper_activation_is_a_failure():
    result = run_bounded(
        ["bash", str(ROOT / "scripts/run_core_runtime_lifecycle_smoke.sh")],
        timeout=35,
        cwd=ROOT,
        env={
            **os.environ,
            "CLINK_LIFECYCLE_REAPER_GUARD_SELF_TEST": "1",
            "CLINK_LIFECYCLE_REAPER_GUARD_DELAY_SECONDS": "0",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "runner reaper guard activated" in result.stderr
