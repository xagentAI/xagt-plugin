from __future__ import annotations

import asyncio
import inspect
import json
import urllib.request
from pathlib import Path

import pytest

import mcp_servers.prediction_markets_server as server
from services.execution_service.service import HttpFundingGateway
from services.portfolio_service.service import PortfolioService
from shared.config import AppConfig
from storage.trading_ledger import TradingLedger


OWNER_WALLET = "0x" + "22" * 20
OTHER_OWNER_WALLET = "0x" + "33" * 20
MIXED_CASE_OWNER_WALLET = "0x" + "CD" * 20
DEPOSIT_WALLET = "0x" + "AB" * 20
TYPE3_BINDING_ERROR = (
    "Polymarket Deposit Wallet is not ready for type-3 binding"
)
OPC_INSTALLATION_ID = "opc_" + "a" * 40


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _operation_payload(
    *, status: str = "finalized", opc_installation_id: str | None = None
) -> dict:
    finalized = status == "finalized"
    return {
        "operation_id": "pm_funding_1",
        "user_id": "user-a",
        "opc_installation_id": opc_installation_id,
        "binding_id": "binding-a",
        "venue_wallet_address": "0x" + "11" * 20,
        "bridge_address": "0x" + "22" * 20,
        "status": status,
        "amount_usdc": "2.000000",
        "resource": "clink://polymarket/funding",
        "action_id": "action_1",
        "policy_decision_id": "policy_1",
        "audit_event_id": "audit_1",
        "reservation_id": "reservation_1",
        "core_tx_hash": "0x" + "12" * 32,
        "core_state": "finalized" if finalized else "payment_submitted",
        "bridge_status": "COMPLETED" if finalized else None,
        "venue_buying_power_before_atomic": "0",
        "venue_buying_power_after_atomic": "2000000" if finalized else None,
        "failure_reason_code": None,
        "confirmed_at": "2026-08-19T00:00:00Z",
        "finalized_at": "2026-08-19T00:01:00Z" if finalized else None,
        "created_at": "2026-08-19T00:00:00Z",
        "updated_at": "2026-08-19T00:01:00Z",
        "revision": 7,
        "next_action": "complete" if finalized else "check_core_status",
    }


def test_direct_funding_accepts_every_canonical_status_action_pair() -> None:
    for status in server.FUNDING_OPERATION_STATUSES:
        payload = _operation_payload(status=status)
        payload["next_action"] = server.funding_operation_next_action(status)

        validated = server._validated_direct_funding_operation(
            payload,
            expected_user_id="user-a",
            expected_amount_usdc="2.000000",
            expected_resource="clink://polymarket/funding",
        )

        assert validated["status"] == status
        assert validated["next_action"] == server.funding_operation_next_action(
            status
        )


def test_direct_funding_rejects_noncanonical_status_action_pair() -> None:
    payload = _operation_payload(status="submitted")
    payload["next_action"] = server.funding_operation_next_action("finalized")

    with pytest.raises(RuntimeError, match="funding response is invalid"):
        server._validated_direct_funding_operation(
            payload,
            expected_user_id="user-a",
            expected_amount_usdc="2.000000",
            expected_resource="clink://polymarket/funding",
        )


def test_direct_funding_binds_opc_installation_across_create_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        if path == "/funding/spending-reservations/reservation_1":
            assert payload is None
            return _finalized_core_reservation()
        assert payload is not None
        calls.append((path, payload))
        status = "created" if path.endswith("funding-operations") else "finalized"
        return _direct_operation_payload(
            status=status,
            opc_installation_id=OPC_INSTALLATION_ID,
        )

    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2",
        confirmation_id="confirmation-1",
        user_confirmed=True,
        opc_installation_id=OPC_INSTALLATION_ID,
    )

    assert result["status"] == "settled"
    assert calls[0][1]["opc_installation_id"] == OPC_INSTALLATION_ID
    assert calls[1][1]["opc_installation_id"] == OPC_INSTALLATION_ID


def test_direct_funding_rejects_cross_installation_adapter_response() -> None:
    with pytest.raises(RuntimeError, match="funding response is invalid"):
        server._validated_direct_funding_operation(
            _operation_payload(
                opc_installation_id="opc_" + "b" * 40,
            ),
            expected_user_id="user-a",
            expected_amount_usdc="2.000000",
            expected_resource="clink://polymarket/funding",
            expected_opc_installation_id=OPC_INSTALLATION_ID,
        )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
        ledger_db_file=str(tmp_path / "ledger.sqlite3"),
        funding_adapter_host="127.0.0.1",
        funding_adapter_port=18046,
        prediction_markets_internal_api_token="prediction-internal-test-token",
    )


def _install_ready_user_requests(
    monkeypatch: pytest.MonkeyPatch,
    *,
    binding: dict,
    core_overrides: dict | None = None,
    readiness_overrides: dict | None = None,
) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []
    core_readiness = {
        "user_id": "user-a",
        "wallet_bound": True,
        "wallet_address": OWNER_WALLET,
        "spending_grant_active": True,
        "ready": True,
        "active_spending_mandate": {"spending_grant_id": "grant-1"},
        **(core_overrides or {}),
    }
    deposit_readiness = {
        "service": "prediction_markets_deposit_wallet_service",
        "user_id": "user-a",
        "owner_wallet": OWNER_WALLET,
        "ready": True,
        "can_use_x402": True,
        "status": "deployed",
        "deposit_wallet": DEPOSIT_WALLET,
        "next_action": "fund_polymarket_deposit_wallet",
        **(readiness_overrides or {}),
    }

    class CoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            assert user_id == "user-a"
            return dict(core_readiness)

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append(("POST" if payload is not None else "GET", path, payload))
        if path == "/polymarket/bindings/latest/user-a":
            return binding
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return dict(deposit_readiness)
        if path == "/execution/readiness":
            return {"live_ready": True, "next_action": "execute"}
        if path == "/funding/readiness":
            return {"status": "ready", "settlement_rail": "native"}
        if path.startswith("/funding/status?"):
            return {"spending_authorizations": []}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())
    monkeypatch.setattr(server, "_request_json", fake_request)
    return calls


def _install_binding_link_requests(
    monkeypatch: pytest.MonkeyPatch,
    *,
    core_overrides: dict | None = None,
    readiness_overrides: dict | None = None,
    latest_binding: dict | None = None,
) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []
    core_readiness = {
        "user_id": "user-a",
        "wallet_bound": True,
        "wallet_address": OWNER_WALLET,
        "spending_grant_active": True,
        "ready": True,
        **(core_overrides or {}),
    }
    readiness = {
        "service": "prediction_markets_deposit_wallet_service",
        "user_id": "user-a",
        "owner_wallet": OWNER_WALLET,
        "deposit_wallet": DEPOSIT_WALLET,
        "status": "deployed",
        "ready": True,
        "can_use_x402": True,
        "next_action": "fund_polymarket_deposit_wallet",
        **(readiness_overrides or {}),
    }

    class CoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            assert user_id == "user-a"
            return dict(core_readiness)

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append(("POST" if payload is not None else "GET", path, payload))
        if path == "/polymarket/bindings/latest/user-a":
            return latest_binding or {
                "binding_id": "stale-binding-1",
                "user_id": "user-a",
                "wallet_address": OWNER_WALLET,
                "status": "active",
            }
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return readiness
        if path == "/internal/polymarket/binding-sessions":
            assert payload is not None
            return {
                "session_id": "binding-session-1",
                "user_id": payload["user_id"],
                "agent_id": payload["agent_id"],
                "polymarket_deposit_wallet": payload["polymarket_deposit_wallet"],
                "message_to_sign": "Sign Polymarket authorization",
                "signing_url": "https://node.test/polymarket/binding-console/session",
                "status": "pending_signature",
                "next_action": "open_polymarket_binding_url",
                "expires_at": "2026-08-23T12:30:00Z",
                "created_at": "2026-08-23T12:00:00Z",
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())
    monkeypatch.setattr(server, "_request_json", fake_request)
    return calls


