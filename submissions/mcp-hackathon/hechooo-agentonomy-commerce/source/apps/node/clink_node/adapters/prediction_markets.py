from __future__ import annotations

from .ownership import object_id, require_owner

import json
import re
import threading
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

import httpx

from .http import DownstreamError, JsonHttpClient, ProxyResponse, proxy_http_request


PREDICTION_MARKET_CAPABILITIES = (
    "create_prediction_market_strategy",
    "create_agent_idea",
    "update_agent_idea",
    "create_core_account_setup_link",
    "resolve_polymarket_funding_target",
    "get_prediction_market_user_readiness",
    "check_polymarket_deposit_wallet_readiness",
    "prepare_polymarket_deposit_wallet",
    "fund_polymarket_from_spending_authorization",
    "create_polymarket_account_binding_link",
    "get_polymarket_account_binding_status",
    "revoke_polymarket_account_binding",
    "search_prediction_markets",
    "score_prediction_market_opportunities",
    "create_prediction_market_order_preview",
    "get_prediction_market_order_preview",
    "build_prediction_market_context",
    "check_prediction_market_execution_readiness",
    "execute_prediction_market_order_preview",
    "create_polymarket_order_signing_session",
    "complete_polymarket_order_signing_session",
    "get_prediction_market_execution",
    "get_prediction_market_portfolio_snapshot",
    "sync_prediction_market_portfolio",
    "create_polymarket_bridge_deposit_address",
    "create_polymarket_bridge_quote",
    "get_polymarket_bridge_status",
    "get_latest_polymarket_bridge_status",
    "prediction_markets_router_health",
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EVM_ADDRESS = re.compile(r"^0[xX]([0-9a-fA-F]{40})$")
_USDC = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{6}$")
_UINT256 = re.compile(r"^(?:0|[1-9][0-9]{0,77})$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NEXT_ACTION = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_CAPABILITY = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_MAX_OPERATION_RESPONSE_BYTES = 128 * 1024
_MAX_SIGNING_PROXY_BODY_BYTES = 64 * 1024
_MAX_SIGNING_PROXY_RESPONSE_BYTES = 256 * 1024
_DEFAULT_DEPOSIT_WALLET_URL = "http://127.0.0.1:8048"

_FUNDING_STATUSES = frozenset(
    {
        "created",
        "confirmed",
        "action_creating",
        "action_unknown",
        "action_created",
        "policy_evaluating",
        "policy_unknown",
        "policy_approved",
        "reservation_creating",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "settlement_unknown",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
        "venue_credited",
        "finalizing",
        "finalized",
        "failed",
        "released",
        "manual_review",
    }
)
_FUNDING_NEXT_ACTIONS = {
    "created": "confirm",
    "confirmed": "processing",
    "action_creating": "manual_reconcile_inflight",
    "action_unknown": "manual_review",
    "action_created": "processing",
    "policy_evaluating": "manual_reconcile_inflight",
    "policy_unknown": "manual_review",
    "policy_approved": "processing",
    "reservation_creating": "manual_reconcile_inflight",
    "reserved": "processing",
    "transaction_prepared": "processing",
    "settlement_submitting": "check_core_status",
    "settlement_unknown": "check_core_status",
    "submitted": "check_core_status",
    "chain_confirmed": "check_bridge_status",
    "bridge_pending": "check_bridge_status",
    "venue_credited": "finalize",
    "finalizing": "manual_reconcile_inflight",
    "finalized": "complete",
    "failed": "terminal",
    "released": "terminal",
    "manual_review": "manual_review",
}
_FUNDING_ADVANCEABLE_STATUSES = frozenset(
    {
        "confirmed",
        "action_created",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "settlement_unknown",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
        "venue_credited",
    }
)
_SIGNING_STATUSES = frozenset(
    {
        "pending_browser_signature",
        "submitting",
        "unknown",
        "submitted",
        "rejected",
        "blocked",
        "expired",
        "failed",
    }
)
_ORDER_SIGNING_ROUTES = {
    ("GET", "/execution/polymarket/order-signing-console/"),
    (
        "GET",
        "/execution/polymarket/order-signing-assets/"
        "polymarket_order_signing.css",
    ),
    (
        "GET",
        "/execution/polymarket/order-signing-assets/"
        "polymarket_order_signing.bundle.js",
    ),
    ("GET", "/execution/polymarket/browser-order-signing-session"),
    (
        "GET",
        "/execution/polymarket/browser-order-signing-session/status",
    ),
    (
        "POST",
        "/execution/polymarket/browser-order-signing-session/complete",
    ),
}
_BROWSER_SIGNING_ROUTES = frozenset(
    {
        "/execution/polymarket/browser-order-signing-session",
        "/execution/polymarket/browser-order-signing-session/status",
        "/execution/polymarket/browser-order-signing-session/complete",
    }
)


class FundingMutationAmbiguousError(DownstreamError):
    def __init__(self) -> None:
        super().__init__(
            "prediction-markets",
            None,
            "funding mutation outcome requires status reconciliation",
        )


class OrderSigningCreationAmbiguousError(DownstreamError):
    def __init__(self) -> None:
        super().__init__(
            "prediction-markets",
            None,
            "order signing creation outcome requires reconciliation",
        )


class _BoundedInternalJsonClient:
    def __init__(
        self,
        *,
        service: str,
        token: str,
        transport: httpx.BaseTransport | None,
    ) -> None:
        if (
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or len(token) > 4_096
        ):
            raise ValueError("prediction internal token is invalid")
        self.service = service
        self.client = httpx.Client(
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            with self.client.stream(
                method,
                url,
                json=payload,
                params=params,
            ) as response:
                if response.is_redirect or response.is_error:
                    raise DownstreamError(
                        self.service,
                        response.status_code,
                        "prediction operation request failed",
                    )
                content = _bounded_response_content(
                    response,
                    maximum=_MAX_OPERATION_RESPONSE_BYTES,
                    service=self.service,
                )
        except DownstreamError:
            raise
        except httpx.HTTPError:
            raise DownstreamError(
                self.service,
                None,
                "prediction operation outcome is unavailable",
            ) from None
        payload_value = _strict_json_object(content)
        if payload_value is None:
            raise DownstreamError(
                self.service,
                200,
                "prediction operation response was invalid",
            )
        return payload_value


class PredictionMarketsHttpAdapter:
    name = "prediction-markets"

    _MINIAPP_AGENT_ID = "hermes"
    _MINIAPP_BINDING_TTL_MINUTES = 10

    def __init__(
        self,
        *,
        base_url: str,
        account_binding_url: str | None = None,
        preview_url: str | None = None,
        execution_url: str | None = None,
        funding_url: str | None = None,
        deposit_wallet_url: str | None = None,
        internal_token: str,
        account_binding_internal_token: str | None = None,
        public_base_url: str | None = None,
        live_operations_enabled: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(live_operations_enabled, bool):
            raise ValueError("prediction live mode is invalid")
        self.base_url = _prediction_service_base_url(base_url)
        self.account_binding_url = _prediction_service_base_url(
            account_binding_url or base_url
        )
        self.preview_url = _prediction_service_base_url(
            preview_url or base_url
        )
        self.execution_url = _prediction_service_base_url(
            execution_url or base_url
        )
        self.funding_url = _prediction_service_base_url(
            funding_url or base_url
        )
        self.deposit_wallet_url = _prediction_service_base_url(
            deposit_wallet_url or _DEFAULT_DEPOSIT_WALLET_URL
        )
        self.public_base_url = (
            public_base_url.rstrip("/") if public_base_url else None
        )
        self.live_operations_enabled = live_operations_enabled
        self.transport = transport
        self.http = JsonHttpClient(
            self.name,
            internal_token=(
                account_binding_internal_token
                if account_binding_internal_token is not None
                else internal_token
            ),
            transport=transport,
        )
        self.operations_http = _BoundedInternalJsonClient(
            service=self.name,
            token=internal_token,
            transport=transport,
        )
        self.deposit_http = JsonHttpClient(
            self.name,
            internal_token=internal_token,
            transport=transport,
        )
        self._funding_ambiguity_lock = threading.Lock()
        self._funding_ambiguities: dict[tuple[str, str], str] = {}
        self._signing_tombstone_lock = threading.Lock()
        self._signing_tombstones: set[tuple[str, str]] = set()

    def health(self) -> dict[str, Any]:
        return self.http.get(f"{self.base_url}/healthz")

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "module": self.name}
            for name in PREDICTION_MARKET_CAPABILITIES
        ]

    def get_order_preview(self, *, user_id: str, preview_id: str) -> dict[str, Any]:
        preview_id = object_id(preview_id)
        payload = self.operations_http.request(
            "GET", f"{self.preview_url}/order-previews/{preview_id}"
        )
        return require_owner(payload, user_id=user_id, id_field="preview_id",
                             expected_id=preview_id, service=self.name, agent_id="hermes")

    def get_execution(self, *, user_id: str, execution_id: str) -> dict[str, Any]:
        execution_id = object_id(execution_id)
        payload = self.operations_http.request(
            "GET", f"{self.execution_url}/execution/{execution_id}"
        )
        return require_owner(payload, user_id=user_id, id_field="execution_id",
                             expected_id=execution_id, service=self.name, agent_id="hermes")

    def get_funding_payment(self, *, user_id: str, operation_id: str) -> dict[str, Any]:
        operation_id = object_id(operation_id)
        payload = self.operations_http.request(
            "GET", f"{self.funding_url}/polymarket/funding-history/{operation_id}",
            params={"user_id": user_id},
        )
        _funding_projection(payload, expected_user=user_id, expected_operation=operation_id)
        return {name: payload.get(name) for name in (
            "operation_id", "status", "reservation_id", "failure_reason_code", "next_action",
        )}

    def create_agent_binding_session(self, *, user_id: str, wallet_address: str) -> dict[str, Any]:
        """Create a user-facing signing link; never sign or confirm for the Agent."""
        user_id = _canonical_id(user_id, field="user_id")
        wallet_address = _canonical_evm_address(wallet_address, field="wallet_address")
        readiness = self.deposit_http.get(
            self.deposit_wallet_url + "/polymarket/deposit-wallet/readiness",
            params={"user_id": user_id, "owner_wallet": wallet_address},
        )
        deposit = _trusted_deposit_wallet(readiness, expected_user=user_id, expected_owner=wallet_address)
        response = self.http.post(self.account_binding_url + "/internal/polymarket/binding-sessions", {
            "user_id": user_id, "agent_id": "hermes", "wallet_address": wallet_address,
            "polymarket_deposit_wallet": deposit, "expires_in_minutes": 15,
            "metadata": {"source": "agentonomy_wallet_app"},
        })
        try:
            session_id = _canonical_session_id(response.get("session_id"))
            expires_at = datetime.fromisoformat(response["expires_at"].replace("Z", "+00:00"))
            valid = (
                response.get("user_id") == user_id
                and response.get("agent_id") == "hermes"
                and _canonical_evm_address(response.get("wallet_address"), field="wallet_address") == wallet_address
                and _canonical_evm_address(response.get("polymarket_deposit_wallet"), field="deposit_wallet") == deposit
                and response.get("status") == "pending"
                and expires_at.tzinfo is not None
                and expires_at > datetime.now(UTC)
            )
        except (KeyError, ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise DownstreamError(self.name, 503, "binding session response was invalid")
        url = _public_binding_url(response.get("signing_url"), account_binding_url=self.account_binding_url,
                                  public_base_url=self.public_base_url)
        if url is None or urlsplit(url).path != f"/polymarket/binding-console/{session_id}":
            raise DownstreamError(self.name, 503, "binding signing URL was invalid")
        return {"url": url, "expires_at": response.get("expires_at"), "kind": "polymarket"}

    def account_status(self, user_id: str) -> dict[str, Any]:
        return self.http.get(
            self.account_binding_url
            + f"/internal/polymarket/bindings/latest/{user_id}"
        )

    def account_balance(self, user_id: str) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        response = self.operations_http.request(
            "GET",
            self.funding_url + "/polymarket/account-balance",
            params={"user_id": normalized_user},
        )
        return _account_balance_projection(
            response,
            expected_user=normalized_user,
        )

    def create_binding_session(
        self,
        user_id: str,
        *,
        wallet_address: str,
    ) -> str:
        if self.public_base_url is None:
            raise DownstreamError(
                self.name,
                None,
                "binding signing URL was invalid",
            )
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_wallet = _canonical_evm_address(
            wallet_address,
            field="wallet_address",
        )
        deposit_readiness = self.deposit_http.get(
            self.deposit_wallet_url
            + "/polymarket/deposit-wallet/readiness",
            params={
                "user_id": normalized_user,
                "owner_wallet": normalized_wallet,
            },
        )
        deposit_wallet = _trusted_deposit_wallet(
            deposit_readiness,
            expected_user=normalized_user,
            expected_owner=normalized_wallet,
        )
        result = self.http.post(
            self.account_binding_url
            + "/internal/polymarket/binding-sessions",
            {
                "user_id": normalized_user,
                "agent_id": self._MINIAPP_AGENT_ID,
                "wallet_address": normalized_wallet,
                "polymarket_deposit_wallet": deposit_wallet,
                "expires_in_minutes": self._MINIAPP_BINDING_TTL_MINUTES,
                "return_url": f"{self.public_base_url}/miniapp/",
                "metadata": {"source": "agentonomy_miniapp"},
            },
        )
        signing_url = _public_binding_url(
            result.get("signing_url"),
            account_binding_url=self.account_binding_url,
            public_base_url=self.public_base_url,
        )
        if signing_url is None:
            raise DownstreamError(
                self.name,
                200,
                "binding signing URL was invalid",
            )
        return signing_url

    def create_funding_operation(
        self,
        *,
        user_id: str,
        amount_usdc: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_amount = _canonical_usdc(amount_usdc)
        normalized_key = _canonical_id(
            idempotency_key,
            field="idempotency_key",
        )
        result = self.operations_http.request(
            "POST",
            self.funding_url + "/polymarket/funding-operations",
            payload={
                "user_id": normalized_user,
                "amount_usdc": normalized_amount,
                "idempotency_key": normalized_key,
                "resource": "clink://polymarket/funding",
            },
        )
        return _funding_projection(
            result,
            expected_user=normalized_user,
            expected_amount=normalized_amount,
        )

    def get_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_operation = _canonical_id(
            operation_id,
            field="operation_id",
        )
        result = self.operations_http.request(
            "GET",
            self.funding_url
            + f"/polymarket/funding-operations/{normalized_operation}",
            params={"user_id": normalized_user},
        )
        projection = _funding_projection(
            result,
            expected_user=normalized_user,
            expected_operation=normalized_operation,
        )
        self._observe_funding_status(
            user_id=normalized_user,
            operation_id=normalized_operation,
            status=result["status"],
        )
        return projection

    def continue_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_operation = _canonical_id(
            operation_id,
            field="operation_id",
        )
        current = self.operations_http.request(
            "GET",
            self.funding_url
            + f"/polymarket/funding-operations/{normalized_operation}",
            params={"user_id": normalized_user},
        )
        projection = _funding_projection(
            current,
            expected_user=normalized_user,
            expected_operation=normalized_operation,
        )
        status = current["status"]
        if self._funding_ambiguity_requires_status_only(
            user_id=normalized_user,
            operation_id=normalized_operation,
            status=status,
        ):
            return projection
        if status == "created":
            suffix = "confirm"
            payload: dict[str, Any] = {
                "user_id": normalized_user,
                "confirmed": True,
            }
        elif status in _FUNDING_ADVANCEABLE_STATUSES:
            suffix = "advance"
            payload = {"user_id": normalized_user}
        else:
            return projection
        try:
            result = self.operations_http.request(
                "POST",
                self.funding_url
                + f"/polymarket/funding-operations/{normalized_operation}/{suffix}",
                payload=payload,
            )
            projected_result = _funding_projection(
                result,
                expected_user=normalized_user,
                expected_operation=normalized_operation,
            )
        except DownstreamError:
            with self._funding_ambiguity_lock:
                self._funding_ambiguities[
                    (normalized_user, normalized_operation)
                ] = status
            raise FundingMutationAmbiguousError() from None
        return projected_result

    def _observe_funding_status(
        self,
        *,
        user_id: str,
        operation_id: str,
        status: str,
    ) -> None:
        key = (user_id, operation_id)
        with self._funding_ambiguity_lock:
            previous = self._funding_ambiguities.get(key)
            if previous is not None and previous != status:
                self._funding_ambiguities.pop(key, None)

    def _funding_ambiguity_requires_status_only(
        self,
        *,
        user_id: str,
        operation_id: str,
        status: str,
    ) -> bool:
        key = (user_id, operation_id)
        with self._funding_ambiguity_lock:
            previous = self._funding_ambiguities.get(key)
            if previous is None:
                return False
            if previous != status:
                self._funding_ambiguities.pop(key, None)
            return True

    def create_order_signing_session(
        self,
        *,
        user_id: str,
        preview_id: str,
    ) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_preview = _canonical_id(preview_id, field="preview_id")
        signing_key = (normalized_user, normalized_preview)
        with self._signing_tombstone_lock:
            if signing_key in self._signing_tombstones:
                raise OrderSigningCreationAmbiguousError()
        preview = self.operations_http.request(
            "GET",
            self.preview_url + f"/order-previews/{normalized_preview}",
        )
        if (
            preview.get("preview_id") != normalized_preview
            or preview.get("user_id") != normalized_user
        ):
            raise DownstreamError(
                self.name,
                404,
                "order preview is unavailable",
            )
        with self._signing_tombstone_lock:
            if signing_key in self._signing_tombstones:
                raise OrderSigningCreationAmbiguousError()
            self._signing_tombstones.add(signing_key)
        try:
            result = self.operations_http.request(
                "POST",
                self.execution_url
                + "/execution/polymarket/order-signing-sessions",
                payload={
                    "preview_id": normalized_preview,
                    "user_confirmed": True,
                    "live_submission_confirmed": True,
                    "confirmation_message": (
                        "confirmed in authenticated Agentonomy Mini App"
                    ),
                    "expires_in_minutes": 10,
                    "metadata": {"source": "agentonomy_miniapp"},
                },
            )
            projection = _signing_projection(
                result,
                expected_user=normalized_user,
                expected_preview=normalized_preview,
                public_base_url=self.public_base_url,
                include_signing_url=True,
            )
        except DownstreamError:
            raise OrderSigningCreationAmbiguousError() from None
        with self._signing_tombstone_lock:
            self._signing_tombstones.discard(signing_key)
        return projection

    def get_order_signing_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        normalized_user = _canonical_id(user_id, field="user_id")
        normalized_session = _canonical_session_id(session_id)
        result = self.operations_http.request(
            "GET",
            self.execution_url
            + "/execution/polymarket/order-signing-sessions/"
            + normalized_session,
        )
        return _signing_projection(
            result,
            expected_user=normalized_user,
            expected_session=normalized_session,
            public_base_url=self.public_base_url,
            include_signing_url=False,
        )

    def proxy_public_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> ProxyResponse:
        binding_route = (
            path.startswith("/polymarket/binding-console/")
            or path.startswith("/polymarket/binding-sessions/")
            or path == "/polymarket/clob-server-time"
        )
        order_route = (method, path) in _ORDER_SIGNING_ROUTES
        if order_route and not self.live_operations_enabled:
            raise ValueError("public order signing routes are disabled")
        if not binding_route and not order_route:
            raise ValueError(
                "only public prediction-market signing routes may be proxied"
            )
        if order_route:
            return self._proxy_order_signing_request(
                method=method,
                path=path,
                query=query,
                headers=headers,
                body=body,
            )
        return proxy_http_request(
            service="prediction-markets-console",
            base_url=self.account_binding_url,
            method=method,
            path=path,
            query=query,
            headers=headers,
            body=body,
            transport=self.transport,
        )

    def _proxy_order_signing_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> ProxyResponse:
        if query or (method, path) not in _ORDER_SIGNING_ROUTES:
            raise ValueError("order signing proxy route is invalid")
        is_browser_route = path in _BROWSER_SIGNING_ROUTES
        if method == "GET":
            if body:
                raise ValueError("order signing GET body is invalid")
        elif path.endswith("/complete"):
            _validate_complete_body(headers, body)
        else:
            raise ValueError("order signing proxy method is invalid")

        forwarded: list[tuple[str, str]] = []
        if is_browser_route:
            authorization = _single_header(headers, "authorization")
            origin = _single_header(headers, "x-clink-origin")
            if (
                authorization is None
                or not authorization.startswith("Bearer ")
                or _CAPABILITY.fullmatch(authorization[7:]) is None
                or self.public_base_url is None
                or _base_origin(origin or "")
                != _base_origin(self.public_base_url)
            ):
                raise ValueError("order signing capability headers are invalid")
            forwarded.extend(
                [
                    ("Authorization", authorization),
                    ("X-Clink-Origin", origin or ""),
                ]
            )
            if method == "POST":
                forwarded.append(("Content-Type", "application/json"))

        try:
            with httpx.Client(
                timeout=15,
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    method,
                    self.execution_url + path,
                    headers=forwarded,
                    content=body,
                ) as response:
                    content = _bounded_response_content(
                        response,
                        maximum=_MAX_SIGNING_PROXY_RESPONSE_BYTES,
                        service="prediction-markets-console",
                    )
                    response_headers = tuple(
                        (name, value)
                        for name, value in response.headers.multi_items()
                        if name.lower()
                        in {
                            "cache-control",
                            "content-security-policy",
                            "content-type",
                            "pragma",
                            "referrer-policy",
                            "x-content-type-options",
                            "x-frame-options",
                        }
                    )
                    return ProxyResponse(
                        status_code=response.status_code,
                        content=content,
                        headers=response_headers,
                    )
        except DownstreamError:
            raise
        except httpx.HTTPError:
            raise DownstreamError(
                "prediction-markets-console",
                None,
                "order signing console is unavailable",
            ) from None


_BINDING_PATH = re.compile(
    r"^/polymarket/binding-console/pm_bind_sess_[0-9a-f]{12}$"
)
_CONSOLE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


def _canonical_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _canonical_session_id(value: object) -> str:
    if not isinstance(value, str) or _SESSION_ID.fullmatch(value) is None:
        raise ValueError("session_id is invalid")
    return value


def _canonical_evm_address(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    match = _EVM_ADDRESS.fullmatch(value)
    if match is None:
        raise ValueError(f"{field} is invalid")
    normalized = "0x" + match.group(1).lower()
    if normalized == "0x" + "0" * 40:
        raise ValueError(f"{field} is invalid")
    return normalized


def _trusted_deposit_wallet(
    readiness: dict[str, Any],
    *,
    expected_user: str,
    expected_owner: str,
) -> str:
    try:
        readiness_user = _canonical_id(
            readiness.get("user_id"),
            field="user_id",
        )
        readiness_owner = _canonical_evm_address(
            readiness.get("owner_wallet"),
            field="owner_wallet",
        )
        deposit_wallet = _canonical_evm_address(
            readiness.get("deposit_wallet"),
            field="polymarket_deposit_wallet",
        )
    except ValueError:
        raise DownstreamError(
            "prediction-markets",
            404,
            "deposit wallet readiness is unavailable",
        ) from None
    if (
        readiness_user != expected_user
        or readiness_owner != expected_owner
        or readiness.get("ready") is not True
        or readiness.get("can_use_x402") is not True
    ):
        raise DownstreamError(
            "prediction-markets",
            404,
            "deposit wallet readiness is unavailable",
        )
    return deposit_wallet


def _canonical_usdc(value: object) -> str:
    if (
        not isinstance(value, str)
        or _USDC.fullmatch(value) is None
        or value == "0.000000"
        or len(value.split(".", 1)[0]) + 6 > 78
    ):
        raise ValueError("amount_usdc is invalid")
    return value


def _account_balance_projection(
    value: dict[str, Any], *, expected_user: str
) -> dict[str, Any]:
    try:
        user_id = _canonical_id(value.get("user_id"), field="user_id")
        venue_wallet = _canonical_evm_address(
            value.get("venue_wallet_address"),
            field="venue_wallet_address",
        )
    except ValueError:
        raise DownstreamError(
            "prediction-markets",
            200,
            "Polymarket balance response was invalid",
        ) from None
    atomic = value.get("available_amount_atomic")
    amount_usdc = value.get("available_amount_usdc")
    if (
        user_id != expected_user
        or value.get("status") != "ready"
        or value.get("venue") != "polymarket"
        or value.get("asset") != "USDC"
        or not isinstance(atomic, str)
        or _UINT256.fullmatch(atomic) is None
        or int(atomic) >= 2**256
        or not isinstance(amount_usdc, str)
        or _USDC.fullmatch(amount_usdc) is None
        or amount_usdc != format(Decimal(int(atomic)).scaleb(-6), ".6f")
    ):
        raise DownstreamError(
            "prediction-markets",
            200,
            "Polymarket balance response was invalid",
        )
    return {
        "status": "ready",
        "user_id": user_id,
        "venue": "polymarket",
        "venue_wallet_address": venue_wallet,
        "asset": "USDC",
        "available_amount_atomic": atomic,
        "available_amount_usdc": amount_usdc,
    }


def _prediction_service_base_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("prediction service URL is invalid")
    try:
        parsed = urlsplit(value)
        parsed.port
    except (UnicodeError, ValueError):
        raise ValueError("prediction service URL is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("prediction service URL is invalid")
    return value.rstrip("/")


def _funding_projection(
    value: dict[str, Any],
    *,
    expected_user: str,
    expected_operation: str | None = None,
    expected_amount: str | None = None,
) -> dict[str, Any]:
    try:
        operation_id = _canonical_id(
            value.get("operation_id"),
            field="operation_id",
        )
        user_id = _canonical_id(value.get("user_id"), field="user_id")
        amount = _canonical_usdc(value.get("amount_usdc"))
        status = value.get("status")
        next_action = value.get("next_action")
    except ValueError:
        raise DownstreamError(
            "prediction-markets",
            200,
            "funding operation response was invalid",
        ) from None
    if (
        status not in _FUNDING_STATUSES
        or not isinstance(next_action, str)
        or _NEXT_ACTION.fullmatch(next_action) is None
        or _FUNDING_NEXT_ACTIONS.get(status) != next_action
    ):
        raise DownstreamError(
            "prediction-markets",
            200,
            "funding operation response was invalid",
        )
    if (
        user_id != expected_user
        or expected_operation is not None
        and operation_id != expected_operation
        or expected_amount is not None
        and amount != expected_amount
    ):
        raise DownstreamError(
            "prediction-markets",
            404,
            "funding operation is unavailable",
        )
    failure = value.get("failure_reason_code")
    if failure is not None and (
        not isinstance(failure, str) or _REASON.fullmatch(failure) is None
    ):
        raise DownstreamError(
            "prediction-markets",
            200,
            "funding operation response was invalid",
        )
    return {
        "operation_id": operation_id,
        "status": status,
        "amount_usdc": amount,
        "chain_status": _chain_status(status),
        "bridge_status": _bridge_status(status, value.get("bridge_status")),
        "buying_power_status": _buying_power_status(status),
        "reason": failure,
        "next_action": next_action,
    }


def _chain_status(status: str) -> str:
    if status in {
        "chain_confirmed",
        "bridge_pending",
        "venue_credited",
        "finalizing",
        "finalized",
    }:
        return "confirmed"
    if status in {
        "settlement_submitting",
        "settlement_unknown",
        "submitted",
    }:
        return "pending"
    if status in {"failed", "released"}:
        return "failed"
    if status in {"action_unknown", "policy_unknown", "manual_review"}:
        return "unknown"
    return "not_started"


def _bridge_status(status: str, value: object) -> str:
    if value is None:
        if status in {"failed", "released"}:
            return "failed"
        return "not_started"
    if value == "COMPLETED":
        return "completed"
    if value == "FAILED":
        return "failed"
    if value in {
        "DEPOSIT_DETECTED",
        "PROCESSING",
        "ORIGIN_TX_CONFIRMED",
        "SUBMITTED",
    }:
        return "pending"
    raise DownstreamError(
        "prediction-markets",
        200,
        "funding operation response was invalid",
    )


def _buying_power_status(status: str) -> str:
    if status in {"venue_credited", "finalizing", "finalized"}:
        return "credited"
    if status in {"chain_confirmed", "bridge_pending"}:
        return "pending"
    if status in {"failed", "released"}:
        return "failed"
    if status in {"action_unknown", "policy_unknown", "manual_review"}:
        return "unknown"
    return "not_started"


def _signing_projection(
    value: dict[str, Any],
    *,
    expected_user: str,
    public_base_url: str | None,
    include_signing_url: bool,
    expected_preview: str | None = None,
    expected_session: str | None = None,
) -> dict[str, Any]:
    try:
        session_id = _canonical_session_id(value.get("session_id"))
        user_id = _canonical_id(value.get("user_id"), field="user_id")
        status = value.get("status")
        next_action = value.get("next_action")
        preview_id = _canonical_id(
            value.get("preview_id"),
            field="preview_id",
        )
    except ValueError:
        raise DownstreamError(
            "prediction-markets",
            200,
            "order signing response was invalid",
        ) from None
    if (
        user_id != expected_user
        or expected_session is not None
        and session_id != expected_session
        or expected_preview is not None
        and preview_id != expected_preview
        or status not in _SIGNING_STATUSES
        or next_action is not None
        and (
            not isinstance(next_action, str)
            or _NEXT_ACTION.fullmatch(next_action) is None
        )
    ):
        raise DownstreamError(
            "prediction-markets",
            404,
            "order signing session is unavailable",
        )
    execution_id = value.get("execution_id")
    if execution_id is not None:
        try:
            execution_id = _canonical_id(execution_id, field="execution_id")
        except ValueError:
            raise DownstreamError(
                "prediction-markets",
                200,
                "order signing response was invalid",
            ) from None
    result = {
        "session_id": session_id,
        "status": status,
        "reason": _safe_signing_reason(status),
        "next_action": next_action,
        "execution_id": execution_id,
    }
    if include_signing_url:
        signing_url = _public_order_signing_url(
            value.get("signing_url"),
            public_base_url=public_base_url,
        )
        if status == "pending_browser_signature" and signing_url is None:
            raise DownstreamError(
                "prediction-markets",
                200,
                "order signing URL was invalid",
            )
        result["signing_url"] = signing_url
    return result


def _safe_signing_reason(status: str) -> str | None:
    return {
        "unknown": "order_submission_unknown",
        "rejected": "order_rejected",
        "blocked": "order_signing_blocked",
        "expired": "order_signing_expired",
        "failed": "order_signing_failed",
    }.get(status)


def _public_order_signing_url(
    value: object,
    *,
    public_base_url: str | None,
) -> str | None:
    if (
        public_base_url is None
        or not isinstance(value, str)
        or not value
        or value != value.strip()
        or not _has_valid_percent_escapes(value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        fragment = parse_qsl(
            parsed.fragment,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (UnicodeError, ValueError):
        return None
    if (
        _parsed_origin(parsed) != _base_origin(public_base_url)
        or parsed.path
        != "/execution/polymarket/order-signing-console/"
        or parsed.query
        or "?" in value.partition("#")[0]
        or len(fragment) != 1
        or fragment[0][0] != "access_token"
        or _CAPABILITY.fullmatch(fragment[0][1]) is None
    ):
        return None
    return (
        public_base_url.rstrip("/")
        + parsed.path
        + "#"
        + urlencode(fragment)
    )


def _has_valid_percent_escapes(value: str) -> bool:
    hexadecimal = frozenset("0123456789abcdefABCDEF")
    for index, character in enumerate(value):
        if character == "%" and (
            index + 2 >= len(value)
            or value[index + 1] not in hexadecimal
            or value[index + 2] not in hexadecimal
        ):
            return False
    return True


def _single_header(
    headers: list[tuple[str, str]],
    expected: str,
) -> str | None:
    values = [
        value
        for name, value in headers
        if name.lower() == expected
    ]
    if len(values) != 1:
        return None
    return values[0]


def _validate_complete_body(
    headers: list[tuple[str, str]],
    body: bytes,
) -> None:
    if (
        not body
        or len(body) > _MAX_SIGNING_PROXY_BODY_BYTES
        or _single_header(headers, "content-type") != "application/json"
    ):
        raise ValueError("order signing completion body is invalid")
    payload = _strict_json_object(body)
    if (
        payload is None
        or not {"signed_order", "wallet_address", "order_type"}.issubset(
            payload
        )
        or not set(payload).issubset(
            {"signed_order", "wallet_address", "order_type", "metadata"}
        )
        or not isinstance(payload.get("signed_order"), dict)
        or not isinstance(payload.get("wallet_address"), str)
        or not isinstance(payload.get("order_type"), str)
        or "metadata" in payload
        and payload.get("metadata") != {}
    ):
        raise ValueError("order signing completion body is invalid")


def _strict_json_object(content: bytes) -> dict[str, Any] | None:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _bounded_response_content(
    response: httpx.Response,
    *,
    maximum: int,
    service: str,
) -> bytes:
    content = bytearray()
    for chunk in response.iter_bytes():
        if len(chunk) > maximum - len(content):
            raise DownstreamError(
                service,
                response.status_code,
                "downstream response was too large",
            )
        content.extend(chunk)
    return bytes(content)


def _public_binding_url(
    value: object,
    *,
    account_binding_url: str,
    public_base_url: str,
) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (UnicodeError, ValueError):
        return None
    accepted_origins = {
        _base_origin(account_binding_url),
        _base_origin(public_base_url),
    }
    if None in accepted_origins or _parsed_origin(parsed) not in accepted_origins:
        return None
    if parsed.fragment or _BINDING_PATH.fullmatch(parsed.path) is None:
        return None
    if (
        len(query) != 1
        or query[0][0] != "access_token"
        or _CONSOLE_TOKEN.fullmatch(query[0][1]) is None
    ):
        return None
    return f"{public_base_url}{parsed.path}?{parsed.query}"


def _base_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
    except (UnicodeError, ValueError):
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    return _parsed_origin(parsed)


def _parsed_origin(parsed: SplitResult) -> tuple[str, str, int] | None:
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, port
