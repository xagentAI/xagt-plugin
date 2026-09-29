import io
import json
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from services.policy_service.misttrack import MistTrackProvider
from services.policy_service.risk_cache import (
    InMemoryRiskCache,
    RedisRiskCache,
    RiskCacheError,
)
from services.policy_service.risk_provider import RiskProviderError, RiskProviderResult
from services.policy_service.risk_rate_limiter import RiskRateLimiterError


TARGET = "0x1111111111111111111111111111111111111111"
TEST_KEY = "test-key"


def low_risk_response(**overrides):
    data = {
        "score": 10,
        "risk_level": "Low",
        "detail_list": [],
        "risk_detail": [],
        "hacking_event": None,
    }
    data.update(overrides)
    return {"success": True, "data": data}


class MutableClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, *, seconds):
        self.now += timedelta(seconds=seconds)


def cached_result(*, subject, assessed_at, expires_at):
    return RiskProviderResult(
        provider="misttrack",
        endpoint="v2/risk_score",
        subject=subject,
        network="eip155:8453",
        asset="USDC",
        coin="USDC-Base",
        score=10,
        risk_level="low",
        indicators=(),
        risk_details=(),
        hacking_event=None,
        assessed_at=assessed_at,
        expires_at=expires_at,
        response_sha256="a" * 64,
    )


def cache_key(subject):
    return ("misttrack", "v2/risk_score", "USDC-Base", subject)


class FakeResponse:
    def __init__(self, payload, *, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self._body = io.BytesIO(body)

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RecordingTransport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, *, url, timeout):
        self.calls.append({"url": url, "timeout": timeout})
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, FakeResponse):
            return outcome
        return FakeResponse(outcome)


class RecordingLimiter:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [(True, 0)]
        self.calls = 0

    def acquire(self):
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def check_ready(self):
        return None


def provider_with(transport, **overrides):
    options = {
        "api_key": TEST_KEY,
        "transport": transport,
        "cache": InMemoryRiskCache(),
        "timeout_seconds": 1,
        "max_attempts": 2,
        "cache_ttl_seconds": 300,
        "response_limit_bytes": 1024,
        "sleep": lambda _delay: None,
    }
    options.update(overrides)
    return MistTrackProvider(**options)


@pytest.mark.parametrize(
    "timeout_seconds",
    [True, float("nan"), float("inf"), float("-inf")],
)
def test_provider_rejects_non_finite_or_boolean_timeouts(timeout_seconds):
    transport = RecordingTransport(low_risk_response())

    with pytest.raises(ValueError, match="timeout_seconds"):
        provider_with(transport, timeout_seconds=timeout_seconds)

    assert transport.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout_seconds": 31.0},
        {"max_attempts": 6},
        {"cache_ttl_seconds": 86401},
    ],
)
def test_provider_rejects_values_over_explicit_maxima(overrides):
    with pytest.raises(ValueError):
        provider_with(RecordingTransport(low_risk_response()), **overrides)


def query(url):
    return parse_qs(urlsplit(url).query)


def http_error(code, *, retry_after=None, body=b"{}"):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        f"https://openapi.misttrack.io/v2/risk_score?api_key={TEST_KEY}",
        code,
        "provider error",
        headers,
        io.BytesIO(body),
    )


def assert_redacted(error):
    rendered = str(error)
    assert TEST_KEY not in rendered
    assert "api_key" not in rendered
    assert "https://" not in rendered


def test_base_and_polygon_use_the_documented_coin_values():
    transport = RecordingTransport(low_risk_response(), low_risk_response())
    provider = provider_with(transport)

    provider.assess(subject=TARGET, network="eip155:8453")
    provider.assess(subject=TARGET, network="eip155:137")

    assert query(transport.calls[0]["url"])["coin"] == ["USDC-Base"]
    assert query(transport.calls[1]["url"])["coin"] == ["USDC-Polygon"]
    assert query(transport.calls[0]["url"])["api_key"] == [TEST_KEY]


@pytest.mark.parametrize("network", ["eip155:1", "eip155:80002"])
def test_provider_rejects_unsupported_network_without_calling_transport(network):
    transport = RecordingTransport(low_risk_response())

    with pytest.raises(RiskProviderError, match="unsupported network") as raised:
        provider_with(transport).assess(subject=TARGET, network=network)

    assert raised.value.category == "unsupported_network"
    assert transport.calls == []
    assert_redacted(raised.value)