def test_mcp_funding_operation_summary_strips_internal_provenance() -> None:
    operation = _operation_payload(status="settlement_unknown")
    operation["reason"] = "settlement is still being verified"

    assert server._public_funding_operation_summary(operation) == {
        "operation_id": "pm_funding_1",
        "status": "settlement_unknown",
        "reason": "settlement is still being verified",
        "next_action": "fund_polymarket_from_spending_authorization",
    }


def test_mcp_order_signing_mutations_return_only_public_session_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []
    full_session = {
        "session_id": "pm_sign_sess_public_1",
        "preview_id": "preview-private",
        "user_id": "user-private",
        "binding_id": "binding-private",
        "projection_hash": "ab" * 32,
        "revision": 1,
        "agent_id": "agent-private",
        "market_id": "market-private",
        "title": "private market title",
        "outcome": "Yes",
        "side": "buy",
        "amount_usd": "1.00",
        "limit_price": 0.2,
        "order_type": "GTC",
        "token_id": "token-private",
        "order_payload": {
            "typed_data": {"private": "typed-order"},
            "provenance": {"funding_proof": "must-not-leak"},
        },
        "signing_url": (
            "https://clink.invalid/sign#access_token=browser-secret"
        ),
        "capability": "browser-capability-secret",
        "access_token": "browser-access-token-secret",
        "status": "pending_browser_signature",
        "reason": None,
        "next_action": "open_polymarket_order_signing_url",
        "signed_order": {"signature": "must-not-leak"},
        "execution_id": None,
        "core_action_id": "core-action-private",
        "core_policy_decision_id": "policy-private",
        "core_audit_event_ids": ["audit-private"],
        "reservation_id": "reservation-private",
        "audit_event_id": "audit-private",
        "core_tx_hash": "0x" + "12" * 32,
        "created_at": "2026-08-20T00:00:00Z",
        "expires_at": "2026-08-20T00:10:00Z",
        "completed_at": None,
        "metadata": {"funding_proof": {"secret": "must-not-leak"}},
        "event_log": [{"core_tx_hash": "must-not-leak"}],
    }

    def fake_request(_base_url: str, path: str, payload: dict) -> dict:
        calls.append((path, payload))
        if path.endswith("/complete"):
            return {
                **full_session,
                "status": "submitted",
                "reason": "order accepted",
                "next_action": "monitor_order_status",
                "execution_id": "execution-private",
            }
        return dict(full_session)

    monkeypatch.setattr(server, "_request_json", fake_request)

    created = server.create_polymarket_order_signing_session(
        "preview-private",
        user_confirmed=True,
        live_submission_confirmed=True,
    )
    completed = server.complete_polymarket_order_signing_session(
        "pm_sign_sess_public_1",
        {"order": {"signature": "browser-signature"}},
        order_type="GTC",
    )
    created_payload = (
        created.model_dump() if hasattr(created, "model_dump") else created
    )
    completed_payload = (
        completed.model_dump() if hasattr(completed, "model_dump") else completed
    )

    assert created_payload == {
        "session_id": "pm_sign_sess_public_1",
        "status": "pending_browser_signature",
        "reason": None,
        "next_action": "open_polymarket_order_signing",
    }
    assert completed_payload == {
        "session_id": "pm_sign_sess_public_1",
        "status": "submitted",
        "reason": "order accepted",
        "next_action": "monitor_order_status",
        "execution_id": "execution-private",
    }
    assert [path for path, _payload in calls] == [
        "/execution/polymarket/order-signing-sessions",
        (
            "/execution/polymarket/order-signing-sessions/"
            "pm_sign_sess_public_1/complete"
        ),
    ]


def test_mcp_blocked_order_signing_create_preserves_safe_next_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_session = {
        "session_id": "pm_sign_sess_blocked_1",
        "preview_id": "preview-blocked",
        "status": "blocked",
        "reason": "funding authorization is not ready",
        "next_action": "restore_funding_authorization",
        "signing_url": "https://clink.invalid/must-not-leak",
        "metadata": {"funding_proof": "must-not-leak"},
        "created_at": "2026-08-20T00:00:00Z",
    }
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda _base_url, _path, _payload: blocked_session,
    )

    result = server.create_polymarket_order_signing_session(
        "preview-blocked",
        user_confirmed=True,
        live_submission_confirmed=True,
    )

    assert result == {
        "session_id": "pm_sign_sess_blocked_1",
        "status": "blocked",
        "reason": "funding authorization is not ready",
        "next_action": "restore_funding_authorization",
    }


def test_prepare_without_amount_returns_actionable_ui_link_and_does_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "CONFIG",
        AppConfig(account_binding_console_base_url="https://node.test"),
    )
    monkeypatch.setattr(server, "_request_json", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert server.prepare_polymarket_funding_ui() == {
        "suggested_amount_usdc": None,
        "next_action": "open_polymarket_funding_operation",
        "funding_url": "https://node.test/miniapp/#funding",
        "action_label": "Open Polymarket funding",
    }
    assert calls == []


@pytest.mark.parametrize(
    ("raw", "normalized", "action_label"),
    [
        ("1", "1.000000", "Fund 1 USDC"),
        ("2", "2.000000", "Fund 2 USDC"),
        (" 0.5 ", "0.500000", "Fund 0.5 USDC"),
        ("1.234567", "1.234567", "Fund 1.234567 USDC"),
    ],
)
def test_prepare_normalizes_exact_usdc_amount_and_returns_actionable_link(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    normalized: str,
    action_label: str,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "CONFIG",
        AppConfig(account_binding_console_base_url="https://node.test"),
    )
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert server.prepare_polymarket_funding_ui(raw) == {
        "suggested_amount_usdc": normalized,
        "next_action": "open_polymarket_funding_operation",
        "funding_url": f"https://node.test/miniapp/#funding={normalized}",
        "action_label": action_label,
    }
    assert calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        pytest.param("http://node.test", id="http-non-loopback"),
        pytest.param("http://127.0.0.1:8047", id="http-loopback"),
        pytest.param("https://127.0.0.1", id="https-ipv4-loopback"),
        pytest.param("https://[::1]", id="https-ipv6-loopback"),
        pytest.param("https://localhost", id="https-localhost"),
        pytest.param("https://LOCALHOST", id="https-localhost-uppercase"),
        pytest.param("https://localhost.", id="https-localhost-trailing-dot"),
        pytest.param("https://wallet.localhost", id="https-localhost-subdomain"),
        pytest.param(
            "https://[::ffff:127.0.0.1]",
            id="https-ipv4-mapped-loopback",
        ),
        pytest.param("https://2130706433", id="browser-decimal-ipv4"),
        pytest.param("https://127.1", id="browser-short-ipv4"),
        pytest.param("https://0x7f000001", id="browser-hex-ipv4"),
        pytest.param("https://0177.0.0.1", id="browser-octal-ipv4"),
        pytest.param("https://0x7f.0.0.1", id="browser-mixed-ipv4"),
        pytest.param("https://example.123", id="numeric-final-label"),
        pytest.param("https://foo.0x10", id="hex-final-label"),
        pytest.param("https://a.01", id="octal-final-label"),
        pytest.param("https://node.999", id="invalid-numeric-final-label"),
        pytest.param("https://x.127.0.0.1", id="numeric-address-suffix"),
        pytest.param("https://0.0.0.0", id="unspecified-ipv4"),
        pytest.param("https://10.0.0.1", id="private-ipv4"),
        pytest.param("https://169.254.1.1", id="link-local-ipv4"),
        pytest.param("https://[::]", id="unspecified-ipv6"),
        pytest.param("https://[fc00::1]", id="private-ipv6"),
        pytest.param(
            "https://[2001:4860:4860::8888%25eth0]",
            id="encoded-ipv6-zone-id",
        ),
        pytest.param(
            "https://[2001:4860:4860::8888%eth0]",
            id="raw-ipv6-zone-id",
        ),
        pytest.param("https://[v1.foo]", id="ipvfuture-authority"),
        pytest.param("https://[vF.a-b]", id="pseudo-ipv6-authority"),
        pytest.param(
            "https://[::ffff:10.0.0.1]",
            id="ipv4-mapped-private",
        ),
        pytest.param("https://user:pass@node.test", id="credentials"),
        pytest.param("https://node.test/base", id="non-root-path"),
        pytest.param("https://node.test/?debug=1", id="query"),
        pytest.param("https://node.test/#debug", id="fragment"),
        pytest.param("https://node.test:8443", id="non-default-port"),
        pytest.param("https://node test", id="malformed-host"),
    ],
)
def test_prepare_fails_closed_for_unsafe_funding_ui_origin_without_io(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "CONFIG",
        AppConfig(account_binding_console_base_url=base_url),
    )
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        RuntimeError,
        match="^Polymarket funding UI URL is unavailable$",
    ):
        server.prepare_polymarket_funding_ui("1")

    assert calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        pytest.param("https://1.2.example.com", id="numeric-prefix"),
        pytest.param("https://example.1a", id="alphanumeric-final-label"),
    ],
)
def test_prepare_accepts_clean_dns_origin_without_io(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "CONFIG",
        AppConfig(account_binding_console_base_url=base_url),
    )
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = server.prepare_polymarket_funding_ui("1")

    assert result["funding_url"] == f"{base_url}/miniapp/#funding=1.000000"
    assert calls == []


