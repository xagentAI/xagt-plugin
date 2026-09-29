from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import redis


IP_GENERAL = "ip_general"
IP_SESSION_EXCHANGE = "ip_session_exchange"
SUBJECT_GENERAL = "subject_general"
MESSAGE_SUBMIT = "message_submit"
OPERATION_LINK = "operation_link"
STOP = "stop"

_MAX_RATE_LIMIT = 1_000_000
_MAX_WINDOW_SECONDS = 3_600
_MIN_SSE_LEASE_TTL_SECONDS = 15 * 60
_MAX_SSE_LEASE_TTL_SECONDS = 24 * 60 * 60
_MAX_SCOPE_BYTES = 4_096
_MAX_TRACKED_SCOPES = 1_000_000
_REDIS_KEY_PREFIX = "clink:miniapp:traffic"

_RATE_LIMIT_SCRIPT = """
local now_parts = redis.call('TIME')
local now_us = (tonumber(now_parts[1]) * 1000000) + tonumber(now_parts[2])
local limit = tonumber(ARGV[1])
local window_us = tonumber(ARGV[2])
local cutoff_us = now_us - window_us
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff_us)
local count = redis.call('ZCARD', KEYS[1])
local ttl_ms = math.floor(window_us / 1000) + 1000
if count >= limit then
    redis.call('PEXPIRE', KEYS[1], ttl_ms)
    return 0
end
redis.call('ZADD', KEYS[1], now_us, ARGV[3])
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return 1
""".strip()