@pytest.mark.parametrize(
    "subject",
    [
        "0x111111111111111111111111111111111111111A",
        " 0x1111111111111111111111111111111111111111",
        "0x1234",
    ],
)
def test_provider_accepts_only_canonical_lowercase_evm_addresses(subject):
    transport = RecordingTransport(low_risk_response())

    with pytest.raises(RiskProviderError, match="invalid address") as raised:
        provider_with(transport).assess(subject=subject, network="eip155:8453")

    assert raised.value.category == "invalid_address"
    assert transport.calls == []
    assert_redacted(raised.value)


def test_provider_error_never_contains_key_or_full_url():
    transport = RecordingTransport(urllib.error.URLError(f"offline {TEST_KEY}"))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert_redacted(raised.value)


@pytest.mark.parametrize(
    ("api_key", "risk_detail"),
    [
        ("TeSt-Key", [{"risk_type": "TeSt-Key", "exposure_type": "direct"}]),
        (TEST_KEY, [{"api_key": "redacted"}]),
    ],
)
def test_provider_rejects_key_material_in_normalized_results(api_key, risk_detail):
    outcome = low_risk_response(risk_detail=risk_detail)
    transport = RecordingTransport(outcome, outcome)
    provider = provider_with(transport, api_key=api_key)

    for _ in range(2):
        with pytest.raises(RiskProviderError) as raised:
            provider.assess(subject=TARGET, network="eip155:8453")
        assert raised.value.category == "invalid_response"
        assert api_key.lower() not in str(raised.value).lower()

    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "response_limit,outcome",
    [
        (1024, FakeResponse(None, raw=b"not-json")),
        (8, FakeResponse(None, raw=b'{"success":true}')),
    ],
)
def test_malformed_or_oversized_responses_are_not_cached(response_limit, outcome):
    transport = RecordingTransport(outcome, outcome)
    provider = provider_with(transport, response_limit_bytes=response_limit)

    for _ in range(2):
        with pytest.raises(RiskProviderError) as raised:
            provider.assess(subject=TARGET, network="eip155:8453")
        assert raised.value.category == "invalid_response"
        assert_redacted(raised.value)

    assert len(transport.calls) == 2


def test_provider_rejects_response_limit_over_hard_maximum():
    with pytest.raises(ValueError, match="response_limit_bytes.*at most"):
        provider_with(
            RecordingTransport(low_risk_response()),
            response_limit_bytes=64 * 1024 + 1,
        )


def test_blocking_body_read_is_cancelled_at_total_deadline():
    started = threading.Event()
    release = threading.Event()
    read_timeouts = []

    class SocketProbe:
        def settimeout(self, timeout):
            read_timeouts.append(timeout)

    class BlockingResponse(FakeResponse):
        def __init__(self, payload):
            super().__init__(payload)
            self.fp = type("FakeFile", (), {})()
            self.fp.raw = type("FakeRaw", (), {})()
            self.fp.raw._sock = SocketProbe()

        def read(self, size=-1):
            started.set()
            release.wait()
            return super().read(size)

        def close(self):
            release.set()

        def __exit__(self, *_args):
            release.set()
            return False

    transport = RecordingTransport(BlockingResponse(low_risk_response()))
    provider = provider_with(
        transport,
        timeout_seconds=0.05,
        max_attempts=1,
    )
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(
        provider.assess,
        subject=TARGET,
        network="eip155:8453",
    )
    try:
        assert started.wait(timeout=1)
        started_at = time.monotonic()
        with pytest.raises(RiskProviderError) as raised:
            future.result(timeout=0.2)
        assert time.monotonic() - started_at < 0.15
        assert raised.value.category == "unavailable"
        assert read_timeouts and 0 < read_timeouts[0] <= 0.1
        assert_redacted(raised.value)
    finally:
        release.set()
        pool.shutdown(wait=True)


