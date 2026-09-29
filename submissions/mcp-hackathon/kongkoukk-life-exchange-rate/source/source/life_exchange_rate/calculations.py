from __future__ import annotations

from math import expm1, log1p

from .models import (
    CalculationStep,
    Confidence,
    EventType,
    ImpactDirection,
    ImpactResult,
    LifeProfile,
    LifeUnitConversion,
    MacroEvent,
    TranslateRequest,
)


def _round(value: float, digits: int = 2) -> float:
    return round(value, digits)


def _direction(delta: float | None) -> ImpactDirection:
    if delta is None:
        return ImpactDirection.UNQUANTIFIED
    if abs(delta) < 1e-9:
        return ImpactDirection.NEUTRAL
    return ImpactDirection.COST_INCREASE if delta > 0 else ImpactDirection.COST_DECREASE


def convert_amount_to_life_units(amount_home: float, profile: LifeProfile) -> tuple[float, list[LifeUnitConversion]]:
    work_hours = amount_home / profile.net_hourly_income
    conversions: list[LifeUnitConversion] = []
    for item in profile.life_units:
        if item.currency != profile.home_currency:
            continue
        conversions.append(
            LifeUnitConversion(
                unit=item.name,
                quantity=_round(amount_home / item.price),
                currency=item.currency,
                unit_price=item.price,
            )
        )
    return _round(work_hours), conversions


def _payment(principal: float, annual_rate_pct: float, years: float) -> float:
    months = int(round(years * 12))
    if months <= 0:
        raise ValueError("remaining_years must imply at least one month")
    monthly_rate = annual_rate_pct / 100 / 12
    if monthly_rate == 0:
        return principal / months
    return principal * monthly_rate / -expm1(-months * log1p(monthly_rate))


def _fx_impact(event: MacroEvent, profile: LifeProfile) -> ImpactResult:
    if not event.base_currency or not event.quote_currency:
        raise ValueError("FX events require base_currency and quote_currency")
    if event.old_value <= 0 or event.new_value <= 0:
        raise ValueError("FX rates must be positive")
    if profile.travel_budget_home is None:
        return ImpactResult(
            event_id=event.event_id,
            headline=event.title,
            home_currency=profile.home_currency,
            explanation="The exchange-rate move is relevant, but no travel budget was supplied, so no personal cost is calculated.",
            confidence=event.confidence,
            warnings=["Add travel_budget_home to quantify the impact."],
        )

    old_rate, new_rate = event.old_value, event.new_value
    if event.base_currency == profile.home_currency:
        target_currency = event.quote_currency
        old_target = profile.travel_budget_home * event.old_value
        new_target = profile.travel_budget_home * event.new_value
        restore_budget = profile.travel_budget_home * event.old_value / event.new_value
    elif event.quote_currency == profile.home_currency:
        target_currency = event.base_currency
        old_rate = 1 / event.old_value
        new_rate = 1 / event.new_value
        old_target = profile.travel_budget_home * old_rate
        new_target = profile.travel_budget_home * new_rate
        restore_budget = profile.travel_budget_home * old_rate / new_rate
    else:
        raise ValueError("FX event must include the profile home currency")

    if profile.travel_target_currency and target_currency != profile.travel_target_currency:
        return ImpactResult(
            event_id=event.event_id,
            headline=event.title,
            home_currency=profile.home_currency,
            explanation=(
                f"This FX move involves {target_currency}, while the supplied travel plan targets "
                f"{profile.travel_target_currency}; no travel impact is quantified."
            ),
            confidence=event.confidence,
            warnings=["Use an FX pair that includes both the home currency and the travel target currency."],
        )

    extra_home = restore_budget - profile.travel_budget_home
    work_hours, units = convert_amount_to_life_units(abs(extra_home), profile)
    more_or_less = "more" if extra_home > 0 else "less"
    explanation = (
        f"To preserve the same {target_currency} purchasing power for the trip, the user would need "
        f"about {abs(extra_home):.2f} {profile.home_currency} {more_or_less} than before."
    )
    return ImpactResult(
        event_id=event.event_id,
        headline=event.title,
        direct_effect_home=_round(extra_home),
        home_currency=profile.home_currency,
        direction=_direction(extra_home),
        impact_horizon="one_off_travel_budget",
        work_hours_equivalent=work_hours,
        life_units=units,
        explanation=explanation,
        confidence=event.confidence,
        assumptions=["Rates in the trace are destination-currency units per home-currency unit.",
                     "Reference-rate comparison excludes retail exchange fees and spreads."],
        calculation_trace=[
            CalculationStep(
                label="old destination purchasing power",
                formula="travel_budget_home × old_fx_rate",
                inputs={"travel_budget_home": profile.travel_budget_home, "old_fx_rate": old_rate},
                result=_round(old_target),
            ),
            CalculationStep(
                label="new destination purchasing power",
                formula="travel_budget_home × new_fx_rate",
                inputs={"travel_budget_home": profile.travel_budget_home, "new_fx_rate": new_rate},
                result=_round(new_target),
            ),
            CalculationStep(
                label="budget required to restore old purchasing power",
                formula="travel_budget_home × old_fx_rate / new_fx_rate",
                inputs={
                    "travel_budget_home": profile.travel_budget_home,
                    "old_fx_rate": old_rate,
                    "new_fx_rate": new_rate,
                },
                result=_round(restore_budget),
            ),
            CalculationStep(
                label="personal impact",
                formula="restore_budget - travel_budget_home",
                inputs={"restore_budget": _round(restore_budget), "travel_budget_home": profile.travel_budget_home},
                result=_round(extra_home),
            ),
        ],
        details={
            "old_target_purchasing_power": _round(old_target),
            "new_target_purchasing_power": _round(new_target),
            "target_currency": target_currency,
            "travel_budget_home": profile.travel_budget_home,
        },
    )


