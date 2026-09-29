"""Shared validation and sanitized failures for structured data adapters."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx

ProviderMode = Literal["live", "fixture", "live_or_fixture"]
Observation = tuple[date, float]


class ProviderError(ValueError):
    """Controlled local messages, never remote payloads or keyed URLs."""


def validate_request(lookback_days: int, mode: str) -> None:
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or not 1 <= lookback_days <= 365:
        raise ValueError("lookback_days must be an integer from 1 to 365")
    if mode not in {"live", "fixture", "live_or_fixture"}:
        raise ValueError("mode must be live, fixture, or live_or_fixture")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def observation_time(day: date) -> datetime:
    # Source calendar date, not an intraday timestamp.
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def numeric_value(raw: object, *, positive: bool = False) -> float:
    try:
        if isinstance(raw, bool) or raw is None:
            raise ValueError
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ProviderError("Structured response contains a missing or invalid numeric value") from None
    if not math.isfinite(value) or (positive and value <= 0):
        raise ProviderError("Structured response contains an unsupported numeric value")
    return value


def observation_date(raw: object) -> date:
    try:
        if not isinstance(raw, str) or len(raw) != 10:
            raise ValueError
        parsed = date.fromisoformat(raw)
        if parsed.isoformat() != raw:
            raise ValueError
        return parsed
    except ValueError:
        raise ProviderError("Structured response contains an invalid observation date") from None


def select_window(rows: list[Observation], as_of: date, lookback_days: int) -> tuple[Observation, Observation, date]:
    if not rows:
        raise ProviderError("Structured response contains no observations")
    if len({day for day, _ in rows}) != len(rows):
        raise ProviderError("Structured response contains duplicate observation dates")
    if any(day > as_of for day, _ in rows):
        raise ProviderError("Structured response contains future observation dates")
    ordered = sorted(rows)
    latest = ordered[-1]
    if (as_of - latest[0]).days > 14:
        raise ProviderError("Latest structured observation is more than 14 days old")
    target = latest[0] - timedelta(days=lookback_days)
    baseline = [row for row in ordered if row[0] <= target]
    if not baseline or (target - baseline[-1][0]).days > 7:
        raise ProviderError("Structured response lacks a baseline within 7 days before the requested window")
    return baseline[-1], latest, target


async def fetch(url: str, params: dict[str, str], timeout: float, transport: httpx.AsyncBaseTransport | None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"Structured provider returned HTTP {exc.response.status_code}") from None
    except httpx.HTTPError:
        raise ProviderError("Structured provider could not be reached") from None


def fixture_rows(name: str) -> tuple[list[Observation], date]:
    """Expand a declared synthetic step scenario; never impute live observations."""
    payload = json.loads((Path(__file__).parent / "data" / f"{name}.json").read_text(encoding="utf-8"))
    start = date.fromisoformat(payload["start_date"])
    end = date.fromisoformat(payload["end_date"])
    levels = [(date.fromisoformat(day), float(value)) for day, value in payload["levels"]]
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        rows.append((day, max((entry for entry in levels if entry[0] <= day), key=lambda entry: entry[0])[1]))
    return rows, end


def window_metadata(old: Observation, new: Observation, target: date, as_of: date, lookback_days: int) -> dict:
    return {
        "requested_lookback_days": lookback_days,
        "requested_as_of": as_of.isoformat(),
        "target_start_date": target.isoformat(),
        "old_date": old[0].isoformat(),
        "new_date": new[0].isoformat(),
        "actual_window_days": (new[0] - old[0]).days,
        "observation_lag_days": (as_of - new[0]).days,
        "window_method": "Latest published observation and last observation on/before its date minus lookback_days; baseline tolerance 7 days.",
        "date_precision": "day; UTC midnight encodes the source date, not an intraday publication timestamp",
    }
