from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from shared.config import CANONICAL_EVM_NETWORKS


_SUBMISSION_REJECTION_REASONS = frozenset(
    {
        "insufficient_funds",
        "intrinsic_gas_too_low",
        "invalid_sender",
        "transaction_type_not_supported",
    }
)
_MAX_RPC_ERROR_MESSAGE = 256
_MAX_RPC_RESPONSE_BYTES = 65_536
_DEFINITE_SUBMISSION_ERROR_CODES = frozenset({-32000, -32003})


class _InvalidRpcResponse(Exception):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class RpcSubmissionRejected(RuntimeError):
    """A redacted, definite pre-broadcast rejection from an EVM node."""

    def __init__(self, reason_code: str) -> None:
        if reason_code not in _SUBMISSION_REJECTION_REASONS:
            raise ValueError("unsupported RPC submission rejection reason")
        super().__init__("EVM transaction submission was definitely rejected")
        self.reason_code = reason_code


def _submission_rejection_reason(error: object) -> str | None:
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    message = error.get("message")
    if (
        type(code) is not int
        or code not in _DEFINITE_SUBMISSION_ERROR_CODES
        or not isinstance(message, str)
        or not message
        or len(message) > _MAX_RPC_ERROR_MESSAGE
        or message.strip() != message
    ):
        return None
    normalized = message.casefold()
    if normalized == "insufficient funds" or normalized.startswith(
        "insufficient funds for gas"
    ):
        return "insufficient_funds"
    exact_or_detail = (
        ("intrinsic gas too low", "intrinsic_gas_too_low"),
        ("invalid sender", "invalid_sender"),
        (
            "transaction type not supported",
            "transaction_type_not_supported",
        ),
    )
    return next(
        (
            reason
            for prefix, reason in exact_or_detail
            if normalized == prefix or normalized.startswith(prefix + ":")
        ),
        None,
    )


class NetworkRpcTransport:
    """Route JSON-RPC without ever including provider URLs in failures."""

    def __init__(
        self,
        rpc_urls: Mapping[str, str],
        *,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: float = 20.0,
    ) -> None:
        unsupported = set(rpc_urls) - set(CANONICAL_EVM_NETWORKS)
        if unsupported:
            raise ValueError(
                f"unsupported canonical EVM network: {sorted(unsupported)[0]}"
            )
        self.rpc_urls = {network: value for network, value in rpc_urls.items() if value}
        self.opener = opener
        self.timeout_seconds = timeout_seconds

    def __call__(self, network: str, method: str, params: list[Any]) -> Any:
        if network not in CANONICAL_EVM_NETWORKS:
            raise ValueError(f"unsupported canonical EVM network: {network}")
        url = self.rpc_urls.get(network)
        if not url:
            raise RuntimeError(f"{CANONICAL_EVM_NETWORKS[network]} is not configured")
        payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": method,
            "params": params,
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Agentonomy-Clink-Node/1.0",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                headers = getattr(response, "headers", None)
                header_get = getattr(headers, "get", None)
                if not callable(header_get):
                    raise _InvalidRpcResponse
                content_type = header_get("Content-Type")
                if (
                    not isinstance(content_type, str)
                    or content_type.split(";", 1)[0].strip().casefold()
                    != "application/json"
                ):
                    raise _InvalidRpcResponse
                content_length = header_get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError):
                        raise _InvalidRpcResponse from None
                    if not 0 <= declared_length <= _MAX_RPC_RESPONSE_BYTES:
                        raise _InvalidRpcResponse
                raw = response.read(_MAX_RPC_RESPONSE_BYTES + 1)
                if not isinstance(raw, bytes) or len(raw) > _MAX_RPC_RESPONSE_BYTES:
                    raise _InvalidRpcResponse
                try:
                    result = json.loads(
                        raw.decode("utf-8"), object_pairs_hook=_unique_json_object
                    )
                except (UnicodeError, ValueError, TypeError):
                    raise _InvalidRpcResponse from None
        except (HTTPError, URLError, OSError):
            raise RuntimeError(f"EVM RPC unavailable for {network}") from None
        except _InvalidRpcResponse:
            raise RuntimeError(
                f"EVM RPC returned an invalid response for {network}"
            ) from None
        if (
            not isinstance(result, dict)
            or result.get("jsonrpc") != "2.0"
            or result.get("id") != payload["id"]
            or ("result" in result) == ("error" in result)
        ):
            raise RuntimeError(f"EVM RPC returned an invalid response for {network}")
        if "error" in result:
            reason = (
                _submission_rejection_reason(result["error"])
                if method == "eth_sendRawTransaction"
                else None
            )
            if reason is not None:
                raise RpcSubmissionRejected(reason)
            raise RuntimeError(f"EVM RPC returned an ambiguous error for {network}")
        return result["result"]
