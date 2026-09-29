import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.router_service.app import app
from services.router_service.service import search_fixture_markets


def main() -> None:
    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    markets = search_fixture_markets(
        "kraken ipo",
        [{"id": "pm1", "question": "Kraken IPO by 2026?", "active": True, "closed": False, "outcomes": '["Yes","No"]', "outcomePrices": '["0.4","0.6"]'}],
        [{"ticker": "KXKRAKEN", "title": "Will Kraken IPO before 2027?", "status": "open", "yes_bid_dollars": "0.39", "yes_ask_dollars": "0.42"}],
    )
    score = client.post("/markets/score", json={"query": "kraken ipo", "markets": [item.model_dump() for item in markets], "max_results": 2})
    assert score.status_code == 200
    payload = score.json()
    assert payload["count"] == 2
    print(json.dumps({"status": "ok", "count": payload["count"]}, indent=2))


if __name__ == "__main__":
    main()
