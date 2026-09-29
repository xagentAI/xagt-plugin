import io
import json
import time
import urllib.error
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from services.action_service.schemas import CreateActionIntentRequest
from services.action_service.service import ActionService
from services.policy_service.risk_provider import RiskProviderError, RiskProviderResult
from services.policy_service.misttrack import MistTrackProvider as ActualMistTrackProvider
from services.policy_service.risk_cache import InMemoryRiskCache
from services.policy_service.schemas import EvaluateActionPolicyRequest, PolicyDecision
from services.policy_service.service import PolicyService
from shared.config import AppConfig


TARGET = "0x1111111111111111111111111111111111111111"
POLYGON_TARGET = "0x2222222222222222222222222222222222222222"
NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)
LEAK_KEY = "policy-test-key-must-not-leak"
LEAK_URL = (
    "https://openapi.misttrack.io/v2/risk_score?api_key=" + LEAK_KEY
)


class FakeRiskProvider:
    def __init__(self, *, score=10, risk_level="low", failure=None):
        self.score = score
        self.risk_level = risk_level.lower()
        self.failure = failure
        self.calls = []

    def assess(self, *, subject: str, network: str, asset: str = "USDC"):
        self.calls.append({"subject": subject, "network": network, "asset": asset})
        if self.failure is not None:
            raise RiskProviderError("provider unavailable", category=self.failure)
        coin = {
            "eip155:8453": "USDC-Base",
            "eip155:137": "USDC-Polygon",
        }[network]
        return RiskProviderResult(
            provider="misttrack",
            endpoint="v2/risk_score",
            subject=subject,
            network=network,
            asset=asset,
            coin=coin,
            score=self.score,
            risk_level=self.risk_level,
            indicators=(),
            risk_details=(),
            hacking_event=None,
            assessed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            response_sha256="a" * 64,
        )


class UnexpectedFailureProvider:
    def assess(self, *, subject: str, network: str, asset: str = "USDC"):
        raise RuntimeError(f"unexpected provider failure at {LEAK_URL}")


class MaliciousCategoryProvider:
    def assess(self, *, subject: str, network: str, asset: str = "USDC"):
        raise RiskProviderError(
            f"provider rejected request at {LEAK_URL}",
            category=LEAK_URL,
        )


class ReadinessLimiter:
    def __init__(self, *, allowed=True, check_failure=None, events=None):
        self.allowed = allowed
        self.check_failure = check_failure
        self.events = events if events is not None else []

    def check_ready(self):
        self.events.append("check_ready")
        if self.check_failure is not None:
            raise self.check_failure

    def acquire(self):
        self.events.append("acquire")
        return (True, 0) if self.allowed else (False, 1_000)


def _service(tmp_path, *, score=10, level="low", mode="enforce", failure=None):
    provider = FakeRiskProvider(score=score, risk_level=level, failure=failure)
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        risk_provider="misttrack",
        risk_mode=mode,
    )
    return PolicyService(config=config, risk_provider=provider), provider


def _request(
    action_type="service_purchase",
    *,
    target=TARGET,
    network="eip155:8453",
    user_confirmed=True,
):
    return EvaluateActionPolicyRequest(
        action_id="act_test",
        user_id="user_test",
        agent_id="hermes",
        action_type=action_type,
        amount_usdc="5",
        merchant_id="merchant_test",
        target_address=target,
        chain=network,
        user_confirmed=user_confirmed,
        requires_confirmation=False,
        metadata={"endpoint": "/api/expensive", "facilitator": "clink_native"},
    )


def _fundable_request(
    service,
    *,
    target=TARGET,
    network="eip155:8453",
    user_confirmed=True,
):
    metadata = {
        "destination": target,
        "network": network,
        "endpoint": "/api/expensive",
        "facilitator": "clink_native",
    }
    action = ActionService(config=service.config).create_intent(
        CreateActionIntentRequest(
            user_id="user_test",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="5",
            metadata=metadata,
        )
    )
    return EvaluateActionPolicyRequest(
        action_id=action.action_id,
        user_id="user_test",
        agent_id="hermes",
        action_type="marketplace_purchase",
        amount_usdc="5",
        target_address=target,
        chain=network,
        user_confirmed=user_confirmed,
        requires_confirmation=False,
        metadata=metadata,
    )