def test_body_attempt_timeout_retries_with_attempt_budget():
    release = threading.Event()
    read_timeouts = []

    class SocketProbe:
        def settimeout(self, timeout):
            read_timeouts.append(timeout)

    class BlockingResponse(FakeResponse):
        def __init__(self, payload):
            super().__init__(payload)
            self.fp = type("FakeFile", (), {})()
            self.fp.raw = type("FakeRaw", (), {})()
            self.fp.raw._sock = SocketProbe()

        def read(self, size=-1):
            release.wait()
            return super().read(size)

        def close(self):
            release.set()

        def __exit__(self, *_args):
            release.set()
            return False

    transport = RecordingTransport(
        BlockingResponse(low_risk_response()),
        low_risk_response(),
    )
    provider = provider_with(
        transport,
        timeout_seconds=0.05,
        max_attempts=2,
    )
    started_at = time.monotonic()

    result = provider.assess(subject=TARGET, network="eip155:8453")

    assert result.score == 10
    assert len(transport.calls) == 2
    assert transport.calls[0]["timeout"] <= 0.06
    assert read_timeouts and read_timeouts[0] <= 0.06
    assert time.monotonic() - started_at < 0.2


def test_http_402_is_not_retried():
    transport = RecordingTransport(http_error(402))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "payment_required"
    assert len(transport.calls) == 1
    assert_redacted(raised.value)


def test_invalid_key_response_is_not_retried():
    transport = RecordingTransport(
        {"success": False, "message": f"Invalid API key: {TEST_KEY}"}
    )

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "invalid_key"
    assert len(transport.calls) == 1
    assert_redacted(raised.value)


@pytest.mark.parametrize("success", ["false", 0, 1, None])
def test_non_boolean_success_is_invalid_and_not_cached(success):
    response = low_risk_response()
    response["success"] = success
    transport = RecordingTransport(response, response)
    provider = provider_with(transport)

    for _ in range(2):
        with pytest.raises(RiskProviderError) as raised:
            provider.assess(subject=TARGET, network="eip155:8453")
        assert raised.value.category == "invalid_response"
        assert_redacted(raised.value)

    assert len(transport.calls) == 2


@pytest.mark.parametrize("number", ["1e1000000", "9" * 129])
def test_provider_rejects_pathological_decimal_expansion_before_normalizing(number):
    raw = (
        '{"success":true,"data":{"score":10,"risk_level":"low",'
        f'"detail_list":[],"risk_detail":[{{"percentage":{number}}}],'
        '"hacking_event":null}}'
    ).encode()
    transport = RecordingTransport(FakeResponse(None, raw=raw))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "invalid_response"
    assert_redacted(raised.value)
    assert len(transport.calls) == 1


def _nested_list(depth):
    value = "leaf"
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    "hacking_event",
    [_nested_list(32), ["item"] * 300],
    ids=("depth", "count"),
)
def test_provider_rejects_excessive_nested_provider_payloads(hacking_event):
    transport = RecordingTransport(low_risk_response(hacking_event=hacking_event))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "invalid_response"
    assert_redacted(raised.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [http_error(500), urllib.error.URLError("timed out"), TimeoutError("timed out")],
)
def test_retryable_failures_make_exactly_max_attempts(failure):
    transport = RecordingTransport(failure)

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport, max_attempts=3).assess(
            subject=TARGET, network="eip155:8453"
        )

    assert raised.value.category == "unavailable"
    assert len(transport.calls) == 3
    assert_redacted(raised.value)


def test_each_transport_timeout_still_gets_the_configured_max_attempts():
    class AdvancingMonotonic:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            return self.value

    monotonic = AdvancingMonotonic()

    class TimingOutTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            monotonic.value += timeout
            raise TimeoutError("timed out")

    transport = TimingOutTransport()

    with pytest.raises(RiskProviderError) as raised:
        provider_with(
            transport,
            max_attempts=3,
            timeout_seconds=1,
            monotonic=monotonic,
        ).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert [call["timeout"] for call in transport.calls] == [1.0, 1.0, 1.0]
    assert_redacted(raised.value)


