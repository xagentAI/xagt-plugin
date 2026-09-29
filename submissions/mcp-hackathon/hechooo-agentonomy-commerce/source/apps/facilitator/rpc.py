"""Narrow, fail-closed JSON-RPC transport for Hosted execution."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping
from threading import Lock
from time import monotonic as _monotonic, sleep as _sleep
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

try:  # pragma: no cover - the injected client path is used by unit tests.
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


SUPPORTED_RPC_METHODS = frozenset(
    {
        "eth_chainId",
        "eth_getTransactionCount",
        "eth_estimateGas",
        "eth_maxPriorityFeePerGas",
        "eth_gasPrice",
        "eth_sendRawTransaction",
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_getBlockByNumber",
        "eth_call",
        "eth_getCode",
    }
)

MAX_RPC_RESPONSE_BYTES = 65_536
MAX_RPC_REQUEST_BYTES = 128 * 1024
MAX_RPC_ERROR_MESSAGE = 256
MAX_RPC_ID_LENGTH = 128
IJSON_SAFE_INTEGER_MAX = (1 << 53) - 1

_MACHINE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CANONICAL_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_KNOWN_TRANSACTION_MARKERS = (
    "already known",
    "known transaction",
    "already imported",
)
_NONCE_CONFLICT_MARKERS = (
    "nonce too low",
    "replacement transaction underpriced",
    "fee too low to replace pending transaction",
)
_DEFINITE_REJECTION_PREFIXES = (
    ("insufficient funds", "insufficient_funds"),
    ("intrinsic gas too low", "intrinsic_gas_too_low"),
    ("invalid sender", "invalid_sender"),
    ("transaction type not supported", "transaction_type_not_supported"),
)
_DEFINITE_REJECTION_CODES = frozenset({-32000, -32003})


class _DuplicateJSONMember(ValueError):
    pass


class _InvalidResponse(ValueError):
    pass


class _HttpFailure(OSError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONMember(key)
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _is_loopback(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _canonical_rpc_url(url: object, *, environment: str) -> tuple[str, str]:
    """Return endpoint URL and a secret-free canonical origin."""

    if environment not in {"production", "test"}:
        raise ValueError("RPC environment is invalid")
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("RPC URL is invalid")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("RPC URL is invalid")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("RPC URL is invalid") from None
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.path == ""
        and parsed.netloc == ""
    ):
        raise ValueError("RPC URL is invalid")
    scheme = parsed.scheme.lower()
    if environment == "production" and scheme != "https":
        raise ValueError("production RPC URL must use HTTPS")
    if environment == "test" and not (
        scheme == "https" or scheme == "http" and _is_loopback(hostname)
    ):
        raise ValueError("test RPC URL must use HTTPS or loopback HTTP")
    if port in {80, 443}:
        raise ValueError("RPC URL must not use an explicit default port")
    try:
        canonical_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("RPC URL is invalid") from None
    try:
        ip = ipaddress.ip_address(canonical_host)
    except ValueError:
        ip = None
    if isinstance(ip, ipaddress.IPv6Address):
        origin_host = f"[{canonical_host}]"
    else:
        origin_host = canonical_host
    origin = f"{scheme}://{origin_host}"
    if port is not None:
        origin += f":{port}"
    endpoint = url
    if not parsed.path:
        endpoint = url.rstrip("/") + "/"
    return endpoint, origin


def canonical_rpc_origin(url: object, *, environment: str = "production") -> str:
    """Validate a provider URL and return only its origin."""

    try:
        _, origin = _canonical_rpc_url(url, environment=environment)
    except ValueError as exc:
        raise RpcConfigurationError(str(exc)) from None
    return origin


def require_distinct_rpc_origins(
    primary: object,
    watcher: object,
    *,
    environment: str = "production",
) -> None:
    """Validate both RPC URLs and require independent canonical origins."""

    primary_origin = canonical_rpc_origin(primary, environment=environment)
    watcher_origin = canonical_rpc_origin(watcher, environment=environment)
    if primary_origin == watcher_origin:
        raise RpcConfigurationError("RPC origins must be distinct")


class RpcError(RuntimeError):
    """Base class for bounded, provider-secret-free RPC failures."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        classification: str | None = None,
        needs_lookup: bool = False,
    ) -> None:
        if _MACHINE_CODE.fullmatch(reason_code) is None:
            raise ValueError("RPC reason code is invalid")
        self.reason_code = reason_code
        self.classification = classification
        self.needs_lookup = needs_lookup
        super().__init__(message)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(reason_code={self.reason_code!r}, "
            f"classification={self.classification!r}, needs_lookup={self.needs_lookup!r})"
        )


