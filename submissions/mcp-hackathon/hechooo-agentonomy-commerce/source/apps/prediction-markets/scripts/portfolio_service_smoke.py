import json
import os
import sys
import warnings
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["PREDICTION_MARKETS_LEDGER_DB_FILE"] = "/tmp/clink_prediction_empty_portfolio_import.sqlite3"
warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from fastapi.testclient import TestClient

from services.portfolio_service.app import create_app
from services.portfolio_service.service import PortfolioService
from shared.config import AppConfig


def main() -> None:
    config = AppConfig.from_env()
    config.ledger_db_file = "/tmp/clink_prediction_empty_portfolio.sqlite3"
    for path in [Path(config.ledger_db_file), Path(f"{config.ledger_db_file}-wal"), Path(f"{config.ledger_db_file}-shm")]:
        path.unlink(missing_ok=True)

    readiness_calls: list[str] = []

    def account_readiness(user_id: str) -> dict:
        readiness_calls.append(user_id)
        return {
            "user_id": user_id,
            "active_spending_mandate": {
                "limits_usdc": {"per_transaction": "3"},
                "remaining_usdc": {
                    "rolling_hour": "2",
                    "daily": "4",
                    "total": "10",
                },
            }
        }

    service = PortfolioService(
        config=config,
        account_readiness_fetcher=account_readiness,
    )
    client = TestClient(create_app(service))
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    snapshot = client.get(
        "/portfolio/snapshot",
        params={"user_id": "attacker-controlled-user"},
    )
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert readiness_calls == []
    assert payload["summary"]["available_budget_usd"] is None
    assert payload["summary"]["available_budget_status"] == "unavailable"
    assert payload["summary"]["open_positions"] == 0
    assert payload["positions"] == []
    assert payload["pending_actions"] == []
    assert payload["timeline"] == []
    assert payload["summary"]["sync_status"] == "never_synced"

    internal_path = "/internal/portfolio/snapshot"
    internal_snapshot = client.get(
        internal_path,
        params={"user_id": "telegram_demo_user"},
        headers={"Authorization": "Bearer ignored-by-public-portfolio"},
    )
    assert internal_snapshot.status_code == 404
    assert readiness_calls == []

    print(json.dumps({"status": "ok", "portfolio_value": payload["summary"]["portfolio_value_usd"]}, indent=2))


if __name__ == "__main__":
    main()
