from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from py_builder_relayer_client.builder.derive import derive_beacon_deposit_wallet
from py_builder_relayer_client.config import get_contract_config

from services.deposit_wallet_service.service import HttpBuilderRelayerClient
from shared.config import AppConfig


class FakeRelayClient:
    def __init__(self, *args, **kwargs):
        self.contract_config = get_contract_config(137)

    def _get_deposit_wallet_factory_beacon(self, factory: str) -> str:
        return "0x7A18EDfe055488A3128f01F563e5B479D92ffc3a"

    def _is_contract_deployed(self, address: str) -> bool:
        return False


def main() -> None:
    owner = "0x1111111111111111111111111111111111111111"
    config = AppConfig(
        polymarket_relayer_url="https://relayer-v2.polymarket.com",
        polymarket_builder_api_key="builder_key",
        polymarket_builder_secret="builder_secret",
        polymarket_builder_passphrase="builder_passphrase",
        polymarket_chain_id=137,
    )
    client = HttpBuilderRelayerClient(config)
    contract_config = get_contract_config(137)
    expected = derive_beacon_deposit_wallet(
        owner,
        contract_config.deposit_wallet_factory,
        "0x7A18EDfe055488A3128f01F563e5B479D92ffc3a",
    )

    with patch("py_builder_relayer_client.client.RelayClient", FakeRelayClient):
        response = client.derive_deposit_wallet(owner)

    assert response["deposit_wallet"] == expected
    assert response["owner_wallet"] == owner
    assert response["source"] == "polymarket_builder_relayer_deterministic_derivation"
    assert response["account_mode"] == "deposit_wallet"

    print(json.dumps({"status": "ok", "deposit_wallet": response["deposit_wallet"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