def test_body_read_cannot_complete_after_total_deadline():
    class AdvancingMonotonic:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            return self.value

    monotonic = AdvancingMonotonic()

    class LateBodyResponse(FakeResponse):
        def read(self, size=-1):
            monotonic.value += 2.0
            return super().read(size)

    transport = RecordingTransport(
        LateBodyResponse(low_risk_response()), low_risk_response()
    )
    provider = provider_with(
        transport,
        timeout_seconds=1,
        max_attempts=2,
        monotonic=monotonic,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert len(transport.calls) == 1
    assert_redacted(raised.value)


def test_singleflight_follower_wait_is_bounded_and_fails_closed():
    started = threading.Event()
    release = threading.Event()

    class BlockingTransport(RecordingTransport):
        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            started.set()
            assert release.wait(timeout=2)
            return FakeResponse(low_risk_response())

    transport = BlockingTransport(low_risk_response())
    provider = provider_with(transport, timeout_seconds=0.05, max_attempts=1)
    key = ("misttrack", "v2/risk_score", "USDC-Base", TARGET)

    def assess():
        return provider.assess(subject=TARGET, network="eip155:8453")

    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(assess)
        assert started.wait(timeout=2)
        follower = pool.submit(assess)
        try:
            with pytest.raises(RiskProviderError) as raised:
                follower.result(timeout=1)
            assert raised.value.category == "unavailable"
            assert_redacted(raised.value)
        finally:
            release.set()
        with pytest.raises(RiskProviderError) as raised:
            leader.result(timeout=2)
        assert raised.value.category == "unavailable"
        assert_redacted(raised.value)

    assert len(transport.calls) == 1
    assert provider._key_locks == {}


def test_429_retries_when_retry_after_fits_deadline():
    transport = RecordingTransport(http_error(429, retry_after="0"), low_risk_response())

    result = provider_with(transport).assess(
        subject=TARGET, network="eip155:8453"
    )

    assert result.score == 10
    assert len(transport.calls) == 2


@pytest.mark.parametrize("retry_after", ["2", "1.999"])
def test_429_near_deadline_preserves_rate_limited_category(retry_after):
    class AdvancingMonotonic:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            return self.value

    monotonic = AdvancingMonotonic()
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        monotonic.value += delay

    transport = RecordingTransport(
        http_error(429, retry_after=retry_after), low_risk_response()
    )
    provider = provider_with(
        transport,
        timeout_seconds=1,
        max_attempts=2,
        monotonic=monotonic,
        sleep=sleep,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "rate_limited"
    assert len(transport.calls) == 1
    assert sleeps == []
    assert_redacted(raised.value)


@pytest.mark.parametrize(
    "retry_after",
    [None, "invalid", "999", "-1", "NaN", "Infinity", "-Infinity"],
)
def test_429_does_not_retry_without_acceptable_retry_after(retry_after):
    transport = RecordingTransport(http_error(429, retry_after=retry_after))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport).assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "rate_limited"
    assert len(transport.calls) == 1
    assert_redacted(raised.value)


def test_second_identical_lookup_before_expiry_uses_cache():
    transport = RecordingTransport(low_risk_response())
    provider = provider_with(transport)

    first = provider.assess(subject=TARGET, network="eip155:8453")
    second = provider.assess(subject=TARGET, network="eip155:8453")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.response_sha256 == first.response_sha256
    assert len(transport.calls) == 1


def test_cache_hit_does_not_consume_a_second_rate_limit_slot():
    transport = RecordingTransport(low_risk_response())
    limiter = RecordingLimiter()
    provider = provider_with(transport, rate_limiter=limiter)

    provider.assess(subject=TARGET, network="eip155:8453")
    cached = provider.assess(subject=TARGET, network="eip155:8453")

    assert cached.cache_hit is True
    assert limiter.calls == 1
    assert len(transport.calls) == 1


def test_local_rate_limit_rejection_stops_before_transport():
    transport = RecordingTransport(low_risk_response())
    limiter = RecordingLimiter((False, 1_000))

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport, rate_limiter=limiter).assess(
            subject=TARGET,
            network="eip155:8453",
        )

    assert raised.value.category == "rate_limited"
    assert_redacted(raised.value)
    assert limiter.calls == 1
    assert transport.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        RiskRateLimiterError("risk rate limiter unavailable"),
        RuntimeError("redis failed " + TEST_KEY),
    ],
)
def test_rate_limiter_failure_is_safe_unavailable_without_transport(failure):
    transport = RecordingTransport(low_risk_response())
    limiter = RecordingLimiter(failure)

    with pytest.raises(RiskProviderError) as raised:
        provider_with(transport, rate_limiter=limiter).assess(
            subject=TARGET,
            network="eip155:8453",
        )

    assert raised.value.category == "unavailable"
    assert_redacted(raised.value)
    assert limiter.calls == 1
    assert transport.calls == []


