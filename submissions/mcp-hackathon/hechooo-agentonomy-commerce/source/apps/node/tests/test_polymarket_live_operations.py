from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.node.clink_node.adapters.core import AccountProxyResponse
from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.adapters.prediction_markets import (
    PredictionMarketsHttpAdapter,
)
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.interactions import InteractionService
from apps.node.clink_node.miniapp.service import MiniAppChatService
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.runtime import ManagedEnvironmentBuilder
from apps.node.clink_node.secrets import MemorySecretStore
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


NOW = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
ORIGIN = "https://www.agentonomy.xyz"
BOT_TOKEN = b"123456:test-only-telegram-token"
COOKIE_SECRET = b"c" * 32
HERMES_SECRET = b"h" * 32
CLIENT_NONCE = base64.urlsafe_b64encode(b"n" * 16).decode().rstrip("=")
PREDICTION_TOKEN = "prediction-internal-token"
CORE_TOKEN = "core-internal-token"

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


def _signed_init_data(*, user_id: int, username: str) -> str:
    fields = {
        "auth_date": str(int(NOW.timestamp())),
        "query_id": f"query-{user_id}",
        "user": json.dumps(
            {"id": user_id, "username": username},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN, hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        check.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


def _funding_view(
    *,
    user_id: str = "telegram:101",
    operation_id: str = "pm_funding_1",
    status: str = "created",
    next_action: str | None = None,
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "user_id": user_id,
        "binding_id": "pm_binding_1",
        "venue_wallet_address": "0x" + "1" * 40,
        "bridge_address": "0x" + "2" * 40,
        "status": status,
        "amount_usdc": "1.250000",
        "resource": "clink://polymarket/funding",
        "action_id": None,
        "policy_decision_id": None,
        "audit_event_id": None,
        "reservation_id": None,
        "core_tx_hash": None,
        "core_state": None,
        "bridge_status": None,
        "venue_buying_power_before_atomic": "0",
        "venue_buying_power_after_atomic": None,
        "failure_reason_code": None,
        "confirmed_at": None,
        "finalized_at": None,
        "created_at": "2026-08-20T04:00:00Z",
        "updated_at": "2026-08-20T04:00:00Z",
        "revision": 0,
        "next_action": next_action or _FUNDING_NEXT_ACTIONS[status],
    }


def _preview(*, user_id: str = "telegram:101") -> dict[str, Any]:
    market = {
        "platform": "polymarket",
        "market_id": "market-1",
        "event_id": "event-1",
        "title": "Will the test pass?",
        "subtitle": None,
        "category": "tests",
        "url": None,
        "status": "active",
        "yes_price": 0.5,
        "no_price": 0.5,
        "bid_ask_spread": 0.01,
        "liquidity_usd": 1000.0,
        "volume_24h_usd": 50.0,
        "end_time": "2026-09-01T00:00:00Z",
        "rules_summary": "Test fixture",
        "tradable": True,
        "execution_ready": True,
        "raw": {"token_id": "123"},
    }
    return {
        "preview_id": "preview-1",
        "user_id": user_id,
        "agent_id": "external_prediction_agent",
        "platform": "polymarket",
        "market_id": "market-1",
        "title": "Will the test pass?",
        "outcome": "Yes",
        "side": "buy",
        "amount_usd": "1.00",
        "limit_price": 0.5,
        "estimated_contracts": 2.0,
        "max_slippage_bps": 100,
        "max_slippage_usd": "0.01",
        "worst_case_price": 0.505,
        "state": "ready",
        "execution_mode": "preview_only",
        "next_action": "create_polymarket_order_signing_session",
        "requires_user_confirmation": True,
        "live_mode": True,
        "core_action_id": "action-1",
        "core_policy_decision_id": "policy-1",
        "core_audit_event_ids": ["audit-1"],
        "core_policy_decision": {"approved": True},
        "market": market,
        "metadata": {},
        "created_at": "2026-08-20T04:00:00Z",
        "expires_at": "2026-08-20T04:10:00Z",
        "event_log": [],
    }


def _signing_session(
    *,
    user_id: str = "telegram:101",
    signing_url: str | None = None,
) -> dict[str, Any]:
    return {
        "session_id": "pm_sign_sess_123456789abc",
        "preview_id": "preview-1",
        "user_id": user_id,
        "binding_id": "pm_binding_1",
        "projection_hash": "a" * 64,
        "revision": 0,
        "agent_id": "external_prediction_agent",
        "market_id": "market-1",
        "title": "Will the test pass?",
        "outcome": "Yes",
        "side": "buy",
        "amount_usd": "1.00",
        "limit_price": 0.5,
        "order_type": "GTC",
        "token_id": "123",
        "order_payload": {},
        "signing_url": signing_url,
        "status": "pending_browser_signature",
        "reason": None,
        "next_action": "open_polymarket_order_signing_url",
        "signed_order": None,
        "execution_id": None,
        "core_action_id": "action-1",
        "core_policy_decision_id": "policy-1",
        "core_audit_event_ids": ["audit-1"],
        "created_at": "2026-08-20T04:00:00Z",
        "expires_at": "2026-08-20T04:10:00Z",
        "completed_at": None,
        "metadata": {},
        "event_log": [],
    }


def _adapter(
    handler,
    *,
    public_base_url: str = ORIGIN,
) -> PredictionMarketsHttpAdapter:
    return PredictionMarketsHttpAdapter(
        base_url="http://127.0.0.1:8040",
        account_binding_url="http://127.0.0.1:8047",
        preview_url="http://127.0.0.1:8041",
        execution_url="http://127.0.0.1:8042",
        funding_url="http://127.0.0.1:8046",
        internal_token=PREDICTION_TOKEN,
        account_binding_internal_token=CORE_TOKEN,
        public_base_url=public_base_url,
        live_operations_enabled=True,
        transport=httpx.MockTransport(handler),
    )


def test_managed_prediction_operations_use_a_separate_internal_token() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(Path(temporary) / ".clink"),
        )
        store = MemorySecretStore(
            {
                "core-internal-api-token": b"core-token-value",
                "prediction-markets-internal-api-token": b"prediction-token-value",
            }
        )
        environment = ManagedEnvironmentBuilder(
            settings,
            store,
            base_env={},
        ).build()

    assert environment["PREDICTION_MARKETS_INTERNAL_API_TOKEN"] == (
        "prediction-token-value"
    )
    assert environment["PREDICTION_MARKETS_INTERNAL_API_TOKEN"] != environment[
        "CLINK_CORE_INTERNAL_API_TOKEN"
    ]


def test_prediction_operation_service_urls_are_independently_configurable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        settings = NodeSettings.load(
            env={
                "CLINK_HOME": temporary,
                "CLINK_PREDICTION_MARKETS_PREVIEW_SERVICE_URL": (
                    "http://prediction-preview:8041"
                ),
                "CLINK_PREDICTION_MARKETS_EXECUTION_SERVICE_URL": (
                    "http://prediction-execution:8042"
                ),
                "CLINK_PREDICTION_MARKETS_FUNDING_ADAPTER_SERVICE_URL": (
                    "http://prediction-funding:8046"
                ),
            }
        )

    assert settings.modules["prediction-markets"].service_urls == {
        "preview": "http://prediction-preview:8041",
        "execution": "http://prediction-execution:8042",
        "funding": "http://prediction-funding:8046",
    }


def test_prediction_operation_urls_reject_credentials_query_and_fragments() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        settings = NodeSettings.load(
            env={
                "CLINK_HOME": temporary,
                "CLINK_PREDICTION_MARKETS_FUNDING_ADAPTER_SERVICE_URL": (
                    "https://user:do-not-leak@prediction.test/?token=secret#x"
                ),
            }
        )

    errors = settings.validation_errors()
    assert errors == ["Prediction Markets funding service URL is invalid"]
    assert "do-not-leak" not in repr(errors)
    with pytest.raises(ValueError, match="prediction service URL is invalid"):
        PredictionMarketsHttpAdapter(
            base_url="http://127.0.0.1:8040",
            funding_url="https://user:secret@prediction.test/",
            internal_token=PREDICTION_TOKEN,
        )


def test_funding_adapter_projects_only_safe_fields_and_never_uses_core_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == httpx.URL(
            "http://127.0.0.1:8046/polymarket/funding-operations"
        )
        assert request.headers["authorization"] == f"Bearer {PREDICTION_TOKEN}"
        assert request.headers["authorization"] != f"Bearer {CORE_TOKEN}"
        assert json.loads(request.content) == {
            "user_id": "telegram:101",
            "amount_usdc": "1.250000",
            "idempotency_key": "miniapp:scoped-key",
            "resource": "clink://polymarket/funding",
        }
        return httpx.Response(201, json=_funding_view(), request=request)

    result = _adapter(handler).create_funding_operation(
        user_id="telegram:101",
        amount_usdc="1.250000",
        idempotency_key="miniapp:scoped-key",
    )

    assert result == {
        "operation_id": "pm_funding_1",
        "status": "created",
        "amount_usdc": "1.250000",
        "chain_status": "not_started",
        "bridge_status": "not_started",
        "buying_power_status": "not_started",
        "reason": None,
        "next_action": "confirm",
    }
    assert len(requests) == 1
    assert "binding_id" not in result
    assert "core_tx_hash" not in result


@pytest.mark.parametrize(
    ("status", "next_action"),
    (
        ("created", "processing"),
        ("finalized", "terminal"),
        ("failed", "complete"),
    ),
)
def test_funding_adapter_rejects_inconsistent_status_and_next_action(
    status: str,
    next_action: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_funding_view(status=status, next_action=next_action),
            request=request,
        )

    with pytest.raises(
        DownstreamError,
        match="funding operation response was invalid",
    ):
        _adapter(handler).get_funding_operation(
            user_id="telegram:101",
            operation_id="pm_funding_1",
        )


@pytest.mark.parametrize(
    ("status", "mutation_path", "mutation_body"),
    (
        (
            "created",
            "/polymarket/funding-operations/pm_funding_1/confirm",
            {"user_id": "telegram:101", "confirmed": True},
        ),
        (
            "confirmed",
            "/polymarket/funding-operations/pm_funding_1/advance",
            {"user_id": "telegram:101"},
        ),
        (
            "settlement_submitting",
            "/polymarket/funding-operations/pm_funding_1/advance",
            {"user_id": "telegram:101"},
        ),
        (
            "settlement_unknown",
            "/polymarket/funding-operations/pm_funding_1/advance",
            {"user_id": "telegram:101"},
        ),
        (
            "submitted",
            "/polymarket/funding-operations/pm_funding_1/advance",
            {"user_id": "telegram:101"},
        ),
    ),
)
def test_funding_continue_reads_scope_then_performs_one_explicit_mutation(
    status: str,
    mutation_path: str,
    mutation_body: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            assert dict(request.url.params) == {"user_id": "telegram:101"}
            return httpx.Response(
                200,
                json=_funding_view(status=status),
                request=request,
            )
        assert request.url.path == mutation_path
        assert json.loads(request.content) == mutation_body
        return httpx.Response(
            200,
            json=_funding_view(status="confirmed", next_action="processing"),
            request=request,
        )

    result = _adapter(handler).continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )

    assert [request.method for request in requests] == ["GET", "POST"]
    assert result["status"] == "confirmed"


def test_funding_continue_does_not_retry_an_ambiguous_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_funding_view(status="confirmed", next_action="processing"),
                request=request,
            )
        raise httpx.ReadTimeout("ambiguous-test-marker", request=request)

    with pytest.raises(DownstreamError) as caught:
        _adapter(handler).continue_funding_operation(
            user_id="telegram:101",
            operation_id="pm_funding_1",
        )

    assert [request.method for request in requests] == ["GET", "POST"]
    assert "ambiguous-test-marker" not in str(caught.value)


