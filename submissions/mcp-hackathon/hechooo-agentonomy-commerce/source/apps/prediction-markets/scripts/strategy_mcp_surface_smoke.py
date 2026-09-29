import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    db_path = Path("/tmp/clink_prediction_strategy_mcp.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)
    os.environ["PREDICTION_MARKETS_LEDGER_DB_FILE"] = str(db_path)

    from mcp_servers.prediction_markets_server import create_prediction_market_strategy
    from storage.trading_ledger import TradingLedger

    strategy = create_prediction_market_strategy(
        user_id="telegram:jeff",
        agent_id="hermes",
        topic="Kraken IPO",
        hypothesis="Kraken IPO exposure is better traded only after comparing venues.",
        agent_reasoning=["Hermes needs a durable thesis before placing capital."],
        strategy_id="strat_mcp_kraken",
        metadata={"source": "mcp_smoke"},
    )

    performance = TradingLedger(db_path).list_strategy_performance()

    assert strategy.strategy_id == "strat_mcp_kraken"
    assert len(performance) == 1
    assert performance[0]["topic"] == "Kraken IPO"
    assert performance[0]["metadata"]["source"] == "mcp_smoke"

    print(json.dumps({"status": "ok", "strategy_id": strategy.strategy_id}, indent=2))


if __name__ == "__main__":
    main()
