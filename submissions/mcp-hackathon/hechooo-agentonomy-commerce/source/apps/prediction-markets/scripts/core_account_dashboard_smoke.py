from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_binding_service import app


class FakeCoreAccountClient:
    def readiness(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "wallet_bound": False,
            "spending_grant_active": False,
            "ready": False,
        }

    def create_setup_link(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "account_url": "https://account.example/account/token-123",
            "expires_at": "2026-07-17T12:00:00Z",
        }


def main() -> None:
    original_client = app.CORE_ACCOUNT_CLIENT
    try:
        app.CORE_ACCOUNT_CLIENT = FakeCoreAccountClient()
        readiness = app.core_account_readiness("telegram_demo_user")
        link = app.create_core_account_setup_link(
            app.CoreAccountSetupRequest(user_id="telegram_demo_user")
        )
    finally:
        app.CORE_ACCOUNT_CLIENT = original_client

    source = (ROOT_DIR / "dashboard_frontend" / "src" / "App.jsx").read_text()
    assert readiness["wallet_bound"] is False
    assert link["account_url"] == "https://account.example/account/token-123"
    assert "/account-api/clink/account/readiness" in source
    assert "/account-api/clink/account/setup-link" in source
    assert "Core Account" in source
    assert "Polymarket Account" in source
    assert "Open Core Account" in source
    print(json.dumps({"status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
