from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.schemas import PreparePolymarketDepositWalletRequest
from services.deposit_wallet_service.service import PolymarketDepositWalletService
from shared.config import AppConfig


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "sdk-missing.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_builder_api_key="builder_key",
            polymarket_builder_secret="builder_secret",
            polymarket_builder_passphrase="builder_passphrase",
            polymarket_deposit_wallet_address=None,
        )
        service = PolymarketDepositWalletService(config=config)

        with patch("importlib.util.find_spec", return_value=None):
            readiness = service.check_readiness(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
            )
            assert readiness.status == "sdk_missing"
            assert readiness.ready is False
            assert readiness.can_use_x402 is False
            assert readiness.next_action == "install_builder_relayer_sdk"
            assert "py-builder-relayer-client" in readiness.missing

            prepared = service.prepare_deposit_wallet(
                PreparePolymarketDepositWalletRequest(
                    user_id="telegram_demo_user",
                    owner_wallet="0x1111111111111111111111111111111111111111",
                    mode="derive",
                )
            )
            assert prepared.status == "blocked"
            assert prepared.next_action == "install_builder_relayer_sdk"
            assert prepared.can_use_x402 is False

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
