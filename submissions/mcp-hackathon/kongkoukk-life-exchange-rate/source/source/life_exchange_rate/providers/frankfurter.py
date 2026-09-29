from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from ..models import Confidence, EventType, MacroEvent, Provenance
from .fx_anomaly import rolling_log_return_anomaly


class FrankfurterProvider:
    """Daily ECB reference rates, with an auditable comparison to prior volatility."""

    def __init__(
        self,
        base_url: str = "https://api.frankfurter.dev",
        timeout: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _extract_rows(payload: Any) -> list[dict[str, Any]]:
        # v2 returns an array. Retain compatible wrapper shapes without
        # dropping malformed rows silently.
        if isinstance(payload, dict):
            if isinstance(payload.get("rates"), list):
                payload = payload["rates"]
            elif {"date", "rate"}.issubset(payload):
                payload = [payload]
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ValueError("Unexpected Frankfurter response shape")
        return payload

    @staticmethod
    def _validate_request(base: str, quote: str, lookback_days: int) -> tuple[str, str]:
        currencies = []
        for value in (base, quote):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
                raise ValueError("FX currencies must be three ASCII letters")
            currencies.append(value.upper())
        if currencies[0] == currencies[1]:
            raise ValueError("FX base and quote must be different currencies")
        if type(lookback_days) is not int or not 2 <= lookback_days <= 90:
            raise ValueError("lookback_days must be an integer from 2 to 90")
        return currencies[0], currencies[1]

    @staticmethod
    def _observations(
        rows: list[dict[str, Any]], base: str, quote: str, start: date, end: date
    ) -> tuple[list[tuple[date, float]], int]:
        observations: dict[date, float] = {}
        duplicate_count = 0
        for row in rows:
            if str(row.get("base", "")).upper() != base or str(row.get("quote", "")).upper() != quote:
                raise ValueError("Frankfurter returned a missing or mismatched currency pair")
            raw_date = row.get("date")
            try:
                observed_date = date.fromisoformat(raw_date)
            except (TypeError, ValueError) as exc:
                raise ValueError("Frankfurter returned an invalid observation date") from exc
            # Frankfurter can backfill a weekend/holiday `from` date to the
            # previous reference observation. Permit only bounded start padding;
            # future/end padding is never accepted.
            if observed_date.isoformat() != raw_date or not start - timedelta(days=7) <= observed_date <= end:
                raise ValueError("Frankfurter returned a non-ISO or out-of-query observation date")
            raw_rate = row.get("rate")
            if isinstance(raw_rate, bool) or not isinstance(raw_rate, (int, float, str)):
                raise ValueError("Frankfurter returned an invalid FX rate")
            try:
                rate = float(raw_rate)
            except (ValueError, OverflowError) as exc:
                raise ValueError("Frankfurter returned an invalid FX rate") from exc
            if not math.isfinite(rate) or rate <= 0:
                raise ValueError("Frankfurter FX rates must be positive and finite")
            if observed_date in observations:
                if observations[observed_date] != rate:
                    raise ValueError("Frankfurter returned conflicting rates for one observation date")
                duplicate_count += 1
            observations[observed_date] = rate
        return sorted(observations.items()), duplicate_count

    async def fx_move(self, base: str, quote: str, lookback_days: int = 7) -> MacroEvent:
        base, quote = self._validate_request(base, quote, lookback_days)
        end = self.now().astimezone(timezone.utc).date()
        # Two horizons plus a year and holiday buffer provide event endpoints
        # and preceding comparison windows in one bounded call.
        start = end - timedelta(days=2 * lookback_days + 380)
        url = f"{self.base_url}/v2/providers/ecb/rates"
        params = {"from": start.isoformat(), "to": end.isoformat(), "base": base, "quotes": quote}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            query_url = str(response.request.url)
            rows = self._extract_rows(response.json())

        observations, duplicate_count = self._observations(rows, base, quote, start, end)
        if len(observations) < 2:
            raise ValueError("Not enough FX observations returned")
        new_date, new_rate = observations[-1]
        if (end - new_date).days > 14:
            raise ValueError("Latest FX observation is more than 14 calendar days old")
        target_date = new_date - timedelta(days=lookback_days)
        prior = [(day, rate) for day, rate in observations if day <= target_date]
        if not prior:
            raise ValueError("No FX observation on or before the requested lookback date")
        old_date, old_rate = prior[-1]
        if (target_date - old_date).days > 7:
            raise ValueError("FX baseline observation is more than 7 calendar days before the requested anchor")
        change_pct = (new_rate / old_rate - 1) * 100
        if not math.isfinite(change_pct):
            raise ValueError("FX percentage change is outside the supported numeric range")
        observed = datetime.combine(new_date, time.min, timezone.utc)
        window_start = datetime.combine(old_date, time.min, timezone.utc)
        anomaly = rolling_log_return_anomaly(observations, old_date, new_date)
        metadata = {
            "old_date": old_date.isoformat(),
            "new_date": new_date.isoformat(),
            "provider": "ECB",
            "requested_lookback_days": lookback_days,
            "target_old_date": target_date.isoformat(),
            "actual_calendar_days": (new_date - old_date).days,
            "anchor_gap_days": (target_date - old_date).days,
            "latest_observation_age_days": (end - new_date).days,
            "query_start_date": start.isoformat(),
            "query_end_date": end.isoformat(),
            "history_start_date": observations[0][0].isoformat(),
            "pre_query_observation_count": sum(day < start for day, _ in observations),
            "query_url": query_url,
            "history_observation_count": len(observations),
            "identical_duplicates_removed": duplicate_count,
            "anomaly": anomaly,
        }
        if anomaly["z_score"] is not None:
            metadata["z_score"] = anomaly["z_score"]
        notes = [
            "Query uses the dedicated ECB provider route; observations are daily reference rates, not executable quotes.",
            "Up to seven calendar days of provider backfill before the query start are retained and counted separately.",
            "Observation timestamps represent source dates at 00:00 UTC, not publication times.",
            f"Requested {lookback_days} calendar days; actual observed window is {old_date} through {new_date}.",
            "Anomaly reference windows end on or before the event start; overlapping reference windows are descriptive, not independent trials.",
        ]
        if anomaly["fallback_reason"]:
            notes.append(f"Volatility score unavailable: {anomaly['fallback_reason']}; radar uses percentage-move fallback.")
        if (end - new_date).days > 7:
            notes.append(f"Latest reference observation is {(end - new_date).days} calendar days old.")
        return MacroEvent(
            event_id=f"fx-{base}-{quote}-{old_date}-{new_date}",
            event_type=EventType.FX_MOVE,
            title=f"{base}/{quote} moved {change_pct:+.2f}% from {old_date} to {new_date}",
            source="Frankfurter / ECB",
            observed_at=observed,
            old_value=old_rate,
            new_value=new_rate,
            unit=f"{quote} per {base}",
            change_pct=change_pct,
            base_currency=base,
            quote_currency=quote,
            affected_currencies=[base, quote],
            evidence_url="https://frankfurter.dev/providers/ecb/",
            window_start=window_start,
            window_end=observed,
            confidence=Confidence.OBSERVED,
            provenance=Provenance(
                provider="Frankfurter (ECB reference-rate provider)",
                source_type="structured_intermediary_official_provider",
                retrieved_at=self.now().astimezone(timezone.utc),
                series_id=f"ECB:{base}/{quote}",
                source_url=query_url,
                notes=notes,
            ),
            metadata=metadata,
        )