def test_enforce_high_risk_blocks_and_records_normalized_assessment(tmp_path):
    service, provider = _service(tmp_path, score=71, level="High")

    result = service.evaluate(_fundable_request(service))

    assert result.decision == "blocked"
    assert result.reason_code == "RISK_PROVIDER_DENIED"
    assert result.risk_assessment["provider"] == "misttrack"
    assert result.risk_assessment["mapping_version"] == "misttrack-policy-v1"
    assert result.risk_assessment["hold_score"] == 31
    assert result.risk_assessment["deny_score"] == 71
    assert type(result.risk_assessment["hold_score"]) is int
    assert type(result.risk_assessment["deny_score"]) is int
    assert result.risk_assessment["decision"] == "deny"
    assert result.credit_model_assessment is None
    assert provider.calls == [
        {"subject": TARGET, "network": "eip155:8453", "asset": "USDC"}
    ]


def test_moderate_requires_explicit_confirmation(tmp_path):
    service, _ = _service(tmp_path, score=31, level="moderate")

    pending = service.evaluate(_request(user_confirmed=False))
    confirmed = service.evaluate(_request(user_confirmed=True))

    assert pending.approved is False
    assert pending.decision == "needs_confirmation"
    assert pending.reason_code == "RISK_PROVIDER_HOLD"
    assert not any(event["event"] == "risk_hold_confirmed" for event in pending.event_log)
    assert confirmed.approved is True
    assert any(event["event"] == "risk_hold_confirmed" for event in confirmed.event_log)


def test_enforce_unavailable_cannot_be_confirmed(tmp_path):
    service, _ = _service(tmp_path, failure="unavailable")

    result = service.evaluate(_fundable_request(service, user_confirmed=True))

    assert result.approved is False
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.risk_assessment["decision"] == "unavailable"
    assert not any(event["event"] == "risk_hold_confirmed" for event in result.event_log)


def test_unexpected_provider_exception_is_persisted_as_redacted_unavailable(tmp_path):
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
        ),
        risk_provider=UnexpectedFailureProvider(),
    )

    result = service.evaluate(_request())
    persisted = service.get_decision(result.policy_decision_id)
    serialized = json.dumps(
        {"result": result.to_dict(), "persisted": persisted.to_dict()},
        sort_keys=True,
    )

    assert result.approved is False
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.risk_assessment["error_category"] == "provider_error"
    assert persisted.policy_decision_id == result.policy_decision_id
    assert LEAK_KEY not in serialized
    assert LEAK_URL not in serialized
    assert "api_key" not in serialized


def test_malicious_provider_error_category_is_normalized(tmp_path):
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
        ),
        risk_provider=MaliciousCategoryProvider(),
    )

    result = service.evaluate(_request())
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert result.approved is False
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.risk_assessment["error_category"] == "provider_error"
    assert LEAK_KEY not in serialized
    assert LEAK_URL not in serialized
    assert "api_key" not in serialized


@pytest.mark.parametrize("user_confirmed", [False, True])
def test_unavailable_reason_survives_generic_confirmation_gate(
    tmp_path, user_confirmed
):
    service, _ = _service(tmp_path, failure="unavailable")
    request = _request(user_confirmed=user_confirmed)
    request.requires_confirmation = True

    result = service.evaluate(request)

    assert result.approved is False
    assert result.decision == "needs_confirmation"
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.required_action == "resolve_risk_assessment"


def test_hold_reason_survives_generic_confirmation_gate(tmp_path):
    service, _ = _service(tmp_path, score=31, level="moderate")
    request = _request(user_confirmed=False)
    request.requires_confirmation = True

    result = service.evaluate(request)

    assert result.approved is False
    assert result.decision == "needs_confirmation"
    assert result.reason_code == "RISK_PROVIDER_HOLD"
    assert result.required_action == "request_user_confirmation"


def test_unavailable_reason_survives_live_market_confirmation_gate(tmp_path):
    service, _ = _service(tmp_path, failure="unavailable")
    request = _request("market_trade", user_confirmed=False)
    request.live_mode = True

    result = service.evaluate(request)

    assert result.approved is False
    assert result.decision == "needs_confirmation"
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.required_action == "resolve_risk_assessment"


