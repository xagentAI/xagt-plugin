from __future__ import annotations

import json
import inspect
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import mcp_servers.prediction_markets_server as server


OWNER_WALLET = "0x1111111111111111111111111111111111111111"
READY_DEPOSIT_WALLET = "0x2222222222222222222222222222222222222222"


class FakeCoreAccountClient:
    def __init__(self) -> None:
        self.wallet_bound = False

    def readiness(self, user_id: str) -> dict:
        if self.wallet_bound:
            return {
                "user_id": user_id,
                "wallet_bound": True,
                "wallet_address": OWNER_WALLET,
                "spending_grant_active": True,
                "ready": True,
            }
        return {
            "user_id": user_id,
            "wallet_bound": False,
            "spending_grant_active": False,
            "chain_allowances": {"eip155:137": False, "eip155:8453": False},
            "ready": False,
        }

    def create_setup_link(self, user_id: str) -> dict:
        assert user_id == "telegram_demo_user"
        return {
            "session_id": "account_session_123",
            "account_url": "https://account.example/account/token-123",
            "expires_at": "2026-07-17T12:00:00Z",
        }


def main() -> None:
    assert "wallet_address" not in inspect.signature(server.create_polymarket_account_binding_link).parameters
    original_client = server.CORE_ACCOUNT_CLIENT
    original_request_json = server._request_json

    def fake_request_json(base_url: str, path: str, payload=None):
        del base_url, payload
        if path == "/polymarket/bindings/latest/telegram_demo_user":
            return {"status": "unavailable", "next_action": "create_polymarket_account_binding"}
        raise AssertionError(f"unexpected request: {path}")

    def fake_binding_request_json(base_url: str, path: str, payload=None):
        del base_url
        if path.startswith("/polymarket/deposit-wallet/readiness?"):
            return {
                "service": "prediction_markets_deposit_wallet_service",
                "user_id": "telegram_demo_user",
                "owner_wallet": OWNER_WALLET,
                "deposit_wallet": READY_DEPOSIT_WALLET,
                "status": "deployed",
                "ready": True,
                "can_use_x402": True,
                "next_action": "fund_polymarket_deposit_wallet",
            }
        if path == "/internal/polymarket/binding-sessions":
            assert payload["wallet_address"] == OWNER_WALLET
            assert payload["polymarket_deposit_wallet"] == READY_DEPOSIT_WALLET
            return {
                "session_id": "binding_session_123",
                "user_id": payload["user_id"],
                "agent_id": payload["agent_id"],
                "polymarket_deposit_wallet": payload["polymarket_deposit_wallet"],
                "message_to_sign": "Sign Polymarket authorization",
                "signing_url": "https://account.example/polymarket/session-123",
                "status": "pending_signature",
                "next_action": "open_polymarket_binding_url",
                "expires_at": "2026-07-17T12:00:00Z",
                "created_at": "2026-07-17T11:30:00Z",
            }
        raise AssertionError(f"unexpected request: {path}")

    try:
        fake_core_account_client = FakeCoreAccountClient()
        server.CORE_ACCOUNT_CLIENT = fake_core_account_client
        server._request_json = fake_request_json
        link = server.create_core_account_setup_link("telegram_demo_user")
        readiness = server.get_prediction_market_user_readiness("telegram_demo_user")
        fake_core_account_client.wallet_bound = True
        server._request_json = fake_binding_request_json
        binding_session = server.create_polymarket_account_binding_link(
            "telegram_demo_user"
        )
    finally:
        server.CORE_ACCOUNT_CLIENT = original_client
        server._request_json = original_request_json

    assert link == {
        "user_id": "telegram_demo_user",
        "status": "pending_user_action",
        "account_url": "https://account.example/account/token-123",
        "expires_at": "2026-07-17T12:00:00Z",
        "next_action": "open_core_account_url",
    }
    assert readiness["wallet_bound"] is False
    assert readiness["polymarket_bound"] is False
    assert readiness["spending_authorization_ready"] is False
    assert readiness["core_account"]["ready"] is False
    assert readiness["active_spending_mandate"] is None
    assert readiness["spending_budget"] is None
    assert readiness["core_account_management"] == {
        "account_url": None,
        "next_action": "create_core_account_setup_link",
    }
    assert readiness["next_action"] == "create_core_account_setup_link"
    assert binding_session.polymarket_deposit_wallet == READY_DEPOSIT_WALLET
    print(json.dumps({"status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