@pytest.mark.parametrize(
    "status",
    (
        "action_creating",
        "action_unknown",
        "policy_evaluating",
        "policy_unknown",
        "reservation_creating",
        "finalizing",
        "manual_review",
        "finalized",
        "failed",
        "released",
    ),
)
def test_funding_continue_is_get_only_outside_the_advance_whitelist(
    status: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_funding_view(status=status),
            request=request,
        )

    result = _adapter(handler).continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )

    assert result["status"] == status
    assert [request.method for request in requests] == ["GET"]


def test_ambiguous_funding_mutation_stays_get_only_until_status_changes() -> None:
    current_status = "confirmed"
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_funding_view(status=current_status),
                request=request,
            )
        post_attempts += 1
        if post_attempts == 1:
            raise httpx.ReadTimeout(
                "ambiguous-test-marker",
                request=request,
            )
        return httpx.Response(
            200,
            json=_funding_view(status="policy_approved"),
            request=request,
        )

    adapter = _adapter(handler)
    with pytest.raises(DownstreamError):
        adapter.continue_funding_operation(
            user_id="telegram:101",
            operation_id="pm_funding_1",
        )

    held = adapter.continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert held["status"] == "confirmed"
    assert post_attempts == 1

    current_status = "action_created"
    assert adapter.get_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )["status"] == "action_created"
    resumed = adapter.continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert resumed["status"] == "policy_approved"
    assert post_attempts == 2


