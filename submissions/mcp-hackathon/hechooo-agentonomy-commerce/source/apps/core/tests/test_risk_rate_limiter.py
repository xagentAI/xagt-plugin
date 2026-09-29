import json

import pytest

from services.policy_service.risk_rate_limiter import (
    RedisRiskRateLimiter,
    RiskRateLimiterError,
)


LEAK_KEY = "misttrack-test-secret"
LEAK_ADDRESS = "0x1111111111111111111111111111111111111111"
LEAK_URL = "https://openapi.misttrack.io/v2/risk_score?api_key=" + LEAK_KEY


class SlidingWindowRedis:
    """Small Redis EVAL semantic double shared by limiter instances."""

    def __init__(self, *, now_ms=1_000_000):
        self.now_ms = now_ms
        self.entries = {}
        self.sequence = 0
        self.calls = []

    def advance(self, milliseconds):
        self.now_ms += milliseconds

    def eval(self, script, numkeys, *keys_and_args):
        self.calls.append(
            {
                "script": script,
                "numkeys": numkeys,
                "keys_and_args": keys_and_args,
            }
        )
        if len(keys_and_args) == 1:
            key = keys_and_args[0]
            self.entries[key] = [(self.now_ms, "clink-readiness")]
            self.entries.pop(key, None)
            return [1, 0]
        key, limit_raw, window_raw, dry_run_raw = keys_and_args
        limit = int(limit_raw)
        window_ms = int(window_raw)
        cutoff = self.now_ms - window_ms
        entries = [
            (score, member)
            for score, member in self.entries.get(key, [])
            if score > cutoff
        ]
        entries.sort()
        self.entries[key] = entries
        if len(entries) >= limit:
            retry_after_ms = max(1, entries[0][0] + window_ms - self.now_ms)
            return [0, retry_after_ms]
        if dry_run_raw == "0":
            self.sequence += 1
            entries.append((self.now_ms, f"{self.now_ms}:{self.sequence}"))
            entries.sort()
        return [1, 0]


def test_shared_redis_limiter_enforces_a_strict_sliding_window_across_instances():
    client = SlidingWindowRedis()
    first = RedisRiskRateLimiter(client, requests_per_window=2, window_seconds=10)
    second = RedisRiskRateLimiter(client, requests_per_window=2, window_seconds=10)

    assert first.acquire() == (True, 0)
    assert second.acquire() == (True, 0)
    assert first.acquire() == (False, 10_000)

    client.advance(9_999)
    assert second.acquire() == (False, 1)

    client.advance(1)
    assert second.acquire() == (True, 0)


def test_limiter_uses_one_fixed_global_key_and_never_passes_sensitive_arguments():
    client = SlidingWindowRedis()
    limiter = RedisRiskRateLimiter(
        client,
        requests_per_window=5,
        window_seconds=60,
    )

    assert limiter.acquire() == (True, 0)

    call = client.calls[0]
    assert call["numkeys"] == 1
    assert call["keys_and_args"] == (
        "clink:core:risk:{misttrack}:outbound:v1",
        "5",
        "60000",
        "0",
    )
    assert "redis.call('TIME')" in call["script"]
    assert "ZREMRANGEBYSCORE" in call["script"]
    assert "ZADD" in call["script"]
    assert ":sequence" not in call["script"]
    assert "INCR" not in call["script"]
    serialized = json.dumps(call, sort_keys=True)
    assert LEAK_KEY not in serialized
    assert LEAK_ADDRESS not in serialized
    assert LEAK_URL not in serialized
    assert "api_key" not in serialized


def test_readiness_probe_exercises_all_commands_without_touching_production_quota():
    client = SlidingWindowRedis()
    limiter = RedisRiskRateLimiter(client, requests_per_window=1, window_seconds=10)

    limiter.check_ready()

    readiness_call = client.calls[0]
    assert readiness_call["numkeys"] == 1
    assert readiness_call["keys_and_args"] == (
        "clink:core:risk:{misttrack}:outbound:readiness:v1",
    )
    assert "redis.call('TIME')" in readiness_call["script"]
    assert "ZREMRANGEBYSCORE" in readiness_call["script"]
    assert "ZCARD" in readiness_call["script"]
    assert "ZADD" in readiness_call["script"]
    assert "PEXPIRE" in readiness_call["script"]
    assert "ZRANGE" in readiness_call["script"]
    assert "clink:core:risk:{misttrack}:outbound:v1" not in client.entries

    assert limiter.acquire() == (True, 0)
    assert limiter.acquire() == (False, 10_000)
    production_entries = list(
        client.entries["clink:core:risk:{misttrack}:outbound:v1"]
    )

    limiter.check_ready()

    assert client.calls[-1]["keys_and_args"] == (
        "clink:core:risk:{misttrack}:outbound:readiness:v1",
    )
    assert client.entries["clink:core:risk:{misttrack}:outbound:v1"] == (
        production_entries
    )
    assert limiter.acquire() == (False, 10_000)