@pytest.mark.parametrize(
    ("base_url", "expected_host"),
    [
        pytest.param("https://8.8.8.8", "8.8.8.8", id="ipv4"),
        pytest.param(
            "https://[2001:4860:4860::8888]",
            "[2001:4860:4860::8888]",
            id="ipv6",
        ),
    ],
)
def test_prepare_accepts_globally_routable_ip_literal_without_io(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    expected_host: str,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "CONFIG",
        AppConfig(account_binding_console_base_url=base_url),
    )
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = server.prepare_polymarket_funding_ui("1")

    assert result["funding_url"] == (
        f"https://{expected_host}/miniapp/#funding=1.000000"
    )
    assert calls == []


@pytest.mark.parametrize("raw", ["", "0", "-1", "1.0000001"])
def test_prepare_rejects_invalid_usdc_amount(raw: str) -> None:
    with pytest.raises(ValueError, match="suggested_amount_usdc is invalid"):
        server.prepare_polymarket_funding_ui(raw)


def test_prepare_signature_accepts_no_identity_or_funding_authority() -> None:
    signature = inspect.signature(server.prepare_polymarket_funding_ui)
    assert list(signature.parameters) == ["suggested_amount_usdc"]
    assert signature.parameters["suggested_amount_usdc"].default is None


def test_public_tool_surface_exposes_direct_funding_without_prepare_ui() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(server.MCP_SERVER.list_tools())
    }

    assert "prepare_polymarket_funding_ui" not in tools
    direct_funding = tools["fund_polymarket_from_spending_authorization"]
    assert (
        "Call fund_polymarket_from_spending_authorization again with the "
        "identical confirmation_id and user_confirmed=True without asking the "
        "user again."
        in direct_funding.description
    )
    assert "show account_url as the single Clink spending-account action" in (
        direct_funding.description
    )
    assert "do not ask for another confirmation or create a new id" in (
        direct_funding.description
    )
    assert direct_funding.inputSchema["required"] == [
        "user_id",
        "amount_usdc",
        "confirmation_id",
    ]
    properties = direct_funding.inputSchema["properties"]
    assert properties["confirmation_id"]["type"] == "string"
    assert properties["user_confirmed"] == {
        "default": False,
        "title": "User Confirmed",
        "type": "boolean",
    }


def test_direct_funding_description_accepts_clear_natural_language_confirmation() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(server.MCP_SERVER.list_tools())
    }
    description = tools[
        "fund_polymarket_from_spending_authorization"
    ].description.lower()

    assert "natural-language confirmation" in description
    assert "exact amount" in description
    assert "execution intent" in description
    assert "fixed phrase" in description


def _direct_operation_payload(
    *,
    status: str,
    operation_id: str = "pm_funding_1",
    user_id: str = "user-a",
    amount_usdc: str = "2.000000",
    resource: str = "clink://polymarket/funding",
    opc_installation_id: str | None = None,
) -> dict:
    operation = _operation_payload()
    operation.update(
        {
            "operation_id": operation_id,
            "user_id": user_id,
            "status": status,
            "amount_usdc": amount_usdc,
            "resource": resource,
            "opc_installation_id": opc_installation_id,
            "next_action": {
                "created": "confirm",
                "settlement_unknown": "check_core_status",
                "bridge_pending": "check_bridge_status",
                "finalized": "complete",
                "failed": "terminal",
                "released": "terminal",
            }[status],
        }
    )
    if status == "created":
        operation.update(
            {
                "action_id": None,
                "policy_decision_id": None,
                "audit_event_id": None,
                "reservation_id": None,
                "core_tx_hash": None,
                "core_state": None,
                "bridge_status": None,
                "venue_buying_power_after_atomic": None,
                "confirmed_at": None,
                "finalized_at": None,
                "revision": 0,
            }
        )
    elif status in {"settlement_unknown", "bridge_pending"}:
        operation["finalized_at"] = None
    return operation


def test_failed_direct_funding_projection_preserves_failure_diagnostics() -> None:
    operation = _direct_operation_payload(status="failed")
    operation.update(
        {
            "failure_reason_code": "BUDGET_AUTHORIZATION_BLOCKED",
            "core_state": None,
            "bridge_status": None,
        }
    )

    projection = server._direct_funding_projection(operation)

    assert projection["failure_reason_code"] == "BUDGET_AUTHORIZATION_BLOCKED"
    assert "core_state" in projection
    assert "bridge_status" in projection
    assert projection["core_state"] is None
    assert projection["bridge_status"] is None


@pytest.mark.parametrize(
    ("status", "failure_reason_code", "core_state", "bridge_status"),
    [
        pytest.param(
            "failed",
            "POLYMARKET_BRIDGE_FAILED",
            "settled",
            "FAILED",
            id="failed",
        ),
        pytest.param(
            "released",
            "CORE_TRANSFER_REJECTED",
            "released",
            None,
            id="released",
        ),
    ],
)
def test_terminal_direct_funding_returns_safe_diagnostics_through_public_tool(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    failure_reason_code: str,
    core_state: str,
    bridge_status: str | None,
) -> None:
    terminal = _direct_operation_payload(status=status)
    terminal.update(
        failure_reason_code=failure_reason_code,
        core_state=core_state,
        bridge_status=bridge_status,
    )

    def fake_request(
        _base_url: str,
        path: str,
        _payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="created")
        if path == "/polymarket/funding-operations/pm_funding_1/confirm":
            return terminal
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2",
        confirmation_id="confirmation-1",
        user_confirmed=True,
    )

    assert result["status"] == status
    assert result["failure_reason_code"] == failure_reason_code
    assert result["core_state"] == core_state
    assert result["bridge_status"] == bridge_status


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        pytest.param("core_state", "secret_state", id="core-state"),
        pytest.param("bridge_status", "SECRET_INTERNAL_ERROR", id="bridge-status"),
    ],
)
def test_direct_funding_rejects_unbounded_terminal_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    invalid_value: str,
) -> None:
    terminal = _direct_operation_payload(status="failed")
    terminal.update(
        failure_reason_code="BUDGET_AUTHORIZATION_BLOCKED",
        core_state="spending_reserved",
        bridge_status=None,
    )
    terminal[field_name] = invalid_value

    def fake_request(
        _base_url: str,
        path: str,
        _payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="created")
        if path == "/polymarket/funding-operations/pm_funding_1/confirm":
            return terminal
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    with pytest.raises(
        RuntimeError,
        match="^Polymarket funding response is invalid$",
    ):
        server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=True,
        )


def _finalized_core_reservation(**overrides: object) -> dict:
    return {
        "reservation_id": "reservation_1",
        "purchase_id": "pm_funding_1",
        "user_id": "user-a",
        "amount_usdc": "2.000000",
        "resource": "clink://polymarket/funding",
        "state": "finalized",
        "receipt_id": "fund_receipt_reservation_1",
        "tx_hash": "0x" + "12" * 32,
        **overrides,
    }


def test_direct_funding_requires_explicit_confirmation_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        RuntimeError,
        match="^explicit user confirmation is required$",
    ):
        server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=False,
        )

    assert calls == []