def test_ambiguous_funding_submitted_advance_waits_for_status_change() -> None:
    current_status = "submitted"
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_funding_view(status=current_status),
                request=request,
            )
        assert request.url.path == (
            "/polymarket/funding-operations/pm_funding_1/advance"
        )
        assert json.loads(request.content) == {"user_id": "telegram:101"}
        post_attempts += 1
        if post_attempts == 1:
            raise httpx.ReadTimeout(
                "ambiguous-test-marker",
                request=request,
            )
        return httpx.Response(
            200,
            json=_funding_view(status="bridge_pending"),
            request=request,
        )

    adapter = _adapter(handler)
    with pytest.raises(DownstreamError):
        adapter.continue_funding_operation(
            user_id="telegram:101",
            operation_id="pm_funding_1",
        )

    held = adapter.continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert held["status"] == "submitted"
    assert post_attempts == 1

    current_status = "chain_confirmed"
    observed = adapter.get_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert observed["status"] == "chain_confirmed"
    resumed = adapter.continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert resumed["status"] == "bridge_pending"
    assert post_attempts == 2


@pytest.mark.parametrize(
    "failure",
    (408, 409, 429, 400, 500, "invalid_projection"),
)
def test_any_non_successful_funding_mutation_enters_status_only_hold(
    failure: int | str,
) -> None:
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_funding_view(status="confirmed"),
                request=request,
            )
        post_attempts += 1
        if post_attempts == 1:
            if failure == "invalid_projection":
                return httpx.Response(
                    200,
                    json={"status": "confirmed"},
                    request=request,
                )
            return httpx.Response(
                int(failure),
                json={"detail": "must-not-be-classified-or-exposed"},
                request=request,
            )
        return httpx.Response(
            200,
            json=_funding_view(status="policy_approved"),
            request=request,
        )

    adapter = _adapter(handler)
    with pytest.raises(DownstreamError):
        adapter.continue_funding_operation(
            user_id="telegram:101",
            operation_id="pm_funding_1",
        )

    held = adapter.continue_funding_operation(
        user_id="telegram:101",
        operation_id="pm_funding_1",
    )
    assert held["status"] == "confirmed"
    assert post_attempts == 1


