import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from services.policy_service.risk_cache import (
    InMemoryRiskCache,
    RiskCache,
    RiskCacheKey,
)
from services.policy_service.risk_provider import RiskProviderError, RiskProviderResult
from services.policy_service.risk_rate_limiter import RiskRateLimiter
from shared.config import (
    MISTTRACK_MAX_ATTEMPTS,
    MISTTRACK_MAX_CACHE_TTL_SECONDS,
    MISTTRACK_MAX_TIMEOUT_SECONDS,
)


MISTTRACK_BASE_URL = "https://openapi.misttrack.io"
MISTTRACK_ENDPOINT = "v2/risk_score"
_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-f]{40}$")
_COINS = {
    "eip155:8453": "USDC-Base",
    "eip155:137": "USDC-Polygon",
}
_RETRYABLE_HTTP_CODES = frozenset({500, 502, 503, 504})
MAX_PROVIDER_CONTAINER_DEPTH = 16
MAX_PROVIDER_CONTAINER_ITEMS = 256
MAX_PROVIDER_NUMERIC_DIGITS = 128
MAX_PROVIDER_NUMERIC_EXPONENT = 128
MAX_PROVIDER_SCALAR_CHARS = 4096
MAX_PROVIDER_SCORE_DIGITS = 3
MISTTRACK_MAX_RESPONSE_LIMIT_BYTES = 64 * 1024
_MIN_RETRY_REMAINING_SECONDS = Decimal("0.001")
_RESPONSE_READ_CHUNK_BYTES = 8192


class _SingleflightEntry:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.users = 0
        self.result: RiskProviderResult | None = None
        self.error: RiskProviderError | None = None


class MistTrackProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = MISTTRACK_BASE_URL,
        timeout_seconds: int | float = 5,
        max_attempts: int = 2,
        cache: RiskCache | None = None,
        cache_fail_closed: bool = False,
        cache_ttl_seconds: int = 300,
        response_limit_bytes: int = MISTTRACK_MAX_RESPONSE_LIMIT_BYTES,
        transport: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        rate_limiter: RiskRateLimiter | None = None,
    ) -> None:
        _validate_official_base_url(base_url)
        if not isinstance(api_key, str) or not api_key.strip():
            raise _error("MistTrack is not configured", "not_configured")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float, Decimal)
        ):
            raise ValueError("timeout_seconds must be positive")
        try:
            normalized_timeout = Decimal(str(timeout_seconds))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("timeout_seconds must be positive") from None
        if not normalized_timeout.is_finite() or normalized_timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        if normalized_timeout > Decimal(str(MISTTRACK_MAX_TIMEOUT_SECONDS)):
            raise ValueError(
                "timeout_seconds must be at most "
                f"{MISTTRACK_MAX_TIMEOUT_SECONDS}"
            )
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        if max_attempts > MISTTRACK_MAX_ATTEMPTS:
            raise ValueError(f"max_attempts must be at most {MISTTRACK_MAX_ATTEMPTS}")
        if type(cache_fail_closed) is not bool:
            raise ValueError("cache_fail_closed must be a boolean")
        if type(cache_ttl_seconds) is not int or cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be a positive integer")
        if cache_ttl_seconds > MISTTRACK_MAX_CACHE_TTL_SECONDS:
            raise ValueError(
                "cache_ttl_seconds must be at most "
                f"{MISTTRACK_MAX_CACHE_TTL_SECONDS}"
            )
        if type(response_limit_bytes) is not int or response_limit_bytes <= 0:
            raise ValueError("response_limit_bytes must be a positive integer")
        if response_limit_bytes > MISTTRACK_MAX_RESPONSE_LIMIT_BYTES:
            raise ValueError(
                "response_limit_bytes must be at most "
                f"{MISTTRACK_MAX_RESPONSE_LIMIT_BYTES}"
            )

        self._api_key = api_key
        self._timeout_seconds = normalized_timeout
        self._max_attempts = max_attempts
        self._total_timeout_seconds = normalized_timeout * max_attempts
        self._cache = cache if cache is not None else InMemoryRiskCache()
        self._cache_fail_closed = cache_fail_closed
        self._cache_ttl_seconds = cache_ttl_seconds
        self._response_limit_bytes = response_limit_bytes
        self._transport = transport or self._open_url
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._rate_limiter = rate_limiter
        self._locks_guard = threading.Lock()
        self._key_locks: dict[RiskCacheKey, _SingleflightEntry] = {}

    @property
    def configured(self) -> bool:
        return True

    def assess(
        self,
        *,
        subject: str,
        network: str,
        asset: str = "USDC",
    ) -> RiskProviderResult:
        coin = self._validate_request(subject=subject, network=network, asset=asset)
        key: RiskCacheKey = ("misttrack", MISTTRACK_ENDPOINT, coin, subject)
        cached = self._cache_get(
            key,
            subject=subject,
            network=network,
            asset=asset,
            coin=coin,
        )
        if cached is not None:
            return _as_cache_hit(cached)

        entry, is_leader = self._join_singleflight(key)
        try:
            if not is_leader:
                wait_deadline = Decimal(str(self._monotonic())) + self._total_timeout_seconds
                remaining = wait_deadline - Decimal(str(self._monotonic()))
                completed = remaining > 0 and entry.done.wait(timeout=float(remaining))
                if not completed:
                    raise _error("MistTrack request unavailable", "unavailable")
                if entry.error is not None:
                    raise _copy_error(entry.error)
                if entry.result is None:
                    raise _error("MistTrack request unavailable", "unavailable")
                return _as_cache_hit(entry.result)

            try:
                cached = self._cache_get(
                    key,
                    subject=subject,
                    network=network,
                    asset=asset,
                    coin=coin,
                )
                if cached is not None:
                    entry.result = _as_cache_hit(cached)
                else:
                    result = self._assess_uncached(
                        subject=subject,
                        network=network,
                        asset=asset,
                        coin=coin,
                    )
                    self._cache_set(key, result)
                    entry.result = result
                return entry.result
            except RiskProviderError as exc:
                entry.result = None
                entry.error = _copy_error(exc)
                raise entry.error
            except Exception:
                entry.result = None
                entry.error = _error(
                    "MistTrack request unavailable", "unavailable"
                )
                raise entry.error from None
            finally:
                entry.done.set()
        finally:
            self._leave_singleflight(key, entry)

    def _validate_request(self, *, subject: str, network: str, asset: str) -> str:
        if not isinstance(subject, str) or _ADDRESS_PATTERN.fullmatch(subject) is None:
            raise _error("MistTrack rejected invalid address", "invalid_address")
        if asset != "USDC":
            raise _error("MistTrack does not support asset", "unsupported_asset")
        coin = _COINS.get(network)
        if coin is None:
            raise _error("MistTrack unsupported network", "unsupported_network")
        return coin

    def _assess_uncached(
        self,
        *,
        subject: str,
        network: str,
        asset: str,
        coin: str,
    ) -> RiskProviderResult:
        url = self._build_url(subject=subject, coin=coin)
        started = Decimal(str(self._monotonic()))
        deadline = started + (self._timeout_seconds * self._max_attempts)
        last_category = "unavailable"

        for attempt in range(self._max_attempts):
            attempt_deadline = min(
                deadline,
                Decimal(str(self._monotonic())) + self._timeout_seconds,
            )
            try:
                self._acquire_rate_limit()
                request_timeout, _ = self._remaining_budget(
                    deadline=deadline,
                    attempt_deadline=attempt_deadline,
                )
                body = self._request_body(
                    url=url,
                    timeout=float(request_timeout),
                    deadline=deadline,
                    attempt_deadline=attempt_deadline,
                )
                if deadline - Decimal(str(self._monotonic())) <= 0:
                    raise _error("MistTrack request unavailable", "unavailable")
                result = self._normalize_response(
                    body=body,
                    subject=subject,
                    network=network,
                    asset=asset,
                    coin=coin,
                )
                if deadline - Decimal(str(self._monotonic())) <= 0:
                    raise _error("MistTrack request unavailable", "unavailable")
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in _RETRYABLE_HTTP_CODES:
                    last_category = "unavailable"
                    if attempt + 1 < self._max_attempts:
                        continue
                    break
                if exc.code == 429:
                    delay = self._retry_after(exc)
                    remaining = deadline - Decimal(str(self._monotonic()))
                    if (
                        delay is not None
                        and delay >= 0
                        and attempt + 1 < self._max_attempts
                        and delay + _MIN_RETRY_REMAINING_SECONDS < remaining
                    ):
                        self._sleep(float(delay))
                        if (
                            deadline - Decimal(str(self._monotonic()))
                            > _MIN_RETRY_REMAINING_SECONDS
                        ):
                            continue
                    raise _error("MistTrack rate limited", "rate_limited") from None
                if exc.code == 402:
                    raise _error("MistTrack payment required", "payment_required") from None
                if exc.code in {401, 403}:
                    raise _error("MistTrack credentials rejected", "invalid_key") from None
                raise _error("MistTrack request rejected", "provider_error") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                last_category = "unavailable"
                if attempt + 1 < self._max_attempts:
                    continue
                break
            except RiskProviderError:
                raise
            except Exception:
                raise _error("MistTrack request unavailable", "unavailable") from None

        raise _error("MistTrack request unavailable", last_category)

    def _acquire_rate_limit(self) -> None:
        if self._rate_limiter is None:
            return
        try:
            result = self._rate_limiter.acquire()
        except Exception:
            raise _error("MistTrack request unavailable", "unavailable") from None
        if not isinstance(result, tuple) or len(result) != 2:
            raise _error("MistTrack request unavailable", "unavailable")
        allowed, retry_after_ms = result
        if (
            type(allowed) is not bool
            or type(retry_after_ms) is not int
            or retry_after_ms < 0
            or (allowed and retry_after_ms != 0)
            or (not allowed and retry_after_ms <= 0)
        ):
            raise _error("MistTrack request unavailable", "unavailable")
        if not allowed:
            raise _error("MistTrack rate limited", "rate_limited")

    def _request_body(
        self,
        *,
        url: str,
        timeout: float,
        deadline: Decimal,
        attempt_deadline: Decimal,
    ) -> bytes:
        remaining, _ = self._remaining_budget(
            deadline=deadline,
            attempt_deadline=attempt_deadline,
        )
        bounded_timeout = min(Decimal(str(timeout)), remaining)
        response = self._transport(url=url, timeout=float(bounded_timeout))
        self._remaining_budget(
            deadline=deadline,
            attempt_deadline=attempt_deadline,
        )
        if hasattr(response, "__enter__"):
            with response as opened:
                return self._read_response_body(
                    opened,
                    deadline=deadline,
                    attempt_deadline=attempt_deadline,
                )
        else:
            return self._read_response_body(
                response,
                deadline=deadline,
                attempt_deadline=attempt_deadline,
            )

    def _read_response_body(
        self,
        response: Any,
        *,
        deadline: Decimal,
        attempt_deadline: Decimal,
    ) -> bytes:
        body = bytearray()
        while True:
            remaining_bytes = self._response_limit_bytes + 1 - len(body)
            if remaining_bytes <= 0:
                raise _error("MistTrack returned invalid response", "invalid_response")
            remaining, budget_is_attempt = self._remaining_budget(
                deadline=deadline,
                attempt_deadline=attempt_deadline,
            )
            read_size = min(_RESPONSE_READ_CHUNK_BYTES, remaining_bytes)
            _set_response_read_timeout(response, float(remaining))
            chunk = _read_response_chunk(
                response,
                read_size=read_size,
                timeout=float(remaining),
                budget_is_attempt=budget_is_attempt,
            )
            if not isinstance(chunk, bytes):
                raise _error("MistTrack returned invalid response", "invalid_response")
            body.extend(chunk)
            if len(body) > self._response_limit_bytes:
                raise _error("MistTrack returned invalid response", "invalid_response")
            self._remaining_budget(
                deadline=deadline,
                attempt_deadline=attempt_deadline,
            )
            if not chunk:
                return bytes(body)

    def _remaining_budget(
        self,
        *,
        deadline: Decimal,
        attempt_deadline: Decimal,
    ) -> tuple[Decimal, bool]:
        now = Decimal(str(self._monotonic()))
        total_remaining = deadline - now
        attempt_remaining = attempt_deadline - now
        if total_remaining <= 0:
            raise _error("MistTrack request unavailable", "unavailable")
        if attempt_remaining <= 0:
            raise TimeoutError("MistTrack attempt timed out")
        return min(total_remaining, attempt_remaining), attempt_remaining < total_remaining

    def _normalize_response(
        self,
        *,
        body: bytes,
        subject: str,
        network: str,
        asset: str,
        coin: str,
    ) -> RiskProviderResult:
        try:
            text = body.decode("utf-8")
            _preflight_json_structure(text)
            payload = json.loads(text, parse_float=Decimal)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            InvalidOperation,
            RecursionError,
        ):
            raise _error("MistTrack returned invalid response", "invalid_response") from None
        if not isinstance(payload, dict):
            raise _error("MistTrack returned invalid response", "invalid_response")
        _validate_payload_structure(payload)
        if "success" in payload:
            success = payload["success"]
            if type(success) is not bool:
                raise _error("MistTrack returned invalid response", "invalid_response")
            if success is False:
                raise self._application_error(payload)
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise _error("MistTrack returned invalid response", "invalid_response")

        score = _normalize_score(data.get("score", data.get("risk_score")))
        risk_level = _normalize_level(data.get("risk_level", data.get("level")))
        indicators = _normalize_indicators(
            data.get("detail_list"), forbidden=self._api_key
        )
        risk_details = _normalize_risk_details(
            data.get("risk_detail"), forbidden=self._api_key
        )
        hacking_event = _normalize_hacking_event(
            data.get("hacking_event"), forbidden=self._api_key
        )
        assessed_at = _aware_utc(self._clock())
        return RiskProviderResult(
            provider="misttrack",
            endpoint=MISTTRACK_ENDPOINT,
            subject=subject,
            network=network,
            asset=asset,
            coin=coin,
            score=score,
            risk_level=risk_level,
            indicators=indicators,
            risk_details=risk_details,
            hacking_event=hacking_event,
            assessed_at=assessed_at,
            expires_at=assessed_at + timedelta(seconds=self._cache_ttl_seconds),
            response_sha256=hashlib.sha256(body).hexdigest(),
        )

    def _application_error(self, payload: dict[str, Any]) -> RiskProviderError:
        message = " ".join(
            str(payload.get(key, "")) for key in ("message", "msg", "error")
        ).lower()
        if "key" in message or "credential" in message or "unauthorized" in message:
            return _error("MistTrack credentials rejected", "invalid_key")
        if "plan" in message or "expired" in message or "payment" in message:
            return _error("MistTrack plan unavailable", "plan_expired")
        if "unsupported" in message and ("coin" in message or "token" in message):
            return _error("MistTrack does not support asset", "unsupported_asset")
        if "address" in message and "invalid" in message:
            return _error("MistTrack rejected invalid address", "invalid_address")
        return _error("MistTrack request rejected", "provider_error")

    def _retry_after(self, error: urllib.error.HTTPError) -> Decimal | None:
        value = error.headers.get("Retry-After") if error.headers is not None else None
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            delay = Decimal(value.strip())
        except InvalidOperation:
            try:
                retry_at = _aware_utc(parsedate_to_datetime(value))
                delay = Decimal(
                    str((retry_at - _aware_utc(self._clock())).total_seconds())
                )
            except (TypeError, ValueError, OverflowError):
                return None
        if not delay.is_finite() or delay < 0:
            return None
        return delay

    def _build_url(self, *, subject: str, coin: str) -> str:
        query = urllib.parse.urlencode(
            {"coin": coin, "address": subject, "api_key": self._api_key}
        )
        return f"{MISTTRACK_BASE_URL}/{MISTTRACK_ENDPOINT}?{query}"

    def _cache_get(
        self,
        key: RiskCacheKey,
        *,
        subject: str,
        network: str,
        asset: str,
        coin: str,
    ) -> RiskProviderResult | None:
        try:
            result = self._cache.get(key)
        except Exception:
            if self._cache_fail_closed:
                raise _error("MistTrack request unavailable", "unavailable") from None
            return None
        if result is None:
            return None
        if (
            not isinstance(result, RiskProviderResult)
            or result.provider != "misttrack"
            or result.endpoint != MISTTRACK_ENDPOINT
            or result.subject != subject
            or result.network != network
            or result.asset != asset
            or result.coin != coin
        ):
            if self._cache_fail_closed:
                raise _error("MistTrack request unavailable", "unavailable")
            return None
        return result

    def _cache_set(self, key: RiskCacheKey, result: RiskProviderResult) -> None:
        try:
            self._cache.set(key, result, self._cache_ttl_seconds)
        except Exception:
            if self._cache_fail_closed:
                raise _error("MistTrack request unavailable", "unavailable") from None
            return

    def _join_singleflight(
        self, key: RiskCacheKey
    ) -> tuple[_SingleflightEntry, bool]:
        with self._locks_guard:
            entry = self._key_locks.get(key)
            is_leader = entry is None
            if is_leader:
                entry = _SingleflightEntry()
                self._key_locks[key] = entry
            entry.users += 1
            return entry, is_leader

    def _leave_singleflight(
        self, key: RiskCacheKey, entry: _SingleflightEntry
    ) -> None:
        with self._locks_guard:
            entry.users -= 1
            if entry.users == 0 and self._key_locks.get(key) is entry:
                self._key_locks.pop(key, None)

    @staticmethod
    def _open_url(*, url: str, timeout: float):
        return urllib.request.urlopen(url, timeout=timeout)


