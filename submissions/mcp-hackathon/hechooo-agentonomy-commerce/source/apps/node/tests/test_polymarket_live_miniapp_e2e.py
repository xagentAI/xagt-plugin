from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient

from apps.node.clink_node.adapters.core import AccountProxyResponse
from apps.node.clink_node.adapters.prediction_markets import (
    PredictionMarketsHttpAdapter,
)
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.interactions import InteractionService
from apps.node.clink_node.miniapp.service import MiniAppChatService
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


NOW = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
ORIGIN = "https://www.agentonomy.xyz"
BOT_TOKEN = b"123456:test-only-telegram-token"
COOKIE_SECRET = b"c" * 32
HERMES_SECRET = b"h" * 32
CLIENT_NONCE = base64.urlsafe_b64encode(b"n" * 16).decode().rstrip("=")
PREDICTION_TOKEN = "prediction-internal-token"
CORE_TOKEN = "core-internal-token"
BROWSER_CAPABILITY = "browser-capability"
SENSITIVE_MARKER = "must-not-leak"


def _signed_init_data(*, user_id: int) -> str:
    fields = {
        "auth_date": str(int(NOW.timestamp())),
        "query_id": f"query-{user_id}",
        "user": json.dumps(
            {"id": user_id, "username": f"user-{user_id}"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret = hmac.new(b"WebAppData", BOT_TOKEN, hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        check.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


class _DeterministicPredictionServices:
    """Deterministic HTTP substitute for external Prediction services."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.funding: dict[str, dict[str, Any]] = {}
        self.signing: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/polymarket/funding-operations":
            return self._create_funding(request)
        if path.startswith("/polymarket/funding-operations/"):
            return self._funding_operation(request)
        if path.startswith("/order-previews/"):
            return self._preview(request)
        if path == "/execution/polymarket/order-signing-sessions":
            return self._create_signing(request)
        if path.startswith(
            "/execution/polymarket/order-signing-sessions/"
        ):
            return self._signing_status(request)
        if path == (
            "/execution/polymarket/"
            "browser-order-signing-session/complete"
        ):
            return self._complete_signing(request)
        return self._response(request, 404, {"detail": "not found"})

    def mutation_count(self, path: str) -> int:
        return self.requests.count(("POST", path))

    def _create_funding(self, request: httpx.Request) -> httpx.Response:
        self._require_internal(request)
        if request.method != "POST":
            return self._response(request, 405, {"detail": "method"})
        payload = self._json(request)
        assert set(payload) == {
            "user_id",
            "amount_usdc",
            "idempotency_key",
            "resource",
        }
        assert payload["resource"] == "clink://polymarket/funding"
        assert str(payload["idempotency_key"]).startswith("miniapp:")
        user_id = str(payload["user_id"])
        operation_id = "pm_funding_" + user_id.removeprefix("telegram:")
        current = self.funding.get(operation_id)
        if current is None:
            current = {
                "operation_id": operation_id,
                "user_id": user_id,
                "amount_usdc": str(payload["amount_usdc"]),
                "status": "created",
                "next_action": "confirm",
            }
            self.funding[operation_id] = current
        return self._response(request, 201, self._funding_view(current))

    def _funding_operation(self, request: httpx.Request) -> httpx.Response:
        self._require_internal(request)
        prefix = "/polymarket/funding-operations/"
        remainder = request.url.path.removeprefix(prefix)
        operation_id, separator, action = remainder.partition("/")
        current = self.funding.get(operation_id)
        if current is None:
            return self._response(request, 404, {"detail": "missing"})
        if request.method == "GET" and not separator:
            if request.url.params.get("user_id") != current["user_id"]:
                return self._response(request, 404, {"detail": "missing"})
            return self._response(request, 200, self._funding_view(current))
        if request.method != "POST" or action not in {"confirm", "advance"}:
            return self._response(request, 404, {"detail": "missing"})
        payload = self._json(request)
        if payload.get("user_id") != current["user_id"]:
            return self._response(request, 404, {"detail": "missing"})
        if action == "confirm":
            assert payload == {
                "user_id": current["user_id"],
                "confirmed": True,
            }
            assert current["status"] == "created"
            current.update(status="confirmed", next_action="processing")
        else:
            assert payload == {"user_id": current["user_id"]}
            assert current["status"] == "confirmed"
            current.update(
                status="finalized",
                next_action="complete",
            )
        return self._response(request, 200, self._funding_view(current))

    def _preview(self, request: httpx.Request) -> httpx.Response:
        self._require_internal(request)
        if request.method != "GET":
            return self._response(request, 405, {"detail": "method"})
        preview_id = request.url.path.rsplit("/", 1)[-1]
        if preview_id != "preview-alice":
            return self._response(request, 404, {"detail": "missing"})
        return self._response(
            request,
            200,
            {
                "preview_id": preview_id,
                "user_id": "telegram:101",
                "agent_id": "external_prediction_agent",
                "platform": "polymarket",
                "market_id": "market-1",
                "title": "Will the local E2E pass?",
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
                "market": {
                    "platform": "polymarket",
                    "market_id": "market-1",
                    "event_id": "event-1",
                    "title": "Will the local E2E pass?",
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
                    "rules_summary": "Deterministic E2E fixture",
                    "tradable": True,
                    "execution_ready": True,
                    "raw": {"token_id": "123"},
                },
                "metadata": {"funding_operation_id": "pm_funding_101"},
                "created_at": "2026-08-20T04:00:00Z",
                "expires_at": "2026-08-20T04:10:00Z",
                "event_log": [],
            },
        )

    def _create_signing(self, request: httpx.Request) -> httpx.Response:
        self._require_internal(request)
        if request.method != "POST":
            return self._response(request, 405, {"detail": "method"})
        payload = self._json(request)
        assert payload == {
            "preview_id": "preview-alice",
            "user_confirmed": True,
            "live_submission_confirmed": True,
            "confirmation_message": (
                "confirmed in authenticated Agentonomy Mini App"
            ),
            "expires_in_minutes": 10,
            "metadata": {"source": "agentonomy_miniapp"},
        }
        session_id = "pm_sign_sess_alice123456"
        current = {
            "session_id": session_id,
            "preview_id": "preview-alice",
            "user_id": "telegram:101",
            "status": "pending_browser_signature",
            "next_action": "open_polymarket_order_signing_url",
            "execution_id": None,
            "completed": False,
        }
        self.signing[session_id] = current
        return self._response(request, 201, self._signing_view(current))

    def _complete_signing(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == (
            f"Bearer {BROWSER_CAPABILITY}"
        )
        assert request.headers.get("x-clink-origin") == ORIGIN
        payload = self._json(request)
        assert set(payload) == {
            "signed_order",
            "wallet_address",
            "order_type",
            "metadata",
        }
        assert payload["order_type"] == "GTC"
        assert payload["metadata"] == {}
        current = self.signing["pm_sign_sess_alice123456"]
        current["completed"] = True
        return self._response(
            request,
            202,
            {"status": "unknown", "next_action": "poll_original_order"},
        )

    def _signing_status(self, request: httpx.Request) -> httpx.Response:
        self._require_internal(request)
        if request.method != "GET":
            return self._response(request, 405, {"detail": "method"})
        session_id = request.url.path.rsplit("/", 1)[-1]
        current = self.signing.get(session_id)
        if current is None:
            return self._response(request, 404, {"detail": "missing"})
        return self._response(request, 200, self._signing_view(current))

    @staticmethod
    def _json(request: httpx.Request) -> dict[str, Any]:
        value = json.loads(request.content)
        assert isinstance(value, dict)
        return value

    @staticmethod
    def _response(
        request: httpx.Request,
        status_code: int,
        payload: dict[str, Any],
    ) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    @staticmethod
    def _require_internal(request: httpx.Request) -> None:
        assert request.headers.get("authorization") == (
            f"Bearer {PREDICTION_TOKEN}"
        )

    @staticmethod
    def _funding_view(current: dict[str, Any]) -> dict[str, Any]:
        finalized = current["status"] == "finalized"
        return {
            "operation_id": current["operation_id"],
            "user_id": current["user_id"],
            "binding_id": "pm_binding_alice",
            "venue_wallet_address": "0x" + "2" * 40,
            "bridge_address": "0x" + "3" * 40,
            "status": current["status"],
            "amount_usdc": current["amount_usdc"],
            "resource": "clink://polymarket/funding",
            "action_id": "action-1" if finalized else None,
            "policy_decision_id": "policy-1" if finalized else None,
            "audit_event_id": "audit-1" if finalized else None,
            "reservation_id": "reservation-1" if finalized else None,
            "core_tx_hash": "0x" + "4" * 64 if finalized else None,
            "core_state": "finalized" if finalized else None,
            "bridge_status": "COMPLETED" if finalized else None,
            "venue_buying_power_before_atomic": "0",
            "venue_buying_power_after_atomic": "1250000" if finalized else None,
            "failure_reason_code": None,
            "confirmed_at": "2026-08-20T04:01:00Z" if finalized else None,
            "finalized_at": "2026-08-20T04:02:00Z" if finalized else None,
            "created_at": "2026-08-20T04:00:00Z",
            "updated_at": "2026-08-20T04:02:00Z",
            "revision": 2 if finalized else 0,
            "next_action": current["next_action"],
            "funding_proof": SENSITIVE_MARKER,
            "credentials": {"api_key": SENSITIVE_MARKER},
        }

    @staticmethod
    def _signing_view(current: dict[str, Any]) -> dict[str, Any]:
        completed = bool(current["completed"])
        return {
            "session_id": current["session_id"],
            "preview_id": current["preview_id"],
            "user_id": current["user_id"],
            "binding_id": "pm_binding_alice",
            "projection_hash": "a" * 64,
            "revision": 1 if completed else 0,
            "agent_id": "external_prediction_agent",
            "market_id": "market-1",
            "title": "Will the local E2E pass?",
            "outcome": "Yes",
            "side": "buy",
            "amount_usd": "1.00",
            "limit_price": 0.5,
            "order_type": "GTC",
            "token_id": "123",
            "order_payload": {},
            "signing_url": (
                f"{ORIGIN}/execution/polymarket/order-signing-console/"
                f"#access_token={BROWSER_CAPABILITY}"
            ),
            "status": "submitted" if completed else current["status"],
            "reason": None,
            "next_action": (
                "check_polymarket_order_signing_session"
                if completed
                else current["next_action"]
            ),
            "signed_order": None,
            "execution_id": "pm_execution_alice" if completed else None,
            "core_action_id": "action-1",
            "core_policy_decision_id": "policy-1",
            "core_audit_event_ids": ["audit-1"],
            "created_at": "2026-08-20T04:00:00Z",
            "expires_at": "2026-08-20T04:10:00Z",
            "completed_at": "2026-08-20T04:03:00Z" if completed else None,
            "metadata": {"funding_proof": SENSITIVE_MARKER},
            "event_log": [],
            "credentials": {"api_key": SENSITIVE_MARKER},
        }


class _Core:
    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "ready": False}

    def create_account_session(self, user_id: str) -> dict[str, Any]:
        del user_id
        return {"account_url": f"{ORIGIN}/account"}

    def proxy_account_request(self, **_kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(404, b"", ())

    def audit_summary(
        self,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        del user_id, limit
        return []


class _Marketplace:
    name = "marketplace"

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def capabilities(self) -> list[dict[str, Any]]:
        return []

    def list_services(self, limit: int = 20) -> dict[str, Any]:
        del limit
        return {"count": 0, "services": []}

    def proxy_public_request(self, **_kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(404, b"", ())


class _HermesMustRemainOutsideLiveOperations:
    def __init__(self) -> None:
        self.calls = 0

    def for_session(self, _session_key: str) -> Any:
        self.calls += 1
        raise AssertionError("live operations must not route through Hermes")


class _NodeHarness:
    def __init__(
        self,
        root: Path,
        *,
        live_enabled: bool,
    ) -> None:
        self.downstream = _DeterministicPredictionServices()
        self.hermes = _HermesMustRemainOutsideLiveOperations()
        paths = NodePaths.from_home(root / ".clink")
        settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
        self.repository = SQLiteNodeRepository(root / "node.sqlite3")
        self.repository.migrate()
        core = _Core()
        self.prediction = PredictionMarketsHttpAdapter(
            base_url="http://127.0.0.1:8040",
            account_binding_url="http://127.0.0.1:8047",
            preview_url="http://127.0.0.1:8041",
            execution_url="http://127.0.0.1:8042",
            funding_url="http://127.0.0.1:8046",
            internal_token=PREDICTION_TOKEN,
            account_binding_internal_token=CORE_TOKEN,
            public_base_url=ORIGIN,
            live_operations_enabled=live_enabled,
            transport=httpx.MockTransport(self.downstream),
        )
        service = MiniAppChatService(
            repository=self.repository,
            hermes_client=self.hermes,
            account_link_factory=core.create_account_session,
            polymarket_live_operations=(
                self.prediction if live_enabled else None
            ),
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: NOW,
            auth_max_age_seconds=300,
            session_ttl_seconds=3600,
        )
        context = NodeApiContext(
            settings=settings,
            repository=self.repository,
            interaction_service=InteractionService(
                self.repository,
                base_url=ORIGIN,
            ),
            session_token="node-test-session",
            core=core,
            marketplace=_Marketplace(),
            prediction_markets=self.prediction,
            miniapp_service=service,
        )
        self.app = create_app(context)

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=ORIGIN)


def _login(client: TestClient, *, user_id: int) -> dict[str, str]:
    response = client.post(
        "/miniapp/api/session",
        headers={"Origin": ORIGIN},
        json={
            "init_data": _signed_init_data(user_id=user_id),
            "client_nonce": CLIENT_NONCE,
        },
    )
    assert response.status_code == 201
    return {
        "Origin": ORIGIN,
        "X-Agentonomy-CSRF": response.json()["csrf_token"],
    }


def _assert_safe_browser_projection(
    payload: dict[str, Any],
    *,
    allow_signing_capability: bool = False,
) -> None:
    forbidden = {
        "access_token",
        "authorization",
        "capability",
        "user_id",
        "binding_id",
        "wallet_address",
        "venue_wallet_address",
        "bridge_address",
        "funding_proof",
        "credentials",
        "api_key",
        "secret",
        "core_tx_hash",
        "reservation_id",
    }
    def assert_forbidden_keys_absent(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for nested in value.values():
                assert_forbidden_keys_absent(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_forbidden_keys_absent(nested)

    assert_forbidden_keys_absent(payload)
    encoded = json.dumps(payload, sort_keys=True)
    assert SENSITIVE_MARKER not in encoded
    assert PREDICTION_TOKEN not in encoded
    assert CORE_TOKEN not in encoded
    if allow_signing_capability:
        assert payload.get("signing_url") == (
            f"{ORIGIN}/execution/polymarket/order-signing-console/"
            f"#access_token={BROWSER_CAPABILITY}"
        )
        assert encoded.count(BROWSER_CAPABILITY) == 1
    else:
        assert BROWSER_CAPABILITY not in encoded


def test_real_node_closes_funding_and_user_signed_order_once(
    tmp_path: Path,
) -> None:
    harness = _NodeHarness(tmp_path, live_enabled=True)
    with harness.client() as alice:
        mutation_headers = _login(alice, user_id=101)
        funding = alice.post(
            "/miniapp/api/operations/polymarket/funding",
            headers=mutation_headers,
            json={"amount_usdc": "1.25", "idempotency_key": "fund-click"},
        )
        assert funding.status_code == 201
        operation_id = funding.json()["operation_id"]

        confirmed = alice.post(
            f"/miniapp/api/operations/polymarket/funding/{operation_id}/continue",
            headers=mutation_headers,
            json={},
        )
        advanced = alice.post(
            f"/miniapp/api/operations/polymarket/funding/{operation_id}/continue",
            headers=mutation_headers,
            json={},
        )
        status = alice.get(
            f"/miniapp/api/operations/polymarket/funding/{operation_id}"
        )
        signing = alice.post(
            "/miniapp/api/operations/polymarket/order-signing",
            headers=mutation_headers,
            json={"preview_id": "preview-alice"},
        )

        assert confirmed.status_code == 200
        assert advanced.status_code == 200
        assert status.status_code == 200
        assert status.json()["status"] == "finalized"
        assert signing.status_code == 201
        signing_payload = signing.json()
        assert signing_payload["signing_url"] == (
            f"{ORIGIN}/execution/polymarket/order-signing-console/"
            f"#access_token={BROWSER_CAPABILITY}"
        )

        browser_complete = alice.post(
            "/execution/polymarket/browser-order-signing-session/complete",
            headers={
                "Authorization": f"Bearer {BROWSER_CAPABILITY}",
                "X-Clink-Origin": ORIGIN,
                "Content-Type": "application/json",
            },
            json={
                "signed_order": {"signature": "0x" + "a" * 130},
                "wallet_address": "0x" + "1" * 40,
                "order_type": "GTC",
                "metadata": {},
            },
        )
        signing_status = alice.get(
            "/miniapp/api/operations/polymarket/order-signing/"
            + signing_payload["session_id"]
        )

        assert browser_complete.status_code == 202
        assert browser_complete.json() == {
            "status": "unknown",
            "next_action": "poll_original_order",
        }
        assert signing_status.status_code == 200
        assert signing_status.json()["status"] == "submitted"
        assert signing_status.json()["execution_id"] == "pm_execution_alice"

        safe_responses = (
            funding,
            confirmed,
            advanced,
            status,
            browser_complete,
            signing_status,
        )
        for response in safe_responses:
            _assert_safe_browser_projection(response.json())
        _assert_safe_browser_projection(
            signing_payload,
            allow_signing_capability=True,
        )
        all_browser_payloads = json.dumps(
            [response.json() for response in safe_responses]
            + [signing_payload],
            sort_keys=True,
        )
        assert all_browser_payloads.count(BROWSER_CAPABILITY) == 1
        assert PREDICTION_TOKEN not in all_browser_payloads
        assert CORE_TOKEN not in all_browser_payloads
        assert harness.hermes.calls == 0
        for path in (
            "/polymarket/funding-operations",
            f"/polymarket/funding-operations/{operation_id}/confirm",
            f"/polymarket/funding-operations/{operation_id}/advance",
            "/execution/polymarket/order-signing-sessions",
            "/execution/polymarket/browser-order-signing-session/complete",
        ):
            assert harness.downstream.mutation_count(path) == 1


def test_shared_sqlite_node_rejects_cross_subject_reads_and_mutations(
    tmp_path: Path,
) -> None:
    harness = _NodeHarness(tmp_path, live_enabled=True)
    with harness.client() as alice, harness.client() as bob:
        alice_headers = _login(alice, user_id=101)
        bob_headers = _login(bob, user_id=202)
        funding = alice.post(
            "/miniapp/api/operations/polymarket/funding",
            headers=alice_headers,
            json={"amount_usdc": "1.25", "idempotency_key": "same-text"},
        )
        assert funding.status_code == 201
        operation_id = funding.json()["operation_id"]
        signing = alice.post(
            "/miniapp/api/operations/polymarket/order-signing",
            headers=alice_headers,
            json={"preview_id": "preview-alice"},
        )
        assert signing.status_code == 201

        bob_read = bob.get(
            f"/miniapp/api/operations/polymarket/funding/{operation_id}"
        )
        bob_continue = bob.post(
            f"/miniapp/api/operations/polymarket/funding/{operation_id}/continue",
            headers=bob_headers,
            json={},
        )
        bob_signing_read = bob.get(
            "/miniapp/api/operations/polymarket/order-signing/"
            + signing.json()["session_id"]
        )
        bob_signing_create = bob.post(
            "/miniapp/api/operations/polymarket/order-signing",
            headers=bob_headers,
            json={"preview_id": "preview-alice"},
        )

        for response in (
            bob_read,
            bob_continue,
            bob_signing_read,
            bob_signing_create,
        ):
            assert response.status_code == 404
            assert response.json() == {"detail": "miniapp_not_found"}
        assert harness.downstream.mutation_count(
            f"/polymarket/funding-operations/{operation_id}/confirm"
        ) == 0
        assert harness.downstream.mutation_count(
            "/execution/polymarket/order-signing-sessions"
        ) == 1


def test_mutations_require_real_session_origin_and_csrf_before_io(
    tmp_path: Path,
) -> None:
    harness = _NodeHarness(tmp_path, live_enabled=True)
    with harness.client() as alice:
        mutation_headers = _login(alice, user_id=101)
        missing_csrf = alice.post(
            "/miniapp/api/operations/polymarket/funding",
            headers={"Origin": ORIGIN},
            json={"amount_usdc": "1.25", "idempotency_key": "click-1"},
        )
        wrong_origin = alice.post(
            "/miniapp/api/operations/polymarket/funding",
            headers={
                **mutation_headers,
                "Origin": "https://attacker.invalid",
            },
            json={"amount_usdc": "1.25", "idempotency_key": "click-1"},
        )

        assert missing_csrf.status_code == 403
        assert wrong_origin.status_code == 403
        assert harness.downstream.requests == []


def test_disabled_live_routes_are_404_with_zero_downstream_and_hermes_io(
    tmp_path: Path,
) -> None:
    harness = _NodeHarness(tmp_path, live_enabled=False)
    with harness.client() as alice:
        mutation_headers = _login(alice, user_id=101)
        responses = (
            alice.post(
                "/miniapp/api/operations/polymarket/funding",
                headers=mutation_headers,
                json={
                    "amount_usdc": "1.25",
                    "idempotency_key": "click-1",
                },
            ),
            alice.get(
                "/miniapp/api/operations/polymarket/funding/pm_funding_101"
            ),
            alice.post(
                "/miniapp/api/operations/polymarket/order-signing",
                headers=mutation_headers,
                json={"preview_id": "preview-alice"},
            ),
            alice.get(
                "/execution/polymarket/order-signing-console/"
            ),
        )

        assert [response.status_code for response in responses] == [404] * 4
        assert harness.downstream.requests == []
        assert harness.hermes.calls == 0
