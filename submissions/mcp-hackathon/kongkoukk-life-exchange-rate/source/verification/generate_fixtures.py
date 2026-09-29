"""Regenerate deterministic verification artifacts, without network access."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from life_exchange_rate.demo import run_demo
from life_exchange_rate.main import app
from life_exchange_rate.models import TranslateRequest
from life_exchange_rate.providers.fixtures import demo_events, demo_profile
from life_exchange_rate.providers.policy_rate import PolicyRateProvider
from life_exchange_rate.providers.energy import EnergyProvider
from life_exchange_rate.service import translate_request

ROOT = Path(__file__).resolve().parent
FIXED = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


async def main():
    fixtures = ROOT / "fixtures"
    fixtures.mkdir(exist_ok=True)
    save(ROOT / "openapi.json", app.openapi())
    events = {
        "fx": demo_events()[0],
        "policy": await PolicyRateProvider(now=lambda: FIXED).policy_rate_move(mode="fixture"),
        "energy": await EnergyProvider(now=lambda: FIXED).oil_move(mode="fixture"),
    }
    for name, event in events.items():
        request = TranslateRequest(event=event, profile=demo_profile())
        save(fixtures / f"{name}-event.json", event.model_dump(mode="json"))
        save(fixtures / f"{name}-request.json", request.model_dump(mode="json"))
        save(fixtures / f"{name}-response.json", translate_request(request))
    save(fixtures / "invalid-request.json", {"event": {"event_type": "fx_move"}, "profile": {}})
    save(fixtures / "offline-demo.json", await run_demo())
    print("Updated OpenAPI and deterministic event, request, response and demo fixtures.")


if __name__ == "__main__":
    asyncio.run(main())