def test_confirmed_direct_funding_uses_coordinator_and_core_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(
        base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append((base_url, path, payload))
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="created")
        if path == "/polymarket/funding-operations/pm_funding_1/confirm":
            return _direct_operation_payload(status="finalized")
        if path == "/funding/spending-reservations/reservation_1":
            return _finalized_core_reservation()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2",
        confirmation_id="confirmation-1",
        user_confirmed=True,
        metadata={
            "wallet": "0x" + "44" * 20,
            "destination": "0x" + "55" * 20,
            "operation_id": "caller-operation",
            "tx_hash": "0x" + "99" * 32,
            "receipt_id": "caller-receipt",
        },
    )

    assert result == {
        "status": "settled",
        "operation_id": "pm_funding_1",
        "receipt_id": "fund_receipt_reservation_1",
        "tx_hash": "0x" + "12" * 32,
        "amount_usdc": "2.000000",
        "signing_url": None,
        "next_action": "complete",
    }
    assert calls == [
        (
            server.CONFIG.funding_adapter_url,
            "/polymarket/funding-operations",
            {
                "user_id": "user-a",
                "amount_usdc": "2.000000",
                "idempotency_key": "confirmation-1",
                "resource": "clink://polymarket/funding",
            },
        ),
        (
            server.CONFIG.funding_adapter_url,
            "/polymarket/funding-operations/pm_funding_1/confirm",
            {"user_id": "user-a", "confirmed": True},
        ),
        (
            server.CONFIG.clink_core_funding_service_url,
            "/funding/spending-reservations/reservation_1",
            None,
        ),
    ]


def test_replayed_finalized_funding_accepts_equivalent_core_amount_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        _base_url: str,
        path: str,
        _payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="created")
        if path == "/polymarket/funding-operations/pm_funding_1/confirm":
            return _direct_operation_payload(status="finalized")
        if path == "/funding/spending-reservations/reservation_1":
            return _finalized_core_reservation(amount_usdc="2")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2",
        confirmation_id="confirmation-1",
        user_confirmed=True,
    )

    assert result == {
        "status": "settled",
        "operation_id": "pm_funding_1",
        "receipt_id": "fund_receipt_reservation_1",
        "tx_hash": "0x" + "12" * 32,
        "amount_usdc": "2.000000",
        "signing_url": None,
        "next_action": "complete",
    }


def test_replayed_finalized_funding_rejects_different_core_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        _base_url: str,
        path: str,
        _payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="created")
        if path == "/polymarket/funding-operations/pm_funding_1/confirm":
            return _direct_operation_payload(status="finalized")
        if path == "/funding/spending-reservations/reservation_1":
            return _finalized_core_reservation(amount_usdc="2.000001")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    with pytest.raises(
        RuntimeError,
        match="^Polymarket funding response is invalid$",
    ):
        server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=True,
        )


def test_replayed_confirmation_advances_only_the_same_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append((path, payload))
        if path == "/polymarket/funding-operations":
            return _direct_operation_payload(status="settlement_unknown")
        if path == "/polymarket/funding-operations/pm_funding_1/advance":
            return _direct_operation_payload(status="bridge_pending")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2.000000",
        confirmation_id="confirmation-1",
        user_confirmed=True,
    )

    assert result == {
        "status": "bridge_pending",
        "operation_id": "pm_funding_1",
        "receipt_id": None,
        "tx_hash": "0x" + "12" * 32,
        "amount_usdc": "2.000000",
        "failure_reason_code": None,
        "core_state": "finalized",
        "bridge_status": "COMPLETED",
        "venue_buying_power_before_atomic": "0",
        "venue_buying_power_after_atomic": "2000000",
        "signing_url": None,
        "next_action": "fund_polymarket_from_spending_authorization",
    }
    assert calls == [
        (
            "/polymarket/funding-operations",
            {
                "user_id": "user-a",
                "amount_usdc": "2.000000",
                "idempotency_key": "confirmation-1",
                "resource": "clink://polymarket/funding",
            },
        ),
        (
            "/polymarket/funding-operations/pm_funding_1/advance",
            {"user_id": "user-a"},
        ),
    ]


def test_missing_core_authorization_returns_one_account_action_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    funding_calls: list[tuple[str, dict | None]] = []

    def blocked_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        funding_calls.append((path, payload))
        raise server._PredictionMarketsRequestError(
            409,
            '{"detail":"Core authorization is not ready"}',
        )

    class CoreAccount:
        @staticmethod
        def create_setup_link(user_id: str) -> dict:
            assert user_id == "user-a"
            return {
                "account_url": "https://www.agentonomy.xyz/account/session/setup-1",
                "expires_at": "2026-08-24T12:00:00Z",
            }

    monkeypatch.setattr(server, "_request_json", blocked_request)
    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())

    result = server.fund_polymarket_from_spending_authorization(
        user_id="user-a",
        amount_usdc="2",
        confirmation_id="confirmation-1",
        user_confirmed=True,
    )

    assert result == {
        "status": "action_required",
        "operation_id": None,
        "receipt_id": None,
        "tx_hash": None,
        "amount_usdc": "2.000000",
        "confirmation_id": "confirmation-1",
        "account_url": "https://www.agentonomy.xyz/account/session/setup-1",
        "action_label": "Open Clink spending account",
        "expires_at": "2026-08-24T12:00:00Z",
        "next_action": "open_core_account_url",
        "resume_action": "fund_polymarket_from_spending_authorization",
        "requires_new_confirmation": False,
    }
    assert funding_calls == [
        (
            "/polymarket/funding-operations",
            {
                "user_id": "user-a",
                "amount_usdc": "2.000000",
                "idempotency_key": "confirmation-1",
                "resource": "clink://polymarket/funding",
            },
        )
    ]


def test_unrelated_funding_failure_does_not_create_account_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_calls: list[str] = []

    def failed_request(*_args, **_kwargs) -> dict:
        raise server._PredictionMarketsRequestError(
            503,
            '{"detail":"Bridge service is temporarily unavailable"}',
        )

    class CoreAccount:
        @staticmethod
        def create_setup_link(user_id: str) -> dict:
            setup_calls.append(user_id)
            return {"account_url": "https://www.agentonomy.xyz/account/session/wrong"}

    monkeypatch.setattr(server, "_request_json", failed_request)
    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())

    with pytest.raises(
        RuntimeError,
        match="Bridge service is temporarily unavailable",
    ):
        server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=True,
        )

    assert setup_calls == []


@pytest.mark.parametrize(
    ("create_result", "mutation_result", "reservation_result"),
    [
        pytest.param(
            _direct_operation_payload(status="created", user_id="user-b"),
            None,
            None,
            id="create-subject-conflict",
        ),
        pytest.param(
            _direct_operation_payload(status="created"),
            _direct_operation_payload(
                status="finalized",
                operation_id="pm_funding_other",
            ),
            None,
            id="confirm-operation-conflict",
        ),
        pytest.param(
            _direct_operation_payload(status="created"),
            _direct_operation_payload(status="finalized"),
            _finalized_core_reservation(receipt_id=None),
            id="missing-authoritative-receipt",
        ),
        pytest.param(
            _direct_operation_payload(status="created"),
            _direct_operation_payload(status="finalized"),
            _finalized_core_reservation(tx_hash="0x" + "34" * 32),
            id="reservation-transaction-conflict",
        ),
    ],
)
def test_direct_funding_fails_closed_for_conflicting_responses(
    monkeypatch: pytest.MonkeyPatch,
    create_result: dict,
    mutation_result: dict | None,
    reservation_result: dict | None,
) -> None:
    calls: list[str] = []

    def fake_request(
        _base_url: str,
        path: str,
        _payload: dict | None = None,
    ) -> dict:
        calls.append(path)
        if path == "/polymarket/funding-operations":
            return create_result
        if path.endswith("/confirm") and mutation_result is not None:
            return mutation_result
        if path.startswith("/funding/spending-reservations/") and (
            reservation_result is not None
        ):
            return reservation_result
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    with pytest.raises(
        RuntimeError,
        match="^Polymarket funding response is invalid$",
    ):
        server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=True,
        )

    assert all("pm_funding_other" not in path for path in calls)


