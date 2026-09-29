import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.polymarket.executor import PolymarketExecutor  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import PredictionMarketOrderPreview, UnifiedMarket  # noqa: E402


def _preview() -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="polymarket",
        market_id="558934",
        title="Will Spain win the 2026 FIFA World Cup?",
        yes_price=0.123,
        no_price=0.877,
        tradable=True,
        execution_ready=True,
        raw={"clobTokenIds": ["123456789", "987654321"], "outcomes": '["Yes", "No"]'},
    )
    return PredictionMarketOrderPreview(
        preview_id="pm_preview_prod_gate",
        user_id="telegram_demo_user",
        agent_id="hermes_agent",
        platform="polymarket",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="1",
        limit_price=0.123,
        estimated_contracts=8.13,
        max_slippage_bps=100,
        max_slippage_usd="0.01",
        worst_case_price=0.124,
        state="confirmation_required",
        next_action="request_user_confirmation",
        live_mode=True,
        market=market,
        created_at="2026-07-05T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def main() -> None:
    browser_config = AppConfig(polymarket_execution_mode="browser_signed")
    browser_executor = PolymarketExecutor(browser_config)
    browser_readiness = browser_executor.readiness()
    assert "POLYMARKET_PRIVATE_KEY" not in browser_readiness.missing
    assert "POLYMARKET_FUNDER_ADDRESS" not in browser_readiness.missing
    assert "py-clob-client package" not in browser_readiness.missing
    assert browser_readiness.metadata["POLYMARKET_EXECUTION_MODE"] == "browser_signed"

    browser_result = browser_executor.submit_order(_preview())
    assert browser_result.submitted is False
    assert browser_result.status == "needs_browser_signature"
    assert browser_result.reason == "Polymarket production mode requires a browser-signed order session"

    unsupported_config = AppConfig(polymarket_execution_mode="server_executor")
    unsupported_executor = PolymarketExecutor(unsupported_config)
    unsupported_readiness = unsupported_executor.readiness()
    assert "POLYMARKET_EXECUTION_MODE=browser_signed" in unsupported_readiness.missing

    print(
        json.dumps(
            {
                "status": "ok",
                "default_mode": browser_readiness.metadata["POLYMARKET_EXECUTION_MODE"],
                "browser_next_action": browser_result.reason,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