def test_readiness_probe_rejects_a_non_success_contract_result():
    class MalformedReadinessRedis:
        def eval(self, *_args):
            return [0, 1]

    limiter = RedisRiskRateLimiter(
        MalformedReadinessRedis(),
        requests_per_window=1,
        window_seconds=10,
    )

    with pytest.raises(RiskRateLimiterError, match="unavailable"):
        limiter.check_ready()


@pytest.mark.parametrize("denied_command", ["ZADD", "PEXPIRE", "ZRANGE"])
def test_readiness_probe_normalizes_command_acl_failures(denied_command):
    class CommandDeniedRedis:
        def __init__(self):
            self.calls = []

        def eval(self, script, numkeys, *keys_and_args):
            self.calls.append((script, numkeys, keys_and_args))
            assert denied_command in script
            raise RuntimeError(f"NOPERM {denied_command} {LEAK_URL}")

    client = CommandDeniedRedis()
    limiter = RedisRiskRateLimiter(
        client,
        requests_per_window=1,
        window_seconds=10,
    )

    with pytest.raises(RiskRateLimiterError) as raised:
        limiter.check_ready()

    assert client.calls[0][1:] == (
        1,
        ("clink:core:risk:{misttrack}:outbound:readiness:v1",),
    )
    assert str(raised.value) == "risk rate limiter unavailable"
    assert LEAK_KEY not in str(raised.value)


@pytest.mark.parametrize(
    "raw_result",
    [
        None,
        [],
        [1],
        [1, 0, 0],
        [True, 0],
        [2, 0],
        [1, 1],
        [0, 0],
        [0, -1],
        ["1", 0],
    ],
)
def test_limiter_rejects_malformed_redis_results(raw_result):
    class MalformedRedis:
        def eval(self, *_args):
            return raw_result

    limiter = RedisRiskRateLimiter(
        MalformedRedis(),
        requests_per_window=1,
        window_seconds=10,
    )

    with pytest.raises(RiskRateLimiterError, match="unavailable"):
        limiter.acquire()


def test_limiter_redacts_redis_failures():
    class FailingRedis:
        def eval(self, *_args):
            raise RuntimeError("redis failed " + LEAK_URL)

    limiter = RedisRiskRateLimiter(
        FailingRedis(),
        requests_per_window=1,
        window_seconds=10,
    )

    with pytest.raises(RiskRateLimiterError) as raised:
        limiter.acquire()

    rendered = str(raised.value)
    assert rendered == "risk rate limiter unavailable"
    assert LEAK_KEY not in rendered
    assert "api_key" not in rendered
    assert "https://" not in rendered


@pytest.mark.parametrize(
    ("requests_per_window", "window_seconds"),
    [(0, 1), (1, 0), (True, 1), (1, False), (1.5, 1), (1, 1.5)],
)
def test_limiter_requires_positive_integer_configuration(
    requests_per_window, window_seconds
):
    with pytest.raises(ValueError, match="positive integer"):
        RedisRiskRateLimiter(
            SlidingWindowRedis(),
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
        )


@pytest.mark.parametrize(
    ("requests_per_window", "window_seconds"),
    [(1001, 60), (10, 3601)],
)
def test_limiter_rejects_values_over_explicit_maxima(
    requests_per_window, window_seconds
):
    with pytest.raises(ValueError, match="at most"):
        RedisRiskRateLimiter(
            SlidingWindowRedis(),
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
        )


def test_limiter_global_key_cannot_be_overridden():
    with pytest.raises(TypeError):
        RedisRiskRateLimiter(
            SlidingWindowRedis(),
            requests_per_window=1,
            window_seconds=10,
            key="tenant-or-address-specific-key",
        )
