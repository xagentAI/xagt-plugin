import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    db_path = Path("/tmp/clink_prediction_agent_idea_mcp.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)
    os.environ["PREDICTION_MARKETS_LEDGER_DB_FILE"] = str(db_path)

    from mcp_servers.prediction_markets_server import create_agent_idea, update_agent_idea
    from services.portfolio_service.service import PortfolioService
    from shared.config import AppConfig
    from storage.trading_ledger import TradingLedger

    market = {
        "platform": "polymarket",
        "market_id": "691547",
        "title": "Kraken IPO by December 31, 2026?",
        "yes_price": 0.26,
        "no_price": 0.74,
        "liquidity_usd": 4200,
        "bid_ask_spread": 0.01,
        "tradable": True,
        "execution_ready": True,
    }

    idea = create_agent_idea(
        user_id="telegram:jeff",
        agent_id="hermes",
        topic="Kraken IPO",
        agent_message="I scanned Polymarket and Kalshi, then found the liquid Kraken IPO market as the best candidate to discuss.",
        recommendation="Discuss a small Buy Yes preview before committing capital.",
        market=market,
        confidence=0.72,
        risks=["No Kalshi comparable market was found.", "This is not a guaranteed positive-EV trade."],
        suggested_trade={"side": "buy", "outcome": "Yes", "amount_usd": "1", "limit_price": 0.26},
        strategy_id="strat_kraken_demo",
        metadata={"source": "hermes_conversation"},
    )
    updated = update_agent_idea(
        idea_id=idea.idea_id,
        status="preview_created",
        preview_id="pm_preview_demo",
        metadata={"operator_note": "preview created after user discussion"},
    )

    ledger_ideas = TradingLedger(db_path).list_agent_ideas()
    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)
    snapshot = PortfolioService(config=config).build_snapshot()

    assert idea.idea_id.startswith("idea_")
    assert updated.status == "preview_created"
    assert updated.preview_id == "pm_preview_demo"
    assert len(ledger_ideas) == 1
    assert ledger_ideas[0]["topic"] == "Kraken IPO"
    assert len(snapshot.agent_ideas) == 1
    assert snapshot.agent_ideas[0].idea_id == idea.idea_id
    assert snapshot.agent_ideas[0].market["market_id"] == "691547"

    print(
        json.dumps(
            {
                "status": "ok",
                "idea_id": idea.idea_id,
                "idea_status": updated.status,
                "snapshot_ideas": len(snapshot.agent_ideas),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
