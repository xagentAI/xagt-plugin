from __future__ import annotations

import math


WEIGHTS = {
    "identity": 25,
    "quote_consistency": 15,
    "availability": 15,
    "payment_success": 20,
    "delivery_success": 15,
    "dispute": 10,
}
REPUTATION_EVENT_TYPES = frozenset(
    {"delivered", "paid_but_undelivered", "failed"}
)


def validate_reputation_event(event_type: str, dimensions: dict) -> dict[str, float]:
    if event_type not in REPUTATION_EVENT_TYPES:
        raise ValueError("unsupported reputation event type")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("reputation dimensions must not be empty")

    normalized = {}
    for key, value in dimensions.items():
        if key not in WEIGHTS:
            raise ValueError(f"unsupported reputation dimension: {key}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"reputation dimension {key} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0 <= numeric <= 100:
            raise ValueError(f"reputation dimension {key} must be between 0 and 100")
        normalized[key] = numeric
    return normalized


def aggregate_reputation_events(events: list[dict]) -> dict:
    ordered = sorted(events, key=lambda event: event["purchase_id"])
    metrics = {}
    for key in WEIGHTS:
        values = sorted(
            event["dimensions"][key]
            for event in ordered
            if key in event["dimensions"]
        )
        if values:
            metrics[key] = math.fsum(values) / len(values)
    return calculate_reputation(metrics, len(ordered))


def calculate_reputation(metrics: dict, sample_size: int):
    dimensions = {
        key: max(0, min(100, float(metrics.get(key, 50)))) for key in WEIGHTS
    }
    score = round(sum(dimensions[key] * weight for key, weight in WEIGHTS.items()) / 100)
    confidence = round(min(1.0, sample_size / 50), 2)
    return {
        "score": score,
        "dimensions": dimensions,
        "sample_size": sample_size,
        "confidence": confidence,
        "weights": WEIGHTS,
    }