def test_each_real_retry_consumes_one_rate_limit_slot():
    transport = RecordingTransport(http_error(500), low_risk_response())
    limiter = RecordingLimiter((True, 0), (True, 0))

    result = provider_with(
        transport,
        rate_limiter=limiter,
        max_attempts=2,
    ).assess(subject=TARGET, network="eip155:8453")

    assert result.score == 10
    assert limiter.calls == 2
    assert len(transport.calls) == 2


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, float("inf")])
def test_in_memory_cache_requires_a_positive_integer_capacity(capacity):
    with pytest.raises(ValueError, match="capacity"):
        InMemoryRiskCache(capacity=capacity)


def test_in_memory_cache_sweeps_cold_expired_entries_on_set():
    started = datetime(2026, 7, 31, tzinfo=UTC)
    clock = MutableClock(started)
    cache = InMemoryRiskCache(clock=clock, capacity=3)
    subjects = [f"0x{value:040x}" for value in range(1, 5)]

    for subject in subjects[:2]:
        cache.set(
            cache_key(subject),
            cached_result(
                subject=subject,
                assessed_at=started,
                expires_at=started + timedelta(seconds=5),
            ),
            100,
        )
    cache.set(
        cache_key(subjects[2]),
        cached_result(
            subject=subjects[2],
            assessed_at=started,
            expires_at=started + timedelta(seconds=100),
        ),
        100,
    )

    clock.advance(seconds=10)
    cache.set(
        cache_key(subjects[3]),
        cached_result(
            subject=subjects[3],
            assessed_at=started,
            expires_at=started + timedelta(seconds=100),
        ),
        100,
    )

    assert len(cache._entries) == 2
    assert cache.get(cache_key(subjects[0])) is None
    assert cache.get(cache_key(subjects[1])) is None
    assert cache.get(cache_key(subjects[2])).subject == subjects[2]
    assert cache.get(cache_key(subjects[3])).subject == subjects[3]


def test_in_memory_cache_evicts_the_least_recently_used_entry():
    started = datetime(2026, 7, 31, tzinfo=UTC)
    clock = MutableClock(started)
    cache = InMemoryRiskCache(clock=clock, capacity=2)
    subjects = [f"0x{value:040x}" for value in range(1, 4)]

    for subject in subjects[:2]:
        cache.set(
            cache_key(subject),
            cached_result(
                subject=subject,
                assessed_at=started,
                expires_at=started + timedelta(seconds=100),
            ),
            100,
        )
    assert cache.get(cache_key(subjects[0])).subject == subjects[0]

    cache.set(
        cache_key(subjects[2]),
        cached_result(
            subject=subjects[2],
            assessed_at=started,
            expires_at=started + timedelta(seconds=100),
        ),
        100,
    )

    assert cache.get(cache_key(subjects[1])) is None
    assert cache.get(cache_key(subjects[0])).subject == subjects[0]
    assert cache.get(cache_key(subjects[2])).subject == subjects[2]


@pytest.mark.parametrize(
    "mutation",
    [
        {"subject": "0x2222222222222222222222222222222222222222"},
        {"network": "eip155:137"},
        {"asset": "DAI"},
        {"coin": "USDC-Polygon"},
    ],
)
def test_provider_ignores_cache_entries_not_bound_to_the_request(mutation):
    valid = provider_with(RecordingTransport(low_risk_response())).assess(
        subject=TARGET, network="eip155:8453"
    )

    class PoisonedCache:
        def get(self, _key):
            return replace(valid, **mutation)

        def set(self, _key, _result, _ttl_seconds):
            return None

    transport = RecordingTransport(low_risk_response())
    result = provider_with(transport, cache=PoisonedCache()).assess(
        subject=TARGET, network="eip155:8453"
    )

    assert result.subject == TARGET
    assert result.network == "eip155:8453"
    assert result.asset == "USDC"
    assert result.coin == "USDC-Base"
    assert result.cache_hit is False
    assert len(transport.calls) == 1