def test_execution_funding_readiness_fails_closed_without_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("missing operation must not perform HTTP"),
    )

    result = HttpFundingGateway(_config(tmp_path)).get_funding_readiness(
        "user-a",
        "polymarket",
        "1.000000",
    )

    assert result == {
        "ready": False,
        "status": "funding_operation_required",
        "reason": "an explicit Polymarket funding operation is required",
        "next_action": "fund_polymarket_from_spending_authorization",
    }


@pytest.mark.parametrize(
    ("operation", "binding_id", "venue_wallet_address"),
    [
        pytest.param(
            _operation_payload(status="settlement_unknown"),
            "binding-a",
            "0x" + "11" * 20,
            id="pending-operation",
        ),
        pytest.param(
            None,
            None,
            "0x" + "11" * 20,
            id="invalid-account-scope",
        ),
    ],
)
def test_execution_funding_readiness_routes_unready_proof_to_direct_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: dict | None,
    binding_id: str | None,
    venue_wallet_address: str,
) -> None:
    requests: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        requests.append(request)
        assert timeout == 5
        assert operation is not None
        return _JsonResponse(operation)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HttpFundingGateway(_config(tmp_path)).get_funding_readiness(
        "user-a",
        "polymarket",
        "1.000000",
        funding_operation_id="pm_funding_1",
        binding_id=binding_id,
        venue_wallet_address=venue_wallet_address,
    )

    assert result["ready"] is False
    assert result["next_action"] == (
        "fund_polymarket_from_spending_authorization"
    )
    assert result.get("funding_proof") is None
    assert len(requests) == (1 if operation is not None else 0)


def test_execution_funding_readiness_reads_only_the_scoped_finalized_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        requests.append(request)
        assert timeout == 5
        return _JsonResponse(_operation_payload())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HttpFundingGateway(_config(tmp_path)).get_funding_readiness(
        "user-a",
        "polymarket",
        "1.000000",
        funding_operation_id="pm_funding_1",
        binding_id="binding-a",
        venue_wallet_address="0x" + "11" * 20,
    )

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["funding_operation_id"] == "pm_funding_1"
    assert result["operation_status"] == "finalized"
    assert result["chain_status"] == "finalized"
    assert result["bridge_status"] == "COMPLETED"
    assert result["buying_power_status"] == "verified"
    assert len(requests) == 1
    assert requests[0].full_url == (
        "http://127.0.0.1:18046/polymarket/funding-operations/pm_funding_1"
        "?user_id=user-a"
    )
    assert requests[0].get_header("Authorization") == (
        "Bearer prediction-internal-test-token"
    )
    assert "latest-bridge-status" not in requests[0].full_url


def test_portfolio_funding_status_fails_closed_without_operation_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("missing scope must not perform HTTP"),
    )
    config = _config(tmp_path)

    snapshot = PortfolioService(
        config=config,
        ledger=TradingLedger(config.ledger_db_file),
    ).build_snapshot()

    assert snapshot.funding.status == "unavailable"
    assert snapshot.funding.error == "funding operation scope is required"


def test_portfolio_funding_status_uses_the_requested_operation_scope(
    tmp_path: Path,
) -> None:
    scopes: list[tuple[str, str]] = []

    def fetch(user_id: str, operation_id: str) -> dict:
        scopes.append((user_id, operation_id))
        return _operation_payload()

    config = _config(tmp_path)
    snapshot = PortfolioService(
        config=config,
        ledger=TradingLedger(config.ledger_db_file),
        funding_status_fetcher=fetch,
    ).build_snapshot(
        user_id="user-a",
        funding_operation_id="pm_funding_1",
    )

    assert scopes == [("user-a", "pm_funding_1")]
    assert snapshot.funding.status == "finalized"
    assert snapshot.funding.bridge_status == "COMPLETED"
    assert snapshot.funding.latest_receipt_tx_hash == "0x" + "12" * 32
    assert snapshot.funding.settled_amount_usdc_by_venue == {
        "polymarket": "2.000000"
    }


def test_user_readiness_keeps_ambiguous_operation_pending_and_status_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class CoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            assert user_id == "user-a"
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": "0x" + "22" * 20,
                "spending_grant_active": True,
                "ready": True,
                "active_spending_mandate": {"spending_grant_id": "grant-1"},
            }

    def fake_request(_base_url: str, path: str, _payload: dict | None = None) -> dict:
        calls.append(path)
        if path == "/polymarket/bindings/latest/user-a":
            return {
                "binding_id": "binding-1",
                "user_id": "user-a",
                "wallet_address": "0x" + "22" * 20,
                "polymarket_deposit_wallet": "0x" + "11" * 20,
                "funder_address": "0x" + "11" * 20,
                "account_mode": "deposit_wallet",
                "polymarket_signature_type": "3",
                "has_api_credentials": True,
                "status": "active",
            }
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return {
                "user_id": "user-a",
                "owner_wallet": "0x" + "22" * 20,
                "ready": True,
                "can_use_x402": True,
                "status": "deployed",
                "deposit_wallet": "0x" + "11" * 20,
            }
        if path == "/execution/readiness":
            return {"live_ready": True, "next_action": "execute"}
        if path == "/funding/readiness":
            return {"status": "ready", "settlement_rail": "native"}
        if path.startswith("/funding/status?"):
            return {"spending_authorizations": []}
        if path == "/polymarket/funding-operations/pm_funding_1?user_id=user-a":
            return _operation_payload(status="settlement_unknown")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())
    monkeypatch.setattr(server, "_request_json", fake_request)

    result = server.get_prediction_market_user_readiness(
        "user-a",
        funding_operation_id="pm_funding_1",
    )

    assert result["status"] == "funding_pending"
    assert result["funding_operation_ready"] is False
    assert result["trading_ready"] is False
    assert result["next_action"] == "fund_polymarket_from_spending_authorization"
    assert result["funding_operation"]["operation_id"] == "pm_funding_1"
    assert result["funding_operation"]["next_action"] == (
        "fund_polymarket_from_spending_authorization"
    )
    assert result["funding_route"]["next_action"] == (
        "fund_polymarket_from_spending_authorization"
    )
    assert all("latest-bridge-status" not in path for path in calls)
    assert all("/spend" not in path for path in calls)


def test_user_readiness_routes_eoa_with_ready_deposit_wallet_to_type3_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": OWNER_WALLET,
        "polymarket_deposit_wallet": None,
        "account_mode": "eoa",
        "polymarket_signature_type": "0",
        "has_api_credentials": True,
        "status": "active",
    }
    calls = _install_ready_user_requests(monkeypatch, binding=binding)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "polymarket_account_required"
    assert result["next_action"] == "create_polymarket_account_binding_link"
    assert result["deposit_wallet_ready"] is True
    assert result.get("deposit_binding_join_ready") is False
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False
    assert all(method != "POST" for method, _path, _payload in calls)


def test_user_readiness_allows_type3_binding_to_reach_funding_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
    }
    _install_ready_user_requests(monkeypatch, binding=binding)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "funding_operation_required"
    assert result["next_action"] == "fund_polymarket_from_spending_authorization"
    assert result["deposit_wallet_ready"] is True
    assert result["deposit_binding_join_ready"] is True
    assert result["funding_target_ready"] is True


def test_user_readiness_prepares_deposit_wallet_before_first_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_ready_user_requests(
        monkeypatch,
        binding={
            "status": "unavailable",
            "next_action": "create_polymarket_account_binding",
        },
        readiness_overrides={
            "status": "not_prepared",
            "ready": False,
            "can_use_x402": False,
            "deposit_wallet": None,
            "next_action": "prepare_polymarket_deposit_wallet",
        },
    )

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "funding_not_ready"
    assert result["next_action"] == "prepare_polymarket_deposit_wallet"
    assert result["deposit_wallet_ready"] is False
    assert result.get("deposit_binding_join_ready") is False
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False
    assert result["funding_route"]["status"] == "blocked"
    assert result["funding_route"]["can_use_x402"] is False
    assert result["funding_route"]["next_action"] == (
        "prepare_polymarket_deposit_wallet"
    )
    assert any(
        path.startswith("/polymarket/deposit-wallet/readiness?")
        for _method, path, _payload in calls
    )
    assert all(
        not path.startswith(("/execution/", "/funding/"))
        and "/polymarket/funding-operations/" not in path
        for _method, path, _payload in calls
    )
    assert all(method != "POST" for method, _path, _payload in calls)


