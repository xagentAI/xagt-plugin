from __future__ import annotations

from typing import Any

from platforms.common import clamp_probability, parse_json_list, round_optional, to_float
from shared.schemas import UnifiedMarket


def normalize_polymarket_market(raw: dict[str, Any]) -> UnifiedMarket:
    outcomes = [str(item) for item in parse_json_list(raw.get("outcomes"))]
    prices = [to_float(item) for item in parse_json_list(raw.get("outcomePrices"))]
    yes_price = prices[0] if prices else to_float(raw.get("best_yes_price"))
    yes_price = clamp_probability(yes_price)
    no_price = prices[1] if len(prices) > 1 else (1.0 - yes_price if yes_price is not None else None)
    no_price = clamp_probability(no_price)
    market_id = str(raw.get("id") or raw.get("conditionId") or raw.get("market_id") or raw.get("slug") or "unknown")
    title = str(raw.get("question") or raw.get("title") or raw.get("description") or market_id)
    slug = raw.get("slug")
    active = bool(raw.get("active", True))
    closed = bool(raw.get("closed", False))
    liquidity = to_float(raw.get("liquidity") or raw.get("liquidityNum"))
    volume = to_float(raw.get("volume24hr") or raw.get("volume24hrClob") or raw.get("volume"))
    return UnifiedMarket(
        platform="polymarket",
        market_id=market_id,
        event_id=str(raw.get("event_id") or raw.get("eventId") or "") or None,
        title=title,
        subtitle=raw.get("subtitle"),
        category=raw.get("category"),
        url=f"https://polymarket.com/market/{slug}" if slug else raw.get("url"),
        status="open" if active and not closed else "closed",
        yes_price=round_optional(yes_price),
        no_price=round_optional(no_price),
        bid_ask_spread=None,
        liquidity_usd=liquidity,
        volume_24h_usd=volume,
        end_time=raw.get("endDate") or raw.get("end_date_iso") or raw.get("endDateIso"),
        rules_summary=raw.get("description") or raw.get("rules"),
        tradable=active and not closed and yes_price is not None,
        execution_ready=bool(raw.get("clobTokenIds") or raw.get("clob_token_ids")),
        raw=raw,
    )
