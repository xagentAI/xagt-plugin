"""Record actual provider checks; never treat missing-key fallback as live EIA."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from life_exchange_rate.providers.policy_rate import PolicyRateProvider
from life_exchange_rate.providers.energy import EnergyProvider


async def main():
    policy = await PolicyRateProvider().policy_rate_move(mode="live")
    energy = await EnergyProvider().oil_move(mode="live_or_fixture")
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "policy_status": "live_passed",
        "policy_event": policy.model_dump(mode="json"),
        "energy_status": "fixture_fallback" if energy.metadata.get("synthetic") else "live_passed",
        "energy_event": energy.model_dump(mode="json"),
    }
    (Path(__file__).parent / "live-providers.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if not k.endswith("_event")}))


if __name__ == "__main__":
    asyncio.run(main())
