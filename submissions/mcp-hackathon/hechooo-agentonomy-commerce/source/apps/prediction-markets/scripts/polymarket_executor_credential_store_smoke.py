import json
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.base import PlatformExecutionResult  # noqa: E402
from platforms.polymarket.executor import PolymarketExecutor  # noqa: E402
from services.account_binding_service.credential_store import CredentialStore, PolymarketApiCredentials  # noqa: E402
from shared.config import AppConfig  # noqa: E402


class CapturingExecutor(PolymarketExecutor):
    def readiness(self, user_id: str | None = None) -> PlatformExecutionResult:
        credentials = self.credential_store.get_polymarket_credentials(user_id) if user_id else None
        if credentials is None:
            return PlatformExecutionResult(
                platform="polymarket",
                ready=False,
                status="missing_configuration",
                missing=["polymarket account binding credentials"],
            )
        return PlatformExecutionResult(
            platform="polymarket",
            ready=True,
            status="ready",
            metadata={"POLYMARKET_CREDENTIAL_SOURCE": "credential_store"},
        )

    def _post_signed_order_with_credentials(self, signed_order, order_type, credentials):
        assert signed_order == {"signature": "0xsigned"}
        assert order_type == "FAK"
        assert credentials.api_key == "pm-key"
        assert credentials.api_secret == "pm-secret"
        assert credentials.api_passphrase == "pm-passphrase"
        return {
            "order_id": self.expected_order_id,
            "tx_hash": "0xtx",
            "status": "matched",
            "raw_response": {
                "status": "matched",
                "orderID": self.expected_order_id,
            },
        }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            polymarket_execution_mode="browser_signed",
            credential_store_file=str(Path(tmpdir) / "credentials.jsonl"),
            credential_encryption_key=Fernet.generate_key().decode("utf-8"),
        )
        store = CredentialStore(config)
        executor = CapturingExecutor(config=config, credential_store=store)
        projection = json.loads(
            (
                ROOT_DIR
                / "tests"
                / "fixtures"
                / "polymarket_clob_v2_official_vectors.json"
            ).read_text(encoding="utf-8")
        )["vector"]["expected_projection"]
        executor.expected_order_id = executor.official_order_id(projection)
        scope = {
            "binding_id": "pm-binding-credential-smoke",
            "owner_address": "0x2222222222222222222222222222222222222222",
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "client_order_id": executor.expected_order_id,
            "order_projection": projection,
        }

        blocked = executor.submit_signed_order(
            {"signature": "0xsigned"},
            "FAK",
            user_id="telegram_demo_user",
            **scope,
        )
        assert blocked.submitted is False
        assert blocked.status == "blocked"
        assert "create_polymarket_account_binding" in (blocked.reason or "")

        store.save_polymarket_credentials(
            user_id="telegram_demo_user",
            wallet_address="0x2222222222222222222222222222222222222222",
            credentials=PolymarketApiCredentials(
                api_key="pm-key",
                api_secret="pm-secret",
                api_passphrase="pm-passphrase",
                signature_type="3",
                funder_address="0x1111111111111111111111111111111111111111",
            ),
        )
        submitted = executor.submit_signed_order(
            {"signature": "0xsigned"},
            "FAK",
            user_id="telegram_demo_user",
            **scope,
        )
        assert submitted.submitted is True
        assert submitted.order_id == executor.expected_order_id
        assert submitted.tx_hash == "0xtx"

        readiness = executor.readiness(user_id="telegram_demo_user")
        assert readiness.ready is True
        assert readiness.metadata["POLYMARKET_CREDENTIAL_SOURCE"] == "credential_store"

        print(json.dumps({"status": "ok", "order_id": submitted.order_id, "source": readiness.metadata["POLYMARKET_CREDENTIAL_SOURCE"]}, indent=2))


if __name__ == "__main__":
    main()
