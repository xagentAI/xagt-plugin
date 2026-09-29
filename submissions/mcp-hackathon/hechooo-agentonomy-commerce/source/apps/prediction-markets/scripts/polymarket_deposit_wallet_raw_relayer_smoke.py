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
    headers = {"content-type": "application/json"}
    text = '{"transactionID":"relayer_tx_123","transactionHash":"0xabc","state":"STATE_NEW"}'

    def json(self):
        return {
            "transactionID": "relayer_tx_123",
            "transactionHash": "0xabc",
            "state": "STATE_NEW",
        }


def main() -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["timeout"] = timeout
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return FakeResponse()

    config = AppConfig(
        polymarket_relayer_url="https://relayer-v2.polymarket.com",
        polymarket_builder_api_key="builder_key",
        polymarket_builder_secret="c2VjcmV0X3NlY3JldF9zZWNyZXRfc2VjcmV0XzEyMzQ=",
        polymarket_builder_passphrase="builder_passphrase",
        polymarket_deposit_wallet_factory_address="0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
    )
    client = HttpBuilderRelayerClient(config)

    with patch("requests.post", fake_post):
        response = client.deploy_deposit_wallet("0x1111111111111111111111111111111111111111")

    assert response["transactionID"] == "relayer_tx_123"
    assert captured["url"] == "https://relayer-v2.polymarket.com/submit"
    assert captured["body"] == {
        "type": "WALLET-CREATE",
        "from": "0x1111111111111111111111111111111111111111",
        "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
    }
    normalized_headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert normalized_headers["poly_builder_api_key"] == "builder_key"
    assert normalized_headers["poly_builder_passphrase"] == "builder_passphrase"
    assert normalized_headers["poly_builder_signature"]

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
