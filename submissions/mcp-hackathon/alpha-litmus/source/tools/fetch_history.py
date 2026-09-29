"""Download a fixed public daily BTC sample without changing rules.

Run from the project root with ``python -m tools.fetch_history``.
"""

import json
from typing import Any
from datetime import datetime, timezone
from pathlib import Path
import httpx

from app.research import Candle, DAY_MS, ResearchRequest, research

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://data-api.binance.vision/api/v3/klines"


def fetch_candles(client: httpx.Client, start: int, end: int) -> list[Candle]:
    """Require every requested closed UTC day, rejecting partial pagination."""
    if start % DAY_MS or (end + 1) % DAY_MS or start > end:
        raise ValueError("Requested window must contain whole UTC days")
    expected = (end + 1 - start) // DAY_MS
    if not 250 <= expected <= 3000 or end >= int(datetime.now(timezone.utc).timestamp() * 1000):
        raise ValueError("Requested window must contain 250-3000 closed days")
    candles: list[Candle] = []
    cursor = start
    while cursor <= end:
        params: dict[str, str | int] = {
            "symbol": "BTCUSDT",
            "interval": "1d",
            "startTime": cursor,
            "endTime": end,
            "limit": 1000,
        }
        with client.stream("GET", ENDPOINT, params=params) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ValueError("Market-data response exceeds size limit")
        rows: Any = json.loads(content)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError("Missing or malformed market-data page")
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("Malformed kline")
            if type(row[0]) is not int or row[0] != cursor or cursor > end:
                raise ValueError("Market data is incomplete, duplicate, or outside the requested window")
            if type(row[6]) is not int or row[6] != cursor + DAY_MS - 1:
                raise ValueError("Kline does not cover a complete UTC day")
            if any(isinstance(value, bool) or not isinstance(value, (str, int, float)) for value in row[1:6]):
                raise ValueError("Invalid market-data number")
            candles.append(
                Candle(t=row[0], o=float(row[1]), h=float(row[2]), l=float(row[3]), c=float(row[4]), v=float(row[5]))
            )
            cursor += DAY_MS
    if len(candles) != expected:
        raise ValueError("Incomplete requested history")
    return candles


def main() -> None:
    # Fixed research window; selected before inspecting the performance.
    start = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        candles = fetch_candles(client, start, end)
    request = ResearchRequest(
        candles=candles,
        source="Binance public market-data API / BTCUSDT daily / 2022-01-01 through 2025-12-31",
        data_kind="historical",
    )
    result = research(request)
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)
    (folder / "btc-history-input.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    (folder / "btc-history-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    receipt = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": "https://data-api.binance.vision/api/v3/klines",
        "bars": len(candles),
        "dataset_sha256": result["dataset_sha256"],
        "decision": result["decision"],
        "reason_codes": result["reason_codes"],
        "test": {k: result["folds"]["test"][k]["metrics"] for k in ("baseline", "guarded", "buy_hold")},
    }
    (folder / "history-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
