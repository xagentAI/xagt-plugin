import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.decision_service.service import DecisionService
from shared.schemas import PredictionMarketDecisionRequest, UnifiedMarket


def _market(
    platform: str,
    market_id: str,
    title: str,
    yes_price: float,
    liquidity: float | None,
    spread: float | None,
    execution_ready: bool,
    rules_summary: str | None = None,
) -> UnifiedMarket:
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
        rules_summary=rules_summary or "Resolves Yes if Kraken completes an IPO before the listed date.",
        tradable=True,
        execution_ready=execution_ready,
    )


def main() -> None:
    markets = [
        _market("polymarket", "pm_kraken_2026", "Kraken IPO by December 31, 2026?", 0.375, 4500, 0.02, True),
        _market("kalshi", "kalshi_kraken_2026", "Kraken IPO before 2027?", 0.41, None, 0.04, False),
        _market("polymarket", "pm_closed", "Unrelated sports market", 0.5, 100, 0.2, False),
    ]
    service = DecisionService()
    result = service.analyze_topic(
        PredictionMarketDecisionRequest(
            topic="Kraken IPO",
            goal="Find the safest executable market or explain if a hedge is better.",
            markets=markets,
            max_results=5,
        )
    )
    assert result.topic == "Kraken IPO"
    assert result.recommended_action == "single_platform_preview"
    assert result.recommended_platform == "polymarket"
    assert result.next_tool_call is not None
    assert result.next_tool_call["tool"] == "create_prediction_market_order_preview"
    assert result.selected_markets[0].platform == "polymarket"
    assert len(result.comparison) >= 2
    assert result.comparison[0].overall_score >= result.comparison[1].overall_score
    assert result.reasoning
    assert any("Polymarket" in line or "polymarket" in line for line in result.reasoning)

    no_trade = service.analyze_topic(
        PredictionMarketDecisionRequest(
            topic="Kraken IPO",
            markets=[_market("kalshi", "kalshi_bad", "Kraken IPO unclear rules", 0.51, None, 0.25, False, rules_summary="")],
        )
    )
    assert no_trade.recommended_action in {"no_trade", "wait"}
    assert no_trade.next_tool_call is None
    assert no_trade.risk_flags

    print(json.dumps({"status": "ok", "recommended_action": result.recommended_action, "recommended_platform": result.recommended_platform}, indent=2))


if __name__ == "__main__":
    main()