def test_order_signing_checks_preview_owner_before_the_single_create_post() -> None:
    requests: list[httpx.Request] = []
    signing_url = (
        f"{ORIGIN}/execution/polymarket/order-signing-console/"
        "#access_token=opaque_browser_capability"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {PREDICTION_TOKEN}"
        if request.method == "GET":
            assert request.url.path == "/order-previews/preview-1"
            return httpx.Response(200, json=_preview(), request=request)
        assert request.url.path == (
            "/execution/polymarket/order-signing-sessions"
        )
        assert json.loads(request.content) == {
            "preview_id": "preview-1",
            "user_confirmed": True,
            "live_submission_confirmed": True,
            "confirmation_message": "confirmed in authenticated Agentonomy Mini App",
            "expires_in_minutes": 10,
            "metadata": {"source": "agentonomy_miniapp"},
        }
        return httpx.Response(
            200,
            json=_signing_session(signing_url=signing_url),
            request=request,
        )

    result = _adapter(handler).create_order_signing_session(
        user_id="telegram:101",
        preview_id="preview-1",
    )

    assert [request.method for request in requests] == ["GET", "POST"]
    assert result == {
        "session_id": "pm_sign_sess_123456789abc",
        "status": "pending_browser_signature",
        "reason": None,
        "next_action": "open_polymarket_order_signing_url",
        "execution_id": None,
        "signing_url": signing_url,
    }


def test_order_signing_rejects_cross_subject_preview_before_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_preview(user_id="telegram:202"),
            request=request,
        )

    with pytest.raises(DownstreamError):
        _adapter(handler).create_order_signing_session(
            user_id="telegram:101",
            preview_id="preview-1",
        )

    assert [request.method for request in requests] == ["GET"]


def test_order_signing_rejects_path_shaped_preview_id_before_downstream_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_preview(), request=request)

    with pytest.raises(ValueError, match="preview_id is invalid"):
        _adapter(handler).create_order_signing_session(
            user_id="telegram:101",
            preview_id="preview-1/../../healthz",
        )

    assert requests == []


@pytest.mark.parametrize(
    "unsafe_url",
    (
        "https://attacker.invalid/execution/polymarket/order-signing-console/#access_token=x",
        f"{ORIGIN}:444/execution/polymarket/order-signing-console/#access_token=x",
        f"https://user@www.agentonomy.xyz/execution/polymarket/order-signing-console/#access_token=x",
        f"{ORIGIN}/execution/polymarket/order-signing-console/?access_token=x",
        f"{ORIGIN}/execution/polymarket/order-signing-console/?#access_token=x",
        f"{ORIGIN}/execution/polymarket/order-signing-console/#access_token=x&extra=1",
        f"{ORIGIN}/execution/polymarket/order-signing-sessions/x#access_token=x",
    ),
)
def test_order_signing_rejects_unsafe_public_url(unsafe_url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _preview() if request.method == "GET" else _signing_session(
            signing_url=unsafe_url
        )
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DownstreamError):
        _adapter(handler).create_order_signing_session(
            user_id="telegram:101",
            preview_id="preview-1",
        )


