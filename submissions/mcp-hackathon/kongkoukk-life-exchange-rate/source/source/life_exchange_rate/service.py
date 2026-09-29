from __future__ import annotations

import os

from .calculations import convert_amount_to_life_units, translate_event
from .models import Confidence, ConvertRequest, MacroEvent, RadarRequest, ScenarioRequest, TranslateRequest
from .providers.fixtures import demo_events, demo_profile
from .providers.frankfurter import FrankfurterProvider
from .providers.official_rss import OfficialRSSProvider
from .providers.policy_rate import PolicyRateProvider
from .providers.energy import EnergyProvider
from .radar import rank_events


def get_demo_events() -> list[MacroEvent]:
    return demo_events()


def get_demo_radar() -> list[dict]:
    return [item.model_dump(mode="json") for item in rank_events(demo_events(), demo_profile())]


async def get_live_fx_event(base: str, quote: str, lookback_days: int = 7) -> MacroEvent:
    provider = FrankfurterProvider(base_url=os.getenv("FRANKFURTER_BASE_URL", "https://api.frankfurter.dev"))
    return await provider.fx_move(base=base, quote=quote, lookback_days=lookback_days)


async def get_policy_rate_event(lookback_days: int = 30, mode: str = "live_or_fixture") -> MacroEvent:
    return await PolicyRateProvider().policy_rate_move(lookback_days=lookback_days, mode=mode)


async def get_energy_event(lookback_days: int = 7, mode: str = "live_or_fixture") -> MacroEvent:
    return await EnergyProvider().oil_move(lookback_days=lookback_days, mode=mode)


async def get_official_headlines(source: str, limit: int = 10) -> list[dict]:
    provider = OfficialRSSProvider()
    items = await provider.headlines(source=source, limit=limit)
    return [item.model_dump(mode="json") for item in items]


def rank_request(request: RadarRequest) -> list[dict]:
    return [item.model_dump(mode="json") for item in rank_events(request.events, request.profile)]


def convert_request(request: ConvertRequest) -> dict:
    if request.currency != request.profile.home_currency:
        raise ValueError("MVP conversion requires amount currency to match profile.home_currency")
    work_hours, units = convert_amount_to_life_units(abs(request.amount), request.profile)
    return {
        "amount": request.amount,
        "currency": request.currency,
        "work_hours_equivalent": work_hours,
        "life_units": [item.model_dump() for item in units],
    }


def translate_request(request: TranslateRequest) -> dict:
    return translate_event(request).model_dump(mode="json")


def compare_scenarios(request: ScenarioRequest) -> list[dict]:
    results: list[dict] = []
    for scenario in request.scenarios:
        event = request.event.model_copy(deep=True)
        event.new_value = request.event.old_value + (request.event.new_value - request.event.old_value) * scenario.multiplier
        event.change_pct = None
        event.confidence = Confidence.SCENARIO
        event.metadata.pop("z_score", None)
        event.metadata.pop("anomaly", None)
        event.metadata["scenario_multiplier"] = scenario.multiplier
        event = MacroEvent.model_validate(event.model_dump())
        translated = translate_event(
            TranslateRequest(event=event, profile=request.profile, assumptions=request.assumptions)
        )
        results.append({"label": scenario.label, "result": translated.model_dump(mode="json")})
    return results