def test_advertised_deposit_preparation_uses_core_owner_without_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    class CoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            assert user_id == "user-a"
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": OWNER_WALLET,
                "spending_grant_active": True,
                "ready": True,
            }

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append(("POST" if payload is not None else "GET", path, payload))
        if path == "/polymarket/bindings/latest/user-a":
            return {
                "status": "unavailable",
                "next_action": "create_polymarket_account_binding",
            }
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return {
                "service": "prediction_markets_deposit_wallet_service",
                "user_id": "user-a",
                "owner_wallet": OWNER_WALLET,
                "deposit_wallet": None,
                "status": "not_prepared",
                "ready": False,
                "can_use_x402": False,
                "next_action": "prepare_polymarket_deposit_wallet",
            }
        if path == "/polymarket/deposit-wallet/prepare":
            return {
                "user_id": "user-a",
                "owner_wallet": OWNER_WALLET.lower(),
                "deposit_wallet": DEPOSIT_WALLET,
                "status": "deployed",
                "reason": None,
                "next_action": "fund_polymarket_deposit_wallet",
                "can_use_x402": True,
                "created_at": "2026-08-23T00:00:00Z",
                "updated_at": "2026-08-23T00:00:00Z",
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", CoreAccount())
    monkeypatch.setattr(server, "_request_json", fake_request)

    readiness = server.get_prediction_market_user_readiness("user-a")
    assert readiness["next_action"] == "prepare_polymarket_deposit_wallet"

    preparation = server.prepare_polymarket_deposit_wallet("user-a")

    prepare_payload = next(
        payload
        for method, path, payload in calls
        if method == "POST"
        and path == "/polymarket/deposit-wallet/prepare"
        and payload is not None
    )
    assert prepare_payload["user_id"] == "user-a"
    assert prepare_payload["owner_wallet"] == OWNER_WALLET.lower()
    assert preparation["state"]["owner_wallet"] == OWNER_WALLET.lower()
    assert preparation["next_action"] == "create_polymarket_account_binding_link"
    assert preparation["funding_route"]["next_action"] == (
        "create_polymarket_account_binding_link"
    )


@pytest.mark.parametrize(
    ("readiness_overrides", "expected_action"),
    [
        pytest.param(
            {"user_id": "other-user", "next_action": "arbitrary_action"},
            "prepare_polymarket_deposit_wallet",
            id="wrong-subject",
        ),
        pytest.param(
            {"owner_wallet": OTHER_OWNER_WALLET, "next_action": "arbitrary_action"},
            "prepare_polymarket_deposit_wallet",
            id="wrong-owner",
        ),
        pytest.param(
            {"deposit_wallet": "not-an-address", "next_action": "arbitrary_action"},
            "prepare_polymarket_deposit_wallet",
            id="malformed-deposit",
        ),
        pytest.param(
            {"deposit_wallet": "0x" + "0" * 40, "next_action": "arbitrary_action"},
            "prepare_polymarket_deposit_wallet",
            id="zero-deposit",
        ),
        pytest.param(
            {"ready": False, "next_action": "fund_polymarket_deposit_wallet"},
            "prepare_polymarket_deposit_wallet",
            id="not-ready-cannot-fund",
        ),
        pytest.param(
            {
                "status": "unavailable",
                "ready": False,
                "can_use_x402": False,
                "deposit_wallet": None,
                "next_action": "arbitrary_action",
            },
            "start_prediction_markets_deposit_wallet_service",
            id="unavailable-service",
        ),
    ],
)
def test_user_readiness_rejects_untrusted_deposit_recovery_action(
    monkeypatch: pytest.MonkeyPatch,
    readiness_overrides: dict,
    expected_action: str,
) -> None:
    calls = _install_ready_user_requests(
        monkeypatch,
        binding={
            "status": "unavailable",
            "next_action": "create_polymarket_account_binding",
        },
        readiness_overrides=readiness_overrides,
    )

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "funding_not_ready"
    assert result["next_action"] == expected_action
    assert result["funding_route"]["next_action"] == expected_action
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False
    assert all(method != "POST" for method, _path, _payload in calls)


@pytest.mark.parametrize(
    ("account_mode", "signature_type", "deposit_wallet", "funder_address"),
    [
        pytest.param("eoa", "0", None, OWNER_WALLET, id="eoa-type0"),
        pytest.param(
            "proxy_or_safe",
            "2",
            DEPOSIT_WALLET,
            DEPOSIT_WALLET,
            id="proxy-type2",
        ),
        pytest.param(
            "unknown",
            "3",
            DEPOSIT_WALLET,
            DEPOSIT_WALLET,
            id="unknown-mode",
        ),
        pytest.param(
            "deposit_wallet",
            "0",
            DEPOSIT_WALLET,
            DEPOSIT_WALLET,
            id="deposit-type0",
        ),
    ],
)
def test_user_readiness_prepares_deposit_wallet_before_rebinding_non_type3(
    monkeypatch: pytest.MonkeyPatch,
    account_mode: str,
    signature_type: str,
    deposit_wallet: str | None,
    funder_address: str,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": funder_address,
        "polymarket_deposit_wallet": deposit_wallet,
        "account_mode": account_mode,
        "polymarket_signature_type": signature_type,
        "has_api_credentials": True,
        "status": "active",
    }
    calls = _install_ready_user_requests(
        monkeypatch,
        binding=binding,
        readiness_overrides={
            "status": "not_prepared",
            "ready": False,
            "can_use_x402": False,
            "deposit_wallet": None,
            "next_action": "prepare_polymarket_deposit_wallet",
        },
    )

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "funding_not_ready"
    assert result["next_action"] == "prepare_polymarket_deposit_wallet"
    assert result["deposit_wallet_ready"] is False
    assert result.get("deposit_binding_join_ready") is False
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False
    assert result["funding_route"]["status"] == "blocked"
    assert result["funding_route"]["can_use_x402"] is False
    assert result["funding_route"]["next_action"] == (
        "prepare_polymarket_deposit_wallet"
    )
    assert all(
        not path.startswith(("/execution/", "/funding/"))
        and "/polymarket/funding-operations/" not in path
        for _method, path, _payload in calls
    )
    assert all(method != "POST" for method, _path, _payload in calls)


def test_user_readiness_rebinds_exact_type3_when_deposit_join_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
    }
    calls = _install_ready_user_requests(
        monkeypatch,
        binding=binding,
        readiness_overrides={"deposit_wallet": OTHER_OWNER_WALLET},
    )

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "polymarket_account_required"
    assert result["next_action"] == "create_polymarket_account_binding_link"
    assert result["deposit_wallet_ready"] is True
    assert result.get("deposit_binding_join_ready") is False
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False
    assert result["funding_route"]["status"] == "blocked"
    assert result["funding_route"]["can_use_x402"] is False
    assert result["funding_route"]["next_action"] == (
        "create_polymarket_account_binding_link"
    )
    assert all(
        not path.startswith(("/execution/", "/funding/"))
        and "/polymarket/funding-operations/" not in path
        for _method, path, _payload in calls
    )
    assert all(method != "POST" for method, _path, _payload in calls)


def test_binding_link_succeeds_without_prior_polymarket_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_binding_link_requests(
        monkeypatch,
        latest_binding={
            "status": "unavailable",
            "next_action": "create_polymarket_account_binding",
        },
    )

    session = server.create_polymarket_account_binding_link("user-a")

    post_payload = next(
        payload
        for method, _path, payload in calls
        if method == "POST" and payload is not None
    )
    assert session.signing_url == "https://node.test/polymarket/binding-console/session"
    assert post_payload["wallet_address"] == OWNER_WALLET.lower()
    assert post_payload["polymarket_deposit_wallet"] == DEPOSIT_WALLET.lower()
    assert any(
        path.endswith(f"user_id=user-a&owner_wallet={OWNER_WALLET.lower()}")
        for method, path, _payload in calls
        if method == "GET"
    )
    assert all(
        path != "/polymarket/bindings/latest/user-a"
        for _method, path, _payload in calls
    )
    assert "wallet_address" not in inspect.signature(
        server.create_polymarket_account_binding_link
    ).parameters