def test_public_order_signing_proxy_is_an_exact_bounded_allowlist() -> None:
    downstream: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        downstream.append(request)
        return httpx.Response(
            200,
            content=b"{}",
            headers={"Content-Type": "application/json", "X-Secret": "no"},
            request=request,
        )

    adapter = _adapter(handler)
    common = {
        "query": "",
        "headers": [
            ("Authorization", "Bearer browser-capability"),
            ("X-Clink-Origin", ORIGIN),
            ("Cookie", "must-not-forward=1"),
        ],
    }
    adapter.proxy_public_request(
        method="GET",
        path="/execution/polymarket/order-signing-console/",
        body=b"",
        **common,
    )
    adapter.proxy_public_request(
        method="GET",
        path=(
            "/execution/polymarket/order-signing-assets/"
            "polymarket_order_signing.bundle.js"
        ),
        body=b"",
        **common,
    )
    adapter.proxy_public_request(
        method="GET",
        path="/execution/polymarket/browser-order-signing-session",
        body=b"",
        **common,
    )
    adapter.proxy_public_request(
        method="POST",
        path="/execution/polymarket/browser-order-signing-session/complete",
        query="",
        headers=[
            *common["headers"],
            ("Content-Type", "application/json"),
        ],
        body=b'{"signed_order":{},"wallet_address":"0x1","order_type":"GTC"}',
    )

    assert len(downstream) == 4
    browser_headers = downstream[2].headers
    assert browser_headers["authorization"] == "Bearer browser-capability"
    assert browser_headers["x-clink-origin"] == ORIGIN
    assert "cookie" not in browser_headers

    blocked = (
        ("GET", "/execution/polymarket/order-signing-sessions/internal", "", b""),
        ("GET", "/execution/polymarket/browser-order-signing-session", "x=1", b""),
        ("GET", "/execution/polymarket/order-signing-assets/other.js", "", b""),
        ("POST", "/execution/polymarket/order-signing-console/", "", b"{}"),
        (
            "POST",
            "/execution/polymarket/browser-order-signing-session/complete",
            "",
            b"x" * (64 * 1024 + 1),
        ),
        (
            "POST",
            "/execution/polymarket/browser-order-signing-session/complete",
            "",
            (
                b'{"signed_order":{},"wallet_address":"0x1",'
                b'"order_type":"GTC","metadata":{"private":"value"}}'
            ),
        ),
    )
    for method, path, query, body in blocked:
        with pytest.raises(ValueError):
            adapter.proxy_public_request(
                method=method,
                path=path,
                query=query,
                headers=[
                    *common["headers"],
                    ("Content-Type", "application/json"),
                ],
                body=body,
            )
    assert len(downstream) == 4


def test_disabled_live_mode_rejects_public_signing_without_downstream_io() -> None:
    assert "live_operations_enabled" in inspect.signature(
        PredictionMarketsHttpAdapter
    ).parameters
    downstream: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        downstream.append(request)
        return httpx.Response(200, content=b"unexpected", request=request)

    adapter = PredictionMarketsHttpAdapter(
        base_url="http://127.0.0.1:8040",
        execution_url="http://127.0.0.1:8042",
        internal_token=PREDICTION_TOKEN,
        public_base_url=ORIGIN,
        live_operations_enabled=False,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="signing routes"):
        adapter.proxy_public_request(
            method="GET",
            path="/execution/polymarket/order-signing-console/",
            query="",
            headers=[],
            body=b"",
        )

    assert downstream == []


