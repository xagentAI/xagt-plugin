import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.portfolio_service.service import PortfolioService
from services.sync_service.service import PortfolioSyncService
from shared.config import AppConfig
from shared.schemas import (
    VenueAccountBalance,
    VenueAccountSnapshot,
    VenueFill,
    VenueOpenOrder,
    VenuePosition,
)
from storage.trading_ledger import TradingLedger


class FakeVenueAdapter:
    platform = "kalshi"

    def fetch_account_snapshot(self) -> VenueAccountSnapshot:
        return VenueAccountSnapshot(
            platform="kalshi",
            status="ok",
            captured_at="2026-07-02T03:00:00Z",
            balances=[
                VenueAccountBalance(platform="kalshi", currency="USD", total="50.00", available="44.00", locked="6.00"),
            ],
            open_orders=[
                VenueOpenOrder(
                    platform="kalshi",
                    order_id="kalshi_order_1",
                    market_id="KXKRAKENIPO-26DEC31",
                    title="Will Kraken IPO before 2027?",
                    outcome="Yes",
                    side="buy",
                    status="open",
                    contracts="12",
                    filled_contracts="6",
                    limit_price="0.40",
                    avg_price="0.39",
                    cost_basis_usd="2.34",
                    created_at="2026-07-02T02:58:00Z",
                    updated_at="2026-07-02T03:00:00Z",
                ),
            ],
            fills=[
                VenueFill(
                    platform="kalshi",
                    fill_id="kalshi_fill_1",
                    order_id="kalshi_order_1",
                    market_id="KXKRAKENIPO-26DEC31",
                    outcome="Yes",
                    side="buy",
                    contracts="6",
                    price="0.39",
                    amount_usd="2.34",
                    filled_at="2026-07-02T03:00:00Z",
                ),
            ],
            positions=[
                VenuePosition(
                    platform="kalshi",
                    position_id="kalshi_pos_kraken_yes",
                    market_id="KXKRAKENIPO-26DEC31",
                    title="Will Kraken IPO before 2027?",
                    outcome="Yes",
                    side="buy",
                    status="open",
                    order_id="kalshi_order_1",
                    contracts="6",
                    entry_price="0.39",
                    mark_price="0.45",
                    cost_basis_usd="2.34",
                    current_value_usd="2.70",
                    unrealized_pnl_usd="0.36",
                    updated_at="2026-07-02T03:00:00Z",
                ),
            ],
        )


def main() -> None:
    db_path = Path("/tmp/clink_prediction_venue_sync.sqlite3")
    preview_file = Path("/tmp/clink_prediction_venue_sync_previews.jsonl")
    execution_file = Path("/tmp/clink_prediction_venue_sync_executions.jsonl")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm"), preview_file, execution_file]:
        path.unlink(missing_ok=True)

    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)
    config.preview_file = str(preview_file)
    config.execution_file = str(execution_file)
    config.sync_venue_accounts = True
    config.sync_stale_after_seconds = 60

    ledger = TradingLedger(db_path)
    result = PortfolioSyncService(config=config, ledger=ledger, venue_adapters=[FakeVenueAdapter()]).sync_once()

    assert result.status == "ok"
    assert result.venue_snapshots_ingested == 1
    assert result.balances_ingested == 1
    assert result.open_orders_ingested == 1
    assert result.fills_ingested == 1
    assert result.positions_reconciled == 1

    snapshot = PortfolioService(config=config, ledger=ledger).build_snapshot()
    assert snapshot.summary.account_equity_usd == "50.00"
    assert snapshot.summary.available_cash_usd == "44.00"
    assert snapshot.summary.open_orders == 1
    assert snapshot.summary.fills_24h == 1
    assert snapshot.summary.unrealized_pnl_usd == "0.36"
    assert snapshot.positions[0].price_source == "venue_account_snapshot"
    assert snapshot.open_orders[0].order_id == "kalshi_order_1"
    assert snapshot.recent_fills[0].fill_id == "kalshi_fill_1"

    print(json.dumps({"status": "ok", "equity": snapshot.summary.account_equity_usd, "positions": len(snapshot.positions)}, indent=2))


if __name__ == "__main__":
    main()
