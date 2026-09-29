from __future__ import annotations

import tempfile
from pathlib import Path

import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.funding_adapter_service.schemas import (  # noqa: E402
    CreatePolymarketBridgeDepositRequest,
)
from services.funding_adapter_service.service import (  # noqa: E402
    BridgeAdapterError,
    PolymarketFundingAdapterService,
)
from shared.config import AppConfig  # noqa: E402


VENUE_WALLET = "0x1111111111111111111111111111111111111111"
BRIDGE_ADDRESS = "0x2222222222222222222222222222222222222222"
SOURCE_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
DESTINATION_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
TX_HASH = "0x" + "a" * 64


class FakeBridgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def post(self, path: str, payload: dict) -> dict:
        self.calls.append(("POST", path, payload))
        if path != "/deposit":
            raise AssertionError(f"unexpected POST {path}")
        return {
            "address": {
                "evm": BRIDGE_ADDRESS,
                "svm": "6vMbiwQjZ6hYwX8b3PjrNBMzCLcXRrsVo8bVn6m5R7qi",
                "btc": "bc1qexample",
                "tron": "TExample",
            },
            "note": "Send only supported assets.",
        }

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        if path != f"/status/{BRIDGE_ADDRESS}?limit=50":
            raise AssertionError(f"unexpected GET {path}")
        return {
            "transactions": [
                {
                    "fromChainId": "137",
                    "fromTokenAddress": SOURCE_TOKEN,
                    "fromAmountBaseUnit": "1990000",
                    "toChainId": "137",
                    "toTokenAddress": DESTINATION_TOKEN,
                    "status": "COMPLETED",
                    "txHash": TX_HASH,
                    "createdTimeMs": 1787121600000,
                }
            ],
            "nextCursor": None,
        }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AppConfig(
            profile="personal",
            polymarket_bridge_database_path=str(Path(tmpdir) / "bridge.sqlite3"),
        )
        client = FakeBridgeClient()
        service = PolymarketFundingAdapterService(
            config=config,
            bridge_client=client,
        )
        request = CreatePolymarketBridgeDepositRequest(
            user_id="user-1",
            binding_id="pm_binding_1",
            venue_wallet_address=VENUE_WALLET,
        )

        deposit = service.create_deposit_address(request)
        assert deposit.status == "ready"
        assert deposit.bridge_address == BRIDGE_ADDRESS
        assert client.calls == [("POST", "/deposit", {"address": VENUE_WALLET})]

        replay = service.create_deposit_address(request)
        assert replay == deposit
        assert len(client.calls) == 1

        status = service.get_bridge_status(
            user_id="user-1",
            binding_id="pm_binding_1",
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1990000",
            not_before_time_ms=1787121599000,
            expected_bridge_tx_hash=TX_HASH,
        )
        assert status.status == "COMPLETED"
        assert status.tx_hash == TX_HASH
        assert status.amount_atomic == "1990000"
        assert "raw_response" not in status.model_dump()

        try:
            service.get_bridge_status(
                user_id="user-2",
                binding_id="pm_binding_1",
                venue_wallet_address=VENUE_WALLET,
                bridge_address=BRIDGE_ADDRESS,
                expected_amount_atomic="1990000",
                not_before_time_ms=1787121599000,
                expected_bridge_tx_hash=TX_HASH,
            )
        except BridgeAdapterError as exc:
            assert str(exc) == "bridge target is unavailable"
        else:
            raise AssertionError("cross-user bridge status read was accepted")

        print(
            {
                "status": "ok",
                "deposit_id": deposit.deposit_id,
                "bridge_status": status.status,
                "scoped": True,
            }
        )


if __name__ == "__main__":
    main()