_RELEASE_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
""".strip()


class MiniAppTrafficUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("miniapp_unavailable")


@dataclass(frozen=True, slots=True)
class MiniAppTrafficPolicy:
    ip_general_limit: int = 240
    session_exchange_limit: int = 10
    subject_general_limit: int = 120
    message_submit_limit: int = 12
    operation_link_limit: int = 12
    stop_limit: int = 12
    window_seconds: int = 60
    sse_lease_ttl_seconds: int = 960

    def __post_init__(self) -> None:
        for name in (
            "ip_general_limit",
            "session_exchange_limit",
            "subject_general_limit",
            "message_submit_limit",
            "operation_link_limit",
            "stop_limit",
        ):
            _bounded_positive_integer(
                getattr(self, name),
                maximum=_MAX_RATE_LIMIT,
            )
        _bounded_positive_integer(
            self.window_seconds,
            maximum=_MAX_WINDOW_SECONDS,
        )
        _bounded_positive_integer(
            self.sse_lease_ttl_seconds,
            minimum=_MIN_SSE_LEASE_TTL_SECONDS,
            maximum=_MAX_SSE_LEASE_TTL_SECONDS,
        )

    def limit_for(self, action: str) -> int:
        limits = {
            IP_GENERAL: self.ip_general_limit,
            IP_SESSION_EXCHANGE: self.session_exchange_limit,
            SUBJECT_GENERAL: self.subject_general_limit,
            MESSAGE_SUBMIT: self.message_submit_limit,
            OPERATION_LINK: self.operation_link_limit,
            STOP: self.stop_limit,
        }
        try:
            return limits[action]
        except (KeyError, TypeError):
            raise ValueError("invalid Mini App traffic action") from None


class MiniAppTrafficGuard(Protocol):
    def consume(self, action: str, scope: str) -> bool: ...

    def acquire_sse(self, scope: str) -> str | None: ...

    def release_sse(self, scope: str, token: str) -> bool: ...


class MemoryMiniAppTrafficGuard:
    def __init__(
        self,
        *,
        policy: MiniAppTrafficPolicy | None = None,
        monotonic: Callable[[], float] | None = None,
        max_rate_scopes: int = 4_096,
        max_sse_scopes: int = 1_024,
        cleanup_batch_size: int = 64,
    ) -> None:
        self.policy = policy or MiniAppTrafficPolicy()
        self._monotonic = monotonic or time.monotonic
        self._max_rate_scopes = _bounded_positive_integer(
            max_rate_scopes,
            maximum=_MAX_TRACKED_SCOPES,
        )
        self._max_sse_scopes = _bounded_positive_integer(
            max_sse_scopes,
            maximum=_MAX_TRACKED_SCOPES,
        )
        self._cleanup_batch_size = _bounded_positive_integer(
            cleanup_batch_size,
            maximum=_MAX_TRACKED_SCOPES,
        )
        self._lock = threading.Lock()
        self._rate_scopes: OrderedDict[
            tuple[str, str],
            deque[float],
        ] = OrderedDict()
        self._sse_scopes: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._last_now: float | None = None

    def consume(self, action: str, scope: str) -> bool:
        try:
            limit = self.policy.limit_for(action)
            digest = _scope_digest(scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        key = (action, digest)
        with self._lock:
            now = self._current_time_locked()
            cutoff = now - self.policy.window_seconds
            self._cleanup_rate_scopes_locked(cutoff)
            bucket = self._rate_scopes.get(key)
            if bucket is None:
                if len(self._rate_scopes) >= self._max_rate_scopes:
                    raise MiniAppTrafficUnavailable()
                bucket = deque()
                self._rate_scopes[key] = bucket
            else:
                self._rate_scopes.move_to_end(key)
            _prune_window(bucket, cutoff)
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def acquire_sse(self, scope: str) -> str | None:
        try:
            digest = _scope_digest(scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        with self._lock:
            now = self._current_time_locked()
            self._cleanup_sse_scopes_locked(now)
            current = self._sse_scopes.get(digest)
            if current is not None:
                _, expires_at = current
                if expires_at > now:
                    self._sse_scopes.move_to_end(digest)
                    return None
                del self._sse_scopes[digest]
            if len(self._sse_scopes) >= self._max_sse_scopes:
                raise MiniAppTrafficUnavailable()
            token = secrets.token_urlsafe(32)
            self._sse_scopes[digest] = (
                token,
                now + self.policy.sse_lease_ttl_seconds,
            )
            return token

    def release_sse(self, scope: str, token: str) -> bool:
        try:
            digest = _scope_digest(scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        if not isinstance(token, str) or not token:
            return False
        with self._lock:
            current = self._sse_scopes.get(digest)
            if current is None:
                return False
            current_token, _ = current
            if not hmac.compare_digest(current_token, token):
                return False
            del self._sse_scopes[digest]
            return True

    def _current_time_locked(self) -> float:
        failed = False
        try:
            raw = self._monotonic()
            if isinstance(raw, bool):
                failed = True
                now = 0.0
            else:
                now = float(raw)
        except Exception:
            failed = True
            now = 0.0
        if (
            failed
            or not math.isfinite(now)
            or (self._last_now is not None and now < self._last_now)
        ):
            raise MiniAppTrafficUnavailable()
        self._last_now = now
        return now

    def _cleanup_rate_scopes_locked(self, cutoff: float) -> None:
        scans = min(self._cleanup_batch_size, len(self._rate_scopes))
        for _ in range(scans):
            key, bucket = self._rate_scopes.popitem(last=False)
            _prune_window(bucket, cutoff)
            if bucket:
                self._rate_scopes[key] = bucket

    def _cleanup_sse_scopes_locked(self, now: float) -> None:
        scans = min(self._cleanup_batch_size, len(self._sse_scopes))
        for _ in range(scans):
            digest, current = self._sse_scopes.popitem(last=False)
            if current[1] > now:
                self._sse_scopes[digest] = current


class RedisMiniAppTrafficGuard:
    def __init__(
        self,
        redis_url: str | None = None,
        *,
        client: Any | None = None,
        policy: MiniAppTrafficPolicy | None = None,
    ) -> None:
        self.policy = policy or MiniAppTrafficPolicy()
        if client is None:
            failed = False
            try:
                if not isinstance(redis_url, str) or not redis_url:
                    raise ValueError
                client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            except Exception:
                failed = True
            if failed:
                raise MiniAppTrafficUnavailable()
        self._client = client

    def __repr__(self) -> str:
        return "RedisMiniAppTrafficGuard(<redacted>)"

    def consume(self, action: str, scope: str) -> bool:
        try:
            limit = self.policy.limit_for(action)
            key = _redis_key(action, scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        member = secrets.token_urlsafe(24)
        failed = False
        try:
            result = self._client.eval(
                _RATE_LIMIT_SCRIPT,
                1,
                key,
                limit,
                self.policy.window_seconds * 1_000_000,
                member,
            )
        except Exception:
            failed = True
            result = None
        if failed or result not in (0, 1, b"0", b"1", "0", "1"):
            raise MiniAppTrafficUnavailable()
        return result in (1, b"1", "1")

    def acquire_sse(self, scope: str) -> str | None:
        try:
            key = _redis_key("sse", scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        token = secrets.token_urlsafe(32)
        failed = False
        try:
            result = self._client.set(
                key,
                token,
                nx=True,
                px=self.policy.sse_lease_ttl_seconds * 1_000,
            )
        except Exception:
            failed = True
            result = None
        if failed:
            raise MiniAppTrafficUnavailable()
        if result in (True, b"OK", "OK"):
            return token
        if result in (False, None):
            return None
        raise MiniAppTrafficUnavailable()

    def release_sse(self, scope: str, token: str) -> bool:
        try:
            key = _redis_key("sse", scope)
        except (TypeError, UnicodeError, ValueError):
            raise MiniAppTrafficUnavailable() from None
        if not isinstance(token, str) or not token:
            return False
        failed = False
        try:
            result = self._client.eval(
                _RELEASE_LEASE_SCRIPT,
                1,
                key,
                token,
            )
        except Exception:
            failed = True
            result = None
        if failed or result not in (0, 1, b"0", b"1", "0", "1"):
            raise MiniAppTrafficUnavailable()
        return result in (1, b"1", "1")


def _bounded_positive_integer(
    value: object,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ValueError("invalid Mini App traffic limit")
    return value


def _scope_digest(scope: object) -> str:
    if not isinstance(scope, str) or not scope:
        raise ValueError("invalid Mini App traffic scope")
    encoded = scope.encode("utf-8")
    if len(encoded) > _MAX_SCOPE_BYTES:
        raise ValueError("invalid Mini App traffic scope")
    return hashlib.sha256(encoded).hexdigest()


def _redis_key(action: str, scope: str) -> str:
    if action not in {
        IP_GENERAL,
        IP_SESSION_EXCHANGE,
        SUBJECT_GENERAL,
        MESSAGE_SUBMIT,
        OPERATION_LINK,
        STOP,
        "sse",
    }:
        raise ValueError("invalid Mini App traffic action")
    return f"{_REDIS_KEY_PREFIX}:{action}:{_scope_digest(scope)}"


def _prune_window(bucket: deque[float], cutoff: float) -> None:
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
