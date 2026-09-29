from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.schemas import PreparePolymarketDepositWalletRequest
from services.deposit_wallet_service.service import PolymarketDepositWalletService
from shared.config import AppConfig


class FailingRelayerClient:
    def derive_deposit_wallet(self, owner_wallet: str) -> dict:
        raise RuntimeError("RPC error: beacon lookup failed")

    def deploy_deposit_wallet(self, owner_wallet: str) -> dict:
        raise RuntimeError("relayer returned 401: invalid relayer api key")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "errors.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_relayer_api_key="relayer_key",
            polymarket_relayer_api_key_address="0x1111111111111111111111111111111111111111",
        )
        service = PolymarketDepositWalletService(config=config, relayer_client=FailingRelayerClient())

        derived = service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="derive",
            )
        )
        assert derived.status == "failed"
        assert derived.next_action == "inspect_builder_relayer_error"
        assert "beacon lookup failed" in (derived.reason or "")

        deployed = service.prepare_deposit_wallet(
            PreparePolymarketDepositWalletRequest(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
                mode="deploy",
            )
        )
        assert deployed.status == "failed"
        assert deployed.next_action == "inspect_builder_relayer_error"
        assert "invalid relayer api key" in (deployed.reason or "")

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
