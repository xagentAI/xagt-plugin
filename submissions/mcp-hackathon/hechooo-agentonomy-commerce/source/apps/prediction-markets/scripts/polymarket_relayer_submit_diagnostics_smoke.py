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
    status_code = 403
    text = "error code: 1010\n"
    headers = {
        "cf-ray": "test-ray-SIN",
        "server": "cloudflare",
        "content-type": "text/plain",
    }

    def json(self):
        raise ValueError("not json")


def main() -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["timeout"] = timeout
        captured["url"] = url
        captured["headers"] = {key.lower(): value for key, value in headers.items()}
        captured["body"] = json
        return FakeResponse()

    config = AppConfig(
        polymarket_relayer_url="https://relayer-v2.polymarket.com",
        polymarket_relayer_api_key="secret_relayer_key",
        polymarket_relayer_api_key_address="0x1111111111111111111111111111111111111111",
        polymarket_builder_api_key="",
        polymarket_builder_secret="",
        polymarket_builder_passphrase="",
    )
    client = HttpBuilderRelayerClient(config)

    with patch("requests.post", fake_post):
        try:
            client.deploy_deposit_wallet("0x2222222222222222222222222222222222222222")
        except RuntimeError as exc:
            detail = getattr(exc, "diagnostics", {})
        else:
            raise AssertionError("expected relayer 403 to raise RuntimeError")

    assert detail["http_status"] == 403
    assert detail["response_body"] == "error code: 1010\n"
    assert detail["response_headers"] == {
        "cf-ray": "test-ray-SIN",
        "server": "cloudflare",
        "content-type": "text/plain",
    }
    assert detail["request"]["endpoint"] == "https://relayer-v2.polymarket.com/submit"
    assert detail["request"]["method"] == "POST"
    assert detail["request"]["credential_mode"] == "relayer_api_key"
    assert detail["request"]["headers"]["relayer_api_key"] == "<redacted>"
    assert detail["request"]["headers"]["relayer_api_key_address"] == "0x1111111111111111111111111111111111111111"
    assert detail["request"]["body_shape"] == {
        "type": "WALLET-CREATE",
        "from": "0x2222222222222222222222222222222222222222",
        "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
    }
    assert "secret_relayer_key" not in json.dumps(detail)

    print(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
