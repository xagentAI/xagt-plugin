from __future__ import annotations

import sys
import tempfile
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import services.account_binding_service.app as account_binding_app  # noqa: E402
from services.account_binding_service.console import POLYMARKET_CONSOLE_HTML  # noqa: E402
from services.account_binding_service.service import PolymarketAccountBindingService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


CORE_WALLET = "0x1111111111111111111111111111111111111111"
SESSION_DEPOSIT_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
NORMALIZED_SESSION_DEPOSIT_WALLET = SESSION_DEPOSIT_WALLET.lower()


class InlineScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and not dict(attrs).get("src"):
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._current is not None:
            self.scripts.append("".join(self._current))
            self._current = None


class FakeCoreAccountClient:
    def readiness(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "wallet_bound": True,
            "wallet_address": CORE_WALLET,
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_active": True,
            "ready": True,
        }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        account_binding_app.CONFIG = AppConfig(
            account_binding_file=str(Path(tmpdir) / "bindings.jsonl"),
            credential_store_file=str(Path(tmpdir) / "credentials.jsonl"),
            account_binding_console_base_url="http://127.0.0.1:8047",
            clink_core_internal_api_token="test-internal-token",
        )
        account_binding_app.SERVICE = PolymarketAccountBindingService(account_binding_app.CONFIG)
        account_binding_app.CORE_ACCOUNT_CLIENT = FakeCoreAccountClient()
        client = TestClient(account_binding_app.APP)

        created = client.post(
            "/internal/polymarket/binding-sessions",
            headers={"Authorization": "Bearer test-internal-token"},
            json={
                "user_id": "api-user",
                "agent_id": "hermes",
                "polymarket_deposit_wallet": SESSION_DEPOSIT_WALLET,
            },
        )
        assert created.status_code == 200
        assert (
            created.json()["polymarket_deposit_wallet"]
            == NORMALIZED_SESSION_DEPOSIT_WALLET
        )
        signing_url = urlparse(created.json()["signing_url"])
        page = client.get(f"{signing_url.path}?{signing_url.query}")
        legacy_funding_proxy = client.get("/clink/funding/readiness")

        assert page.status_code == 200
        assert legacy_funding_proxy.status_code == 404
        assert "CLINK / POLYMARKET" in page.text
        assert "Authorize your Polymarket account." in page.text
        assert "Core identity" in page.text
        assert "Core wallet" in page.text
        assert CORE_WALLET in page.text
        assert "Choose wallet" in page.text
        assert "Connect Core wallet" in page.text
        assert "Authorize Polymarket" in page.text
        assert "Managed in Clink Core" in page.text
        assert "Unbind Polymarket account" in page.text
        assert "Type UNBIND" in page.text
        assert "Open Polymarket account setup" in page.text
        assert "Retry account discovery" in page.text
        assert "window.okxwallet?.ethereum" in page.text
        assert "Wallet connection failed:" in page.text
        assert "typeof candidate.request === 'function'" in page.text
        assert "Selected wallet does not match the Core wallet" in page.text
        assert "accountsChanged" in page.text
        assert "resetConnectedWallet" in page.text
        assert "account_binding_active" in page.text
        assert "Unexpected Polymarket authorization state" in page.text
        assert (
            f'const expectedDepositWallet = "{NORMALIZED_SESSION_DEPOSIT_WALLET}";'
            in page.text
        )
        assert (
            "polymarket_deposit_wallet: expectedDepositWallet || null"
            in page.text
        )
        assert (
            'polymarket_signature_type: expectedDepositWallet ? "3" : "auto"'
            in page.text
        )
        assert "__DEPOSIT_WALLET_JS__" not in page.text
        assert "Authorize spending cap" not in page.text
        assert "authorizeSpendingCap" not in page.text
        assert "/clink/funding/readiness" not in page.text
        assert "/clink/funding/spending-authorizations" not in page.text
        assert "Revoke spending cap" not in page.text
        assert "revokeSpendingCap" not in page.text
        assert "capMax" not in page.text
        assert "radial-gradient" not in page.text
        assert "box-shadow" not in page.text
        assert "Connect wallet & bind Polymarket" not in page.text
        assert "Confirm deposit wallet" not in page.text
        assert "Paste your Polymarket deposit wallet" not in page.text
        assert "funding/signing-console" not in page.text
        assert "funding/x402/payment-console" not in page.text
        assert "hermes" not in POLYMARKET_CONSOLE_HTML.lower()
        assert f"api-user / Agentonomy" in page.text
        assert "return to Agentonomy" in page.text

        parser = InlineScriptParser()
        parser.feed(page.text)
        assert parser.scripts
        syntax_check = subprocess.run(
            ["node", "--check"],
            input="\n".join(parser.scripts),
            capture_output=True,
            text=True,
            check=False,
        )
        assert syntax_check.returncode == 0, syntax_check.stderr

        print({"status": "ok"})


if __name__ == "__main__":
    main()