def _interest_impact(request: TranslateRequest) -> ImpactResult:
    event, profile, assumptions = request.event, request.profile, request.assumptions
    delta_points = event.new_value - event.old_value
    pass_through = assumptions.interest_rate_pass_through
    warnings = [
        "Policy-rate changes do not mechanically pass through one-for-one to household borrowing or deposit rates.",
        "This is a scenario estimate, not a forecast of the user's bank rate.",
    ]

    exposure_currency = profile.home_currency
    mortgage_eligible = bool(profile.mortgage and profile.mortgage_currency == profile.home_currency)
    if profile.mortgage and not mortgage_eligible:
        warnings.append("Foreign-currency mortgage excluded: conversion into home currency requires a separate FX model.")
    if not event.affected_currencies or exposure_currency not in event.affected_currencies:
        return ImpactResult(
            event_id=event.event_id,
            headline=event.title,
            home_currency=profile.home_currency,
            explanation=(
                f"The event is scoped to {', '.join(event.affected_currencies)}, while the user's declared rate exposure "
                f"is {exposure_currency}; no direct mortgage or savings impact is calculated."
            ),
            confidence=Confidence.SCENARIO,
            warnings=["Cross-border monetary-policy spillovers require a separate model and are outside the MVP.", "Explicit matching affected_currencies are required for a direct rate scenario."],
            details={"exposure_currency": exposure_currency, "event_affected_currencies": event.affected_currencies},
        )

    details: dict[str, float | str] = {
        "policy_rate_change_percentage_points": _round(delta_points, 4),
        "assumed_pass_through": pass_through,
        "exposure_currency": exposure_currency,
    }
    trace: list[CalculationStep] = []
    monthly_effect = 0.0

    if mortgage_eligible:
        current = profile.mortgage.current_annual_rate_pct
        assumed_new = max(0.0, current + delta_points * pass_through)
        old_payment = _payment(profile.mortgage.principal, current, profile.mortgage.remaining_years)
        new_payment = _payment(profile.mortgage.principal, assumed_new, profile.mortgage.remaining_years)
        mortgage_delta = new_payment - old_payment
        monthly_effect += mortgage_delta
        details.update(
            {
                "mortgage_old_monthly_payment": _round(old_payment),
                "mortgage_scenario_monthly_payment": _round(new_payment),
                "mortgage_monthly_delta": _round(mortgage_delta),
                "mortgage_scenario_rate_pct": _round(assumed_new, 4),
            }
        )
        trace.append(
            CalculationStep(
                label="mortgage scenario rate",
                formula="max(0, current_mortgage_rate + policy_rate_change × pass_through)",
                inputs={"current_rate_pct": current, "policy_change_pp": delta_points, "pass_through": pass_through},
                result=_round(assumed_new, 4),
            )
        )

    if profile.savings_balance:
        savings_delta = profile.savings_balance * (delta_points * pass_through / 100) / 12
        monthly_effect -= savings_delta
        details["savings_monthly_interest_delta"] = _round(savings_delta)
        trace.append(
            CalculationStep(
                label="savings interest offset",
                formula="savings_balance × policy_rate_change / 100 × pass_through / 12",
                inputs={"savings_balance": profile.savings_balance, "policy_change_pp": delta_points, "pass_through": pass_through},
                result=_round(savings_delta),
            )
        )

    if not mortgage_eligible and not profile.savings_balance:
        return ImpactResult(
            event_id=event.event_id,
            headline=event.title,
            home_currency=profile.home_currency,
            explanation="The rate move may matter, but the profile has no mortgage or savings exposure to quantify.",
            confidence=Confidence.SCENARIO,
            assumptions=[f"Interest-rate pass-through set to {pass_through:.0%}."],
            warnings=warnings,
            details=details,
        )

    work_hours, units = convert_amount_to_life_units(abs(monthly_effect), profile)
    direction = "higher" if monthly_effect > 0 else "lower"
    trace.append(
        CalculationStep(
            label="net monthly household impact",
            formula="mortgage_payment_delta - savings_interest_delta",
            inputs={
                "mortgage_payment_delta": details.get("mortgage_monthly_delta", 0.0),
                "savings_interest_delta": details.get("savings_monthly_interest_delta", 0.0),
            },
            result=_round(monthly_effect),
        )
    )
    return ImpactResult(
        event_id=event.event_id,
        headline=event.title,
        direct_effect_home=_round(monthly_effect),
        home_currency=profile.home_currency,
        direction=_direction(monthly_effect),
        impact_horizon="monthly_scenario",
        work_hours_equivalent=work_hours,
        life_units=units,
        explanation=f"Under the chosen pass-through assumption, monthly net household cost is about {abs(monthly_effect):.2f} {profile.home_currency} {direction}.",
        confidence=Confidence.SCENARIO,
        assumptions=[f"Interest-rate pass-through set to {pass_through:.0%}."],
        warnings=warnings,
        calculation_trace=trace,
        details=details,
    )