def test_shadow_deny_is_recorded_without_changing_policy(tmp_path):
    service, _ = _service(tmp_path, score=80, level="High", mode="shadow")

    result = service.evaluate(_request())

    assert result.approved is True
    assert result.risk_assessment["decision"] == "deny"
    assert result.risk_assessment["enforced"] is False


def test_shadow_without_key_records_unavailable_without_network(tmp_path):
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="shadow",
            misttrack_api_key="",
        )
    )

    result = service.evaluate(_request())

    assert result.approved is True
    assert result.risk_assessment["decision"] == "unavailable"
    assert result.risk_assessment["error_category"] == "not_configured"


def test_enforce_without_key_is_unavailable_and_cannot_be_confirmed(tmp_path):
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key="",
        )
    )

    result = service.evaluate(_request(user_confirmed=True))

    assert result.approved is False
    assert result.reason_code == "RISK_PROVIDER_UNAVAILABLE"
    assert result.risk_assessment["error_category"] == "not_configured"


def test_configured_provider_factory_uses_all_misttrack_transport_settings(
    tmp_path, monkeypatch
):
    captured = {}
    provider = FakeRiskProvider()

    def factory(**kwargs):
        captured.update(kwargs)
        return provider

    monkeypatch.setattr(
        "services.policy_service.service.MistTrackProvider", factory
    )
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            misttrack_api_key="test-key",
            misttrack_base_url="https://openapi.misttrack.io",
            misttrack_timeout_seconds=3.5,
            misttrack_max_attempts=3,
            risk_cache_ttl_seconds=60,
        )
    )

    assert service.risk_provider is provider
    assert isinstance(captured.pop("cache"), InMemoryRiskCache)
    assert captured.pop("rate_limiter") is None
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://openapi.misttrack.io",
        "timeout_seconds": 3.5,
        "max_attempts": 3,
        "cache_ttl_seconds": 60,
        "cache_fail_closed": False,
    }


def test_server_policy_services_share_the_redis_risk_cache(tmp_path, monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}
            self.set_calls = []
            self.eval_calls = []

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, *, ex):
            self.set_calls.append({"key": key, "value": value, "ex": ex})
            self.values[key] = value
            return True

        def eval(self, script, numkeys, *keys_and_args):
            self.eval_calls.append(
                {
                    "script": script,
                    "numkeys": numkeys,
                    "keys_and_args": keys_and_args,
                }
            )
            return [1, 0]

    class Response:
        def __init__(self):
            self.body = json.dumps(
                {
                    "success": True,
                    "data": {
                        "score": 10,
                        "risk_level": "Low",
                        "detail_list": [],
                        "risk_detail": [],
                        "hacking_event": None,
                    },
                }
            ).encode("utf-8")
            self.offset = 0

        def read(self, limit=-1):
            if limit < 0:
                chunk = self.body[self.offset :]
                self.offset = len(self.body)
                return chunk
            chunk = self.body[self.offset : self.offset + limit]
            self.offset += len(chunk)
            return chunk

    class Transport:
        def __init__(self):
            self.calls = []

        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            return Response()

    shared_redis = FakeRedis()
    redis_factory_calls = []
    transports = [Transport(), Transport()]
    providers = []

    def provider_factory(**kwargs):
        provider = ActualMistTrackProvider(
            **kwargs,
            transport=transports[len(providers)],
            response_limit_bytes=1024,
        )
        providers.append(provider)
        return provider

    import services.policy_service.service as service_module

    monkeypatch.setattr(service_module, "MistTrackProvider", provider_factory)
    monkeypatch.setattr(
        service_module,
        "redis",
        SimpleNamespace(
            Redis=SimpleNamespace(
                from_url=lambda url, **kwargs: (
                    redis_factory_calls.append({"url": url, **kwargs})
                    or shared_redis
                )
            )
        ),
        raising=False,
    )
    config = AppConfig(
        clink_profile="server",
        clink_redis_url="redis://redis.example:6379/0",
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        misttrack_api_key="test-key",
        misttrack_rate_limit_requests_per_window=10,
        misttrack_rate_limit_window_seconds=60,
        clink_redis_operation_timeout_seconds=0.75,
    )

    first_service = PolicyService(config=config)
    second_service = PolicyService(config=config)
    first = first_service.risk_provider.assess(
        subject=TARGET, network="eip155:8453"
    )
    second = second_service.risk_provider.assess(
        subject=TARGET, network="eip155:8453"
    )

    assert first_service.risk_provider is not second_service.risk_provider
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(transports[0].calls) == 1
    assert transports[1].calls == []
    assert shared_redis.set_calls
    assert len(shared_redis.eval_calls) == 1
    assert all(
        provider._cache._client is provider._rate_limiter._client
        for provider in providers
    )
    assert all(provider._cache_fail_closed is True for provider in providers)
    assert redis_factory_calls == [
        {
            "url": "redis://redis.example:6379/0",
            "socket_timeout": 0.75,
            "socket_connect_timeout": 0.75,
        },
        {
            "url": "redis://redis.example:6379/0",
            "socket_timeout": 0.75,
            "socket_connect_timeout": 0.75,
        },
    ]
    assert all(
        call["key"].startswith("clink:core:risk:misttrack:v1:")
        for call in shared_redis.set_calls
    )