def test_binding_link_ignores_stale_binding_and_uses_current_core_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_binding_link_requests(
        monkeypatch,
        latest_binding={
            "binding_id": "stale-binding",
            "user_id": "other-user",
            "wallet_address": OTHER_OWNER_WALLET,
            "funder_address": MIXED_CASE_OWNER_WALLET,
            "status": "active",
        },
    )

    session = server.create_polymarket_account_binding_link("user-a")

    post_payload = next(
        payload
        for method, _path, payload in calls
        if method == "POST" and payload is not None
    )
    assert session.polymarket_deposit_wallet == DEPOSIT_WALLET.lower()
    assert post_payload["wallet_address"] == OWNER_WALLET.lower()
    assert all(
        path != "/polymarket/bindings/latest/user-a"
        for _method, path, _payload in calls
    )


@pytest.mark.parametrize(
    "readiness",
    [
        {"ready": False, "can_use_x402": False, "deposit_wallet": None},
        {"ready": True, "can_use_x402": True, "deposit_wallet": "not-an-address"},
        {"ready": True, "can_use_x402": True, "deposit_wallet": "0x" + "0" * 40},
        {"ready": "true", "can_use_x402": True, "deposit_wallet": DEPOSIT_WALLET},
        {"ready": True, "can_use_x402": "true", "deposit_wallet": DEPOSIT_WALLET},
    ],
)
def test_binding_link_fails_closed_without_valid_ready_deposit_wallet(
    monkeypatch: pytest.MonkeyPatch,
    readiness: dict,
) -> None:
    calls = _install_binding_link_requests(
        monkeypatch,
        readiness_overrides={
            "status": "blocked",
            "next_action": "prepare_polymarket_deposit_wallet",
            **readiness,
        },
    )

    with pytest.raises(RuntimeError) as exc_info:
        server.create_polymarket_account_binding_link("user-a")

    assert str(exc_info.value) == TYPE3_BINDING_ERROR
    assert all(method != "POST" for method, _path, _payload in calls)


def test_binding_link_submits_core_wallet_for_post_boundary_race_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    import services.account_binding_service.app as account_binding_app
    from services.account_binding_service.service import (
        PolymarketAccountBindingService,
    )

    account_config = AppConfig(
        account_binding_file=str(tmp_path / "bindings.jsonl"),
        credential_store_file=str(tmp_path / "credentials.jsonl"),
        account_binding_console_base_url="https://node.test/polymarket",
        clink_core_internal_api_token="test-internal-token",
    )
    account_service = PolymarketAccountBindingService(account_config)

    class InitialCoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": OWNER_WALLET,
                "spending_grant_active": True,
                "ready": True,
            }

    class ChangedCoreAccount:
        @staticmethod
        def readiness(user_id: str) -> dict:
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": OTHER_OWNER_WALLET,
                "spending_grant_active": True,
                "ready": True,
            }

    monkeypatch.setattr(account_binding_app, "CONFIG", account_config)
    monkeypatch.setattr(account_binding_app, "SERVICE", account_service)
    monkeypatch.setattr(
        account_binding_app,
        "CORE_ACCOUNT_CLIENT",
        ChangedCoreAccount(),
    )
    monkeypatch.setattr(server, "CORE_ACCOUNT_CLIENT", InitialCoreAccount())

    boundary_responses = []
    client = TestClient(account_binding_app.APP)

    def fake_request(
        _base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/bindings/latest/user-a":
            return {
                "binding_id": "stale-binding",
                "user_id": "user-a",
                "wallet_address": OWNER_WALLET,
                "status": "active",
            }
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return {
                "service": "prediction_markets_deposit_wallet_service",
                "user_id": "user-a",
                "owner_wallet": OWNER_WALLET,
                "deposit_wallet": DEPOSIT_WALLET,
                "status": "deployed",
                "ready": True,
                "can_use_x402": True,
                "next_action": "fund_polymarket_deposit_wallet",
            }
        if path == "/internal/polymarket/binding-sessions":
            response = client.post(
                path,
                headers={"Authorization": "Bearer test-internal-token"},
                json=payload,
            )
            boundary_responses.append(response)
            if response.status_code >= 400:
                raise RuntimeError("binding service rejected request")
            return response.json()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(server, "_request_json", fake_request)

    with pytest.raises(RuntimeError, match="binding service rejected request"):
        server.create_polymarket_account_binding_link("user-a")

    assert boundary_responses[0].status_code == 409
    assert boundary_responses[0].json()["detail"] == (
        "Selected wallet does not match the active Core wallet"
    )
    assert account_service._load_latest("session") == {}


@pytest.mark.parametrize(
    ("account_mode", "signature_type"),
    [
        pytest.param("proxy_or_safe", "2", id="proxy-type2"),
        pytest.param("unknown", "3", id="unknown-mode"),
        pytest.param("deposit_wallet", "0", id="deposit-type0"),
    ],
)
def test_user_readiness_requires_type3_binding_for_every_other_account_mode(
    monkeypatch: pytest.MonkeyPatch,
    account_mode: str,
    signature_type: str,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": account_mode,
        "polymarket_signature_type": signature_type,
        "has_api_credentials": True,
        "status": "active",
    }
    _install_ready_user_requests(monkeypatch, binding=binding)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["status"] == "polymarket_account_required"
    assert result["next_action"] == "create_polymarket_account_binding_link"
    assert result["funding_target_ready"] is False
    assert result["trading_ready"] is False


@pytest.mark.parametrize(
    "core_overrides",
    [
        pytest.param({"user_id": "other-user"}, id="user-mismatch"),
        pytest.param({"user_id": None}, id="user-missing"),
        pytest.param({"wallet_bound": False}, id="wallet-unbound"),
        pytest.param({"wallet_bound": "true"}, id="wallet-bound-not-bool"),
        pytest.param({"wallet_address": None}, id="wallet-missing"),
        pytest.param({"wallet_address": "not-an-address"}, id="wallet-malformed"),
        pytest.param({"wallet_address": "0x" + "0" * 40}, id="wallet-zero"),
    ],
)
def test_binding_link_fails_closed_on_invalid_current_core_readiness(
    monkeypatch: pytest.MonkeyPatch,
    core_overrides: dict,
) -> None:
    calls = _install_binding_link_requests(
        monkeypatch,
        core_overrides=core_overrides,
    )

    with pytest.raises(RuntimeError) as exc_info:
        server.create_polymarket_account_binding_link("user-a")

    assert str(exc_info.value) == TYPE3_BINDING_ERROR
    assert all(method != "POST" for method, _path, _payload in calls)


@pytest.mark.parametrize(
    "readiness_overrides",
    [
        pytest.param({"user_id": "other-user"}, id="user-mismatch"),
        pytest.param({"owner_wallet": OTHER_OWNER_WALLET}, id="owner-mismatch"),
        pytest.param({"owner_wallet": None}, id="owner-missing"),
        pytest.param({"owner_wallet": "not-an-address"}, id="owner-malformed"),
        pytest.param({"owner_wallet": "0x" + "0" * 40}, id="owner-zero"),
    ],
)
def test_binding_link_fails_closed_on_deposit_subject_or_owner_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    readiness_overrides: dict,
) -> None:
    calls = _install_binding_link_requests(
        monkeypatch,
        readiness_overrides=readiness_overrides,
    )

    with pytest.raises(RuntimeError) as exc_info:
        server.create_polymarket_account_binding_link("user-a")

    assert str(exc_info.value) == TYPE3_BINDING_ERROR
    assert all(method != "POST" for method, _path, _payload in calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("wallet_address", None, id="wallet-missing"),
        pytest.param("wallet_address", "not-an-address", id="wallet-nonhex"),
        pytest.param("wallet_address", "0x" + "0" * 40, id="wallet-zero"),
        pytest.param("polymarket_deposit_wallet", None, id="deposit-missing"),
        pytest.param(
            "polymarket_deposit_wallet",
            "0x" + "g" * 40,
            id="deposit-nonhex",
        ),
        pytest.param(
            "polymarket_deposit_wallet",
            "0x" + "0" * 40,
            id="deposit-zero",
        ),
        pytest.param("funder_address", None, id="funder-missing"),
        pytest.param("funder_address", "not-an-address", id="funder-nonhex"),
        pytest.param("funder_address", "0x" + "0" * 40, id="funder-zero"),
        pytest.param(
            "funder_address",
            OTHER_OWNER_WALLET,
            id="funder-deposit-mismatch",
        ),
    ],
)
def test_funding_route_rejects_incomplete_or_inconsistent_type3_binding(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str | None,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
        field: value,
    }
    monkeypatch.setattr(
        server,
        "_deposit_wallet_readiness_for_binding",
        lambda _binding: {
            "user_id": "user-a",
            "owner_wallet": OWNER_WALLET,
            "deposit_wallet": DEPOSIT_WALLET,
            "status": "deployed",
            "ready": True,
            "can_use_x402": True,
        },
    )

    route = server._resolve_polymarket_funding_target_from_binding(binding)

    assert route["status"] == "blocked"
    assert route["can_use_x402"] is False
    assert route["target_address"] is None
    assert route["next_action"] == "create_polymarket_account_binding_link"


