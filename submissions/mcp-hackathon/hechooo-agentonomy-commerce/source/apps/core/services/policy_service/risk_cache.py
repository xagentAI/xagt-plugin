import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from services.policy_service.risk_provider import RiskProviderResult


RiskCacheKey = tuple[str, str, str, str]
_RISK_LEVELS = frozenset({"low", "moderate", "high", "severe"})
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_API_KEY_FIELD_PATTERN = re.compile(r"api[\s_-]*key", re.IGNORECASE)
_API_KEY_ASSIGNMENT_PATTERN = re.compile(r"api[\s_-]*key\s*=", re.IGNORECASE)


class RiskCacheError(RuntimeError):
    """Safe failure raised when a shared risk cache cannot be trusted."""


class RiskCache(Protocol):
    def get(self, key: RiskCacheKey) -> RiskProviderResult | None: ...

    def set(
        self,
        key: RiskCacheKey,
        result: RiskProviderResult,
        ttl_seconds: int,
    ) -> None: ...


class InMemoryRiskCache:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        capacity: int = 4096,
    ) -> None:
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("cache capacity must be a positive integer")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._capacity = capacity
        self._entries: OrderedDict[
            RiskCacheKey, tuple[datetime, RiskProviderResult]
        ] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: RiskCacheKey) -> RiskProviderResult | None:
        now = _aware_utc(self._clock())
        with self._lock:
            self._sweep_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            self._entries.move_to_end(key)
            return _copy_result(result)

    def set(
        self,
        key: RiskCacheKey,
        result: RiskProviderResult,
        ttl_seconds: int,
    ) -> None:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("cache TTL must be a positive integer")
        now = _aware_utc(self._clock())
        expires_at = min(result.expires_at, now + timedelta(seconds=ttl_seconds))
        with self._lock:
            self._sweep_expired(now)
            self._entries.pop(key, None)
            if expires_at <= now:
                return
            if len(self._entries) >= self._capacity:
                self._entries.popitem(last=False)
            self._entries[key] = (expires_at, _copy_result(result))

    def _sweep_expired(self, now: datetime) -> None:
        expired = [
            key
            for key, (expires_at, result) in self._entries.items()
            if expires_at <= now or result.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)


