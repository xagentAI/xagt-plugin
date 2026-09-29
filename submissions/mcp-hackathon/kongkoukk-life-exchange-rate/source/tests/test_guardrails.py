import math

import pytest
from pydantic import ValidationError

from life_exchange_rate.calculations import _payment
from life_exchange_rate.models import MacroEvent, ScenarioInput, ScenarioRequest, TranslateRequest
from life_exchange_rate.providers.fixtures import demo_events, demo_profile
from life_exchange_rate.service import compare_scenarios, translate_request


def test_inverse_fx_trace_and_amount_match_forward_quote():
    forward = demo_events()[0]
    inverse_data = forward.model_dump()
    inverse_data.update(base_currency="JPY", quote_currency="SEK", unit="SEK per JPY",
                        old_value=1 / forward.old_value, new_value=1 / forward.new_value, change_pct=None)
    inverse = MacroEvent.model_validate(inverse_data)
    result = translate_request(TranslateRequest(event=inverse, profile=demo_profile()))
    direct = translate_request(TranslateRequest(event=forward, profile=demo_profile()))
    assert result["direct_effect_home"] == direct["direct_effect_home"] == 1739.13
    for step in result["calculation_trace"][:2]:
        inputs = step["inputs"]
        rate = inputs.get("old_fx_rate", inputs.get("new_fx_rate"))
        assert round(inputs["travel_budget_home"] * rate, 2) == step["result"]


def test_foreign_mortgage_is_not_counted_as_home_money():
    profile = demo_profile()
    profile.mortgage.currency = "USD"
    profile.savings_balance = None
    result = translate_request(TranslateRequest(event=demo_events()[1], profile=profile))
    assert result["direct_effect_home"] is None
    assert any("Foreign-currency mortgage" in warning for warning in result["warnings"])


def test_home_savings_remain_eligible_when_foreign_mortgage_excluded():
    profile = demo_profile()
    profile.mortgage.currency = "USD"
    result = translate_request(TranslateRequest(event=demo_events()[1], profile=profile))
    assert result["direct_effect_home"] == -10.42
    assert "mortgage_monthly_delta" not in result["details"]


def test_unscoped_policy_cannot_drive_calculation():
    event = demo_events()[1].model_copy(update={"affected_currencies": []})
    result = translate_request(TranslateRequest(event=event, profile=demo_profile()))
    assert result["direct_effect_home"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_market_values_rejected(value):
    data = demo_events()[0].model_dump()
    data["new_value"] = value
    with pytest.raises(ValidationError):
        MacroEvent.model_validate(data)


def test_conflicting_percent_and_missing_structured_values_rejected():
    data = demo_events()[2].model_dump()
    data["change_pct"] = 100
    with pytest.raises(ValidationError, match="agree"):
        MacroEvent.model_validate(data)
    with pytest.raises(ValidationError):
        MacroEvent.model_validate({"title": "Rates rise", "requires_quantification": True})


def test_scenarios_are_labeled_and_invalid_scaled_prices_rejected():
    request = ScenarioRequest(event=demo_events()[0], profile=demo_profile(),
                              scenarios=[ScenarioInput(label="mild", multiplier=.5)])
    result = compare_scenarios(request)[0]["result"]
    assert result["confidence"] == "scenario"
    request.scenarios = [ScenarioInput(label="invalid", multiplier=20)]
    with pytest.raises(ValidationError, match="positive"):
        compare_scenarios(request)


def test_fixtures_are_stable_and_carry_provenance_to_result():
    assert [e.model_dump() for e in demo_events()] == [e.model_dump() for e in demo_events()]
    event = demo_events()[0]
    result = translate_request(TranslateRequest(event=event, profile=demo_profile()))
    assert result["event_provenance"]["source_type"] == "fixture"
    assert result["confidence"] == "scenario"
    assert any("synthetic" in warning for warning in result["warnings"])


def test_payment_is_stable_near_zero_and_at_high_rates():
    assert _payment(120000, 0, 10) == 1000
    assert _payment(120000, 1e-12, 10) == pytest.approx(1000)
    assert math.isfinite(_payment(120000, 100, 1000))


def test_radar_does_not_claim_relevance_for_excluded_exposures():
    from life_exchange_rate.radar import score_user_relevance
    profile = demo_profile()
    rate = demo_events()[1].model_copy(update={"affected_currencies": ["EUR"]})
    assert score_user_relevance(rate, profile)[0] == 0
    profile.commute.monthly_fuel_liters = 0
    assert score_user_relevance(demo_events()[2], profile)[0] == 0
    profile.travel_target_currency = "USD"
    assert score_user_relevance(demo_events()[0], profile)[0] == 0
