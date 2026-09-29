import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.decision_service.app import app
from shared.schemas import UnifiedMarket


def _market(platform: str, market_id: str, title: str, yes_price: float, liquidity: float) -> UnifiedMarket:
    return UnifiedMarket(
        platform=platform,
        market_id=market_id,
        title=title,
        yes_price=yes_price,
        no_price=1 - yes_price,
        bid_ask_spread=0.02,
        liquidity_usd=liquidity,
        volume_24h_usd=liquidity / 10,
        status="open",
        rules_summary="Resolves Yes if Kraken completes an IPO before the listed date.",
        tradable=True,
        execution_ready=platform == "polymarket",
    )


def main() -> None:
    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["mode"] == "hermes_context_layer"

    response = client.post(
        "/context/build",
        json={
            "topic": "Kraken IPO",
            "goal": "Give Hermes cross-platform evidence before it decides whether to trade.",
            "markets": [
                _market("polymarket", "pm_kraken_2026", "Kraken IPO by December 31, 2026?", 0.375, 4500).model_dump(),
                _market("kalshi", "kalshi_kraken_2026", "Kraken IPO before 2027?", 0.41, 3300).model_dump(),
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_role"] == "hermes_decides"
    assert payload["clink_role"] == "context_and_execution_infrastructure"
    assert payload["execution_constraints"]["final_decision_owner"] == "Hermes"
    assert payload["execution_constraints"]["does_clink_make_trade_decision"] is False
    assert "recommended_action" not in payload
    assert "recommended_platform" not in payload
    assert "single_platform_preview" in payload["available_routes"]
    assert "hedge_preview" not in payload["available_routes"]
    assert payload["suggested_next_tools"]["single_platform_preview"] == "create_prediction_market_order_preview"

    print(json.dumps({"status": "ok", "routes": payload["available_routes"], "evidence_count": len(payload["evidence"])}, indent=2))


if __name__ == "__main__":
    main()