def test_redis_cache_uses_injected_client_and_stores_only_normalized_json():
    class RedisLike:
        def __init__(self):
            self.values = {}
            self.set_calls = []

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, *, ex):
            self.set_calls.append({"key": key, "value": value, "ex": ex})
            self.values[key] = value
            return True

    client = RedisLike()
    cache = RedisRiskCache(client)
    first_transport = RecordingTransport(
        low_risk_response(risk_detail=[{"percentage": 2.5}])
    )
    first = provider_with(first_transport, cache=cache).assess(
        subject=TARGET, network="eip155:8453"
    )
    second_transport = RecordingTransport(low_risk_response())
    second = provider_with(second_transport, cache=cache).assess(
        subject=TARGET, network="eip155:8453"
    )

    stored = client.set_calls[0]
    assert stored["ex"] == 300
    assert TEST_KEY not in stored["key"] + stored["value"]
    assert "api_key" not in stored["key"] + stored["value"]
    assert "https://" not in stored["key"] + stored["value"]
    assert '"percentage":"2.5"' in stored["value"]
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second_transport.calls == []


@pytest.mark.parametrize(
    "risk_detail",
    [
        {"api_key": "redacted"},
        {"misttrack_api_key": "redacted"},
        {"apikey": "redacted"},
        {"api-key": "redacted"},
        {"api key": "redacted"},
        {"note": "api_key=redacted"},
        {"note": "api_key = redacted"},
    ],
)
def test_redis_cache_refuses_non_normalized_key_named_fields(risk_detail):
    class RedisLike:
        def __init__(self):
            self.set_calls = []

        def get(self, _key):
            return None

        def set(self, *args, **kwargs):
            self.set_calls.append((args, kwargs))
            return True

    result = provider_with(RecordingTransport(low_risk_response())).assess(
        subject=TARGET, network="eip155:8453"
    )
    client = RedisLike()
    cache = RedisRiskCache(client)

    with pytest.raises(ValueError, match="normalized"):
        cache.set(
            ("misttrack", "v2/risk_score", "USDC-Base", TARGET),
            replace(result, risk_details=(risk_detail,)),
            300,
        )

    assert client.set_calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(score=101),
        lambda payload: payload.update(risk_level="unknown"),
        lambda payload: payload.update(response_sha256="g" * 64),
        lambda payload: payload.update(cache_hit="false"),
        lambda payload: payload.update(expires_at=payload["assessed_at"]),
    ],
)
def test_redis_cache_decode_rejects_untrusted_result_fields(mutation):
    class RedisLike:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, *, ex):
            self.values[key] = value
            return True

    client = RedisLike()
    cache = RedisRiskCache(client)
    key = cache_key(TARGET)
    now = datetime.now(UTC)
    cache.set(
        key,
        cached_result(
            subject=TARGET,
            assessed_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=300),
        ),
        300,
    )
    redis_key = next(iter(client.values))
    payload = json.loads(client.values[redis_key])
    mutation(payload)
    client.values[redis_key] = json.dumps(payload)

    with pytest.raises(RiskCacheError, match="unavailable"):
        cache.get(key)


