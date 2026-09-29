import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.decision_service.service import DecisionService
from shared.schemas import PredictionMarketContextRequest, UnifiedMarket


def _market(platform: str, market_id: str, title: str, yes_price: float, liquidity: float | None, spread: float | None, execution_ready: bool) -> UnifiedMarket:
    return UnifiedMarket(
        platform=platform,
        market_id=market_id,
        title=title,
        yes_price=yes_price,
        no_price=1 - yes_price,
        bid_ask_spread=spread,
        liquidity_usd=liquidity,
        volume_24h_usd=liquidity / 10 if liquidity else None,
        status="open",
        rules_summary="Resolves Yes if Kraken completes an IPO before the listed date.",
        tradable=True,
        execution_ready=execution_ready,
    )


def main() -> None:
    service = DecisionService()
    result = service.build_context(
        PredictionMarketContextRequest(
            topic="Kraken IPO",
            goal="Let Hermes decide whether and where to trade.",
            markets=[
                _market("polymarket", "pm_kraken_2026", "Kraken IPO by December 31, 2026?", 0.375, 4500, 0.02, True),
                _market("kalshi", "kalshi_kraken_2026", "Kraken IPO before 2027?", 0.41, 2800, 0.04, False),
            ],
        )
    )
    assert result.topic == "Kraken IPO"
    assert result.agent_role == "hermes_decides"
    assert result.clink_role == "context_and_execution_infrastructure"
    assert result.available_routes
    assert "single_platform_preview" in result.available_routes
    assert "hedge_preview" not in result.available_routes
    assert result.suggested_next_tools["single_platform_preview"] == "create_prediction_market_order_preview"
    assert "hedge_preview" not in result.suggested_next_tools
    assert result.markets_by_platform["polymarket"][0].market_id == "pm_kraken_2026"
    assert result.markets_by_platform["kalshi"][0].market_id == "kalshi_kraken_2026"
    assert result.evidence
    assert result.evidence[0].quality_score >= result.evidence[1].quality_score
    assert result.hermes_prompt_hints
    assert result.execution_constraints["final_decision_owner"] == "Hermes"
    assert not hasattr(result, "recommended_action")
    assert not hasattr(result, "recommended_platform")

    print(json.dumps({"status": "ok", "routes": result.available_routes, "top_platform": result.evidence[0].platform}, indent=2))


if __name__ == "__main__":
    main()