class RpcConfigurationError(ValueError):
    """Invalid local transport configuration without echoing its value."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class RpcProtocolError(RpcError):
    def __init__(self, message: str = "RPC protocol response is invalid") -> None:
        super().__init__("rpc_protocol_error", message)


class RpcTransportError(RpcError):
    def __init__(self, reason_code: str = "rpc_unavailable") -> None:
        super().__init__(reason_code, "RPC transport is unavailable")


class RpcReadError(RpcError):
    def __init__(self, reason_code: str = "rpc_error") -> None:
        super().__init__(reason_code, "RPC read failed")


class RpcSubmissionUnknown(RpcTransportError):
    def __init__(self, *, classification: str = "transport_error") -> None:
        RpcError.__init__(
            self,
            "submission_unknown",
            "RPC transaction submission status is unknown; lookup is required",
            classification=classification,
            needs_lookup=True,
        )


class RpcSubmissionRejected(RpcError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(
            reason_code,
            f"RPC transaction submission was definitely rejected ({reason_code})",
            classification="definite_rejection",
            needs_lookup=False,
        )


def _validate_jsonrpc_id(value: object) -> str | int:
    if type(value) is int:
        if not 0 <= value <= IJSON_SAFE_INTEGER_MAX:
            raise ValueError("JSON-RPC request ID is invalid")
        return value
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_RPC_ID_LENGTH
        or not value.isascii()
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("JSON-RPC request ID is invalid")
    return value


def _header_value(headers: object, name: str) -> object:
    if not isinstance(headers, Mapping):
        return None
    name = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name:
            return value
    return None


def _validate_error_object(error: object) -> dict[str, Any]:
    if not isinstance(error, dict):
        raise _InvalidResponse
    if not set(error) <= {"code", "message", "data"}:
        raise _InvalidResponse
    code = error.get("code")
    message = error.get("message")
    if (
        type(code) is not int
        or not isinstance(message, str)
        or not message
        or len(message) > MAX_RPC_ERROR_MESSAGE
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in message)
    ):
        raise _InvalidResponse
    return error


def _classify_submission_error(error: dict[str, Any]) -> RpcError:
    code = error["code"]
    message = error["message"].strip().casefold()
    if any(marker in message for marker in _KNOWN_TRANSACTION_MARKERS):
        return RpcSubmissionUnknown(classification="already_known")
    if any(marker in message for marker in _NONCE_CONFLICT_MARKERS):
        return RpcSubmissionUnknown(classification="nonce_conflict")
    if type(code) is int and code in _DEFINITE_REJECTION_CODES:
        for prefix, reason_code in _DEFINITE_REJECTION_PREFIXES:
            if message == prefix or message.startswith(prefix + ":"):
                return RpcSubmissionRejected(reason_code)
    return RpcSubmissionUnknown(classification="provider_error")


class JsonRpcTransport:
    """A single-request, no-retry JSON-RPC transport for Hosted methods."""

    def __init__(
        self,
        url: str,
        *,
        environment: str = "production",
        client: Any | None = None,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = MAX_RPC_RESPONSE_BYTES,
    ) -> None:
        try:
            endpoint, origin = _canonical_rpc_url(url, environment=environment)
        except ValueError as exc:
            raise RpcConfigurationError(str(exc)) from None
        if (
            type(timeout_seconds) not in {int, float}
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
            or timeout_seconds > 60
        ):
            raise RpcConfigurationError("RPC timeout is invalid")
        if (
            type(max_response_bytes) is not int
            or not 1024 <= max_response_bytes <= MAX_RPC_RESPONSE_BYTES
        ):
            raise RpcConfigurationError("RPC response limit is invalid")
        if client is None:
            if httpx is None:
                raise RpcConfigurationError("HTTP client is unavailable")
            client = httpx.Client()
            self._owns_client = True
        else:
            self._owns_client = False
        if not callable(getattr(client, "post", None)):
            raise RpcConfigurationError("HTTP client is invalid")
        self._endpoint = endpoint
        self._origin = origin
        self._environment = environment
        self._client = client
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(origin={self._origin!r}, "
            f"environment={self._environment!r}, timeout_seconds={self._timeout_seconds!r})"
        )

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "JsonRpcTransport":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __call__(
        self,
        method: str,
        params: list[Any],
        *,
        request_id: str | int | None = None,
    ) -> Any:
        return self.call(method, params, request_id=request_id)

    def call(
        self,
        method: str,
        params: list[Any],
        *,
        request_id: str | int | None = None,
    ) -> Any:
        if not isinstance(method, str) or method not in SUPPORTED_RPC_METHODS:
            raise RpcProtocolError("RPC method is not allowed")
        if type(params) is not list:
            raise RpcProtocolError("RPC params must be an array")
        if request_id is None:
            request_id = uuid4().hex
        try:
            request_id = _validate_jsonrpc_id(request_id)
        except ValueError:
            raise RpcProtocolError("RPC request ID is invalid") from None
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError):
            raise RpcProtocolError("RPC request is not valid JSON") from None
        if len(encoded) > MAX_RPC_REQUEST_BYTES:
            raise RpcProtocolError("RPC request is too large")

        try:
            response = self._client.post(
                self._endpoint,
                json=payload,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                timeout=self._timeout_seconds,
            )
        except Exception:
            if method == "eth_sendRawTransaction":
                raise RpcSubmissionUnknown() from None
            raise RpcTransportError() from None

        try:
            if type(getattr(response, "status_code", None)) is not int:
                raise _InvalidResponse
            if not 200 <= response.status_code < 300:
                raise _HttpFailure
            body = self._read_response_body(response)
            decoded = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            kind, value = self._validate_response(decoded, request_id)
        except _HttpFailure:
            if method == "eth_sendRawTransaction":
                raise RpcSubmissionUnknown() from None
            raise RpcTransportError() from None
        except (UnicodeError, TypeError, ValueError, _InvalidResponse):
            if method == "eth_sendRawTransaction":
                raise RpcSubmissionUnknown() from None
            raise RpcProtocolError() from None
        except Exception:
            if method == "eth_sendRawTransaction":
                raise RpcSubmissionUnknown() from None
            raise RpcTransportError() from None

        if kind == "error":
            if method == "eth_sendRawTransaction":
                raise _classify_submission_error(value)
            raise RpcReadError()
        if method == "eth_sendRawTransaction" and (
            not isinstance(value, str) or _CANONICAL_TX_HASH.fullmatch(value) is None
        ):
            raise RpcSubmissionUnknown(classification="invalid_result")
        return value

    def _read_response_body(self, response: Any) -> bytes:
        content_type = _header_value(getattr(response, "headers", None), "content-type")
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().casefold() != "application/json"
        ):
            raise _InvalidResponse
        content_length = _header_value(getattr(response, "headers", None), "content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except (TypeError, ValueError):
                raise _InvalidResponse from None
            if declared < 0 or declared > self._max_response_bytes:
                raise _InvalidResponse
        body = getattr(response, "content", None)
        if not isinstance(body, bytes):
            raise _InvalidResponse
        if len(body) > self._max_response_bytes:
            raise _InvalidResponse
        return body

    @staticmethod
    def _validate_response(decoded: object, request_id: str | int) -> tuple[str, Any]:
        if not isinstance(decoded, dict):
            raise _InvalidResponse
        if set(decoded) - {"jsonrpc", "id", "result", "error"}:
            raise _InvalidResponse
        if (
            decoded.get("jsonrpc") != "2.0"
            or type(decoded.get("id")) is not type(request_id)
            or decoded.get("id") != request_id
        ):
            raise _InvalidResponse
        has_result = "result" in decoded
        has_error = "error" in decoded
        if has_result == has_error:
            raise _InvalidResponse
        if has_error:
            return "error", _validate_error_object(decoded["error"])
        return "result", decoded["result"]


class PacedRpcTransport:
    """Serialize read-only watcher RPC calls with an opt-in minimum interval."""

    def __init__(
        self,
        delegate: Any,
        *,
        min_interval_seconds: float,
        monotonic: Callable[[], float] = _monotonic,
        sleep: Callable[[float], None] = _sleep,
    ) -> None:
        if (
            type(min_interval_seconds) not in {int, float}
            or isinstance(min_interval_seconds, bool)
            or not 0 <= min_interval_seconds <= 60
        ):
            raise RpcConfigurationError("RPC pacing interval is invalid")
        if not callable(getattr(delegate, "call", None)):
            raise RpcConfigurationError("RPC pacing delegate is invalid")
        if not callable(monotonic) or not callable(sleep):
            raise RpcConfigurationError("RPC pacing clock is invalid")
        self._delegate = delegate
        self._min_interval_seconds = float(min_interval_seconds)
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = Lock()
        self._last_started_at: float | None = None

    def call(
        self,
        method: str,
        params: list[Any],
        *,
        request_id: str | int | None = None,
    ) -> Any:
        with self._lock:
            now = self._monotonic()
            if self._last_started_at is not None:
                remaining = self._min_interval_seconds - (now - self._last_started_at)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._monotonic()
            self._last_started_at = now
            return self._delegate.call(method, params, request_id=request_id)

    def __call__(
        self,
        method: str,
        params: list[Any],
        *,
        request_id: str | int | None = None,
    ) -> Any:
        return self.call(method, params, request_id=request_id)

    def close(self) -> None:
        close = getattr(self._delegate, "close", None)
        if callable(close):
            close()