def _oil_impact(request: TranslateRequest) -> ImpactResult:
    event, profile, assumptions = request.event, request.profile, request.assumptions
    if not profile.commute:
        return ImpactResult(
            event_id=event.event_id,
            headline=event.title,
            home_currency=profile.home_currency,
            explanation="The oil-price move may affect transport costs, but no fuel-consumption profile was supplied.",
            confidence=Confidence.SCENARIO,
            warnings=["Add commute.monthly_fuel_liters and fuel_price_per_liter to quantify a scenario."],
        )

    crude_change = event.change_pct
    if crude_change is None:
        if event.old_value == 0:
            raise ValueError("Cannot derive oil change from a zero old_value")
        crude_change = (event.new_value / event.old_value - 1) * 100

    pass_through = assumptions.oil_to_fuel_pass_through
    fuel_pct_change = crude_change * pass_through
    old_monthly = profile.commute.monthly_fuel_liters * profile.commute.fuel_price_per_liter
    new_monthly = old_monthly * (1 + fuel_pct_change / 100)
    delta = new_monthly - old_monthly
    work_hours, units = convert_amount_to_life_units(abs(delta), profile)
    return ImpactResult(
        event_id=event.event_id,
        headline=event.title,
        direct_effect_home=_round(delta),
        home_currency=profile.home_currency,
        direction=_direction(delta),
        impact_horizon="monthly_scenario",
        work_hours_equivalent=work_hours,
        life_units=units,
        explanation=f"Under the selected pass-through scenario, monthly fuel spending changes by about {delta:.2f} {profile.home_currency}.",
        confidence=Confidence.SCENARIO,
        assumptions=[f"{pass_through:.0%} of the crude-oil percentage move is applied to the user's pump price as a scenario."],
        warnings=[
            "Crude-oil prices do not translate one-for-one into retail fuel prices.",
            "Taxes, refining, distribution, inventories, currency moves, and timing can materially change pass-through.",
        ],
        calculation_trace=[
            CalculationStep(
                label="fuel-price scenario move",
                formula="crude_change_pct × pass_through",
                inputs={"crude_change_pct": _round(crude_change), "pass_through": pass_through},
                result=_round(fuel_pct_change),
            ),
            CalculationStep(
                label="baseline monthly fuel spend",
                formula="monthly_fuel_liters × fuel_price_per_liter",
                inputs={
                    "monthly_fuel_liters": profile.commute.monthly_fuel_liters,
                    "fuel_price_per_liter": profile.commute.fuel_price_per_liter,
                },
                result=_round(old_monthly),
            ),
            CalculationStep(
                label="monthly impact",
                formula="baseline_monthly_spend × scenario_fuel_change_pct / 100",
                inputs={"baseline_monthly_spend": _round(old_monthly), "scenario_fuel_change_pct": _round(fuel_pct_change)},
                result=_round(delta),
            ),
        ],
        details={
            "crude_change_pct": _round(crude_change),
            "scenario_fuel_change_pct": _round(fuel_pct_change),
            "old_monthly_fuel_cost": _round(old_monthly),
            "scenario_monthly_fuel_cost": _round(new_monthly),
        },
    )


def translate_event(request: TranslateRequest) -> ImpactResult:
    if request.event.event_type == EventType.FX_MOVE:
        result = _fx_impact(request.event, request.profile)
    elif request.event.event_type == EventType.INTEREST_RATE_CHANGE:
        result = _interest_impact(request)
    elif request.event.event_type == EventType.OIL_MOVE:
        result = _oil_impact(request)
    else:
        raise ValueError(f"Unsupported event type: {request.event.event_type}")
    result.event_provenance = request.event.provenance
    result.event_observed_at = request.event.observed_at
    if request.event.provenance and request.event.provenance.source_type in ("fixture", "synthetic_fixture"):
        result.warnings.append("This event uses a synthetic judging fixture, not a current market observation.")
    return result
