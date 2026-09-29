from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn
from urllib.parse import urlsplit

import httpx

_MAX_REQUEST_BYTES = 32_768
_MAX_RESPONSE_BYTES = 65_536
_MAX_JSON_DEPTH = 8
_MAX_JSON_NODES = 2_048
_MAX_JSON_STRING = 4_096
_UINT256_MAX = 2**256 - 1
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}$")
_PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$")
_ATOMIC = re.compile(r"^[1-9][0-9]{0,77}$")
_ADDRESS = re.compile(r"^0[xX]([0-9a-fA-F]{40})$")
_HASH = re.compile(r"^0[xX]([0-9a-fA-F]{64})$")
_OPC_INSTALLATION = re.compile(r"^opc_[0-9a-f]{40}$")
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)

_NETWORK = "eip155:137"
_PRODUCT = "prediction_markets"
_VENUE = _MERCHANT = "polymarket"
_MERCHANT_TRUST = "clink_verified"
_RAIL = "native_allowance"
_RISK_LEVELS = {"low", "medium", "high", "critical"}
_RISK_ACTIONS = {
    "approve", "hold", "block", "blocked", "reject", "deny",
    "manual_review", "review",
}
_MISTTRACK_PROVIDER = "misttrack"
_MISTTRACK_ENDPOINT = "v2/risk_score"
_MISTTRACK_MAPPING_VERSION = "misttrack-policy-v1"
_MISTTRACK_ASSET = "USDC"
_MISTTRACK_COIN = "USDC-Polygon"
_MISTTRACK_LEVELS = {"low", "moderate", "high", "severe"}
_MISTTRACK_DECISIONS = {"allow", "hold", "deny", "unavailable"}
_MISTTRACK_MODES = {"shadow", "enforce"}
_MISTTRACK_ERROR_CATEGORIES = {
    "configuration",
    "invalid_address",
    "invalid_key",
    "invalid_response",
    "not_configured",
    "payment_required",
    "plan_expired",
    "provider_error",
    "rate_limited",
    "unavailable",
    "unsupported_asset",
    "unsupported_network",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

class PredictionCoreGatewayError(RuntimeError):
    """Redacted failure at the Prediction Markets -> Core boundary."""

    def __init__(
        self,
        message: str = "Core request failed",
        *,
        status_code: int | None = None,
        reason_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code

@dataclass(frozen=True)
class PredictionFundingContext:
    user_id: str
    agent_id: str
    operation_id: str
    idempotency_key: str
    resource: str
    wallet_identity_id: str
    spending_grant_id: str
    asset_allowance_id: str
    amount_usdc: str
    amount_atomic: str
    token_address: str
    destination: str
    quote_hash: str
    opc_installation_id: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.user_id, self.agent_id, self.operation_id, self.idempotency_key,
            self.wallet_identity_id, self.spending_grant_id, self.asset_allowance_id,
        ):
            _identifier(value)
        _resource(self.resource)
        amount, atomic = _matched_amounts(self.amount_usdc, self.amount_atomic)
        object.__setattr__(self, "amount_usdc", _render_decimal(amount))
        object.__setattr__(self, "amount_atomic", atomic)
        object.__setattr__(self, "token_address", _address(self.token_address))
        object.__setattr__(self, "destination", _address(self.destination))
        object.__setattr__(self, "quote_hash", _hash(self.quote_hash))
        if self.opc_installation_id is not None:
            object.__setattr__(
                self,
                "opc_installation_id",
                _opc_installation_id(self.opc_installation_id),
            )

    @property
    def provenance(self) -> dict[str, str]:
        result = {
            "purchase_id": self.operation_id, "quote_hash": self.quote_hash,
            "network": _NETWORK, "asset": self.token_address,
            "amount_atomic": self.amount_atomic, "destination": self.destination,
            "resource": self.resource, "authorization_rail": _RAIL,
            "product": _PRODUCT, "merchant_trust_tier": _MERCHANT_TRUST,
            "wallet_identity_id": self.wallet_identity_id,
            "spending_grant_id": self.spending_grant_id,
            "asset_allowance_id": self.asset_allowance_id,
        }
        if self.opc_installation_id is not None:
            result["opc_installation_id"] = self.opc_installation_id
        return result

class HttpPredictionCoreFundingGateway:
    """One-shot, loopback-only HTTP gateway for Core-owned funding controls."""

    def __init__(
        self, *, token: str,
        action_base_url: str = "http://127.0.0.1:8016",
        policy_base_url: str = "http://127.0.0.1:8015",
        audit_base_url: str = "http://127.0.0.1:8017",
        funding_base_url: str = "http://127.0.0.1:8018",
        account_base_url: str = "http://127.0.0.1:8019",
        timeout_seconds: float = 15,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (
            not isinstance(token, str) or token.strip() != token or not token
            or len(token) > 512 or any(not 33 <= ord(char) <= 126 for char in token)
        ):
            raise ValueError("Core internal bearer token is invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("Core timeout is invalid")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1_024 <= max_response_bytes <= 1_048_576
        ):
            raise ValueError("Core response limit is invalid")
        self.action_base_url = _loopback_origin(action_base_url)
        self.policy_base_url = _loopback_origin(policy_base_url)
        self.audit_base_url = _loopback_origin(audit_base_url)
        self.funding_base_url = _loopback_origin(funding_base_url)
        self.account_base_url = _loopback_origin(account_base_url)
        self.max_response_bytes = max_response_bytes
        self._client = httpx.Client(
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=float(timeout_seconds), transport=transport,
            follow_redirects=False, trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpPredictionCoreFundingGateway:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def funding_readiness(self) -> dict[str, Any]:
        return _funding_readiness(
            self._request("GET", self.funding_base_url, "/funding/readiness")
        )

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        user_id = _identifier(user_id)
        response = self._request(
            "GET", self.account_base_url, "/internal/account-readiness",
            params={"user_id": user_id},
        )
        return _account_readiness(response, user_id)

    def resolve_authorization(
        self, *, user_id: str, agent_id: str, amount_usdc: str,
        amount_atomic: str, token_address: str, spender_address: str,
        destination: str, resource: str,
        opc_installation_id: str | None = None,
    ) -> dict[str, Any]:
        amount, atomic = _matched_amounts(amount_usdc, amount_atomic)
        payload = {
            "user_id": _identifier(user_id), "agent_id": _identifier(agent_id),
            "authorization_rail": _RAIL, "product": _PRODUCT,
            "venue": _VENUE, "merchant": _MERCHANT,
            "merchant_trust_tier": _MERCHANT_TRUST, "network": _NETWORK,
            "token_address": _address(token_address),
            "spender_address": _address(spender_address),
            "amount_usdc": _render_decimal(amount),
            "destination": _address(destination), "resource": _resource(resource),
        }
        if opc_installation_id is not None:
            payload["opc_installation_id"] = _opc_installation_id(
                opc_installation_id
            )
        response = self._request(
            "POST", self.account_base_url, "/internal/authorization-resolution",
            payload=payload,
        )
        return _authorization(
            response,
            int(atomic),
            expected_opc_installation_id=opc_installation_id,
        )

    def create_action(self, context: PredictionFundingContext) -> dict[str, Any]:
        response = self._request(
            "POST", self.action_base_url, "/actions",
            payload={
                "user_id": context.user_id, "agent_id": context.agent_id,
                "action_type": "funding_transfer", "amount_usdc": context.amount_usdc,
                "target": context.destination, "merchant_id": _MERCHANT,
                "authorization_id": context.spending_grant_id,
                "description": "Fund Polymarket Bridge deposit",
                "metadata": context.provenance,
            },
        )
        return _action(response, context, "created")

    def evaluate_policy(
        self, context: PredictionFundingContext, *, action_id: str,
        risk_level: str, risk_score: int, risk_action: str,
        user_confirmed: bool, live_mode: bool,
    ) -> dict[str, Any]:
        action_id = _path_identifier(action_id)
        if not isinstance(risk_level, str):
            raise ValueError("Core risk level is invalid")
        risk_level = risk_level.strip().lower()
        if risk_level not in _RISK_LEVELS:
            raise ValueError("Core risk level is invalid")
        if isinstance(risk_score, bool) or not isinstance(risk_score, int) or not 0 <= risk_score <= 100:
            raise ValueError("Core risk score is invalid")
        if not isinstance(risk_action, str):
            raise ValueError("Core risk action is invalid")
        risk_action = risk_action.strip().lower()
        if risk_action not in _RISK_ACTIONS:
            raise ValueError("Core risk action is invalid")
        if not isinstance(user_confirmed, bool) or not isinstance(live_mode, bool):
            raise ValueError("Core policy flags are invalid")
        response = self._request(
            "POST", self.policy_base_url, "/policies/evaluate",
            payload={
                "action_id": action_id, "user_id": context.user_id,
                "agent_id": context.agent_id, "action_type": "funding_transfer",
                "amount_usdc": context.amount_usdc,
                "merchant_id": _MERCHANT, "target_address": context.destination,
                "chain": _NETWORK, "risk_level": risk_level,
                "risk_score": risk_score, "risk_action": risk_action,
                "user_confirmed": user_confirmed, "requires_confirmation": True,
                "live_mode": live_mode, "metadata": context.provenance,
            },
        )
        return _policy(
            response, context, action_id,
            risk_level=risk_level, risk_score=risk_score, risk_action=risk_action,
        )

    def update_action_policy_approved(
        self, context: PredictionFundingContext, *, action_id: str,
        policy_decision_id: str,
    ) -> dict[str, Any]:
        action_id = _path_identifier(action_id)
        policy_decision_id = _identifier(policy_decision_id)
        response = self._request(
            "POST", self.action_base_url, f"/actions/{action_id}/update",
            payload={"state": "policy_approved", "policy_decision_id": policy_decision_id},
        )
        return _action(response, context, "policy_approved", action_id, policy_decision_id)

    def audit_policy_evaluated(
        self, context: PredictionFundingContext, *, action_id: str,
        policy_decision_id: str,
    ) -> dict[str, Any]:
        action_id = _path_identifier(action_id)
        policy_decision_id = _identifier(policy_decision_id)
        idempotency_key = f"{context.idempotency_key}:policy-evaluated"
        if len(idempotency_key) > 128:
            raise ValueError("Core audit idempotency key is invalid")
        audit_payload = {**context.provenance, "merchant_id": _MERCHANT, "venue": _VENUE}
        response = self._request(
            "POST", self.audit_base_url, "/audit/events",
            payload={
                "idempotency_key": idempotency_key,
                "event_type": "prediction_market_funding_policy_evaluated",
                "source_service": "clink_prediction_markets",
                "action_id": action_id, "user_id": context.user_id,
                "agent_id": context.agent_id,
                "policy_decision_id": policy_decision_id, "payload": audit_payload,
            },
        )
        return _audit(response, context, action_id, policy_decision_id, audit_payload)

    def reserve(
        self, context: PredictionFundingContext, *, action_id: str,
        policy_decision_id: str,
    ) -> dict[str, Any]:
        action_id = _path_identifier(action_id)
        policy_decision_id = _identifier(policy_decision_id)
        payload = {
            "purchase_id": context.operation_id,
            "idempotency_key": context.idempotency_key,
            "authorization_rail": _RAIL,
            "wallet_identity_id": context.wallet_identity_id,
            "spending_grant_id": context.spending_grant_id,
            "asset_allowance_id": context.asset_allowance_id,
            "product": _PRODUCT, "action_id": action_id,
            "policy_decision_id": policy_decision_id,
            "merchant_id": _MERCHANT,
            "merchant_trust_tier": _MERCHANT_TRUST,
            "quote_hash": context.quote_hash,
            "amount_usdc": context.amount_usdc,
            "amount_atomic": context.amount_atomic, "network": _NETWORK,
            "asset": context.token_address, "destination": context.destination,
            "resource": context.resource, "venue": _VENUE,
        }
        if context.opc_installation_id is not None:
            payload["opc_installation_id"] = context.opc_installation_id
        response = self._request(
            "POST", self.funding_base_url, "/funding/spending-reservations",
            payload=payload,
        )
        return _reservation(response, context=context)

    def settle(
        self, reservation_id: str, *, payment_authorization: dict[str, Any]
    ) -> dict[str, Any]:
        reservation_id = _path_identifier(reservation_id)
        response = self._request(
            "POST", self.funding_base_url,
            f"/funding/spending-reservations/{reservation_id}/settle",
            payload={"payment_authorization": _payment_authorization(payment_authorization, reservation_id)},
        )
        return _reservation(response, reservation_id=reservation_id)

    def reservation(self, reservation_id: str) -> dict[str, Any]:
        reservation_id = _path_identifier(reservation_id)
        response = self._request(
            "GET", self.funding_base_url,
            f"/funding/spending-reservations/{reservation_id}",
        )
        return _reservation(response, reservation_id=reservation_id)

    def reconcile(self, reservation_id: str) -> dict[str, Any]:
        reservation_id = _path_identifier(reservation_id)
        response = self._request(
            "POST", self.funding_base_url,
            f"/funding/spending-reservations/{reservation_id}/reconcile", payload={},
        )
        return _reservation(response, reservation_id=reservation_id)

    def finalize(
        self, reservation_id: str, *, delivery_status: str,
        output_hash: str | None = None,
    ) -> dict[str, Any]:
        reservation_id = _path_identifier(reservation_id)
        request: dict[str, Any] = {"delivery_status": _identifier(delivery_status)}
        if output_hash is not None:
            request["output_hash"] = _hash(output_hash)
        response = self._request(
            "POST", self.funding_base_url,
            f"/funding/spending-reservations/{reservation_id}/finalize", payload=request,
        )
        return _reservation(response, reservation_id=reservation_id)

    def release(self, reservation_id: str, *, reason: str) -> dict[str, Any]:
        reservation_id = _path_identifier(reservation_id)
        response = self._request(
            "POST", self.funding_base_url,
            f"/funding/spending-reservations/{reservation_id}/release",
            payload={"reason": _identifier(reason)},
        )
        return _reservation(response, reservation_id=reservation_id)

    def _request(
        self, method: str, base_url: str, path: str, *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Core request path is invalid")
        content = headers = None
        if payload is not None:
            _safe_json(payload)
            content = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            ).encode()
            if len(content) > _MAX_REQUEST_BYTES:
                raise ValueError("Core request body is too large")
            headers = {"Content-Type": "application/json"}
        try:
            with self._client.stream(
                method, f"{base_url}{path}", params=params,
                content=content, headers=headers,
            ) as response:
                raw = self._body(response)
        except PredictionCoreGatewayError:
            raise
        except httpx.HTTPError:
            raise PredictionCoreGatewayError() from None
        if response.status_code != 200:
            raise PredictionCoreGatewayError(
                status_code=response.status_code,
                reason_code=_reason_code(response, raw),
            ) from None
        return _decode(response, raw)

    def _body(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if not 0 <= int(declared) <= self.max_response_bytes:
                    _invalid()
            except ValueError:
                _invalid()
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_response_bytes:
                    _invalid()
                chunks.append(chunk)
        except PredictionCoreGatewayError:
            raise
        except httpx.HTTPError:
            _invalid()
        return b"".join(chunks)

def _invalid() -> NoReturn:
    raise PredictionCoreGatewayError("Core response was invalid") from None

def _loopback_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Core service URL is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        value.strip() != value or parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None or parsed.password is not None
        or port is None or not 1 <= port <= 65_535
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        raise ValueError("Core service URL is invalid")
    return f"http://{parsed.hostname}:{port}"

def _match(value: Any, pattern: re.Pattern[str], message: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value

def _identifier(value: Any) -> str:
    return _match(value, _ID, "Core resource identifier is invalid")


def _opc_installation_id(value: Any) -> str:
    return _match(
        value,
        _OPC_INSTALLATION,
        "OPC installation identifier is invalid",
    )

def _path_identifier(value: Any) -> str:
    return _match(value, _PATH_ID, "Core resource identifier is invalid")

def _resource(value: Any) -> str:
    return _match(value, _RESOURCE, "Core resource identifier is invalid")

def _amount(value: Any, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError("funding amount_usdc is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("funding amount_usdc is invalid") from None
    if result < 0 or (not allow_zero and result == 0):
        raise ValueError("funding amount_usdc is invalid")
    return result

def _render_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered

def _atomic(value: Any) -> str:
    if not isinstance(value, str) or _ATOMIC.fullmatch(value) is None:
        raise ValueError("funding amount_atomic is invalid")
    if int(value) > _UINT256_MAX:
        raise ValueError("funding amount_atomic is invalid")
    return str(int(value))

def _matched_amounts(amount_usdc: Any, amount_atomic: Any) -> tuple[Decimal, str]:
    amount, atomic = _amount(amount_usdc), _atomic(amount_atomic)
    if amount * Decimal(1_000_000) != Decimal(atomic):
        raise ValueError("funding decimal and atomic amounts do not match")
    return amount, atomic

def _canonical(value: Any, pattern: re.Pattern[str], message: str) -> str:
    matched = _match(value, pattern, message)
    return "0x" + matched[2:].lower()

def _address(value: Any) -> str:
    return _canonical(value, _ADDRESS, "EVM address is invalid")

def _hash(value: Any) -> str:
    return _canonical(value, _HASH, "hash is invalid")

def _safe_json(value: Any) -> None:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise ValueError("JSON is too complex")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, int) and not isinstance(item, bool):
            if abs(item) > _UINT256_MAX:
                raise ValueError("JSON integer is out of range")
            return
        if isinstance(item, str):
            if len(item) > _MAX_JSON_STRING or any(ord(char) < 32 for char in item):
                raise ValueError("JSON string is invalid")
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or not key or len(key) > 128 or any(ord(char) < 32 for char in key):
                    raise ValueError("JSON key is invalid")
                visit(child, depth + 1)
            return
        raise ValueError("JSON type is invalid")

    visit(value, 0)

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

def _decode(response: httpx.Response, raw: bytes) -> dict[str, Any]:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        _invalid()
    try:
        payload = json.loads(raw.decode(), object_pairs_hook=_pairs)
        _safe_json(payload)
    except (UnicodeError, ValueError):
        _invalid()
    if not isinstance(payload, dict):
        _invalid()
    return payload

def _reason_code(response: httpx.Response, raw: bytes) -> str | None:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    try:
        body = json.loads(raw.decode(), object_pairs_hook=_pairs)
        _safe_json(body)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    candidates = [body.get("reason_code"), body.get("code")]
    if isinstance(detail, dict):
        candidates += [detail.get("reason_code"), detail.get("code")]
    return next((item for item in candidates if isinstance(item, str) and _REASON.fullmatch(item)), None)

def _shape(payload: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    if not required <= payload.keys() or not payload.keys() <= allowed:
        _invalid()

_READINESS_FIELDS = set("service status settlement_rail live_funding_enabled native_facilitator_enabled native_facilitator_ready hosted_facilitator_enabled hosted_facilitator_ready relayer_address universal_payer_ready payer_address automatic_payment_rail supported_assets mandate_limits_enforced spending_authorization_supported spender_address spender_addresses spending_mode network token token_address missing warnings next_action".split())

def _funding_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    required = set("status settlement_rail live_funding_enabled native_facilitator_ready supported_assets spender_address".split())
    _shape(payload, _READINESS_FIELDS, required)
    assets = payload["supported_assets"]
    try:
        rail = payload["settlement_rail"]
        if payload["status"] not in {"ready", "not_ready"} or rail not in {
            "clink_native_facilitator",
            "clink_hosted_executor",
        }:
            _invalid()
        if not isinstance(payload["live_funding_enabled"], bool) or not isinstance(payload["native_facilitator_ready"], bool):
            _invalid()
        if not isinstance(assets, dict) or not assets.keys() <= {"eip155:137", "eip155:8453"}:
            _invalid()
        assets = {network: _address(address) for network, address in assets.items()}
        spender = _address(payload["spender_address"]) if payload["spender_address"] is not None else None
        spenders_payload = payload.get("spender_addresses") or {}
        if not isinstance(spenders_payload, dict) or not spenders_payload.keys() <= {
            "eip155:137",
            "eip155:8453",
        }:
            _invalid()
        spenders = {
            network: _address(address)
            for network, address in spenders_payload.items()
        }
    except ValueError:
        _invalid()
    hosted_ready = payload.get("hosted_facilitator_ready")
    hosted_enabled = payload.get("hosted_facilitator_enabled")
    automatic_rail = payload.get("automatic_payment_rail")
    if hosted_ready is not None and not isinstance(hosted_ready, bool):
        _invalid()
    if hosted_enabled is not None and not isinstance(hosted_enabled, bool):
        _invalid()
    if payload["status"] == "ready":
        if not payload["live_funding_enabled"] or _NETWORK not in assets:
            _invalid()
        if rail == "clink_native_facilitator" and (
            not payload["native_facilitator_ready"] or spender is None
        ):
            _invalid()
        if rail == "clink_hosted_executor" and (
            hosted_enabled is not True
            or hosted_ready is not True
            or automatic_rail != "clink_hosted_executor"
            or _NETWORK not in spenders
        ):
            _invalid()
    result = {
        "status": payload["status"], "live_funding_enabled": payload["live_funding_enabled"],
        "native_facilitator_ready": payload["native_facilitator_ready"],
        "settlement_rail": payload["settlement_rail"], "spender_address": spender,
        "supported_assets": assets,
    }
    if rail == "clink_hosted_executor":
        result.update(
            hosted_facilitator_enabled=hosted_enabled,
            hosted_facilitator_ready=hosted_ready,
            automatic_payment_rail=automatic_rail,
            spender_addresses=spenders,
        )
    return result

_ACCOUNT_FIELDS = set("user_id wallet_bound wallet_address wallet_identity_id spending_grant_active active_spending_mandate chain_allowances ready".split())
_MANDATE_FIELDS = set("spending_grant_id agent_id limits_usdc remaining_usdc product_scopes venue_scopes merchant_scopes merchant_trust_scopes network_scopes asset_scopes notification_mode expires_at".split())

def _account_readiness(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    _shape(payload, _ACCOUNT_FIELDS, _ACCOUNT_FIELDS)
    if payload["user_id"] != user_id or any(not isinstance(payload[key], bool) for key in ("wallet_bound", "spending_grant_active", "ready")):
        _invalid()
    try:
        wallet = _address(payload["wallet_address"]) if payload["wallet_bound"] else None
        wallet_id = _identifier(payload["wallet_identity_id"]) if payload["wallet_bound"] else None
    except ValueError:
        _invalid()
    if not payload["wallet_bound"] and (payload["wallet_address"] is not None or payload["wallet_identity_id"] is not None):
        _invalid()
    mandate = payload["active_spending_mandate"]
    if mandate is not None:
        if not isinstance(mandate, dict):
            _invalid()
        _shape(mandate, _MANDATE_FIELDS, _MANDATE_FIELDS)
        try:
            _identifier(mandate["spending_grant_id"])
            _identifier(mandate["agent_id"])
            if set(mandate["limits_usdc"]) != {"per_transaction", "rolling_hour", "daily", "total"}:
                _invalid()
            if set(mandate["remaining_usdc"]) != {"rolling_hour", "daily", "total"}:
                _invalid()
            for value in mandate["limits_usdc"].values():
                _amount(value)
            for value in mandate["remaining_usdc"].values():
                _amount(value, allow_zero=True)
            scope_fields = ("product_scopes", "venue_scopes", "merchant_scopes", "merchant_trust_scopes", "network_scopes", "asset_scopes")
            for key in scope_fields:
                if not isinstance(mandate[key], list) or any(not isinstance(value, str) for value in mandate[key]):
                    _invalid()
            for asset in mandate["asset_scopes"]:
                _address(asset)
            if mandate["notification_mode"] not in {"silent_under_limits", "notify_all"}:
                _invalid()
        except (TypeError, ValueError):
            _invalid()
    if payload["spending_grant_active"] != (mandate is not None):
        _invalid()
    allowances = payload["chain_allowances"]
    if not isinstance(allowances, dict) or not allowances.keys() <= {"eip155:137", "eip155:8453"} or any(not isinstance(value, bool) for value in allowances.values()):
        _invalid()
    return {**payload, "wallet_address": wallet, "wallet_identity_id": wallet_id}

_AUTH_FIELDS = set("ready authorization_rail reason_code wallet_identity_id spending_grant_id asset_allowance_id remaining_amount_usdc remaining_daily_amount_usdc remaining_hourly_amount_usdc notification_mode user_interaction_required interaction_reason_code required_amount_atomic observed_allowance_atomic opc_installation_id next_action".split())

def _authorization(
    payload: dict[str, Any],
    expected_atomic: int,
    *,
    expected_opc_installation_id: str | None = None,
) -> dict[str, Any]:
    _shape(payload, _AUTH_FIELDS, {"ready", "next_action"})
    if not isinstance(payload["ready"], bool) or not isinstance(payload["next_action"], str):
        _invalid()
    if not payload["ready"]:
        reason = payload.get("reason_code")
        if not isinstance(reason, str) or _REASON.fullmatch(reason) is None:
            _invalid()
        return {"ready": False, "reason_code": reason, "next_action": payload["next_action"]}
    required = set("authorization_rail wallet_identity_id spending_grant_id asset_allowance_id required_amount_atomic observed_allowance_atomic".split())
    if not required <= payload.keys() or payload["authorization_rail"] != _RAIL:
        _invalid()
    try:
        for key in ("wallet_identity_id", "spending_grant_id", "asset_allowance_id"):
            _identifier(payload[key])
        returned_opc_installation_id = payload.get("opc_installation_id")
        if returned_opc_installation_id is not None:
            returned_opc_installation_id = _opc_installation_id(
                returned_opc_installation_id
            )
    except ValueError:
        _invalid()
    needed, observed = payload["required_amount_atomic"], payload["observed_allowance_atomic"]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (needed, observed)) or needed != expected_atomic or not needed <= observed <= _UINT256_MAX:
        _invalid()
    if returned_opc_installation_id != expected_opc_installation_id:
        _invalid()
    return dict(payload)

_ACTION_FIELDS = set("action_id user_id agent_id action_type amount_usdc target merchant_id authorization_id policy_decision_id payment_id order_id receipt_id tx_hash approval_id approval_state description state error metadata created_at updated_at event_log".split())

def _action(payload: dict[str, Any], context: PredictionFundingContext, state: str, action_id: str | None = None, policy_id: str | None = None) -> dict[str, Any]:
    required = set("action_id user_id agent_id action_type amount_usdc target merchant_id authorization_id state metadata".split())
    _shape(payload, _ACTION_FIELDS, required)
    try:
        returned_id = _identifier(payload["action_id"])
        matches = _amount(payload["amount_usdc"]) == Decimal(context.amount_usdc) and _address(payload["target"]) == context.destination
    except ValueError:
        _invalid()
    expected = {"user_id": context.user_id, "agent_id": context.agent_id, "action_type": "funding_transfer", "merchant_id": _MERCHANT, "authorization_id": context.spending_grant_id, "state": state, "metadata": context.provenance}
    if not matches or (action_id is not None and returned_id != action_id) or any(payload.get(key) != value for key, value in expected.items()) or (policy_id is not None and payload.get("policy_decision_id") != policy_id):
        _invalid()
    return {"action_id": returned_id, "state": state, "policy_decision_id": payload.get("policy_decision_id")}

_POLICY_FIELDS = set("policy_decision_id action_id approved decision reason_code reasons required_action user_id agent_id action_type amount_usdc authorization_id merchant_id target_address chain authorization_approved remaining_amount_usdc risk_level risk_score risk_action risk_assessment evaluated_at event_log metadata".split())
_RISK_ASSESSMENT_COMMON_FIELDS = set("provider provider_endpoint subject network asset decision mode enforced mapping_version hold_score deny_score".split())
_RISK_ASSESSMENT_RESULT_FIELDS = _RISK_ASSESSMENT_COMMON_FIELDS | set("coin score risk_level indicators risk_details hacking_event decision_reasons assessed_at expires_at cache_hit response_sha256".split())
_RISK_ASSESSMENT_UNAVAILABLE_FIELDS = _RISK_ASSESSMENT_COMMON_FIELDS | {"error_category"}
_POLICY_DECISIONS = {"approved", "blocked", "needs_confirmation"}

def _policy(
    payload: dict[str, Any], context: PredictionFundingContext, action_id: str,
    *, risk_level: str, risk_score: int, risk_action: str,
) -> dict[str, Any]:
    required = set("policy_decision_id action_id approved decision reason_code required_action user_id agent_id action_type amount_usdc authorization_id merchant_id target_address chain risk_level risk_score risk_action risk_assessment metadata".split())
    _shape(payload, _POLICY_FIELDS, required)
    try:
        policy_id = _identifier(payload["policy_decision_id"])
        matches = _amount(payload["amount_usdc"]) == Decimal(context.amount_usdc) and _address(payload["target_address"]) == context.destination
        required_action = payload["required_action"]
        if required_action is not None:
            required_action = _identifier(required_action)
    except ValueError:
        _invalid()
    reason = payload["reason_code"]
    decision = payload["decision"]
    expected = {"action_id": action_id, "user_id": context.user_id, "agent_id": context.agent_id, "action_type": "funding_transfer", "authorization_id": None, "merchant_id": _MERCHANT, "chain": _NETWORK, "metadata": context.provenance}
    returned_score = payload["risk_score"]
    risk_matches = (
        payload["risk_level"] == risk_level
        and payload["risk_action"] == risk_action
        and isinstance(returned_score, int) and not isinstance(returned_score, bool)
        and 0 <= returned_score <= 100 and returned_score == risk_score
    )
    if (
        not isinstance(payload["approved"], bool)
        or not isinstance(decision, str) or decision not in _POLICY_DECISIONS
        or payload["approved"] != (decision == "approved")
        or not isinstance(reason, str) or _REASON.fullmatch(reason) is None
        or not matches or not risk_matches
        or any(payload.get(key) != value for key, value in expected.items())
    ):
        _invalid()
    assessment = _risk_assessment(payload["risk_assessment"], context)
    return {"policy_decision_id": policy_id, "approved": payload["approved"], "decision": decision, "reason_code": reason, "required_action": required_action, "risk_level": risk_level, "risk_score": risk_score, "risk_action": risk_action, "risk_assessment": assessment}


def _risk_assessment(
    payload: Any,
    context: PredictionFundingContext,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _invalid()
    fields = set(payload)
    if (
        fields != _RISK_ASSESSMENT_RESULT_FIELDS
        and fields != _RISK_ASSESSMENT_UNAVAILABLE_FIELDS
    ):
        _invalid()
    try:
        subject = _address(payload["subject"])
    except ValueError:
        _invalid()
    mode = payload["mode"]
    hold_score = payload["hold_score"]
    deny_score = payload["deny_score"]
    if (
        payload["provider"] != _MISTTRACK_PROVIDER
        or payload["provider_endpoint"] != _MISTTRACK_ENDPOINT
        or payload["subject"] != subject
        or subject != context.destination
        or payload["network"] != _NETWORK
        or payload["asset"] != _MISTTRACK_ASSET
        or not isinstance(payload["decision"], str)
        or payload["decision"] not in _MISTTRACK_DECISIONS
        or not isinstance(mode, str)
        or mode not in _MISTTRACK_MODES
        or type(payload["enforced"]) is not bool
        or payload["enforced"] != (mode == "enforce")
        or payload["mapping_version"] != _MISTTRACK_MAPPING_VERSION
        or type(hold_score) is not int
        or type(deny_score) is not int
        or not 1 <= hold_score < deny_score <= 100
    ):
        _invalid()

    if fields == _RISK_ASSESSMENT_UNAVAILABLE_FIELDS:
        if (
            payload["decision"] != "unavailable"
            or not isinstance(payload["error_category"], str)
            or payload["error_category"] not in _MISTTRACK_ERROR_CATEGORIES
        ):
            _invalid()
        return dict(payload)

    score = payload["score"]
    if (
        payload["coin"] != _MISTTRACK_COIN
        or type(score) is not int
        or not 0 <= score <= 100
        or not isinstance(payload["risk_level"], str)
        or payload["risk_level"] not in _MISTTRACK_LEVELS
        or type(payload["cache_hit"]) is not bool
        or not isinstance(payload["response_sha256"], str)
        or _SHA256.fullmatch(payload["response_sha256"]) is None
    ):
        _invalid()
    indicators = _risk_string_list(payload["indicators"], allow_empty=True)
    reasons = _risk_string_list(payload["decision_reasons"], allow_empty=False)
    details = _risk_details(payload["risk_details"])
    hacking_event = payload["hacking_event"]
    if hacking_event is not None:
        hacking_event = _risk_text(hacking_event)
    assessed_at = _risk_timestamp(payload["assessed_at"])
    expires_at = _risk_timestamp(payload["expires_at"])
    if expires_at <= assessed_at:
        _invalid()
    return {
        **payload,
        "subject": subject,
        "indicators": indicators,
        "risk_details": details,
        "hacking_event": hacking_event,
        "decision_reasons": reasons,
    }


def _risk_string_list(value: Any, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _invalid()
    return [_risk_text(item) for item in value]


def _risk_details(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        _invalid()
    result: list[dict[str, str]] = []
    for detail in value:
        if not isinstance(detail, dict) or not detail:
            _invalid()
        normalized: dict[str, str] = {}
        for key, item in detail.items():
            if (
                not isinstance(key, str)
                or not key
                or key != re.sub(r"[\s-]+", "_", key.strip().lower())
                or "api_key" in key
                or "://" in key
            ):
                _invalid()
            normalized[key] = _risk_text(item)
        result.append(normalized)
    return result


def _risk_text(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip().lower()
        or "api_key" in value
        or "://" in value
    ):
        _invalid()
    return value


def _risk_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        _invalid()
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z"))
    except ValueError:
        _invalid()
    if parsed.tzinfo is not None or parsed.isoformat() + "Z" != value:
        _invalid()
    return parsed

_AUDIT_FIELDS = set("event_id event_type source_service action_id user_id agent_id policy_decision_id payment_id order_id receipt_id tx_hash payload created_at".split())

def _audit(payload: dict[str, Any], context: PredictionFundingContext, action_id: str, policy_id: str, expected_payload: dict[str, Any]) -> dict[str, Any]:
    required = set("event_id event_type source_service action_id user_id agent_id policy_decision_id payload".split())
    _shape(payload, _AUDIT_FIELDS, required)
    try:
        event_id = _identifier(payload["event_id"])
    except ValueError:
        _invalid()
    expected = {"event_type": "prediction_market_funding_policy_evaluated", "source_service": "clink_prediction_markets", "action_id": action_id, "user_id": context.user_id, "agent_id": context.agent_id, "policy_decision_id": policy_id, "payload": expected_payload}
    if any(payload.get(key) != value for key, value in expected.items()):
        _invalid()
    return {"event_id": event_id, "event_type": payload["event_type"], "source_service": payload["source_service"]}

_PREBROADCAST_RISK_FIELDS = {
    "risk_prebroadcast_state",
    "risk_prebroadcast_blocked",
    "risk_prebroadcast_blocked_at",
}
_RESERVATION_FIELDS = set("reservation_id purchase_id idempotency_key spending_authorization_id authorization_rail wallet_identity_id spending_grant_id asset_allowance_id product user_id agent_id action_id policy_decision_id merchant_id merchant_trust_tier quote_hash amount_usdc amount_atomic network asset token_address token_decimals token_symbol destination resource venue spender_address authorization_path budget_accounting_state usage_date state receipt_id tx_hash created_at updated_at payment_authorization_hash settlement_rail settlement_sender settlement_nonce settlement_transaction reconciliation_status next_action reconciliation_attempts reconciliation_started_at last_reconciliation_at last_reconciliation_error operator_reconciliation_attempts last_operator_reconciliation_at manual_review_reason manual_review_required_at failed_tx_hashes failed_merchant_tx_hashes failed_submission_evidence payment_proof_hash payment_payload proxy_challenge_hash proxy_nonce proxy_valid_after proxy_valid_before proxy_payment_prepared_at payer_funded_at reimbursement_tx_hash merchant_tx_hash receipt settled_at reconciled_after_authorization_revocation delivery_status output_hash finalized_at release_reason single_submission replacement_forbidden definitive_failure failure_reason failed_at nonce valid_after valid_before".split()) | _PREBROADCAST_RISK_FIELDS
_PRIVATE_RESERVATION_FIELDS = {"payment_authorization_hash", "settlement_transaction", "payment_payload", "payment_proof_hash", "proxy_challenge_hash"}
_RESERVATION_STATES = {"spending_reserved", "payment_submitted", "settled", "finalized", "released", "payer_funded", "proxy_payment_ready", "proxy_authorization_ready"}


def _failure_evidence(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    if (
        payload.get("product") != _PRODUCT
        or payload.get("single_submission") is not True
        or not isinstance(payload.get("replacement_forbidden"), bool)
    ):
        _invalid()
    present = "failed_submission_evidence" in payload
    evidence = payload.get("failed_submission_evidence", [])
    if not isinstance(evidence, list):
        _invalid()
    canonical_fields = (
        "tx_hash",
        "settlement_sender",
        "settlement_nonce",
        "settlement_transaction",
    )
    populated = tuple(payload.get(field) is not None for field in canonical_fields)
    if any(populated) and not all(populated):
        _invalid()
    canonical_complete = all(populated)
    canonical_tx_hash = canonical_relayer = None
    canonical_nonce = None
    if canonical_complete:
        try:
            canonical_tx_hash = _hash(payload["tx_hash"])
            canonical_relayer = _address(payload["settlement_sender"])
        except ValueError:
            _invalid()
        canonical_nonce = payload["settlement_nonce"]
        if (
            type(canonical_nonce) is not int
            or not 0 <= canonical_nonce < 2**64
            or not isinstance(payload["settlement_transaction"], dict)
        ):
            _invalid()
    state = payload.get("state")
    replacement_forbidden = payload["replacement_forbidden"]
    if state in {"payment_submitted", "settled", "finalized"}:
        if not canonical_complete or replacement_forbidden or evidence:
            _invalid()
    elif state in {"spending_reserved", "released"}:
        if canonical_complete:
            if not replacement_forbidden or len(evidence) != 1:
                _invalid()
        elif replacement_forbidden or evidence:
            _invalid()
    else:
        _invalid()
    if not evidence:
        return [] if present else None
    if (
        len(evidence) != 1
        or replacement_forbidden is not True
        or state not in {"spending_reserved", "released"}
        or payload.get("reconciliation_status") != "failed"
        or payload.get("next_action") != "release_reservation"
    ):
        _invalid()
    item = evidence[0]
    if not isinstance(item, dict) or set(item) != {
        "kind",
        "reason_code",
        "tx_hash",
        "relayer",
        "nonce",
        "recorded_at",
    }:
        _invalid()
    allowed_reasons = {
        "definite_rpc_rejection": {
            "insufficient_funds",
            "intrinsic_gas_too_low",
            "invalid_sender",
            "transaction_type_not_supported",
        },
        "failed_receipt": {"onchain_revert"},
    }
    kind = item.get("kind")
    reason = item.get("reason_code")
    timestamp = item.get("recorded_at")
    nonce = item.get("nonce")
    try:
        tx_hash = _hash(item.get("tx_hash"))
        relayer = _address(item.get("relayer"))
        if (
            kind not in allowed_reasons
            or reason not in allowed_reasons[kind]
            or type(nonce) is not int
            or not 0 <= nonce < 2**64
            or not isinstance(timestamp, str)
            or _RFC3339_UTC.fullmatch(timestamp) is None
        ):
            _invalid()
        parsed = datetime.fromisoformat(timestamp.removesuffix("Z"))
        if parsed.tzinfo is not None or parsed.isoformat() + "Z" != timestamp:
            _invalid()
        if (
            tx_hash != canonical_tx_hash
            or relayer != canonical_relayer
            or nonce != canonical_nonce
        ):
            _invalid()
    except (TypeError, ValueError):
        _invalid()
    return [
        {
            "kind": kind,
            "reason_code": reason,
            "tx_hash": tx_hash,
            "relayer": relayer,
            "nonce": nonce,
            "recorded_at": timestamp,
        }
    ]


def _prebroadcast_risk_state(payload: dict[str, Any]) -> None:
    present = _PREBROADCAST_RISK_FIELDS & payload.keys()
    native_submitted = (
        payload.get("state") == "payment_submitted"
        and payload.get("authorization_rail") == _RAIL
        and payload.get("settlement_rail") == "clink_allowance"
    )
    if not present:
        if native_submitted:
            _invalid()
        return
    if present != _PREBROADCAST_RISK_FIELDS:
        _invalid()
    risk_state = payload["risk_prebroadcast_state"]
    blocked = payload["risk_prebroadcast_blocked"]
    blocked_at = payload["risk_prebroadcast_blocked_at"]
    if (
        risk_state not in {"pending", "ready", "blocked"}
        or type(blocked) is not bool
        or payload.get("authorization_rail") != _RAIL
        or payload.get("settlement_rail") != "clink_allowance"
    ):
        _invalid()
    if risk_state == "pending":
        if (
            blocked
            or blocked_at is not None
            or payload.get("state") != "payment_submitted"
            or payload.get("reconciliation_status") != "pending"
            or payload.get("next_action") != "reconcile_payment"
            or payload.get("manual_review_reason") is not None
            or payload.get("manual_review_required_at") is not None
        ):
            _invalid()
        return
    if risk_state == "ready":
        if (
            blocked
            or blocked_at is not None
            or payload.get("reconciliation_status") == "manual_review_required"
            or payload.get("next_action") == "operator_reconcile"
            or payload.get("manual_review_reason") is not None
            or payload.get("manual_review_required_at") is not None
            or payload.get("state") == "payment_submitted"
            and (
                payload.get("reconciliation_status") != "pending"
                or payload.get("next_action") != "reconcile_payment"
            )
        ):
            _invalid()
        return
    reason = payload.get("manual_review_reason")
    try:
        blocked_time = _risk_timestamp(blocked_at)
        manual_review_time = _risk_timestamp(payload.get("manual_review_required_at"))
    except (TypeError, ValueError):
        _invalid()
    if (
        blocked is not True
        or payload.get("state") != "payment_submitted"
        or payload.get("reconciliation_status") != "manual_review_required"
        or payload.get("next_action") != "operator_reconcile"
        or not isinstance(reason, str)
        or not reason.strip()
        or blocked_time < manual_review_time
    ):
        _invalid()

def _reservation(payload: dict[str, Any], *, context: PredictionFundingContext | None = None, reservation_id: str | None = None) -> dict[str, Any]:
    _shape(payload, _RESERVATION_FIELDS, {"reservation_id", "state"})
    try:
        returned_id = _identifier(payload["reservation_id"])
    except ValueError:
        _invalid()
    if (reservation_id is not None and returned_id != reservation_id) or payload["state"] not in _RESERVATION_STATES:
        _invalid()
    if context is not None:
        expected = {"purchase_id": context.operation_id, "idempotency_key": context.idempotency_key, "authorization_rail": _RAIL, "wallet_identity_id": context.wallet_identity_id, "spending_grant_id": context.spending_grant_id, "asset_allowance_id": context.asset_allowance_id, "product": _PRODUCT, "user_id": context.user_id, "agent_id": context.agent_id, "merchant_trust_tier": _MERCHANT_TRUST, "quote_hash": context.quote_hash, "amount_atomic": context.amount_atomic, "network": _NETWORK, "destination": context.destination, "resource": context.resource, "venue": _VENUE}
        if any(payload.get(key) != value for key, value in expected.items()):
            _invalid()
        try:
            if _amount(payload.get("amount_usdc")) != Decimal(context.amount_usdc) or _address(payload.get("token_address")) != context.token_address:
                _invalid()
        except ValueError:
            _invalid()
    evidence = _failure_evidence(payload)
    _prebroadcast_risk_state(payload)
    result = {key: value for key, value in payload.items() if key not in _PRIVATE_RESERVATION_FIELDS}
    result["reservation_id"] = returned_id
    if evidence is not None:
        result["failed_submission_evidence"] = evidence
    for key in ("tx_hash", "output_hash", "reimbursement_tx_hash", "merchant_tx_hash"):
        if result.get(key) is not None:
            try:
                result[key] = _hash(result[key])
            except ValueError:
                _invalid()
    if result.get("settlement_sender") is not None:
        try:
            result["settlement_sender"] = _address(result["settlement_sender"])
        except ValueError:
            _invalid()
    if result.get("settlement_nonce") is not None and (
        type(result["settlement_nonce"]) is not int
        or not 0 <= result["settlement_nonce"] < 2**64
    ):
        _invalid()
    return result

def _payment_authorization(payload: dict[str, Any], reservation_id: str) -> dict[str, Any]:
    fields = set("kind operation_id reservation_id binding_id bridge_address source_token amount_atomic".split())
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("Core payment authorization is invalid")
    try:
        result = {"kind": "prediction_market_bridge_transfer", "operation_id": _identifier(payload["operation_id"]), "reservation_id": reservation_id, "binding_id": _identifier(payload["binding_id"]), "bridge_address": _address(payload["bridge_address"]), "source_token": _address(payload["source_token"]), "amount_atomic": _atomic(payload["amount_atomic"])}
    except ValueError:
        raise ValueError("Core payment authorization is invalid") from None
    if payload["kind"] != result["kind"] or payload["reservation_id"] != reservation_id:
        raise ValueError("Core payment authorization is invalid")
    return result
