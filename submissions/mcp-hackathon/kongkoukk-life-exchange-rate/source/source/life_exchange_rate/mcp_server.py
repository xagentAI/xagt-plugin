from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import __version__
from .models import (
    ConvertRequest,
    ImpactAssumptions,
    LifeProfile,
    MacroEvent,
    RadarRequest,
    ScenarioInput,
    ScenarioRequest,
    TranslateRequest,
)
from .service import (
    compare_scenarios,
    convert_request,
    get_demo_events,
    get_energy_event as fetch_energy_event,
    get_live_fx_event as fetch_live_fx_event,
    get_official_headlines,
    get_policy_rate_event as fetch_policy_rate_event,
    rank_request,
    translate_request,
)

Currency = Annotated[str, Field(pattern="^[A-Za-z]{3}$")]
FXLookback = Annotated[int, Field(ge=2, le=90)]
ProviderLookback = Annotated[int, Field(ge=2, le=365)]
ProviderMode = Literal["live", "fixture", "live_or_fixture"]
HeadlineLimit = Annotated[int, Field(ge=1, le=50)]
PositiveMultiplier = Annotated[float, Field(gt=0, allow_inf_nan=False)]

mcp = MCPServer(
    "Life Exchange Rate",
    version=__version__,
    instructions=(
        "Translate macroeconomic events into concrete personal-life impacts. "
        "Separate headlines from quantified events; headlines alone cannot be calculated. "
        "Prefer structured observations, identify fixtures and fallback provenance, "
        "keep supplied prices, wages and pass-through assumptions explicit, "
        "and never present scenario estimates as guaranteed forecasts."
    ),
)


@mcp.tool()
def get_macro_events(mode: Literal["demo"] = "demo") -> list[dict[str, Any]]:
    """Return explicitly labeled, reproducible synthetic macro events for the judging demo."""
    return [event.model_dump(mode="json") for event in get_demo_events()]


@mcp.tool()
async def get_official_macro_headlines(
    source: Literal["fed", "ecb"] = "fed", limit: HeadlineLimit = 10,
) -> list[dict[str, Any]]:
    """Read official central-bank headlines as triggers only; quantify separately before calculating impact."""
    try:
        return await get_official_headlines(source=source, limit=limit)
    except Exception as exc:
        raise ToolError("Official headline provider unavailable; retry later.") from exc


@mcp.tool()
async def get_live_fx_event(
    base_currency: Currency, quote_currency: Currency, lookback_days: FXLookback = 7,
) -> dict[str, Any]:
    """Get an observed FX move with a transparent rolling anomaly score from ECB-filtered Frankfurter data."""
    if base_currency.upper() == quote_currency.upper():
        raise ToolError("FX base and quote currencies must differ")
    try:
        event = await fetch_live_fx_event(base_currency, quote_currency, lookback_days)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise ToolError("FX provider unavailable; retry later.") from exc


@mcp.tool()
async def get_policy_rate_event(
    lookback_days: ProviderLookback = 30, mode: ProviderMode = "live_or_fixture",
) -> dict[str, Any]:
    """Get structured ECB euro-area deposit-rate changes scoped to EUR; fixture mode is synthetic and fallback is labeled in provenance."""
    try:
        event = await fetch_policy_rate_event(lookback_days=lookback_days, mode=mode)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise ToolError("Policy-rate provider unavailable; retry later or use fixture mode.") from exc


@mcp.tool()
async def get_energy_event(
    lookback_days: ProviderLookback = 7, mode: ProviderMode = "live_or_fixture",
) -> dict[str, Any]:
    """Get structured EIA Brent observations; fixture mode is reproducible and crude-to-fuel pass-through remains a scenario."""
    try:
        event = await fetch_energy_event(lookback_days=lookback_days, mode=mode)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise ToolError("Energy provider unavailable; retry later or use fixture mode.") from exc


@mcp.tool()
def rank_events_for_user(events: list[MacroEvent], profile: LifeProfile) -> list[dict[str, Any]]:
    """Rank quantified events by transparent market significance and relevance to the supplied profile."""
    return rank_request(RadarRequest(events=events, profile=profile))


@mcp.tool()
def translate_event_to_life(
    event: MacroEvent, profile: LifeProfile, assumptions: ImpactAssumptions | None = None,
) -> dict[str, Any]:
    """Calculate money, work time and supplied life-unit equivalents; optional pass-through inputs are scenarios, not forecasts."""
    try:
        return translate_request(TranslateRequest(
            event=event, profile=profile, assumptions=assumptions or ImpactAssumptions(),
        ))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def convert_to_life_units(
    amount: Annotated[float, Field(allow_inf_nan=False)], currency: Currency, profile: LifeProfile,
) -> dict[str, Any]:
    """Convert a home-currency amount to work time and user-supplied everyday units without inventing prices or wages."""
    try:
        return convert_request(ConvertRequest(amount=amount, currency=currency, profile=profile))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def compare_event_scenarios(
    event: MacroEvent,
    profile: LifeProfile,
    mild_multiplier: PositiveMultiplier = 0.5,
    severe_multiplier: PositiveMultiplier = 1.5,
    assumptions: ImpactAssumptions | None = None,
) -> list[dict[str, Any]]:
    """Compare milder, baseline and more severe versions of an event using explicit pass-through assumptions; this is not a forecast."""
    try:
        request = ScenarioRequest(
            event=event,
            profile=profile,
            scenarios=[
                ScenarioInput(label="milder", multiplier=mild_multiplier),
                ScenarioInput(label="baseline", multiplier=1.0),
                ScenarioInput(label="severe", multiplier=severe_multiplier),
            ],
            assumptions=assumptions or ImpactAssumptions(),
        )
        return compare_scenarios(request)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
