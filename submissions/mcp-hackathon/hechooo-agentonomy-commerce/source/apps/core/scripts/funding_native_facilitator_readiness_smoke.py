from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.funding_service.service import FundingService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


def main() -> None:
    misttrack_api_key = os.getenv("MISTTRACK_API_KEY", "").strip()
    if not misttrack_api_key:
        raise RuntimeError(
            "MISTTRACK_API_KEY must be provided through the process environment"
        )
    missing = FundingService(
        config=AppConfig(
            clink_live_funding=True,
            risk_provider="misttrack",
            risk_mode="enforce",
            misttrack_api_key=misttrack_api_key,
            clink_native_facilitator_enabled=True,
            x402_payment_network="eip155:137",
            x402_payment_token="USDC",
        )
    ).get_funding_readiness()
    assert missing["settlement_rail"] == "clink_native_facilitator"
    assert missing["native_facilitator_enabled"] is True
    assert missing["live_funding_enabled"] is True
    assert missing["native_facilitator_ready"] is False
    assert "CLINK_POLYGON_RPC_URL" in missing["missing"]
    assert "CLINK_BASE_RPC_URL" in missing["missing"]
    assert "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY" in missing["missing"]
    assert missing["next_action"] == "configure_native_facilitator"

    ready = FundingService(
        config=AppConfig(
            clink_live_funding=True,
            risk_provider="misttrack",
            risk_mode="enforce",
            misttrack_api_key=misttrack_api_key,
            clink_native_facilitator_enabled=True,
            polygon_rpc_url="https://polygon-rpc.example",
            base_rpc_url="https://base-rpc.example",
            clink_polygon_usdc_address=(
                "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
            ),
            clink_base_usdc_address=(
                "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
            ),
            clink_receipt_signing_key=(
                "readiness-smoke-only-not-a-production-secret"
            ),
            clink_native_facilitator_relayer_private_key="0x" + "77" * 32,
            x402_payment_network="eip155:137",
            x402_payment_token="USDC",
        )
    ).get_funding_readiness()
    assert ready["settlement_rail"] == "clink_native_facilitator"
    assert ready["native_facilitator_ready"] is True
    assert ready["missing"] == []
    assert ready["relayer_address"].startswith("0x")
    assert ready["next_action"] == "authorize_spending_cap_or_spend"

    print(json.dumps({"status": "ok", "ready": ready}, indent=2))


if __name__ == "__main__":
    main()
