from __future__ import annotations

import argparse
import asyncio
import json

from .models import ConvertRequest, RadarRequest, TranslateRequest
from .providers.fixtures import demo_profile
from .service import (
    convert_request, get_demo_events, get_live_fx_event, get_policy_rate_event,
    rank_request, translate_request,
)


def sample_profile():
    """All wages, budgets and life-unit prices are declared demonstration inputs."""
    return demo_profile()


async def run_demo(live: bool = False) -> dict:
    profile = sample_profile()
    events = (
        [await get_live_fx_event("SEK", "JPY"), await get_policy_rate_event(mode="live")]
        if live else get_demo_events()
    )
    ranked = rank_request(RadarRequest(events=events, profile=profile))
    selected = next(event for event in events if event.base_currency == "SEK" and event.quote_currency == "JPY")
    impact = translate_request(TranslateRequest(event=selected, profile=profile))
    conversion = convert_request(ConvertRequest(amount=impact["direct_effect_home"], currency="SEK", profile=profile))
    return {
        "mode": "live_official_structured_events" if live else "synthetic_offline_fixture",
        "profile_source": "Explicit synthetic demonstration inputs; not inferred user finances or local prices.",
        "profile": profile.model_dump(mode="json"),
        "radar": ranked,
        "selected_event_id": selected.event_id,
        "impact": impact,
        "life_conversion": conversion,
        "boundary": "Only structured old/new observations drive arithmetic; headlines never supply values.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured event -> radar -> JPY/SEK travel -> work/life units")
    parser.add_argument("--live", action="store_true", help="Use live ECB/Frankfurter observations; fail if unavailable.")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_demo(args.live)), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
