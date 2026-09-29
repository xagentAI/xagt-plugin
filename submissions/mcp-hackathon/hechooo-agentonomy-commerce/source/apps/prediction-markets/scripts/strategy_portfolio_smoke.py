import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.portfolio_service.service import PortfolioService
from shared.config import AppConfig
from shared.schemas import StrategyRecord, VenueAccountSnapshot, VenueFill, VenuePosition
from storage.trading_ledger import TradingLedger


def main() -> None:
    db_path = Path("/tmp/clink_prediction_strategy_portfolio.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)

    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)

    ledger = TradingLedger(db_path)
    ledger.upsert_strategy(
        StrategyRecord(
            strategy_id="strat_btc_momentum",
            user_id="telegram:jeff",
            agent_id="hermes",
            topic="BTC 5 minute momentum",
            hypothesis="Short horizon BTC markets are temporarily underpricing downside momentum.",
            agent_reasoning=[
                "Hermes compared the available markets and selected the most liquid route.",
                "Clink required preview and human confirmation before live execution.",
            ],
            status="active",
            created_at="2026-07-02T04:00:00Z",
            updated_at="2026-07-02T04:00:00Z",
            metadata={"confidence": "medium"},
        )
    )
    ledger.link_strategy_entity(
        "strat_btc_momentum",
        "position",
        "kalshi_pos_btc_down",
        platform="kalshi",
        metadata={"clink_control": "human_confirmed_live_execution"},
    )
    ledger.link_strategy_entity("strat_btc_momentum", "fill", "kalshi_fill_1", platform="kalshi")

    ledger.upsert_venue_account_snapshot(
        VenueAccountSnapshot(
            platform="kalshi",
            status="ok",
            captured_at="2026-07-02T04:01:00Z",
            fills=[
                VenueFill(
                    platform="kalshi",
                    fill_id="kalshi_fill_1",
                    order_id="kalshi_order_btc_1",
                    market_id="KXBTCDOWN-5M",
                    outcome="No",
                    side="buy",
                    contracts="10",
                    price="0.51",
                    amount_usd="5.10",
                    filled_at="2026-07-02T04:01:00Z",
                ),
            ],
            positions=[
                VenuePosition(
                    platform="kalshi",
                    position_id="kalshi_pos_btc_down",
                    market_id="KXBTCDOWN-5M",
                    title="Bitcoin Up or Down - 5m",
                    outcome="No",
                    side="buy",
                    status="open",
                    order_id="kalshi_order_btc_1",
                    contracts="10",
                    entry_price="0.51",
                    mark_price="0.58",
                    cost_basis_usd="5.10",
                    current_value_usd="5.80",
                    unrealized_pnl_usd="0.70",
                    updated_at="2026-07-02T04:01:00Z",
                ),
            ],
        )
    )

    snapshot = PortfolioService(config=config, ledger=ledger).build_snapshot()

    assert len(snapshot.strategies) == 1
    strategy = snapshot.strategies[0]
    assert strategy.strategy_id == "strat_btc_momentum"
    assert strategy.topic == "BTC 5 minute momentum"
    assert strategy.status == "active"
    assert strategy.capital_deployed_usd == "5.10"
    assert strategy.current_value_usd == "5.80"
    assert strategy.total_pnl_usd == "0.70"
    assert strategy.total_pnl_pct == "13.73"
    assert strategy.platforms == ["kalshi"]
    assert strategy.open_positions == 1
    assert strategy.fills == 1
    assert strategy.metadata["confidence"] == "medium"
    assert snapshot.summary.active_strategies == 1
    assert snapshot.summary.best_strategy_id == "strat_btc_momentum"

    print(
        json.dumps(
            {
                "status": "ok",
                "active_strategies": snapshot.summary.active_strategies,
                "best_strategy": snapshot.summary.best_strategy_id,
                "strategy_pnl": strategy.total_pnl_usd,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
