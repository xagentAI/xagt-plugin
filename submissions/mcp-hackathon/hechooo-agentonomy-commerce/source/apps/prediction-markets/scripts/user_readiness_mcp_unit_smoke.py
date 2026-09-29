from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import mcp_servers.prediction_markets_server as server


def main() -> None:
    original_request_json = server._request_json
    calls: list[str] = []

    class FakeCoreAccountClient:
        def readiness(self, user_id: str) -> dict:
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": "0x1111111111111111111111111111111111111111",
                "spending_grant_active": True,
                "active_spending_mandate": {
                    "spending_grant_id": "spending_grant_123",
                    "agent_id": "hermes",
                    "limits_usdc": {
                        "per_transaction": "0.1",
                        "rolling_hour": "1",
                        "daily": "5",
                        "total": "25",
                    },
                    "remaining_usdc": {
                        "rolling_hour": "0.8",
                        "daily": "4",
                        "total": "24",
                    },
                    "product_scopes": ["clink_prediction_markets"],
                    "venue_scopes": ["polymarket"],
                    "merchant_scopes": [],
                    "merchant_trust_scopes": ["clink_verified"],
                    "network_scopes": ["eip155:137"],
                    "asset_scopes": ["USDC"],
                    "notification_mode": "silent_under_limits",
                    "expires_at": "2026-08-20T00:00:00Z",
                },
                "chain_allowances": {"eip155:137": True, "eip155:8453": True},
                "ready": True,
            }

    original_core_account_client = server.CORE_ACCOUNT_CLIENT

    def fake_request_json(base_url: str, path: str, payload=None):
        calls.append(path)
        if path == "/polymarket/bindings/latest/telegram_demo_user":
            return {
                "binding_id": "pm_binding_123",
                "user_id": "telegram_demo_user",
                "status": "active",
                "has_api_credentials": True,
                "wallet_address": "0x1111111111111111111111111111111111111111",
                "funder_address": "0x1111111111111111111111111111111111111111",
                "polymarket_deposit_wallet": None,
                "account_mode": "eoa",
                "polymarket_signature_type": "0",
            }
        if path.startswith("/polymarket/deposit-wallet/readiness"):
            return {
                "service": "prediction_markets_deposit_wallet_service",
                "user_id": "telegram_demo_user",
                "owner_wallet": "0x1111111111111111111111111111111111111111",
                "deposit_wallet": "0x2222222222222222222222222222222222222222",
                "status": "deployed",
                "ready": True,
                "can_use_x402": True,
                "missing": [],
                "reason": None,
                "next_action": "fund_polymarket_deposit_wallet",
                "relayer_url_configured": True,
                "builder_credentials_configured": True,
                "state": None,
                "metadata": {},
            }
        if path == "/execution/readiness":
            return {
                "live_ready": True,
                "live_mode_enabled": True,
                "polymarket": {"ready": True},
                "missing": [],
                "warnings": [],
                "next_action": "execute_prediction_market_order_preview",
            }
        if path == "/funding/readiness":
            return {
                "service": "funding_service",
                "status": "ready",
                "settlement_rail": "clink_native_facilitator",
                "live_funding_enabled": True,
                "native_facilitator_enabled": True,
                "native_facilitator_ready": True,
                "relayer_address": "0x3333333333333333333333333333333333333333",
                "network": "eip155:137",
                "token": "USDC",
                "missing": [],
                "warnings": [],
                "next_action": "authorize_spending_cap_or_spend",
            }
        if path.startswith("/funding/status"):
            return {
                "spending_authorizations": [
                    {
                        "spending_authorization_id": "spend_auth_123",
                        "user_id": "telegram_demo_user",
                        "agent_id": "hermes",
                        "wallet_address": "0x1111111111111111111111111111111111111111",
                        "spender_address": "0x3333333333333333333333333333333333333333",
                        "max_amount_usdc": "5",
                        "per_order_limit_usdc": "1",
                        "used_amount_usdc": "0",
                        "remaining_amount_usdc": "5",
                        "venue": "polymarket",
                        "chain": "eip155:137",
                        "token": "USDC",
                        "status": "active",
                    }
                ],
                "available_budget_usdc_by_venue": {"polymarket": "5"},
                "settled_amount_usdc_by_venue": {},
            }
        if path == (
            "/polymarket/funding-operations/pm_funding_123"
            "?user_id=telegram_demo_user"
        ):
            return {
                "operation_id": "pm_funding_123",
                "status": "finalized",
                "amount_usdc": "2.000000",
                "resource": "clink://polymarket/funding",
                "action_id": "action_123",
                "policy_decision_id": "policy_123",
                "audit_event_id": "audit_123",
                "reservation_id": "reservation_123",
                "core_tx_hash": "0x" + "12" * 32,
                "core_state": "finalized",
                "bridge_status": "COMPLETED",
                "failure_reason_code": None,
                "confirmed_at": "2026-08-19T00:00:00Z",
                "finalized_at": "2026-08-19T00:01:00Z",
                "created_at": "2026-08-19T00:00:00Z",
                "updated_at": "2026-08-19T00:01:00Z",
                "revision": 7,
                "next_action": "complete",
            }
        raise AssertionError(f"unexpected request: {base_url} {path}")

    try:
        server.CORE_ACCOUNT_CLIENT = FakeCoreAccountClient()
        server._request_json = fake_request_json
        readiness = server.get_prediction_market_user_readiness(
            "telegram_demo_user",
            funding_operation_id="pm_funding_123",
        )
    finally:
        server.CORE_ACCOUNT_CLIENT = original_core_account_client
        server._request_json = original_request_json

    assert readiness["status"] == "polymarket_account_required"
    assert readiness["wallet_bound"] is True
    assert readiness["polymarket_bound"] is True
    assert readiness["deposit_wallet_ready"] is True
    assert readiness["deposit_binding_join_ready"] is False
    assert readiness["x402_funding_ready"] is False
    assert readiness["funding_target_ready"] is False
    assert readiness["funding_operation_ready"] is False
    assert readiness["trading_ready"] is False
    assert readiness["spending_authorization_ready"] is True
    assert readiness["core_account"]["ready"] is True
    assert readiness["active_spending_mandate"]["spending_grant_id"] == "spending_grant_123"
    assert readiness["spending_budget"] == {
        "limits_usdc": {
            "per_transaction": "0.1",
            "rolling_hour": "1",
            "daily": "5",
            "total": "25",
        },
        "remaining_usdc": {
            "rolling_hour": "0.8",
            "daily": "4",
            "total": "24",
        },
        "notification_mode": "silent_under_limits",
        "expires_at": "2026-08-20T00:00:00Z",
    }
    assert readiness["core_account_management"] == {
        "account_url": None,
        "next_action": "create_core_account_setup_link",
    }
    assert readiness["next_action"] == "create_polymarket_account_binding_link"
    assert readiness["funding_route"]["target_address"] is None
    assert readiness["funding_route"]["reason_code"] == "POLYMARKET_TYPE3_BINDING_REQUIRED"
    assert readiness["funding_route"]["next_action"] == "create_polymarket_account_binding_link"
    assert "legacy_funding_authorization" not in readiness
    assert "funding_readiness" not in readiness
    assert "funding_status" not in readiness
    assert "funding_operation" not in readiness
    assert "execution_readiness" not in readiness
    assert all("latest-bridge-status" not in path for path in calls)
    assert all("/spend" not in path for path in calls)
    assert all(
        not path.startswith(("/execution/", "/funding/"))
        and "/polymarket/funding-operations/" not in path
        for path in calls
    )

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
