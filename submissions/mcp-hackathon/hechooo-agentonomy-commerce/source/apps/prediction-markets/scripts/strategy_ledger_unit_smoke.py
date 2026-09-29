import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.schemas import (
    StrategyRecord,
    VenueAccountSnapshot,
    VenueFill,
    VenueOpenOrder,
    VenuePosition,
    VenueSettlement,
)
from storage.trading_ledger import TradingLedger


def main() -> None:
    db_path = Path("/tmp/clink_prediction_strategy_ledger.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)

    ledger = TradingLedger(db_path)
    ledger.upsert_strategy(
        StrategyRecord(
            strategy_id="strat_kraken_ipo",
            user_id="telegram:jeff",
            agent_id="hermes",
            topic="Kraken IPO",
            hypothesis="Kraken IPO probability is mispriced across venues.",
            agent_reasoning=[
                "Hermes found comparable Polymarket and Kalshi exposure.",
                "Clink should track the thesis as one strategy, not isolated orders.",
            ],
            status="active",
            created_at="2026-07-02T03:00:00Z",
            updated_at="2026-07-02T03:00:00Z",
        )
    )
    ledger.link_strategy_entity("strat_kraken_ipo", "order", "poly_order_1", platform="polymarket")
    ledger.link_strategy_entity("strat_kraken_ipo", "fill", "poly_fill_1", platform="polymarket")
    ledger.link_strategy_entity("strat_kraken_ipo", "position", "poly_pos_1", platform="polymarket")
    ledger.link_strategy_entity("strat_kraken_ipo", "settlement", "poly_settle_1", platform="polymarket")

    ledger.upsert_venue_account_snapshot(
        VenueAccountSnapshot(
            platform="polymarket",
            status="ok",
            captured_at="2026-07-02T03:01:00Z",
            open_orders=[
                VenueOpenOrder(
                    platform="polymarket",
                    order_id="poly_order_1",
                    market_id="691547",
                    title="Kraken IPO by December 31, 2026?",
                    outcome="Yes",
                    side="buy",
                    status="open",
                    contracts="10",
                    filled_contracts="4",
                    limit_price="0.40",
                    avg_price="0.38",
                    cost_basis_usd="1.52",
                    updated_at="2026-07-02T03:01:00Z",
                ),
            ],
            fills=[
                VenueFill(
                    platform="polymarket",
                    fill_id="poly_fill_1",
                    order_id="poly_order_1",
                    market_id="691547",
                    outcome="Yes",
                    side="buy",
                    contracts="4",
                    price="0.38",
                    amount_usd="1.52",
                    filled_at="2026-07-02T03:01:00Z",
                ),
            ],
            positions=[
                VenuePosition(
                    platform="polymarket",
                    position_id="poly_pos_1",
                    market_id="691547",
                    title="Kraken IPO by December 31, 2026?",
                    outcome="Yes",
                    side="buy",
                    status="open",
                    order_id="poly_order_1",
                    contracts="4",
                    entry_price="0.38",
                    mark_price="0.45",
                    cost_basis_usd="1.52",
                    current_value_usd="1.80",
                    unrealized_pnl_usd="0.28",
                    updated_at="2026-07-02T03:01:00Z",
                ),
            ],
            settlements=[
                VenueSettlement(
                    platform="polymarket",
                    settlement_id="poly_settle_1",
                    market_id="691547",
                    title="Kraken IPO by December 31, 2026?",
                    realized_pnl_usd="0.12",
                    payout_usd="1.64",
                    settled_at="2026-07-02T03:02:00Z",
                ),
            ],
        )
    )

    performance = ledger.list_strategy_performance()

    assert len(performance) == 1
    strategy = performance[0]
    assert strategy["strategy_id"] == "strat_kraken_ipo"
    assert strategy["topic"] == "Kraken IPO"
    assert strategy["capital_deployed_usd"] == "1.52"
    assert strategy["current_value_usd"] == "1.80"
    assert strategy["unrealized_pnl_usd"] == "0.28"
    assert strategy["realized_pnl_usd"] == "0.12"
    assert strategy["total_pnl_usd"] == "0.40"
    assert strategy["open_orders"] == 1
    assert strategy["fills"] == 1
    assert strategy["open_positions"] == 1
    assert strategy["settlements"] == 1
    assert strategy["platforms"] == ["polymarket"]
    assert strategy["linked_entities"]["order"] == ["poly_order_1"]

    print(json.dumps({"status": "ok", "strategy": strategy["strategy_id"], "pnl": strategy["total_pnl_usd"]}, indent=2))


if __name__ == "__main__":
    main()
