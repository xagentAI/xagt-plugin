import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.schemas import (
    VenueAccountBalance,
    VenueAccountSnapshot,
    VenueFill,
    VenueOpenOrder,
    VenuePosition,
    VenueSettlement,
)
from storage.trading_ledger import TradingLedger


def main() -> None:
    db_path = Path("/tmp/clink_prediction_venue_ledger.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)

    ledger = TradingLedger(db_path)
    snapshot = VenueAccountSnapshot(
        platform="polymarket",
        status="ok",
        captured_at="2026-07-02T02:00:00Z",
        balances=[
            VenueAccountBalance(platform="polymarket", currency="USDC", total="105.50", available="88.25", locked="17.25"),
        ],
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
                limit_price="0.37",
                avg_price="0.36",
                cost_basis_usd="3.60",
                created_at="2026-07-02T01:59:00Z",
                updated_at="2026-07-02T02:00:00Z",
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
                price="0.36",
                amount_usd="1.44",
                fee_usd="0.00",
                filled_at="2026-07-02T02:00:00Z",
            ),
        ],
        positions=[
            VenuePosition(
                platform="polymarket",
                position_id="poly_pos_691547_yes",
                market_id="691547",
                title="Kraken IPO by December 31, 2026?",
                outcome="Yes",
                side="buy",
                status="open",
                order_id="poly_order_1",
                contracts="4",
                entry_price="0.36",
                mark_price="0.42",
                cost_basis_usd="1.44",
                current_value_usd="1.68",
                unrealized_pnl_usd="0.24",
                realized_pnl_usd="0.00",
                updated_at="2026-07-02T02:00:00Z",
            ),
        ],
        settlements=[
            VenueSettlement(
                platform="polymarket",
                settlement_id="poly_settle_1",
                market_id="old_market",
                title="Resolved old market",
                realized_pnl_usd="2.10",
                payout_usd="7.10",
                settled_at="2026-07-02T01:50:00Z",
            ),
        ],
    )

    ledger.upsert_venue_account_snapshot(snapshot)

    assert ledger.list_account_balances()[0]["available"] == "88.25"
    assert ledger.list_open_orders()[0]["filled_contracts"] == "4"
    assert ledger.list_fills()[0]["amount_usd"] == "1.44"
    assert ledger.list_settlements()[0]["realized_pnl_usd"] == "2.10"
    positions = ledger.list_positions()
    assert positions[0]["position_id"] == "poly_pos_691547_yes"
    assert positions[0]["price_source"] == "venue_account_snapshot"
    assert positions[0]["unrealized_pnl_usd"] == "0.24"

    print(json.dumps({"status": "ok", "balances": 1, "positions": len(positions)}, indent=2))


if __name__ == "__main__":
    main()
