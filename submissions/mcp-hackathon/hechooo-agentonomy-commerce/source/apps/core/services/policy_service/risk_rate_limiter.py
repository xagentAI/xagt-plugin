from typing import Any, Protocol

from shared.config import (
    MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW,
    MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS,
)


REDIS_RISK_RATE_LIMIT_KEY = "clink:core:risk:{misttrack}:outbound:v1"
REDIS_RISK_RATE_LIMIT_READINESS_KEY = (
    "clink:core:risk:{misttrack}:outbound:readiness:v1"
)


class RiskRateLimiterError(RuntimeError):
    """Safe, provider-neutral failure raised by a risk request limiter."""


class RiskRateLimiter(Protocol):
    def acquire(self) -> tuple[bool, int]: ...

    def check_ready(self) -> None: ...


class RedisRiskRateLimiter:
    """Redis-atomic strict sliding-window limiter shared by Server workers."""

    _SCRIPT = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local dry_run = ARGV[3]
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after_ms = math.max(1, math.floor(tonumber(oldest[2]) + window_ms - now_ms))
    return {0, retry_after_ms}
end

if dry_run == '0' then
    local member = tostring(now_ms) .. ':' .. tostring(count + 1)
    redis.call('ZADD', KEYS[1], now_ms, member)
    redis.call('PEXPIRE', KEYS[1], window_ms)
end
return {1, 0}
""".strip()
    _READINESS_SCRIPT = """
local now = redis.call('TIME')
local probe_score = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local probe_member = 'clink-readiness'

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '+inf')
local initial_count = redis.call('ZCARD', KEYS[1])
local added = redis.call('ZADD', KEYS[1], probe_score, probe_member)
local expiry_set = redis.call('PEXPIRE', KEYS[1], 1000)
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local removed = redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '+inf')

if initial_count ~= 0
    or added ~= 1
    or expiry_set ~= 1
    or #oldest ~= 2
    or oldest[1] ~= probe_member
    or tonumber(oldest[2]) ~= probe_score
    or removed ~= 1 then
    return {0, 0}
end
return {1, 0}
""".strip()

    def __init__(
        self,
        client: Any,
        *,
        requests_per_window: int,
        window_seconds: int,
    ) -> None:
        if type(requests_per_window) is not int or requests_per_window <= 0:
            raise ValueError("requests_per_window must be a positive integer")
        if requests_per_window > MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW:
            raise ValueError(
                "requests_per_window must be at most "
                f"{MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW}"
            )
        if type(window_seconds) is not int or window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")
        if window_seconds > MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS:
            raise ValueError(
                "window_seconds must be at most "
                f"{MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS}"
            )
        self._client = client
        self._requests_per_window = requests_per_window
        self._window_ms = window_seconds * 1000
        self._key = REDIS_RISK_RATE_LIMIT_KEY

    def acquire(self) -> tuple[bool, int]:
        return self._execute(dry_run=False)

    def check_ready(self) -> None:
        try:
            raw_result = self._client.eval(
                self._READINESS_SCRIPT,
                1,
                REDIS_RISK_RATE_LIMIT_READINESS_KEY,
            )
            allowed, _retry_after_ms = _parse_result(raw_result)
            if not allowed:
                raise RiskRateLimiterError("risk rate limiter unavailable")
        except RiskRateLimiterError:
            raise
        except Exception:
            raise RiskRateLimiterError("risk rate limiter unavailable") from None

    def _execute(self, *, dry_run: bool) -> tuple[bool, int]:
        try:
            raw_result = self._client.eval(
                self._SCRIPT,
                1,
                self._key,
                str(self._requests_per_window),
                str(self._window_ms),
                "1" if dry_run else "0",
            )
            return _parse_result(raw_result)
        except RiskRateLimiterError:
            raise
        except Exception:
            raise RiskRateLimiterError("risk rate limiter unavailable") from None


def _parse_result(raw_result: Any) -> tuple[bool, int]:
    if not isinstance(raw_result, (list, tuple)) or len(raw_result) != 2:
        raise RiskRateLimiterError("risk rate limiter unavailable")
    allowed, retry_after_ms = raw_result
    if type(allowed) is not int or allowed not in {0, 1}:
        raise RiskRateLimiterError("risk rate limiter unavailable")
    if type(retry_after_ms) is not int or retry_after_ms < 0:
        raise RiskRateLimiterError("risk rate limiter unavailable")
    if (allowed == 1 and retry_after_ms != 0) or (
        allowed == 0 and retry_after_ms <= 0
    ):
        raise RiskRateLimiterError("risk rate limiter unavailable")
    return allowed == 1, retry_after_ms
