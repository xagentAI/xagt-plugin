from __future__ import annotations

from typing import Any

from platforms.common import clamp_probability, round_optional, to_float
from shared.schemas import UnifiedMarket


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return bid if bid is not None else ask


def normalize_kalshi_market(raw: dict[str, Any]) -> UnifiedMarket:
    ticker = str(raw.get("ticker") or raw.get("market_ticker") or "unknown")
    yes_bid = to_float(raw.get("yes_bid_dollars"))
    yes_ask = to_float(raw.get("yes_ask_dollars"))
    if yes_bid is None:
        yes_bid_cents = to_float(raw.get("yes_bid"))
        yes_bid = yes_bid_cents / 100 if yes_bid_cents is not None else None
    if yes_ask is None:
        yes_ask_cents = to_float(raw.get("yes_ask"))
        yes_ask = yes_ask_cents / 100 if yes_ask_cents is not None else None
    yes_price = clamp_probability(_midpoint(yes_bid, yes_ask))
    spread = abs(yes_ask - yes_bid) if yes_bid is not None and yes_ask is not None else None
    title = str(raw.get("title") or raw.get("subtitle") or ticker)
    status = str(raw.get("status") or "unknown")
    volume = to_float(raw.get("volume_24h") or raw.get("volume") or raw.get("volume_fp"))
    return UnifiedMarket(
        platform="kalshi",
        market_id=ticker,
        event_id=raw.get("event_ticker"),
        title=title,
        subtitle=raw.get("subtitle"),
        category=raw.get("category"),
        url=f"https://kalshi.com/markets/{str(raw.get('event_ticker') or ticker).lower()}",
        status=status,
        yes_price=round_optional(yes_price),
        no_price=round_optional(1.0 - yes_price if yes_price is not None else None),
        bid_ask_spread=round_optional(spread),
        liquidity_usd=None,
        volume_24h_usd=volume,
        end_time=raw.get("close_time") or raw.get("expiration_time"),
        rules_summary=raw.get("rules_primary") or raw.get("rules_secondary"),
        tradable=status == "open" and yes_price is not None,
        execution_ready=status == "open" and yes_price is not None,
        raw=raw,
    )