def _validate_official_base_url(base_url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(base_url)
    except (TypeError, ValueError):
        raise ValueError("MistTrack base URL must use the official HTTPS host") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "openapi.misttrack.io"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MistTrack base URL must use the official HTTPS host")


def _set_response_read_timeout(response: Any, timeout: float) -> None:
    pending = [response]
    visited: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in visited:
            continue
        visited.add(id(candidate))
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(timeout)
            except Exception:
                pass
        for attribute in (
            "fp",
            "raw",
            "_fp",
            "_sock",
            "sock",
            "connection",
            "_connection",
        ):
            try:
                nested = getattr(candidate, attribute, None)
            except Exception:
                nested = None
            if nested is not None:
                pending.append(nested)


def _read_response_chunk(
    response: Any,
    *,
    read_size: int,
    timeout: float,
    budget_is_attempt: bool,
) -> Any:
    outcome: dict[str, Any] = {}
    completed = threading.Event()

    def read() -> None:
        try:
            outcome["value"] = response.read(read_size)
        except Exception as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    if not completed.wait(timeout=max(0.0, timeout)):
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        worker.join(timeout=min(0.05, max(0.0, timeout)))
        if budget_is_attempt:
            raise TimeoutError("MistTrack attempt timed out")
        raise _error("MistTrack request unavailable", "unavailable")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _preflight_json_structure(text: str) -> None:
    depth = 0
    item_count = 0
    in_string = False
    escaped = False
    try:
        for character in text:
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "[{":
                depth += 1
                if depth > MAX_PROVIDER_CONTAINER_DEPTH:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                item_count += 1
            elif character in "]}":
                depth -= 1
                if depth < 0:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
            elif character == ",":
                item_count += 1
            if item_count > MAX_PROVIDER_CONTAINER_ITEMS:
                raise _error(
                    "MistTrack returned invalid response", "invalid_response"
                )
    except MemoryError:
        raise _error("MistTrack returned invalid response", "invalid_response") from None
    if in_string or depth != 0:
        raise _error("MistTrack returned invalid response", "invalid_response")


def _validate_payload_structure(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    item_count = 0
    try:
        while stack:
            current, depth = stack.pop()
            if isinstance(current, dict):
                if depth >= MAX_PROVIDER_CONTAINER_DEPTH:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                item_count += len(current)
                if item_count > MAX_PROVIDER_CONTAINER_ITEMS:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                for key, item in current.items():
                    if (
                        not isinstance(key, str)
                        or len(key) > MAX_PROVIDER_SCALAR_CHARS
                    ):
                        raise _error(
                            "MistTrack returned invalid response", "invalid_response"
                        )
                    stack.append((item, depth + 1))
                continue
            if isinstance(current, list):
                if depth >= MAX_PROVIDER_CONTAINER_DEPTH:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                item_count += len(current)
                if item_count > MAX_PROVIDER_CONTAINER_ITEMS:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                stack.extend((item, depth + 1) for item in current)
                continue
            if isinstance(current, Decimal) or (
                isinstance(current, int) and not isinstance(current, bool)
            ):
                _validate_decimal(current)
                continue
            if isinstance(current, str):
                if len(current) > MAX_PROVIDER_SCALAR_CHARS:
                    raise _error(
                        "MistTrack returned invalid response", "invalid_response"
                    )
                continue
            if current is None or isinstance(current, bool):
                continue
            raise _error("MistTrack returned invalid response", "invalid_response")
    except (MemoryError, OverflowError, ValueError):
        raise _error("MistTrack returned invalid response", "invalid_response") from None


def _validate_decimal(value: int | Decimal) -> Decimal:
    try:
        decimal = Decimal(value)
        _sign, digits, exponent = decimal.as_tuple()
        if (
            not decimal.is_finite()
            or len(digits) > MAX_PROVIDER_NUMERIC_DIGITS
            or abs(exponent) > MAX_PROVIDER_NUMERIC_EXPONENT
        ):
            raise _error("MistTrack returned invalid response", "invalid_response")
        rendered = format(decimal, "f")
    except (InvalidOperation, MemoryError, OverflowError, ValueError):
        raise _error("MistTrack returned invalid response", "invalid_response") from None
    if len(rendered) > MAX_PROVIDER_SCALAR_CHARS:
        raise _error("MistTrack returned invalid response", "invalid_response")
    return decimal


def _normalize_score(value: Any) -> int:
    if type(value) is int:
        score = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        if len(value) > MAX_PROVIDER_SCORE_DIGITS:
            raise _error("MistTrack returned invalid response", "invalid_response")
        score = int(value)
    else:
        raise _error("MistTrack returned invalid response", "invalid_response")
    if not 0 <= score <= 100:
        raise _error("MistTrack returned invalid response", "invalid_response")
    return score


def _normalize_level(value: Any) -> str:
    if not isinstance(value, str):
        raise _error("MistTrack returned invalid response", "invalid_response")
    normalized = value.strip().lower()
    if normalized not in {"low", "moderate", "high", "severe"}:
        raise _error("MistTrack returned invalid response", "invalid_response")
    return normalized


def _normalize_indicators(value: Any, *, forbidden: str) -> tuple[str, ...]:
    if value in (None, "", [], {}):
        return ()
    candidates: list[Any]
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, dict):
        candidates = [key for key, enabled in value.items() if enabled]
    else:
        raise _error("MistTrack returned invalid response", "invalid_response")
    normalized: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = next(
                (
                    candidate.get(key)
                    for key in ("label", "name", "risk_type", "type")
                    if candidate.get(key)
                ),
                None,
            )
        text = _safe_text(candidate, forbidden=forbidden, identifier=False)
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _normalize_risk_details(
    value: Any,
    *,
    forbidden: str,
) -> tuple[dict[str, str], ...]:
    if value in (None, "", [], {}):
        return ()
    if isinstance(value, list):
        details = value
    elif isinstance(value, dict):
        normalized_keys = {_normalize_field_name(key) for key in value}
        if normalized_keys & {"risk_type", "exposure_type"}:
            details = [value]
        else:
            details = [
                {"risk_type": key, "value": item}
                for key, item in value.items()
                if item not in (None, "", 0, "0", False, [], {})
            ]
    else:
        raise _error("MistTrack returned invalid response", "invalid_response")

    normalized: list[dict[str, str]] = []
    for detail in details:
        if isinstance(detail, str):
            normalized.append(
                {"risk_type": _safe_text(detail, forbidden=forbidden, identifier=True)}
            )
            continue
        if not isinstance(detail, dict) or not detail:
            raise _error("MistTrack returned invalid response", "invalid_response")
        normalized_detail: dict[str, str] = {}
        for key, item in detail.items():
            field = _normalize_field_name(key)
            normalized_detail[field] = _safe_scalar(
                item,
                forbidden=forbidden,
                identifier=field in {"risk_type", "exposure_type"},
            )
        normalized.append(normalized_detail)
    return tuple(normalized)


def _normalize_hacking_event(value: Any, *, forbidden: str) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return _safe_text(value, forbidden=forbidden, identifier=False)
    if isinstance(value, (list, dict)):
        normalized = _json_safe(value, forbidden=forbidden)
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    raise _error("MistTrack returned invalid response", "invalid_response")


def _json_safe(value: Any, *, forbidden: str) -> Any:
    if isinstance(value, dict):
        return {
            _normalize_field_name(key): _json_safe(item, forbidden=forbidden)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe(item, forbidden=forbidden) for item in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return _decimal_string(value)
    return _safe_text(value, forbidden=forbidden, identifier=False)


def _safe_scalar(value: Any, *, forbidden: str, identifier: bool) -> str:
    if isinstance(value, bool) or value is None:
        raise _error("MistTrack returned invalid response", "invalid_response")
    if isinstance(value, (int, Decimal)):
        return _decimal_string(value)
    return _safe_text(value, forbidden=forbidden, identifier=identifier)


def _decimal_string(value: int | Decimal) -> str:
    return format(_validate_decimal(value), "f")


def _safe_text(value: Any, *, forbidden: str, identifier: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MistTrack returned invalid response", "invalid_response")
    text = value.strip().lower()
    if forbidden.lower() in text or "api_key" in text or "://" in text:
        raise _error("MistTrack returned invalid response", "invalid_response")
    if identifier:
        text = re.sub(r"[\s-]+", "_", text)
    return text


def _normalize_field_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MistTrack returned invalid response", "invalid_response")
    normalized = re.sub(r"[\s-]+", "_", value.strip().lower())
    if "api_key" in normalized or "://" in normalized:
        raise _error("MistTrack returned invalid response", "invalid_response")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("MistTrack clock must return an aware datetime", "configuration")
    return value.astimezone(UTC)


def _as_cache_hit(result: RiskProviderResult) -> RiskProviderResult:
    return replace(
        result,
        indicators=tuple(result.indicators),
        risk_details=tuple(dict(detail) for detail in result.risk_details),
        cache_hit=True,
    )


def _copy_error(error: RiskProviderError) -> RiskProviderError:
    return RiskProviderError(str(error), category=error.category)


def _error(message: str, category: str) -> RiskProviderError:
    return RiskProviderError(message, category=category)
