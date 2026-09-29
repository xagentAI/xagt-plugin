import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.portfolio_service.service import PortfolioService
from shared.config import AppConfig
from storage.trading_ledger import TradingLedger


def main() -> None:
    db_path = Path("/tmp/clink_prediction_funding_status.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)

    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)
    scopes: list[tuple[str, str]] = []

    def funding_status_fetcher(user_id: str, operation_id: str) -> dict:
        scopes.append((user_id, operation_id))
        return {
            "operation_id": operation_id,
            "status": "finalized",
            "amount_usdc": "3.000000",
            "core_tx_hash": "0x" + "12" * 32,
            "core_state": "finalized",
            "bridge_status": "COMPLETED",
            "failure_reason_code": None,
        }

    snapshot = PortfolioService(
        config=config,
        ledger=TradingLedger(db_path),
        funding_status_fetcher=funding_status_fetcher,
    ).build_snapshot(
        user_id="user-demo",
        funding_operation_id="pm_funding_demo",
    )

    assert scopes == [("user-demo", "pm_funding_demo")]
    assert snapshot.funding.status == "finalized"
    assert snapshot.funding.available_budget_usdc_by_venue == {}
    assert snapshot.funding.settled_amount_usdc_by_venue["polymarket"] == "3.000000"
    assert snapshot.funding.spending_authorization_count == 0
    assert snapshot.funding.receipt_count == 1
    assert snapshot.funding.latest_receipt_tx_hash == "0x" + "12" * 32
    assert snapshot.funding.bridge_status == "COMPLETED"

    print(json.dumps({"status": "ok", "funding": snapshot.funding.model_dump()}, indent=2))


if __name__ == "__main__":
    main()
