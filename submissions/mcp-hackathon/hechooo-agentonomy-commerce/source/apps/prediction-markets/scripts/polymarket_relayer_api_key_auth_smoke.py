from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.service import HttpBuilderRelayerClient, PolymarketDepositWalletService
from shared.config import AppConfig


class FakeResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    text = '{"transactionID":"relayer_tx_123","state":"STATE_NEW"}'

    def json(self):
        return {"transactionID": "relayer_tx_123", "state": "STATE_NEW"}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            deposit_wallet_state_file=str(Path(tmpdir) / "relayer-key.jsonl"),
            polymarket_relayer_url="https://relayer-v2.polymarket.com",
            polymarket_relayer_api_key="relayer_key",
            polymarket_relayer_api_key_address="0x1111111111111111111111111111111111111111",
            polymarket_builder_api_key="",
            polymarket_builder_secret="",
            polymarket_builder_passphrase="",
        )
        service = PolymarketDepositWalletService(config=config)

        with patch("importlib.util.find_spec") as find_spec:
            find_spec.return_value = object()
            readiness = service.check_readiness(
                user_id="telegram_demo_user",
                owner_wallet="0x1111111111111111111111111111111111111111",
            )

        assert readiness.status == "not_prepared"
        assert readiness.builder_credentials_configured is True
        assert readiness.metadata["credential_mode"] == "relayer_api_key"

        captured = {}

        def fake_post(url, *, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = {key.lower(): value for key, value in headers.items()}
            captured["body"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        client = HttpBuilderRelayerClient(config)
        with patch("requests.post", fake_post):
            deployed = client.deploy_deposit_wallet("0x1111111111111111111111111111111111111111")

        assert deployed["transactionID"] == "relayer_tx_123"
        assert captured["url"] == "https://relayer-v2.polymarket.com/submit"
        assert captured["headers"]["relayer_api_key"] == "relayer_key"
        assert captured["headers"]["relayer_api_key_address"] == "0x1111111111111111111111111111111111111111"

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
