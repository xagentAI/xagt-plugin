from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any


MIN_REFERENCE_SAMPLES = 30
MAX_REFERENCE_SAMPLES = 252
VOLATILITY_EPSILON = 1e-12


def rolling_log_return_anomaly(
    observations: list[tuple[date, float]], old_date: date, new_date: date
) -> dict[str, Any]:
    """Compare an event against prior equal-calendar-horizon log returns.

    Input observations must already be unique, positive, finite, and sorted.
    Reference returns may overlap each other, but never the selected event.
    Missing exact-horizon endpoints are omitted rather than interpolated.
    """
    rates = dict(observations)
    horizon = (new_date - old_date).days
    event_return = math.log(rates[new_date]) - math.log(rates[old_date])
    references: list[tuple[date, date, float]] = []
    for end_date, end_rate in observations:
        if end_date > old_date:
            break
        start_date = end_date - timedelta(days=horizon)
        if start_date in rates:
            references.append((start_date, end_date, math.log(end_rate) - math.log(rates[start_date])))
    references = references[-MAX_REFERENCE_SAMPLES:]
    returns = [row[2] for row in references]
    mean = statistics.fmean(returns) if returns else None
    stdev = statistics.stdev(returns) if len(returns) >= 2 else None
    result = {
        "method": "preceding_equal_calendar_horizon_log_return_z_score",
        "formula": "(event_log_return - reference_mean_log_return) / reference_sample_stddev",
        "horizon_calendar_days": horizon,
        "sample_count": len(returns),
        "minimum_sample_count": MIN_REFERENCE_SAMPLES,
        "maximum_sample_count": MAX_REFERENCE_SAMPLES,
        "reference_window_start": references[0][0].isoformat() if references else None,
        "reference_window_end": references[-1][1].isoformat() if references else None,
        "reference_windows_may_overlap": True,
        "event_excluded_from_reference": True,
        "missing_endpoint_policy": "skip_window_without_exact_calendar_horizon_endpoints",
        "event_log_return": event_return,
        "reference_mean_log_return": mean,
        "reference_sample_stddev": stdev,
        "z_score": None,
        "fallback_reason": None,
    }
    if len(returns) < MIN_REFERENCE_SAMPLES:
        result["fallback_reason"] = "insufficient_history"
    elif stdev is None or stdev <= VOLATILITY_EPSILON:
        result["fallback_reason"] = "zero_or_negligible_reference_volatility"
    else:
        z_score = (event_return - mean) / stdev
        if math.isfinite(z_score):
            result["z_score"] = z_score
        else:
            result["fallback_reason"] = "nonfinite_score"
    return result