class _Core:
    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "ready": False}

    def create_account_session(self, user_id: str) -> dict[str, Any]:
        return {"account_url": f"{ORIGIN}/account"}

    def proxy_account_request(self, **_kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(200, b"account", ())

    def audit_summary(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        return []


class _Business:
    name = "test-business"

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def capabilities(self) -> list[dict[str, Any]]:
        return []

    def list_services(self, limit: int = 20) -> dict[str, Any]:
        return {"count": 0, "services": []}

    def account_status(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "status": "unavailable"}

    def proxy_public_request(self, **_kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(404, b"", ())


class _LiveOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def create_funding_operation(
        self,
        *,
        user_id: str,
        amount_usdc: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls.append(("create_funding", user_id, amount_usdc, idempotency_key))
        return {
            "operation_id": "pm_funding_1",
            "status": "created",
            "amount_usdc": amount_usdc,
            "chain_status": "not_started",
            "bridge_status": "not_started",
            "buying_power_status": "not_started",
            "reason": None,
            "next_action": "confirm",
        }

    def get_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("get_funding", user_id, operation_id))
        return {
            "operation_id": operation_id,
            "status": "created",
            "amount_usdc": "1.250000",
            "chain_status": "not_started",
            "bridge_status": "not_started",
            "buying_power_status": "not_started",
            "reason": None,
            "next_action": "confirm",
        }

    def continue_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("continue_funding", user_id, operation_id))
        return {
            "operation_id": operation_id,
            "status": "confirmed",
            "amount_usdc": "1.250000",
            "chain_status": "not_started",
            "bridge_status": "not_started",
            "buying_power_status": "not_started",
            "reason": None,
            "next_action": "processing",
        }

    def create_order_signing_session(
        self,
        *,
        user_id: str,
        preview_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("create_signing", user_id, preview_id))
        return {
            "session_id": "pm_sign_sess_123456789abc",
            "status": "pending_browser_signature",
            "reason": None,
            "next_action": "open_polymarket_order_signing_url",
            "execution_id": None,
            "signing_url": (
                f"{ORIGIN}/execution/polymarket/order-signing-console/"
                "#access_token=opaque_browser_capability"
            ),
        }

    def get_order_signing_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("get_signing", user_id, session_id))
        return {
            "session_id": session_id,
            "status": "submitted",
            "reason": None,
            "next_action": "check_polymarket_order_signing_session",
            "execution_id": "pm_execution_1",
        }


class _BlockingLiveOperations(_LiveOperations):
    def __init__(self) -> None:
        super().__init__()
        self.continue_started = threading.Event()
        self.continue_release = threading.Event()
        self.continue_calls = 0
        self.signing_started = threading.Event()
        self.signing_release = threading.Event()
        self.signing_calls = 0

    def continue_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        self.continue_calls += 1
        self.continue_started.set()
        assert self.continue_release.wait(timeout=2)
        return super().continue_funding_operation(
            user_id=user_id,
            operation_id=operation_id,
        )

    def create_order_signing_session(
        self,
        *,
        user_id: str,
        preview_id: str,
    ) -> dict[str, Any]:
        self.signing_calls += 1
        self.signing_started.set()
        assert self.signing_release.wait(timeout=2)
        return super().create_order_signing_session(
            user_id=user_id,
            preview_id=preview_id,
        )


class _MiniAppHarness:
    def __init__(self, live: _LiveOperations | None) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        paths = NodePaths.from_home(root / ".clink")
        self.settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
        self.repository = SQLiteNodeRepository(root / "node.db")
        self.repository.migrate()
        core = _Core()
        service = MiniAppChatService(
            repository=self.repository,
            hermes_client=object(),
            account_link_factory=core.create_account_session,
            polymarket_live_operations=live,
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: NOW,
            auth_max_age_seconds=300,
            session_ttl_seconds=3600,
        )
        context = NodeApiContext(
            settings=self.settings,
            repository=self.repository,
            interaction_service=InteractionService(
                self.repository,
                base_url=ORIGIN,
            ),
            session_token="node-test-session",
            core=core,
            marketplace=_Business(),
            prediction_markets=_Business(),
            miniapp_service=service,
        )
        self.app = create_app(context)
        self.client = TestClient(self.app, base_url=ORIGIN)

    def close(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def login(self, *, user_id: int, username: str) -> str:
        response = self.client.post(
            "/miniapp/api/session",
            headers={"Origin": ORIGIN},
            json={
                "init_data": _signed_init_data(
                    user_id=user_id,
                    username=username,
                ),
                "client_nonce": CLIENT_NONCE,
            },
        )
        assert response.status_code == 201
        return response.json()["csrf_token"]


def test_miniapp_live_operations_derive_subject_and_scope_idempotency() -> None:
    live = _LiveOperations()
    alice = _MiniAppHarness(live)
    bob = _MiniAppHarness(live)
    try:
        alice_csrf = alice.login(user_id=101, username="alice")
        bob_csrf = bob.login(user_id=202, username="bob")
        endpoint = "/miniapp/api/operations/polymarket/funding"
        unsafe = alice.client.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf},
            json={
                "amount_usdc": "1.25",
                "idempotency_key": "same-click",
                "user_id": "telegram:202",
            },
        )
        alice_response = alice.client.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf},
            json={"amount_usdc": "1.25", "idempotency_key": "same-click"},
        )
        bob_response = bob.client.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": bob_csrf},
            json={"amount_usdc": "1.25", "idempotency_key": "same-click"},
        )

        assert unsafe.status_code == 400
        assert alice_response.status_code == 201
        assert bob_response.status_code == 201
        creates = [call for call in live.calls if call[0] == "create_funding"]
        assert [call[1] for call in creates] == ["telegram:101", "telegram:202"]
        assert [call[2] for call in creates] == ["1.250000", "1.250000"]
        assert creates[0][3] != creates[1][3]
        assert "same-click" not in {creates[0][3], creates[1][3]}
    finally:
        alice.close()
        bob.close()


def test_miniapp_rejects_oversized_usdc_before_the_live_boundary() -> None:
    live = _LiveOperations()
    harness = _MiniAppHarness(live)
    try:
        csrf = harness.login(user_id=101, username="alice")
        response = harness.client.post(
            "/miniapp/api/operations/polymarket/funding",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={"amount_usdc": "1" * 79, "idempotency_key": "click-1"},
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "miniapp_invalid_request"}
        assert live.calls == []
    finally:
        harness.close()


