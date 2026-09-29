from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from platforms.kalshi.normalizer import normalize_kalshi_market
from platforms.polymarket.normalizer import normalize_polymarket_market
from shared.config import AppConfig
from shared.schemas import ScoredMarket, SearchMarketsResult, UnifiedMarket


@dataclass
class FetchResult:
    platform: str
    markets: list[UnifiedMarket]
    detail: str


def _request_json(url: str, timeout: int = 20) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": "clink-prediction-markets/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _matches_query(market: UnifiedMarket, query: str | None) -> bool:
    if not query:
        return True
    terms = [term.lower() for term in query.split() if term.strip()]
    haystack = " ".join(
        str(value or "")
        for value in [market.title, market.subtitle, market.category, market.rules_summary, market.market_id, market.event_id]
    ).lower()
    return all(term in haystack for term in terms)


def _dedupe(markets: list[UnifiedMarket]) -> list[UnifiedMarket]:
    seen: set[tuple[str, str]] = set()
    result: list[UnifiedMarket] = []
    for market in markets:
        key = (market.platform, market.market_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(market)
    return result


def search_fixture_markets(
    query: str | None,
    polymarket_raw: list[dict[str, Any]],
    kalshi_raw: list[dict[str, Any]],
    tradable_only: bool = True,
) -> list[UnifiedMarket]:
    markets = [normalize_polymarket_market(item) for item in polymarket_raw]
    markets.extend(normalize_kalshi_market(item) for item in kalshi_raw)
    markets = [market for market in markets if _matches_query(market, query)]
    if tradable_only:
        markets = [market for market in markets if market.tradable]
    return _dedupe(markets)


def fetch_polymarket_markets(config: AppConfig, query: str | None, limit: int, tradable_only: bool) -> FetchResult:
    params = urllib.parse.urlencode({"active": "true", "closed": "false", "limit": max(limit, 100)})
    url = f"{config.polymarket_gamma_api_url.rstrip('/')}/events/keyset?{params}"
    data = _request_json(url)
    events = data.get("events") if isinstance(data, dict) else data
    raw_markets: list[dict[str, Any]] = []
    for event in events or []:
        for market in event.get("markets", []) if isinstance(event, dict) else []:
            enriched = {**market, "event_id": event.get("id"), "category": event.get("category")}
            raw_markets.append(enriched)
    markets = [normalize_polymarket_market(item) for item in raw_markets]
    markets = [market for market in markets if _matches_query(market, query)]
    if tradable_only:
        markets = [market for market in markets if market.tradable]
    return FetchResult("polymarket", markets[:limit], f"Fetched {len(events or [])} Polymarket events; matched {len(markets)} markets.")


def fetch_kalshi_markets(config: AppConfig, query: str | None, limit: int, tradable_only: bool) -> FetchResult:
    params = urllib.parse.urlencode({"status": "open", "limit": max(limit, 100)})
    url = f"{config.kalshi_api_base_url.rstrip('/')}/markets?{params}"
    data = _request_json(url)
    raw_markets = data.get("markets", []) if isinstance(data, dict) else []
    markets = [normalize_kalshi_market(item) for item in raw_markets]
    markets = [market for market in markets if _matches_query(market, query)]
    if tradable_only:
        markets = [market for market in markets if market.tradable]
    return FetchResult("kalshi", markets[:limit], f"Fetched {len(raw_markets)} Kalshi markets; matched {len(markets)} markets.")


def search_markets(
    query: str | None = None,
    platforms: list[str] | None = None,
    limit: int = 20,
    tradable_only: bool = True,
    config: AppConfig | None = None,
) -> SearchMarketsResult:
    config = config or AppConfig.from_env()
    platforms = platforms or ["polymarket", "kalshi"]
    markets: list[UnifiedMarket] = []
    details: list[str] = []
    for platform in platforms:
        try:
            if platform == "polymarket":
                result = fetch_polymarket_markets(config, query, limit, tradable_only)
            elif platform == "kalshi":
                result = fetch_kalshi_markets(config, query, limit, tradable_only)
            else:
                details.append(f"Skipped unsupported platform {platform}.")
                continue
            markets.extend(result.markets)
            details.append(result.detail)
        except Exception as exc:  # Keep router resilient when one venue is down.
            details.append(f"{platform} fetch failed: {type(exc).__name__}: {exc}")
    markets = _dedupe(markets)
    scored = score_markets(query, markets, max_results=limit)
    ordered = [item.market for item in scored]
    return SearchMarketsResult(source_detail=" ".join(details), markets=ordered[:limit], count=len(ordered[:limit]))


def _term_score(query: str | None, market: UnifiedMarket) -> tuple[float, str | None]:
    if not query:
        return 0.0, None
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return 0.0, None
    haystack = " ".join(
        str(value or "") for value in [market.title, market.subtitle, market.category, market.rules_summary, market.market_id]
    ).lower()
    hits = sum(1 for term in terms if term in haystack)
    if hits == 0:
        return 0.0, None
    return min(40.0, 40.0 * hits / len(terms)), f"topic match {hits}/{len(terms)}"


def score_markets(query: str | None, markets: list[UnifiedMarket], max_results: int = 5) -> list[ScoredMarket]:
    scored: list[ScoredMarket] = []
    for market in markets:
        score = 0.0
        rationale: list[str] = []
        term_score, term_reason = _term_score(query, market)
        score += term_score
        if term_reason:
            rationale.append(term_reason)
        if market.tradable:
            score += 15
            rationale.append("tradable")
        if market.yes_price is not None and 0.05 <= market.yes_price <= 0.95:
            score += 15
            rationale.append("usable probability")
        if market.bid_ask_spread is not None:
            spread_score = max(0.0, 15.0 * (1.0 - min(market.bid_ask_spread, 0.2) / 0.2))
            score += spread_score
            rationale.append(f"spread {market.bid_ask_spread:.3f}")
        if market.liquidity_usd:
            score += min(15.0, market.liquidity_usd / 1000.0)
            rationale.append(f"liquidity {market.liquidity_usd:.0f}")
        elif market.volume_24h_usd:
            score += min(10.0, market.volume_24h_usd / 500.0)
            rationale.append(f"volume {market.volume_24h_usd:.0f}")
        if market.execution_ready:
            score += 5
            rationale.append("execution context ready")
        scored.append(ScoredMarket(market=market, score=round(score, 4), rationale=rationale))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:max_results]
