"""Official ECB deposit-facility daily levels; headlines never supply values."""
from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import date, datetime, timedelta

import httpx

from ..models import Confidence, EventType, MacroEvent, Provenance
from .common import (
    Observation, ProviderError, ProviderMode, fetch, fixture_rows, numeric_value,
    observation_date, observation_time, select_window, utc_now, validate_request, window_metadata,
)


class PolicyRateProvider:
    SERIES_ID = "FM.D.U2.EUR.4F.KR.DFR.LEV"
    SOURCE_URL = "https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV"
    API_URL = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV"

    def __init__(
        self, timeout: float = 10.0, *, transport: httpx.AsyncBaseTransport | None = None,
        today: Callable[[], date] | None = None, now: Callable[[], datetime] = utc_now,
    ):
        self.timeout, self.transport, self.now = timeout, transport, now
        self.today = today or (lambda: self.now().date())

    @classmethod
    def _parse(cls, content: str) -> list[Observation]:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        if not {"KEY", "TIME_PERIOD", "OBS_VALUE", "UNIT", "UNIT_MULT"}.issubset(reader.fieldnames or []):
            raise ProviderError("ECB response is missing required structured fields")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ProviderError("ECB response contains duplicate structured fields")
        rows = []
        try:
            for row in reader:
                if row.get("KEY") != cls.SERIES_ID:
                    raise ProviderError("ECB response contains an unexpected series")
                if row.get("UNIT") not in ("PC", "PCPA") or row.get("UNIT_MULT") != "0":
                    raise ProviderError("ECB response contains unexpected units")
                if row.get("OBS_STATUS") in {"M", "L"}:
                    raise ProviderError("ECB response contains an unavailable observation")
                rows.append((observation_date(row.get("TIME_PERIOD")), numeric_value(row.get("OBS_VALUE"))))
        except csv.Error:
            raise ProviderError("ECB response is not valid structured CSV") from None
        return rows

    async def policy_rate_move(self, lookback_days: int = 30, mode: ProviderMode = "live_or_fixture") -> MacroEvent:
        validate_request(lookback_days, mode)
        requested_as_of = self.today()
        as_of, fallback_reason = requested_as_of, None
        synthetic = mode == "fixture"
        if not synthetic:
            try:
                response = await fetch(self.API_URL, {
                    "startPeriod": (as_of - timedelta(days=lookback_days + 28)).isoformat(),
                    "endPeriod": as_of.isoformat(), "format": "csvdata",
                }, self.timeout, self.transport)
                rows = self._parse(response.text)
                old, new, target = select_window(rows, as_of, lookback_days)
                numeric_value((new[1] - old[1]) * 100)
            except ProviderError as exc:
                if mode == "live":
                    raise
                synthetic, fallback_reason = True, str(exc)
        if synthetic:
            rows, as_of = fixture_rows("policy_rate")
            old, new, target = select_window(rows, as_of, lookback_days)
        delta_bp = (new[1] - old[1]) * 100
        metadata = window_metadata(old, new, target, as_of, lookback_days)
        metadata.update({
            "provider": "synthetic-fixture" if synthetic else "ECB",
            "synthetic": synthetic, "mode": mode, "fallback_used": fallback_reason is not None,
            "change_basis_points": delta_bp, "change_percentage_points": new[1] - old[1],
            "scope": "Euro area; EUR exposures only", "rate_name": "deposit facility",
        })
        if synthetic:
            metadata.update({"fixture_anchor_date": as_of.isoformat(), "live_request_as_of": requested_as_of.isoformat()})
        if fallback_reason:
            metadata["fallback_reason"] = fallback_reason
        return MacroEvent(
            event_id=f"{'synthetic' if synthetic else 'ecb'}-deposit-rate-{old[0]}-{new[0]}",
            event_type=EventType.INTEREST_RATE_CHANGE,
            title=f"{'Synthetic scenario: ' if synthetic else ''}Euro-area deposit facility rate moved {delta_bp:+.1f} basis points",
            source="synthetic judging fixture" if synthetic else "European Central Bank",
            observed_at=observation_time(new[0]), old_value=old[1], new_value=new[1],
            unit="percent", change_pct=None, affected_currencies=["EUR"], jurisdiction="EA",
            evidence_url=None if synthetic else self.SOURCE_URL,
            window_start=observation_time(old[0]), window_end=observation_time(new[0]),
            confidence=Confidence.SCENARIO if synthetic else Confidence.OBSERVED,
            provenance=Provenance(
                provider="synthetic-fixture" if synthetic else "European Central Bank",
                source_type="synthetic_fixture" if synthetic else "official_structured",
                retrieved_at=self.now(), series_id="synthetic-policy-rate-step-v1" if synthetic else self.SERIES_ID,
                source_url=None if synthetic else self.API_URL,
                notes=["Synthetic fixed step scenario; values and dates are not ECB observations."] if synthetic else [
                    "ECB daily deposit facility levels, percent per annum; signed basis-point change is 100 × (new − old).",
                    "Daily levels measure the requested window; this does not identify a specific monetary-policy announcement.",
                ],
            ), metadata=metadata,
        )