class RedisRiskCache:
    """Risk cache backed by an injected Redis-like get/set client."""

    def __init__(self, client: Any, *, key_prefix: str = "clink:risk:v1") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def get(self, key: RiskCacheKey) -> RiskProviderResult | None:
        try:
            value = self._client.get(self._redis_key(key))
        except Exception:
            raise RiskCacheError("risk cache unavailable") from None
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            payload = json.loads(value)
            result = _result_from_payload(payload)
        except Exception:
            raise RiskCacheError("risk cache unavailable") from None
        if result.expires_at <= datetime.now(UTC):
            return None
        return result

    def set(
        self,
        key: RiskCacheKey,
        result: RiskProviderResult,
        ttl_seconds: int,
    ) -> None:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("cache TTL must be a positive integer")
        payload = _result_to_payload(result)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            acknowledged = self._client.set(
                self._redis_key(key), serialized, ex=ttl_seconds
            )
        except Exception:
            raise RiskCacheError("risk cache unavailable") from None
        if acknowledged is not True:
            raise RiskCacheError("risk cache unavailable")

    def _redis_key(self, key: RiskCacheKey) -> str:
        encoded = json.dumps(key, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return f"{self._key_prefix}:{digest}"


def _copy_result(result: RiskProviderResult) -> RiskProviderResult:
    return replace(
        result,
        indicators=tuple(result.indicators),
        risk_details=tuple(dict(detail) for detail in result.risk_details),
    )


def _result_to_payload(result: RiskProviderResult) -> dict[str, Any]:
    if "://" in result.endpoint or "?" in result.endpoint:
        raise ValueError("cache endpoint must be a safe endpoint identifier")
    payload = {
        "provider": result.provider,
        "endpoint": result.endpoint,
        "subject": result.subject,
        "network": result.network,
        "asset": result.asset,
        "coin": result.coin,
        "score": result.score,
        "risk_level": result.risk_level,
        "indicators": list(result.indicators),
        "risk_details": [dict(detail) for detail in result.risk_details],
        "hacking_event": result.hacking_event,
        "assessed_at": result.assessed_at.isoformat(),
        "expires_at": result.expires_at.isoformat(),
        "response_sha256": result.response_sha256,
        "cache_hit": False,
    }
    _validate_normalized_payload(payload)
    return payload


def _result_from_payload(payload: Any) -> RiskProviderResult:
    if not isinstance(payload, dict):
        raise ValueError("invalid cached risk result")
    _validate_normalized_payload(payload)
    expected = {
        "provider",
        "endpoint",
        "subject",
        "network",
        "asset",
        "coin",
        "score",
        "risk_level",
        "indicators",
        "risk_details",
        "hacking_event",
        "assessed_at",
        "expires_at",
        "response_sha256",
        "cache_hit",
    }
    if set(payload) != expected:
        raise ValueError("invalid cached risk result")
    endpoint = payload["endpoint"]
    if not isinstance(endpoint, str) or "://" in endpoint or "?" in endpoint:
        raise ValueError("invalid cached risk endpoint")
    indicators = payload["indicators"]
    risk_details = payload["risk_details"]
    if not isinstance(indicators, list) or not all(
        isinstance(value, str) for value in indicators
    ):
        raise ValueError("invalid cached indicators")
    if not isinstance(risk_details, list) or not all(
        isinstance(value, dict)
        and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())
        for value in risk_details
    ):
        raise ValueError("invalid cached risk details")
    score = payload["score"]
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("invalid cached score")
    risk_level = payload["risk_level"]
    if not isinstance(risk_level, str) or risk_level not in _RISK_LEVELS:
        raise ValueError("invalid cached risk_level")
    response_sha256 = payload["response_sha256"]
    if not isinstance(response_sha256, str) or _SHA256_PATTERN.fullmatch(
        response_sha256
    ) is None:
        raise ValueError("invalid cached response_sha256")
    if type(payload["cache_hit"]) is not bool:
        raise ValueError("invalid cached cache_hit")
    assessed_at = _parse_datetime(payload["assessed_at"])
    expires_at = _parse_datetime(payload["expires_at"])
    if expires_at <= assessed_at:
        raise ValueError("invalid cached timestamp ordering")
    return RiskProviderResult(
        provider=_required_string(payload, "provider"),
        endpoint=endpoint,
        subject=_required_string(payload, "subject"),
        network=_required_string(payload, "network"),
        asset=_required_string(payload, "asset"),
        coin=_required_string(payload, "coin"),
        score=score,
        risk_level=risk_level,
        indicators=tuple(indicators),
        risk_details=tuple(dict(detail) for detail in risk_details),
        hacking_event=_optional_string(payload, "hacking_event"),
        assessed_at=assessed_at,
        expires_at=expires_at,
        response_sha256=response_sha256,
        cache_hit=False,
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid cached {key}")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise ValueError(f"invalid cached {key}")
    return value


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid cached timestamp")
    return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("risk cache clock must return an aware datetime")
    return value.astimezone(UTC)


def _validate_normalized_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("risk cache accepts only normalized payloads")
            normalized_key = re.sub(r"[\s-]+", "_", key.strip().lower())
            if _API_KEY_FIELD_PATTERN.search(key) or "://" in normalized_key:
                raise ValueError("risk cache accepts only normalized key-free payloads")
            _validate_normalized_payload(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_normalized_payload(item)
        return
    if isinstance(value, str):
        lowered = value.lower()
        if "://" in lowered or _API_KEY_ASSIGNMENT_PATTERN.search(value):
            raise ValueError("risk cache accepts only normalized key-free payloads")