@pytest.mark.parametrize(
    (
        "core_overrides",
        "binding_overrides",
        "readiness_overrides",
        "authoritative_deposit_ready",
    ),
    [
        pytest.param(
            {"user_id": "other-user"},
            {},
            {},
            False,
            id="core-user-mismatch",
        ),
        pytest.param(
            {"wallet_address": OTHER_OWNER_WALLET},
            {},
            {"owner_wallet": OTHER_OWNER_WALLET},
            True,
            id="binding-core-owner-mismatch",
        ),
        pytest.param(
            {},
            {"user_id": "other-user"},
            {},
            True,
            id="binding-user-mismatch",
        ),
        pytest.param(
            {},
            {},
            {"user_id": "other-user"},
            False,
            id="deposit-user-mismatch",
        ),
        pytest.param(
            {},
            {},
            {"owner_wallet": OTHER_OWNER_WALLET},
            False,
            id="deposit-owner-mismatch",
        ),
        pytest.param(
            {},
            {},
            {"deposit_wallet": OTHER_OWNER_WALLET},
            True,
            id="deposit-address-mismatch",
        ),
        pytest.param(
            {},
            {},
            {"ready": False},
            False,
            id="deposit-not-ready",
        ),
        pytest.param(
            {},
            {},
            {"can_use_x402": False},
            False,
            id="deposit-cannot-use-x402",
        ),
    ],
)
def test_user_readiness_cross_checks_core_binding_and_deposit_identity(
    monkeypatch: pytest.MonkeyPatch,
    core_overrides: dict,
    binding_overrides: dict,
    readiness_overrides: dict,
    authoritative_deposit_ready: bool,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
        **binding_overrides,
    }
    calls = _install_ready_user_requests(
        monkeypatch,
        binding=binding,
        core_overrides=core_overrides,
        readiness_overrides=readiness_overrides,
    )

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["deposit_wallet_ready"] is authoritative_deposit_ready
    assert result.get("deposit_binding_join_ready") is False
    assert result["funding_target_ready"] is False
    assert result["x402_funding_ready"] is False
    assert result["trading_ready"] is False
    assert result["status"] != "funding_operation_required"
    assert all(method != "POST" for method, _path, _payload in calls)


def test_user_readiness_sanitizes_binding_service_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_ready_user_requests(
        monkeypatch,
        binding={"status": "unavailable"},
    )
    base_request = server._request_json

    def raising_binding_request(
        base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        if path == "/polymarket/bindings/latest/user-a":
            raise RuntimeError(
                "private binding HTTP 502 body from RuntimeError"
            )
        return base_request(base_url, path, payload)

    monkeypatch.setattr(server, "_request_json", raising_binding_request)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result["binding"]["reason"] == (
        "Polymarket account binding is unavailable"
    )
    assert result["status"] == "polymarket_account_required"
    assert result["next_action"] == "create_polymarket_account_binding_link"
    assert result["deposit_wallet_ready"] is True
    assert result.get("deposit_binding_join_ready") is False
    serialized = json.dumps(result)
    assert "private binding HTTP 502 body" not in serialized
    assert "RuntimeError" not in serialized
    assert all(
        not path.startswith(("/execution/", "/funding/"))
        for _method, path, _payload in calls
    )


@pytest.mark.parametrize(
    ("failing_path", "result_field", "fixed_reason"),
    [
        pytest.param(
            "/execution/readiness",
            "execution_readiness",
            "execution service unavailable",
            id="execution-readiness",
        ),
        pytest.param(
            "/funding/readiness",
            "funding_readiness",
            "funding service unavailable",
            id="funding-readiness",
        ),
        pytest.param(
            "/funding/status?",
            "funding_status",
            "funding status unavailable",
            id="funding-status",
        ),
    ],
)
def test_user_readiness_sanitizes_downstream_readiness_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    failing_path: str,
    result_field: str,
    fixed_reason: str,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
    }
    _install_ready_user_requests(monkeypatch, binding=binding)
    base_request = server._request_json

    def raising_readiness_request(
        base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        if path.startswith(failing_path):
            raise RuntimeError(
                "private downstream HTTP 502 body from RuntimeError"
            )
        return base_request(base_url, path, payload)

    monkeypatch.setattr(server, "_request_json", raising_readiness_request)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result[result_field]["reason"] == fixed_reason
    serialized = json.dumps(result)
    assert "private downstream HTTP 502 body" not in serialized
    assert "RuntimeError" not in serialized


@pytest.mark.parametrize(
    ("malformed_path", "result_field", "fixed_reason"),
    [
        pytest.param(
            "/execution/readiness",
            "execution_readiness",
            "execution service unavailable",
            id="execution-readiness",
        ),
        pytest.param(
            "/funding/readiness",
            "funding_readiness",
            "funding service unavailable",
            id="funding-readiness",
        ),
        pytest.param(
            "/funding/status?",
            "funding_status",
            "funding status unavailable",
            id="funding-status",
        ),
    ],
)
def test_user_readiness_sanitizes_malformed_downstream_success_payloads(
    monkeypatch: pytest.MonkeyPatch,
    malformed_path: str,
    result_field: str,
    fixed_reason: str,
) -> None:
    binding = {
        "binding_id": "binding-1",
        "user_id": "user-a",
        "wallet_address": OWNER_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "status": "active",
    }
    _install_ready_user_requests(monkeypatch, binding=binding)
    base_request = server._request_json

    def malformed_readiness_request(
        base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        if path.startswith(malformed_path):
            return ["private downstream payload type"]  # type: ignore[return-value]
        return base_request(base_url, path, payload)

    monkeypatch.setattr(server, "_request_json", malformed_readiness_request)

    result = server.get_prediction_market_user_readiness("user-a")

    assert result[result_field]["reason"] == fixed_reason
    serialized = json.dumps(result)
    assert "private downstream payload type" not in serialized
    assert "list" not in serialized


def test_deposit_wallet_readiness_sanitizes_service_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private upstream response body")
        ),
    )

    readiness = server._deposit_wallet_readiness_for_binding(
        {"user_id": "user-a", "wallet_address": OWNER_WALLET}
    )

    assert readiness["reason"] == "deposit wallet service unavailable"
    serialized = json.dumps(readiness)
    assert "private upstream response body" not in serialized
    assert "RuntimeError" not in serialized


def test_deposit_wallet_readiness_sanitizes_malformed_service_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *_args, **_kwargs: ["private upstream response body"],
    )

    readiness = server._deposit_wallet_readiness_for_binding(
        {"user_id": "user-a", "wallet_address": OWNER_WALLET}
    )

    assert readiness["reason"] == "deposit wallet service unavailable"
    assert "private upstream response body" not in json.dumps(readiness)


def test_deposit_wallet_readiness_never_uses_funder_as_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        server,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    readiness = server._deposit_wallet_readiness_for_binding(
        {
            "user_id": "user-a",
            "wallet_address": None,
            "funder_address": OWNER_WALLET,
        }
    )

    assert readiness["status"] == "blocked"
    assert readiness["can_use_x402"] is False
    assert calls == []