def test_shadow_risk_readiness_is_not_required_without_external_io(
    tmp_path, monkeypatch
):
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="shadow",
            clink_live_funding=False,
        )
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe shadow readiness must not perform I/O")
        ),
    )

    assert service.get_risk_readiness() == {
        "ok": True,
        "detail": "not_required",
    }


def test_enforce_risk_readiness_probes_only_the_official_status_endpoint(
    tmp_path, monkeypatch
):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit=-1):
            return b'{"success":true}'[:limit]

    def open_status(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        return Response()

    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key="test-key",
            misttrack_timeout_seconds=3.5,
        ),
        risk_provider=FakeRiskProvider(),
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen", open_status
    )

    readiness = service.get_risk_readiness()

    assert readiness == {"ok": True, "detail": "reachable"}
    assert calls[0]["request"].method == "GET"
    assert calls[0]["request"].full_url == (
        "https://openapi.misttrack.io/v1/status?api_key=test-key"
    )
    assert calls[0]["timeout"] == 3.5
    assert "test-key" not in json.dumps(readiness)
    assert "https://" not in json.dumps(readiness)


def test_risk_readiness_slow_body_respects_total_wall_clock_budget(
    tmp_path, monkeypatch
):
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def close(self):
            return None

        def read(self, _limit=-1):
            time.sleep(0.2)
            return b'{"success":true}'

    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key="test-key",
            misttrack_timeout_seconds=0.05,
        ),
        risk_provider=FakeRiskProvider(),
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen",
        lambda *_args, **_kwargs: SlowResponse(),
    )

    started_at = time.monotonic()
    readiness = service.get_risk_readiness()
    elapsed = time.monotonic() - started_at

    assert readiness == {"ok": False, "detail": "unavailable"}
    assert elapsed < 0.15


def test_server_readiness_checks_redis_then_charges_status_probe_to_local_quota(
    tmp_path, monkeypatch
):
    events = []
    limiter = ReadinessLimiter(events=events)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit=-1):
            return b'{"success":true}'[:limit]

    def open_status(*_args, **_kwargs):
        events.append("misttrack_status")
        return Response()

    service = PolicyService(
        config=AppConfig(
            clink_profile="server",
            clink_redis_url="redis://redis.example:6379/0",
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key="test-key",
            misttrack_rate_limit_requests_per_window=10,
            misttrack_rate_limit_window_seconds=60,
        ),
        risk_provider=FakeRiskProvider(),
        risk_rate_limiter=limiter,
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen", open_status
    )

    assert service.get_risk_readiness() == {"ok": True, "detail": "reachable"}
    assert events == ["check_ready", "acquire", "misttrack_status"]


def test_server_shadow_with_key_still_checks_redis_quota_and_status(
    tmp_path, monkeypatch
):
    events = []
    limiter = ReadinessLimiter(events=events)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit=-1):
            return b'{"success":true}'[:limit]

    def open_status(*_args, **_kwargs):
        events.append("misttrack_status")
        return Response()

    service = PolicyService(
        config=AppConfig(
            clink_profile="server",
            clink_redis_url="redis://redis.example:6379/0",
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="shadow",
            misttrack_api_key="test-key",
            misttrack_rate_limit_requests_per_window=10,
            misttrack_rate_limit_window_seconds=60,
        ),
        risk_provider=FakeRiskProvider(),
        risk_rate_limiter=limiter,
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen", open_status
    )

    assert service.get_risk_readiness() == {"ok": True, "detail": "reachable"}
    assert events == ["check_ready", "acquire", "misttrack_status"]