def test_miniapp_funding_and_signing_routes_require_operation_guards() -> None:
    live = _LiveOperations()
    harness = _MiniAppHarness(live)
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        funding = harness.client.get(
            "/miniapp/api/operations/polymarket/funding/pm_funding_1"
        )
        continued = harness.client.post(
            "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue",
            headers=headers,
            json={},
        )
        signing = harness.client.post(
            "/miniapp/api/operations/polymarket/order-signing",
            headers=headers,
            json={"preview_id": "preview-1"},
        )
        signing_status = harness.client.get(
            "/miniapp/api/operations/polymarket/order-signing/"
            "pm_sign_sess_123456789abc"
        )
        missing_origin = harness.client.post(
            "/miniapp/api/operations/polymarket/funding/"
            "pm_funding_1/continue",
            headers={"X-Agentonomy-CSRF": csrf},
            json={},
        )

        assert funding.status_code == 200
        assert continued.status_code == 200
        assert signing.status_code == 201
        assert signing_status.status_code == 200
        assert missing_origin.status_code == 403
        assert live.calls == [
            ("get_funding", "telegram:101", "pm_funding_1"),
            ("continue_funding", "telegram:101", "pm_funding_1"),
            ("create_signing", "telegram:101", "preview-1"),
            (
                "get_signing",
                "telegram:101",
                "pm_sign_sess_123456789abc",
            ),
        ]
    finally:
        harness.close()


def test_live_operation_routes_reject_queries_before_the_boundary() -> None:
    live = _LiveOperations()
    harness = _MiniAppHarness(live)
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        responses = (
            harness.client.post(
                "/miniapp/api/operations/polymarket/funding?user_id=x",
                headers=headers,
                json={"amount_usdc": "1.25", "idempotency_key": "click-1"},
            ),
            harness.client.get(
                "/miniapp/api/operations/polymarket/funding/pm_funding_1?x=1"
            ),
            harness.client.post(
                "/miniapp/api/operations/polymarket/funding/"
                "pm_funding_1/continue?x=1",
                headers=headers,
                json={},
            ),
            harness.client.post(
                "/miniapp/api/operations/polymarket/order-signing?x=1",
                headers=headers,
                json={"preview_id": "preview-1"},
            ),
            harness.client.get(
                "/miniapp/api/operations/polymarket/order-signing/"
                "pm_sign_sess_123456789abc?x=1"
            ),
        )

        assert [response.status_code for response in responses] == [400] * 5
        assert live.calls == []
    finally:
        harness.close()


def test_funding_mutation_http_rejection_is_not_classified_as_business_error() -> None:
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_funding_view(status="confirmed"),
                request=request,
            )
        post_attempts += 1
        return httpx.Response(
            409,
            json={"detail": "must-not-be-classified-or-exposed"},
            request=request,
        )

    harness = _MiniAppHarness(_adapter(handler))
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        path = (
            "/miniapp/api/operations/polymarket/funding/"
            "pm_funding_1/continue"
        )
        rejected = harness.client.post(path, headers=headers, json={})
        held = harness.client.post(path, headers=headers, json={})

        assert rejected.status_code == 503
        assert rejected.json() == {"detail": "miniapp_unavailable"}
        assert held.status_code == 200
        assert held.json()["status"] == "confirmed"
        assert post_attempts == 1
    finally:
        harness.close()


def test_concurrent_funding_continue_requests_share_one_boundary_call() -> None:
    live = _BlockingLiveOperations()
    harness = _MiniAppHarness(live)
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}

        async def run_requests() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=harness.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=ORIGIN,
                cookies=dict(harness.client.cookies),
            ) as client:
                first = asyncio.create_task(
                    client.post(
                        "/miniapp/api/operations/polymarket/funding/"
                        "pm_funding_1/continue",
                        headers=headers,
                        json={},
                    )
                )
                assert await asyncio.to_thread(
                    live.continue_started.wait,
                    1,
                )
                second = asyncio.create_task(
                    client.post(
                        "/miniapp/api/operations/polymarket/funding/"
                        "pm_funding_1/continue",
                        headers=headers,
                        json={},
                    )
                )
                await asyncio.sleep(0.05)
                live.continue_release.set()
                return list(await asyncio.gather(first, second))

        responses = asyncio.run(run_requests())
        assert [response.status_code for response in responses] == [200, 200]
        assert live.continue_calls == 1
    finally:
        live.continue_release.set()
        harness.close()


