from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.service import HttpBuilderRelayerClient
from shared.config import AppConfig


class FakeResponse:
    status_code = 200
    headers = {
        "server": "cloudflare",
        "content-type": "application/json",
        "cf-ray": "ok-ray-SIN",
    }
    text = '{"transactionID":"relayer_tx_requests","state":"STATE_NEW"}'

    def json(self):
        return {"transactionID": "relayer_tx_requests", "state": "STATE_NEW"}


def main() -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = {key.lower(): value for key, value in headers.items()}
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    config = AppConfig(
        polymarket_relayer_url="https://relayer-v2.polymarket.com/",
        polymarket_relayer_api_key="secret_relayer_key",
        polymarket_relayer_api_key_address="0x1111111111111111111111111111111111111111",
        polymarket_builder_api_key="",
        polymarket_builder_secret="",
        polymarket_builder_passphrase="",
    )
    client = HttpBuilderRelayerClient(config)

    with patch("requests.post", fake_post):
        response = client.deploy_deposit_wallet("0x2222222222222222222222222222222222222222")

    assert response["transactionID"] == "relayer_tx_requests"
    assert captured["url"] == "https://relayer-v2.polymarket.com/submit"
    assert captured["timeout"] == 30
    assert captured["json"] == {
        "type": "WALLET-CREATE",
        "from": "0x2222222222222222222222222222222222222222",
        "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
    }
    assert captured["headers"]["relayer_api_key"] == "secret_relayer_key"
    assert captured["headers"]["relayer_api_key_address"] == "0x1111111111111111111111111111111111111111"
    assert "user-agent" in captured["headers"]
    assert "ClinkPredictionMarkets" in captured["headers"]["user-agent"]

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