def test_server_readiness_reports_full_local_quota_without_misttrack_io(
    tmp_path, monkeypatch
):
    limiter = ReadinessLimiter(allowed=False)
    service = PolicyService(
        config=AppConfig(
            clink_profile="server",
            clink_redis_url="redis://redis.example:6379/0",
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key="test-key",
            misttrack_rate_limit_requests_per_window=10,
            misttrack_rate_limit_window_seconds=60,
        ),
        risk_provider=FakeRiskProvider(),
        risk_rate_limiter=limiter,
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full local quota must stop before MistTrack")
        ),
    )

    readiness = service.get_risk_readiness()

    assert readiness == {"ok": False, "detail": "rate_limited"}
    assert limiter.events == ["check_ready", "acquire"]


def test_server_readiness_fails_closed_on_redis_error_without_misttrack_io(
    tmp_path, monkeypatch
):
    limiter = ReadinessLimiter(check_failure=RuntimeError(LEAK_URL))
    service = PolicyService(
        config=AppConfig(
            clink_profile="server",
            clink_redis_url="redis://redis.example:6379/0",
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key=LEAK_KEY,
            misttrack_rate_limit_requests_per_window=10,
            misttrack_rate_limit_window_seconds=60,
        ),
        risk_provider=FakeRiskProvider(),
        risk_rate_limiter=limiter,
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Redis failure must stop before MistTrack")
        ),
    )

    readiness = service.get_risk_readiness()
    serialized = json.dumps(readiness, sort_keys=True)

    assert readiness == {"ok": False, "detail": "redis_unavailable"}
    assert LEAK_KEY not in serialized
    assert "api_key" not in serialized
    assert "https://" not in serialized


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "invalid_key"),
        (402, "payment_required"),
        (429, "rate_limited"),
        (500, "unavailable"),
        (418, "provider_error"),
    ],
)
def test_risk_readiness_returns_only_safe_http_error_categories(
    tmp_path, monkeypatch, status, expected
):
    error = urllib.error.HTTPError(
        "https://openapi.misttrack.io/v1/status?api_key=" + LEAK_KEY,
        status,
        "provider error " + LEAK_KEY,
        {},
        io.BytesIO(("provider body " + LEAK_KEY).encode("utf-8")),
    )
    service = PolicyService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
            risk_mode="enforce",
            misttrack_api_key=LEAK_KEY,
        ),
        risk_provider=FakeRiskProvider(),
    )
    monkeypatch.setattr(
        "services.policy_service.service.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    readiness = service.get_risk_readiness()
    serialized = json.dumps(readiness, sort_keys=True)

    assert readiness == {"ok": False, "detail": expected}
    assert LEAK_KEY not in serialized
    assert "api_key" not in serialized
    assert "https://" not in serialized


def test_preview_does_not_call_provider(tmp_path):
    service, provider = _service(tmp_path, score=80, level="high")

    result = service.evaluate(_request("prediction_market_order_preview"))

    assert result.approved is True
    assert result.risk_assessment is None
    assert provider.calls == []


def test_polygon_action_uses_polygon_coin(tmp_path):
    service, provider = _service(tmp_path)

    result = service.evaluate(
        _fundable_request(service, target=POLYGON_TARGET, network="eip155:137")
    )

    assert result.approved is True
    assert result.risk_assessment["coin"] == "USDC-Polygon"
    assert provider.calls[0]["network"] == "eip155:137"


def test_amoy_rehearsal_uses_polygon_address_risk_with_explicit_provenance(tmp_path):
    provider = FakeRiskProvider()
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        risk_provider="misttrack",
        risk_mode="enforce",
        clink_facilitator_mode="hosted",
        clink_hosted_rehearsal_network="eip155:80002",
        clink_hosted_rehearsal_rpc_url="https://rpc-amoy.example.test",
        clink_hosted_facilitator_chain_targets={
            "eip155:80002": {
                "origin": "https://hosted.example.test",
                "server_public_jwk": (
                    '{"crv":"P-256","kty":"EC","x":"x","y":"y"}'
                ),
                "executor_contract": "0x3333333333333333333333333333333333333333",
            }
        },
    )
    service = PolicyService(config=config, risk_provider=provider)

    result = service.evaluate(
        _fundable_request(
            service,
            target=POLYGON_TARGET,
            network="eip155:80002",
        )
    )

    assert result.approved is True
    assert provider.calls == [
        {"subject": POLYGON_TARGET, "network": "eip155:137", "asset": "USDC"}
    ]
    assert result.risk_assessment["network"] == "eip155:80002"
    assert result.risk_assessment["provider_network"] == "eip155:137"
    assert result.risk_assessment["coin"] == "USDC-Polygon"


