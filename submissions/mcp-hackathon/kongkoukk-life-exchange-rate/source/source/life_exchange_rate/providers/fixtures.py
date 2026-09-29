from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import (
    CommuteProfile,
    Confidence,
    EventType,
    LifeProfile,
    LifeUnit,
    MacroEvent,
    MortgageProfile,
    Provenance,
)


def demo_events() -> list[MacroEvent]:
    now = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    return [
        MacroEvent(
            event_id="demo-jpy-sek-8pct",
            event_type=EventType.FX_MOVE,
            title="JPY strengthens sharply against SEK",
            source="synthetic judging fixture",
            observed_at=now,
            old_value=15.00,
            new_value=13.80,
            unit="JPY per SEK",
            change_pct=-8.0,
            base_currency="SEK",
            quote_currency="JPY",
            affected_currencies=["SEK", "JPY"],
            evidence_url=None,
            window_start=now - timedelta(days=7),
            window_end=now,
            confidence=Confidence.SCENARIO,
            provenance=Provenance(provider="demo-fixture", source_type="fixture", retrieved_at=now, notes=["Synthetic scenario; values and z-score are illustrative, not official observations."]),
            metadata={"demo": True, "z_score": -3.2},
        ),
        MacroEvent(
            event_id="demo-se-policy-rate-25bp",
            event_type=EventType.INTEREST_RATE_CHANGE,
            title="Swedish policy rate rises by 25 basis points",
            source="demo-fixture",
            observed_at=now,
            old_value=4.00,
            new_value=4.25,
            unit="percent",
            change_pct=6.25,
            affected_currencies=["SEK"],
            jurisdiction="SE",
            confidence=Confidence.SCENARIO,
            provenance=Provenance(provider="demo-fixture", source_type="fixture", retrieved_at=now, notes=["Synthetic scenario, not official observations."]),
            metadata={"demo": True},
        ),
        MacroEvent(
            event_id="demo-brent-15pct",
            event_type=EventType.OIL_MOVE,
            title="Brent crude rises 15% over the observation window",
            source="demo-fixture",
            observed_at=now,
            old_value=80.0,
            new_value=92.0,
            unit="USD per barrel",
            change_pct=15.0,
            confidence=Confidence.SCENARIO,
            provenance=Provenance(provider="demo-fixture", source_type="fixture", retrieved_at=now, notes=["Synthetic scenario; values and z-score are illustrative, not official observations."]),
            metadata={"demo": True, "z_score": 2.4},
        ),
    ]


def demo_profile() -> LifeProfile:
    return LifeProfile(
        home_currency="SEK",
        home_country="SE",
        net_monthly_income=32000,
        monthly_work_hours=160,
        travel_budget_home=20000,
        travel_target_currency="JPY",
        mortgage=MortgageProfile(
            principal=2500000,
            remaining_years=25,
            current_annual_rate_pct=3.8,
            currency="SEK",
        ),
        savings_balance=100000,
        commute=CommuteProfile(monthly_fuel_liters=65, fuel_price_per_liter=18.5),
        life_units=[
            LifeUnit(name="beer", price=80, currency="SEK"),
            LifeUnit(name="coffee", price=45, currency="SEK"),
            LifeUnit(name="lunch", price=140, currency="SEK"),
        ],
    )
