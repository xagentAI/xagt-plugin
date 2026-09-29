"""Fixed-seed synthetic fixtures: reproducible UI examples, never real returns."""

import math
import random
from datetime import datetime, timezone
from .research import Candle, ResearchRequest


def fixture(scenario: str = "mixed") -> ResearchRequest:
    if scenario not in ("mixed", "shock"):
        raise ValueError("Unknown fixture scenario")
    rng = random.Random(812)
    t = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    price = 30_000.0
    candles: list[Candle] = []
    for i in range(900):
        phase = (i // 100) % 4
        drift = (0.0025, -0.0015, 0.0004, 0.0012)[phase]
        vol = (0.012, 0.035, 0.008, 0.019)[phase]
        if scenario == "shock" and i > 720:
            drift = -0.004
            vol = 0.065
        opened = price * math.exp(rng.gauss(0, 0.002))
        price = opened * math.exp(drift + rng.gauss(0, vol))
        span = abs(rng.gauss(0, vol)) + 0.002
        candles.append(
            Candle(
                t=t + i * 86_400_000,
                o=opened,
                h=max(opened, price) * (1 + span),
                l=min(opened, price) / (1 + span),
                c=price,
                v=rng.uniform(1000, 5000),
            )
        )
    return ResearchRequest(
        candles=candles, data_kind="synthetic", source="AlphaLitmus seeded synthetic fixture / seed 812"
    )