def test_amoy_fundable_policy_requires_the_explicit_rehearsal_gate(tmp_path):
    service, provider = _service(tmp_path)

    result = service.evaluate(
        _fundable_request(
            service,
            target=POLYGON_TARGET,
            network="eip155:80002",
        )
    )

    assert result.approved is False
    assert result.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"
    assert provider.calls == []


def test_prediction_market_order_execute_keeps_bound_polygon_policy_path(tmp_path):
    service, provider = _service(tmp_path)
    metadata = {
        "destination": POLYGON_TARGET,
        "network": "eip155:137",
        "execution_ready": True,
    }
    action = ActionService(config=service.config).create_intent(
        CreateActionIntentRequest(
            user_id="user_test",
            agent_id="hermes",
            action_type="prediction_market_order_execute",
            amount_usdc="5",
            metadata=metadata,
        )
    )

    result = service.evaluate(
        EvaluateActionPolicyRequest(
            action_id=action.action_id,
            user_id="user_test",
            agent_id="hermes",
            action_type="prediction_market_order_execute",
            amount_usdc="5",
            target_address=POLYGON_TARGET,
            chain="eip155:137",
            user_confirmed=True,
            requires_confirmation=False,
            metadata=metadata,
        )
    )

    assert result.approved is True
    assert result.reason_code == "APPROVED"
    assert result.target_address == POLYGON_TARGET
    assert result.chain == "eip155:137"
    assert result.risk_assessment["coin"] == "USDC-Polygon"
    assert provider.calls == [
        {"subject": POLYGON_TARGET, "network": "eip155:137", "asset": "USDC"}
    ]


def test_fundable_action_uses_immutable_destination_and_network(tmp_path):
    service, provider = _service(tmp_path)
    request = _fundable_request(service, target=POLYGON_TARGET, network="eip155:137")

    result = service.evaluate(request)

    assert result.target_address == POLYGON_TARGET
    assert result.chain == "eip155:137"
    assert provider.calls == [
        {"subject": POLYGON_TARGET, "network": "eip155:137", "asset": "USDC"}
    ]


def test_fundable_metadata_cannot_override_immutable_action(tmp_path):
    service, provider = _service(tmp_path)
    request = _fundable_request(service)
    request.metadata = {**request.metadata, "destination": POLYGON_TARGET}

    result = service.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"
    assert provider.calls == []


def test_legacy_credit_model_payload_remains_readable_but_not_current(tmp_path):
    historical = PolicyDecision.model_validate(
        {
            "policy_decision_id": "policy_legacy",
            "approved": True,
            "decision": "approved",
            "reason_code": "APPROVED",
            "user_id": "user_test",
            "agent_id": "hermes",
            "action_type": "service_purchase",
            "amount_usdc": "5",
            "credit_model_assessment": {"decision": "allow"},
            "evaluated_at": "2026-07-01T00:00:00Z",
        }
    )
    service, _ = _service(tmp_path)

    current = service.evaluate(_request())
    persisted_payload = service.repository.policy_decision(current.policy_decision_id)

    assert historical.credit_model_assessment == {"decision": "allow"}
    assert historical.risk_assessment is None
    assert historical.to_dict()["credit_model_assessment"] == {"decision": "allow"}
    assert historical.model_dump()["credit_model_assessment"] == {"decision": "allow"}
    assert json.loads(historical.model_dump_json())["credit_model_assessment"] == {
        "decision": "allow"
    }
    assert current.risk_assessment["provider"] == "misttrack"
    assert current.credit_model_assessment is None
    assert "credit_model_assessment" not in current.to_dict()
    assert "credit_model_assessment" not in current.model_dump()
    assert "credit_model_assessment" not in json.loads(current.model_dump_json())
    assert "credit_model_assessment" not in persisted_payload
