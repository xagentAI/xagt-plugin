"""EIA API v2 Brent daily spot prices with explicit synthetic fallback."""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date, datetime, timedelta

import httpx

from ..models import Confidence, EventType, MacroEvent, Provenance
from .common import (
    Observation, ProviderError, ProviderMode, fetch, fixture_rows, numeric_value,
    observation_date, observation_time, select_window, utc_now, validate_request, window_metadata,
)


class EnergyProvider:
    SERIES_ID = "PET.RBRTE.D"
    API_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
    SOURCE_URL = "https://www.eia.gov/dnav/pet/hist/RBRTED.htm"

    def __init__(
        self, api_key: str | None = None, timeout: float = 10.0, *,
        transport: httpx.AsyncBaseTransport | None = None,
        today: Callable[[], date] | None = None, now: Callable[[], datetime] = utc_now,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("EIA_API_KEY", "")
        self.timeout, self.transport, self.now = timeout, transport, now
        self.today = today or (lambda: self.now().date())

    @staticmethod
    def _parse(payload: object) -> list[Observation]:
        if not isinstance(payload, dict) or payload.get("error"):
            raise ProviderError("EIA returned an invalid structured response")
        response = payload.get("response")
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ProviderError("EIA response is missing required structured fields")
        data = response["data"]
        try:
            if "total" in response and int(response["total"]) != len(data):
                raise ProviderError("EIA response is incomplete; pagination or a narrower query is required")
        except (TypeError, ValueError):
            raise ProviderError("EIA response is incomplete or has an invalid record count") from None
        rows = []
        for row in data:
            if not isinstance(row, dict) or row.get("series") != "RBRTE":
                raise ProviderError("EIA response contains an unexpected series")
            if row.get("units") != "Dollars per Barrel":
                raise ProviderError("EIA response contains unexpected units")
            rows.append((observation_date(row.get("period")), numeric_value(row.get("value"), positive=True)))
        return rows

    async def oil_move(self, lookback_days: int = 7, mode: ProviderMode = "live_or_fixture") -> MacroEvent:
        validate_request(lookback_days, mode)
        requested_as_of = self.today()
        as_of, fallback_reason = requested_as_of, None
        synthetic = mode == "fixture"
        if not synthetic:
            try:
                if not self.api_key.strip():
                    raise ProviderError("EIA_API_KEY is not configured")
                response = await fetch(self.API_URL, {
                    "api_key": self.api_key, "frequency": "daily", "data[0]": "value",
                    "facets[series][]": "RBRTE",
                    "start": (as_of - timedelta(days=lookback_days + 28)).isoformat(), "end": as_of.isoformat(),
                    "sort[0][column]": "period", "sort[0][direction]": "asc", "offset": "0", "length": "5000",
                }, self.timeout, self.transport)
                try:
                    rows = self._parse(response.json())
                except (ValueError, TypeError) as exc:
                    if isinstance(exc, ProviderError):
                        raise
                    raise ProviderError("EIA response is not valid structured JSON") from None
                old, new, target = select_window(rows, as_of, lookback_days)
                numeric_value((new[1] / old[1] - 1) * 100)
            except ProviderError as exc:
                if mode == "live":
                    raise
                synthetic, fallback_reason = True, str(exc)
        if synthetic:
            rows, as_of = fixture_rows("energy")
            old, new, target = select_window(rows, as_of, lookback_days)
        change_pct = (new[1] / old[1] - 1) * 100
        metadata = window_metadata(old, new, target, as_of, lookback_days)
        metadata.update({
            "provider": "synthetic-fixture" if synthetic else "EIA",
            "synthetic": synthetic, "mode": mode, "fallback_used": fallback_reason is not None,
            "commodity": "Brent crude oil", "price_currency": "USD", "scope": "Brent Europe spot benchmark",
        })
        if synthetic:
            metadata.update({"fixture_anchor_date": as_of.isoformat(), "live_request_as_of": requested_as_of.isoformat()})
        if fallback_reason:
            metadata["fallback_reason"] = fallback_reason
        return MacroEvent(
            event_id=f"{'synthetic' if synthetic else 'eia'}-brent-{old[0]}-{new[0]}", event_type=EventType.OIL_MOVE,
            title=f"{'Synthetic scenario: ' if synthetic else ''}Brent crude moved {change_pct:+.2f}% over the observation window",
            source="synthetic judging fixture" if synthetic else "U.S. Energy Information Administration",
            observed_at=observation_time(new[0]), old_value=old[1], new_value=new[1], unit="USD per barrel", change_pct=change_pct,
            evidence_url=None if synthetic else self.SOURCE_URL,
            window_start=observation_time(old[0]), window_end=observation_time(new[0]),
            confidence=Confidence.SCENARIO if synthetic else Confidence.OBSERVED,
            provenance=Provenance(
                provider="synthetic-fixture" if synthetic else "U.S. Energy Information Administration",
                source_type="synthetic_fixture" if synthetic else "official_structured", retrieved_at=self.now(),
                series_id="synthetic-brent-step-v1" if synthetic else self.SERIES_ID,
                source_url=None if synthetic else self.API_URL,
                notes=["Synthetic fixed step scenario; values and dates are not EIA observations."] if synthetic else [
                    "EIA API v2; frequency=daily, series=RBRTE, value in Dollars per Barrel.",
                    "Brent benchmark move only; household fuel pass-through is a separate explicit scenario assumption.",
                    "API key, keyed request URL, and remote request echoes are never retained in provenance.",
                ],
            ), metadata=metadata,
        )
