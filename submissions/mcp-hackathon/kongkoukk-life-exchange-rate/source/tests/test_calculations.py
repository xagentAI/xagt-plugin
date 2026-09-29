from life_exchange_rate.models import (
    CommuteProfile,
    EventType,
    LifeProfile,
    LifeUnit,
    MacroEvent,
    MortgageProfile,
    TranslateRequest,
)
from life_exchange_rate.service import translate_request


def profile() -> LifeProfile:
    return LifeProfile(
        home_currency="SEK",
        home_country="SE",
        net_monthly_income=32000,
        monthly_work_hours=160,
        travel_budget_home=20000,
        travel_target_currency="JPY",
        mortgage=MortgageProfile(principal=2500000, remaining_years=25, current_annual_rate_pct=3.8, currency="SEK"),
        savings_balance=100000,
        commute=CommuteProfile(monthly_fuel_liters=65, fuel_price_per_liter=18.5),
        life_units=[LifeUnit(name="beer", price=80, currency="SEK")],
    )


def test_fx_stronger_jpy_requires_more_home_budget_and_trace():
    event = MacroEvent(
        event_id="fx",
        event_type=EventType.FX_MOVE,
        title="JPY strengthens",
        source="test",
        old_value=15.0,
        new_value=13.8,
        unit="JPY per SEK",
        base_currency="SEK",
        quote_currency="JPY",
    )
    result = translate_request(TranslateRequest(event=event, profile=profile()))
    assert result["direct_effect_home"] > 0
    assert 1700 < result["direct_effect_home"] < 1800
    assert result["work_hours_equivalent"] > 8
    assert result["direction"] == "cost_increase"
    assert len(result["calculation_trace"]) >= 4


def test_interest_rate_result_is_scenario_labeled():
    event = MacroEvent(
        event_id="rate",
        event_type=EventType.INTEREST_RATE_CHANGE,
        title="Swedish rate up",
        source="test",
        old_value=4.0,
        new_value=4.25,
        unit="percent",
        affected_currencies=["SEK"],
        jurisdiction="SE",
    )
    result = translate_request(TranslateRequest(event=event, profile=profile()))
    assert result["confidence"] == "scenario"
    assert result["assumptions"]
    assert result["details"]["mortgage_monthly_delta"] > 0


def test_foreign_policy_rate_does_not_apply_directly_to_sek_mortgage():
    event = MacroEvent(
        event_id="fed",
        event_type=EventType.INTEREST_RATE_CHANGE,
        title="Fed rate up",
        source="test",
        old_value=5.0,
        new_value=5.25,
        unit="percent",
        affected_currencies=["USD"],
        jurisdiction="US",
    )
    result = translate_request(TranslateRequest(event=event, profile=profile()))
    assert result["direct_effect_home"] is None
    assert result["direction"] == "unquantified"
    assert "outside the MVP" in result["warnings"][0]


def test_oil_result_warns_about_pass_through():
    event = MacroEvent(
        event_id="oil",
        event_type=EventType.OIL_MOVE,
        title="Brent up",
        source="test",
        old_value=80,
        new_value=92,
        unit="USD per barrel",
        change_pct=15,
    )
    result = translate_request(TranslateRequest(event=event, profile=profile()))
    assert result["direct_effect_home"] > 0
    assert any("one-for-one" in warning for warning in result["warnings"])
    assert result["calculation_trace"]
