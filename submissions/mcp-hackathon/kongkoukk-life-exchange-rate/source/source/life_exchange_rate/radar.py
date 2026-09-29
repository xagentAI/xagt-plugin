from __future__ import annotations

import math

from .models import EventScore, EventType, LifeProfile, MacroEvent


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 1)))


def score_market_significance(event: MacroEvent) -> tuple[float, str]:
    """Transparent heuristic. If a provider supplies a z-score, prefer it over type-specific fallbacks."""
    z = event.metadata.get("z_score")
    if isinstance(z, (int, float)) and not isinstance(z, bool):
        try:
            numeric_z = float(z)
        except OverflowError:
            numeric_z = None
        if numeric_z is not None and math.isfinite(numeric_z):
            return _clamp(abs(numeric_z) * 25.0), "provider_z_score"

    if event.event_type == EventType.FX_MOVE:
        move = abs(event.change_pct or 0.0)
        return _clamp(move * 18.0), "fallback_fx_percent_move"
    if event.event_type == EventType.OIL_MOVE:
        move = abs(event.change_pct or 0.0)
        return _clamp(move * 6.0), "fallback_oil_percent_move"
    if event.event_type == EventType.INTEREST_RATE_CHANGE:
        basis_points = abs(event.new_value - event.old_value) * 100
        return _clamp(basis_points * 1.8), "fallback_policy_rate_basis_points"
    return 0.0, "unsupported"


def score_user_relevance(event: MacroEvent, profile: LifeProfile) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if event.event_type == EventType.FX_MOVE:
        pair = {event.base_currency, event.quote_currency}
        if profile.home_currency not in pair or (profile.travel_target_currency and profile.travel_target_currency not in pair):
            return 0.0, ["FX pair does not match the declared home/travel currency exposure"]
        if profile.home_currency in pair:
            score += 35
            reasons.append("FX pair includes the user's home currency")
        if profile.travel_target_currency and profile.travel_target_currency in pair:
            score += 45
            reasons.append("FX pair includes the user's travel target currency")
        if profile.travel_budget_home is not None:
            score += 20
            reasons.append("User supplied a travel budget")

    elif event.event_type == EventType.INTEREST_RATE_CHANGE:
        exposure_currency = profile.home_currency
        mortgage_eligible = bool(profile.mortgage and profile.mortgage_currency == profile.home_currency)
        if exposure_currency not in event.affected_currencies:
            return 0.0, ["Policy-rate currency scope does not support a direct home-currency impact"]
        if not mortgage_eligible and not profile.savings_balance:
            return 0.0, ["No eligible home-currency mortgage or savings exposure"]
        if mortgage_eligible:
            score += 40
            reasons.append("User has declared mortgage exposure")
        if profile.savings_balance:
            score += 20
            reasons.append("User has declared savings exposure")
        if not event.affected_currencies or exposure_currency in event.affected_currencies:
            score += 30
            reasons.append("Policy-rate scope matches the user's declared currency exposure")
        if profile.home_country and event.jurisdiction and profile.home_country == event.jurisdiction:
            score += 10
            reasons.append("Policy jurisdiction matches the user's home country")

    elif event.event_type == EventType.OIL_MOVE:
        if not profile.commute or profile.commute.monthly_fuel_liters == 0:
            return 0.0, ["No positive monthly fuel consumption declared"]
        if profile.commute:
            score += 80
            reasons.append("User supplied monthly fuel use and pump price")
        if profile.commute and profile.commute.monthly_fuel_liters > 0:
            score += 20
            reasons.append("User has direct driving exposure")

    return _clamp(score), reasons


def rank_events(events: list[MacroEvent], profile: LifeProfile) -> list[EventScore]:
    scored: list[EventScore] = []
    for event in events:
        significance, method = score_market_significance(event)
        relevance, reasons = score_user_relevance(event, profile)
        # Relevance is weighted slightly more heavily because the product thesis is personal impact, not market news ranking.
        priority = _clamp(significance * 0.45 + relevance * 0.55)
        scored.append(
            EventScore(
                event=event,
                market_significance=significance,
                user_relevance=relevance,
                priority_score=priority,
                significance_method=method,
                relevance_reasons=reasons,
            )
        )
    return sorted(scored, key=lambda item: item.priority_score, reverse=True)