def test_fail_closed_cache_get_acl_error_stops_before_limiter_and_transport():
    class GetDeniedRedis:
        def get(self, _key):
            raise RuntimeError("NOPERM GET " + TEST_KEY)

        def set(self, *_args, **_kwargs):
            raise AssertionError("cache SET must not run after GET failure")

    transport = RecordingTransport(low_risk_response())
    limiter = RecordingLimiter()
    provider = provider_with(
        transport,
        cache=RedisRiskCache(GetDeniedRedis()),
        cache_fail_closed=True,
        rate_limiter=limiter,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert_redacted(raised.value)
    assert limiter.calls == 0
    assert transport.calls == []


def test_fail_closed_cache_deserialization_error_stops_before_transport():
    class MalformedRedis:
        def get(self, _key):
            return b"{not-json"

        def set(self, *_args, **_kwargs):
            raise AssertionError("cache SET must not run after malformed GET")

    transport = RecordingTransport(low_risk_response())
    provider = provider_with(
        transport,
        cache=RedisRiskCache(MalformedRedis()),
        cache_fail_closed=True,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert_redacted(raised.value)
    assert transport.calls == []


def test_fail_closed_cache_set_error_discards_current_transport_result():
    class SetDeniedRedis:
        def get(self, _key):
            return None

        def set(self, *_args, **_kwargs):
            raise RuntimeError("NOPERM SET " + TEST_KEY)

    transport = RecordingTransport(low_risk_response())
    limiter = RecordingLimiter()
    provider = provider_with(
        transport,
        cache=RedisRiskCache(SetDeniedRedis()),
        cache_fail_closed=True,
        rate_limiter=limiter,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert_redacted(raised.value)
    assert limiter.calls == 1
    assert len(transport.calls) == 1
    assert provider._key_locks == {}


@pytest.mark.parametrize("acknowledgement", [None, False, "OK", 1])
def test_fail_closed_cache_rejects_unconfirmed_set(acknowledgement):
    class UnconfirmedSetRedis:
        def get(self, _key):
            return None

        def set(self, *_args, **_kwargs):
            return acknowledgement

    transport = RecordingTransport(low_risk_response())
    provider = provider_with(
        transport,
        cache=RedisRiskCache(UnconfirmedSetRedis()),
        cache_fail_closed=True,
    )

    with pytest.raises(RiskProviderError) as raised:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert raised.value.category == "unavailable"
    assert len(transport.calls) == 1


def test_tolerant_cache_errors_do_not_block_personal_provider():
    class FailingCache:
        def get(self, _key):
            raise RuntimeError("local cache read failed")

        def set(self, _key, _result, _ttl_seconds):
            raise RuntimeError("local cache write failed")

    transport = RecordingTransport(low_risk_response())
    result = provider_with(transport, cache=FailingCache()).assess(
        subject=TARGET,
        network="eip155:8453",
    )

    assert result.score == 10
    assert result.cache_hit is False
    assert len(transport.calls) == 1


def test_fail_closed_cache_set_error_reaches_all_singleflight_followers():
    started = threading.Event()
    release = threading.Event()

    class SetDeniedCache:
        def get(self, _key):
            return None

        def set(self, _key, _result, _ttl_seconds):
            raise RuntimeError("shared cache write failed")

    class BlockingTransport(RecordingTransport):
        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            started.set()
            assert release.wait(timeout=2)
            return FakeResponse(low_risk_response())

    transport = BlockingTransport(low_risk_response())
    provider = provider_with(
        transport,
        cache=SetDeniedCache(),
        cache_fail_closed=True,
    )
    key = ("misttrack", "v2/risk_score", "USDC-Base", TARGET)

    def assess():
        with pytest.raises(RiskProviderError) as raised:
            provider.assess(subject=TARGET, network="eip155:8453")
        return raised.value

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(assess)
        assert started.wait(timeout=2)
        second = pool.submit(assess)
        assert _wait_for_singleflight_users(provider, key, expected=2)
        release.set()
        errors = [first.result(timeout=2), second.result(timeout=2)]

    assert len(transport.calls) == 1
    assert {error.category for error in errors} == {"unavailable"}
    assert provider._key_locks == {}


def test_concurrent_identical_lookups_share_one_transport_call():
    started = threading.Event()
    release = threading.Event()

    class BlockingTransport(RecordingTransport):
        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            started.set()
            assert release.wait(timeout=2)
            return FakeResponse(low_risk_response())

    transport = BlockingTransport(low_risk_response())
    provider = provider_with(transport)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            provider.assess, subject=TARGET, network="eip155:8453"
        )
        assert started.wait(timeout=2)
        second = pool.submit(
            provider.assess, subject=TARGET, network="eip155:8453"
        )
        release.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert len(transport.calls) == 1
    assert sorted(result.cache_hit for result in results) == [False, True]


def test_singleflight_follower_does_not_consume_a_rate_limit_slot():
    started = threading.Event()
    release = threading.Event()

    class BlockingTransport(RecordingTransport):
        def __call__(self, *, url, timeout):
            self.calls.append({"url": url, "timeout": timeout})
            started.set()
            assert release.wait(timeout=2)
            return FakeResponse(low_risk_response())

    transport = BlockingTransport(low_risk_response())
    limiter = RecordingLimiter()
    provider = provider_with(transport, rate_limiter=limiter)
    key = ("misttrack", "v2/risk_score", "USDC-Base", TARGET)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            provider.assess, subject=TARGET, network="eip155:8453"
        )
        assert started.wait(timeout=2)
        second = pool.submit(
            provider.assess, subject=TARGET, network="eip155:8453"
        )
        assert _wait_for_singleflight_users(provider, key, expected=2)
        release.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert limiter.calls == 1
    assert len(transport.calls) == 1
    assert sorted(result.cache_hit for result in results) == [False, True]


def test_concurrent_identical_failures_share_the_leader_error_but_do_not_cache_it():
    started = threading.Event()
    release = threading.Event()

    class BlockingFailingTransport:
        def __init__(self):
            self.calls = []
            self._lock = threading.Lock()

        def __call__(self, *, url, timeout):
            with self._lock:
                self.calls.append({"url": url, "timeout": timeout})
                call_number = len(self.calls)
            if call_number == 1:
                started.set()
                assert release.wait(timeout=2)
            raise urllib.error.URLError(f"offline {TEST_KEY}")

    transport = BlockingFailingTransport()
    provider = provider_with(transport, max_attempts=2)
    key = ("misttrack", "v2/risk_score", "USDC-Base", TARGET)

    def assess():
        try:
            provider.assess(subject=TARGET, network="eip155:8453")
        except RiskProviderError as exc:
            return exc
        raise AssertionError("provider failure was expected")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(assess)
        assert started.wait(timeout=2)
        second = pool.submit(assess)
        assert _wait_for_singleflight_users(provider, key, expected=2)
        release.set()
        concurrent_errors = [first.result(timeout=2), second.result(timeout=2)]

    assert len(transport.calls) == 2
    assert {error.category for error in concurrent_errors} == {"unavailable"}
    assert len({str(error) for error in concurrent_errors}) == 1
    for error in concurrent_errors:
        assert_redacted(error)
    assert provider._key_locks == {}

    with pytest.raises(RiskProviderError) as later:
        provider.assess(subject=TARGET, network="eip155:8453")

    assert later.value.category == "unavailable"
    assert_redacted(later.value)
    assert len(transport.calls) == 4
    assert provider._key_locks == {}


def _wait_for_singleflight_users(provider, key, *, expected):
    deadline = datetime.now(UTC) + timedelta(seconds=2)
    while datetime.now(UTC) < deadline:
        with provider._locks_guard:
            entry = provider._key_locks.get(key)
            if entry is not None and entry.users == expected:
                return True
        threading.Event().wait(0.001)
    return False


def test_completed_singleflight_entry_is_reused_until_concurrent_users_drain():
    provider = provider_with(RecordingTransport(low_risk_response()))
    key = ("misttrack", "v2/risk_score", "USDC-Base", TARGET)

    entry, is_leader = provider._join_singleflight(key)
    waiting_entry, waiter_is_leader = provider._join_singleflight(key)
    entry.error = RiskProviderError("MistTrack request unavailable", category="unavailable")
    entry.done.set()
    provider._leave_singleflight(key, entry)

    late_entry, late_is_leader = provider._join_singleflight(key)

    assert is_leader is True
    assert waiter_is_leader is False
    assert waiting_entry is entry
    assert late_is_leader is False
    assert late_entry is entry
    assert entry.users == 2

    provider._leave_singleflight(key, waiting_entry)
    provider._leave_singleflight(key, late_entry)
    assert provider._key_locks == {}

    sequential_entry, sequential_is_leader = provider._join_singleflight(key)
    assert sequential_is_leader is True
    assert sequential_entry is not entry
    provider._leave_singleflight(key, sequential_entry)
    assert provider._key_locks == {}


def test_sequential_unique_lookups_leave_no_singleflight_lock_entries():
    lookup_count = 20
    transport = RecordingTransport(*[low_risk_response() for _ in range(lookup_count)])
    provider = provider_with(transport, cache=InMemoryRiskCache(capacity=4))

    for value in range(1, lookup_count + 1):
        provider.assess(subject=f"0x{value:040x}", network="eip155:8453")

    assert len(transport.calls) == lookup_count
    assert provider._key_locks == {}


def test_normalizes_provider_facts_without_float_values():
    transport = RecordingTransport(
        low_risk_response(
            detail_list=["Mixer"],
            risk_detail=[
                {
                    "risk_type": "mixer",
                    "exposure_type": "direct",
                    "percentage": 2.5,
                }
            ],
            hacking_event=[],
        )
    )

    result = provider_with(transport).assess(
        subject=TARGET, network="eip155:8453"
    )

    assert result.risk_level == "low"
    assert result.indicators == ("mixer",)
    assert result.risk_details == (
        {
            "risk_type": "mixer",
            "exposure_type": "direct",
            "percentage": "2.5",
        },
    )
    assert result.hacking_event is None
    assert len(result.response_sha256) == 64
