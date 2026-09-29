import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.kalshi.normalizer import normalize_kalshi_market
from platforms.polymarket.normalizer import normalize_polymarket_market
from services.router_service.service import score_markets, search_fixture_markets


def main() -> None:
    polymarket_raw = {
        "id": "691547",
        "question": "Kraken IPO by December 31, 2026?",
        "slug": "kraken-ipo-by-december-31-2026",
        "active": True,
        "closed": False,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.37", "0.63"]',
        "liquidity": "4367.10",
        "volume24hr": "84.05",
        "endDate": "2026-12-31T23:59:59Z",
        "description": "Resolves Yes if Kraken completes an IPO by the date.",
    }
    kalshi_raw = {
        "ticker": "KXKRAKENIPO-26DEC31",
        "event_ticker": "KXKRAKENIPO",
        "title": "Will Kraken IPO before 2027?",
        "subtitle": "Kraken IPO by Dec 31, 2026",
        "status": "open",
        "yes_bid_dollars": "0.39",
        "yes_ask_dollars": "0.42",
        "volume": 1200,
        "close_time": "2026-12-31T23:59:59Z",
        "rules_primary": "Pays out if Kraken completes an IPO before 2027.",
    }

    poly = normalize_polymarket_market(polymarket_raw)
    kalshi = normalize_kalshi_market(kalshi_raw)
    assert poly.platform == "polymarket"
    assert kalshi.platform == "kalshi"
    assert poly.yes_price == 0.37
    assert kalshi.yes_price == 0.405
    assert kalshi.bid_ask_spread == 0.03
    assert kalshi.execution_ready is True

    markets = search_fixture_markets("kraken ipo", [polymarket_raw], [kalshi_raw])
    assert len(markets) == 2
    scored = score_markets("kraken ipo", markets, max_results=2)
    assert scored[0].score >= scored[1].score
    assert scored[0].market.platform in {"polymarket", "kalshi"}

    print(json.dumps({"status": "ok", "count": len(scored), "top_platform": scored[0].market.platform}, indent=2))


if __name__ == "__main__":
    main()