def test_order_signing_create_is_singleflight_and_cached_for_the_preview() -> None:
    live = _BlockingLiveOperations()
    harness = _MiniAppHarness(live)
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        path = "/miniapp/api/operations/polymarket/order-signing"

        async def run_requests() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=harness.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=ORIGIN,
                cookies=dict(harness.client.cookies),
            ) as client:
                first = asyncio.create_task(
                    client.post(
                        path,
                        headers=headers,
                        json={"preview_id": "preview-1"},
                    )
                )
                assert await asyncio.to_thread(
                    live.signing_started.wait,
                    1,
                )
                second = asyncio.create_task(
                    client.post(
                        path,
                        headers=headers,
                        json={"preview_id": "preview-1"},
                    )
                )
                await asyncio.sleep(0.05)
                live.signing_release.set()
                return list(await asyncio.gather(first, second))

        first_responses = asyncio.run(run_requests())
        status = harness.client.get(
            "/miniapp/api/operations/polymarket/order-signing/"
            "pm_sign_sess_123456789abc"
        )
        replay = harness.client.post(
            path,
            headers=headers,
            json={"preview_id": "preview-1"},
        )

        assert [response.status_code for response in first_responses] == [
            201,
            201,
        ]
        assert first_responses[0].json() == first_responses[1].json()
        assert status.status_code == 200
        assert status.json()["status"] == "submitted"
        assert replay.status_code == 201
        assert replay.json() == first_responses[0].json()
        assert live.signing_calls == 1
    finally:
        live.signing_release.set()
        harness.close()


@pytest.mark.parametrize("first_post_failure", ("http_503", "invalid_response"))
def test_order_signing_create_failure_tombstones_the_preview(
    first_post_failure: str,
) -> None:
    post_attempts = 0
    signing_url = (
        f"{ORIGIN}/execution/polymarket/order-signing-console/"
        "#access_token=opaque_browser_capability"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return httpx.Response(200, json=_preview(), request=request)
        post_attempts += 1
        if post_attempts == 1:
            if first_post_failure == "http_503":
                return httpx.Response(
                    503,
                    json={"detail": "must-not-be-exposed"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={"unexpected": "response"},
                request=request,
            )
        return httpx.Response(
            200,
            json=_signing_session(signing_url=signing_url),
            request=request,
        )

    harness = _MiniAppHarness(_adapter(handler))
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        path = "/miniapp/api/operations/polymarket/order-signing"
        first = harness.client.post(
            path,
            headers=headers,
            json={"preview_id": "preview-1"},
        )
        replay = harness.client.post(
            path,
            headers=headers,
            json={"preview_id": "preview-1"},
        )

        expected = {
            "detail": "miniapp_order_signing_outcome_unknown",
            "next_action": "create_new_preview_or_manual_reconcile",
        }
        assert first.status_code == 503
        assert first.json() == expected
        assert replay.status_code == 503
        assert replay.json() == expected
        assert post_attempts == 1
    finally:
        harness.close()


def test_order_signing_preview_get_failure_remains_retryable() -> None:
    get_attempts = 0
    post_attempts = 0
    signing_url = (
        f"{ORIGIN}/execution/polymarket/order-signing-console/"
        "#access_token=opaque_browser_capability"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_attempts, post_attempts
        if request.method == "GET":
            get_attempts += 1
            if get_attempts == 1:
                return httpx.Response(
                    503,
                    json={"detail": "preview temporarily unavailable"},
                    request=request,
                )
            return httpx.Response(200, json=_preview(), request=request)
        post_attempts += 1
        return httpx.Response(
            200,
            json=_signing_session(signing_url=signing_url),
            request=request,
        )

    harness = _MiniAppHarness(_adapter(handler))
    try:
        csrf = harness.login(user_id=101, username="alice")
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        path = "/miniapp/api/operations/polymarket/order-signing"
        first = harness.client.post(
            path,
            headers=headers,
            json={"preview_id": "preview-1"},
        )
        retried = harness.client.post(
            path,
            headers=headers,
            json={"preview_id": "preview-1"},
        )

        assert first.status_code == 503
        assert first.json() == {"detail": "miniapp_unavailable"}
        assert retried.status_code == 201
        assert retried.json()["signing_url"] == signing_url
        assert get_attempts == 2
        assert post_attempts == 1
    finally:
        harness.close()


def test_unwired_miniapp_live_operations_are_404_without_downstream_calls() -> None:
    harness = _MiniAppHarness(None)
    try:
        csrf = harness.login(user_id=101, username="alice")
        mutation_headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        responses = (
            harness.client.post(
                "/miniapp/api/operations/polymarket/funding",
                headers=mutation_headers,
                json={"amount_usdc": "1.25", "idempotency_key": "click-1"},
            ),
            harness.client.get(
                "/miniapp/api/operations/polymarket/funding/pm_funding_1"
            ),
            harness.client.post(
                "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue",
                headers=mutation_headers,
                json={},
            ),
            harness.client.post(
                "/miniapp/api/operations/polymarket/order-signing",
                headers=mutation_headers,
                json={"preview_id": "preview-1"},
            ),
            harness.client.get(
                "/miniapp/api/operations/polymarket/order-signing/session-1"
            ),
        )
        for response in responses:
            assert response.status_code == 404
            assert response.json() == {"detail": "miniapp_not_found"}
    finally:
        harness.close()
