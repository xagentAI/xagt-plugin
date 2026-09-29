import math
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from life_exchange_rate.providers.frankfurter import FrankfurterProvider
from life_exchange_rate.radar import score_market_significance


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def row(day, rate=15.0, **changes):
    return {"date": day.isoformat() if isinstance(day, date) else day, "base": "SEK", "quote": "JPY", "rate": rate, **changes}


def history(days=350, shock=0.92):
    start = NOW.date() - timedelta(days=days)
    result = []
    for index in range(days + 1):
        day = start + timedelta(days=index)
        if day.weekday() < 5 and day <= date(2026, 9, 11):
            result.append(row(day, 15 * math.exp(0.005 * math.sin(index / 4) + 0.004 * math.cos(index / 11))))
    result[-1]["rate"] *= shock
    return result


def provider_for(payload, requests=None, status_code=200):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(status_code, json=payload)

    return FrankfurterProvider(transport=httpx.MockTransport(handler), now=lambda: NOW)


@pytest.mark.asyncio
async def test_live_move_selects_latest_minus_horizon_and_keeps_query_provenance():
    payload = history()
    requests = []
    event = await provider_for(list(reversed(payload)), requests).fx_move("sek", "jpy", 7)
    assert event.window_end.date() == date(2026, 9, 11)
    assert event.window_start.date() == date(2026, 9, 4)
    assert event.metadata["requested_lookback_days"] == 7
    assert event.metadata["actual_calendar_days"] == 7
    rates = {item["date"]: item["rate"] for item in payload}
    assert event.old_value == rates["2026-09-04"]
    assert event.new_value == rates["2026-09-11"]
    assert event.change_pct == pytest.approx((rates["2026-09-11"] / rates["2026-09-04"] - 1) * 100)
    assert requests[0].url.path == "/v2/providers/ecb/rates"
    assert requests[0].url.params["base"] == "SEK"
    assert requests[0].url.params["quotes"] == "JPY"
    assert requests[0].url.params["from"] == (NOW.date() - timedelta(days=394)).isoformat()
    assert requests[0].url.params["to"] == NOW.date().isoformat()
    assert event.provenance.source_url == str(requests[0].url)
    assert event.provenance.retrieved_at == NOW
    assert event.observed_at.tzinfo == timezone.utc
    assert "2026-09-04-2026-09-11" in event.event_id


@pytest.mark.asyncio
async def test_weekend_anchor_uses_equal_actual_calendar_horizon():
    event = await provider_for(history()).fx_move("SEK", "JPY", 5)
    assert event.metadata["target_old_date"] == "2026-09-06"
    assert event.metadata["old_date"] == "2026-09-04"
    assert event.metadata["anchor_gap_days"] == 2
    assert event.metadata["anomaly"]["horizon_calendar_days"] == 7


@pytest.mark.asyncio
async def test_z_score_matches_prior_equal_horizon_returns_and_excludes_event():
    payload = history()
    event = await provider_for(payload).fx_move("SEK", "JPY")
    rates = {date.fromisoformat(item["date"]): item["rate"] for item in payload}
    old = date(2026, 9, 4)
    references = [
        math.log(rates[day] / rates[day - timedelta(days=7)])
        for day in sorted(rates)
        if day <= old and day - timedelta(days=7) in rates
    ][-252:]
    mean = sum(references) / len(references)
    stddev = math.sqrt(sum((value - mean) ** 2 for value in references) / (len(references) - 1))
    expected = (math.log(event.new_value / event.old_value) - mean) / stddev
    anomaly = event.metadata["anomaly"]
    assert anomaly["sample_count"] == len(references)
    assert anomaly["reference_mean_log_return"] == pytest.approx(mean, abs=1e-14)
    assert anomaly["reference_sample_stddev"] == pytest.approx(stddev)
    assert event.metadata["z_score"] == pytest.approx(expected)
    assert anomaly["reference_window_end"] <= event.metadata["old_date"]
    assert anomaly["fallback_reason"] is None
    assert score_market_significance(event)[1] == "provider_z_score"
    changed = [dict(item) for item in payload]
    for item in changed:
        if item["date"] > old.isoformat():
            item["rate"] *= 1.1
    changed_event = await provider_for(changed).fx_move("SEK", "JPY")
    changed_anomaly = changed_event.metadata["anomaly"]
    assert changed_anomaly["reference_mean_log_return"] == anomaly["reference_mean_log_return"]
    assert changed_anomaly["reference_sample_stddev"] == anomaly["reference_sample_stddev"]
    assert changed_event.metadata["z_score"] != event.metadata["z_score"]


@pytest.mark.asyncio
async def test_insufficient_history_is_explicit_and_does_not_invent_score():
    event = await provider_for(history(days=20)).fx_move("SEK", "JPY")
    assert event.metadata["anomaly"]["fallback_reason"] == "insufficient_history"
    assert event.metadata["anomaly"]["sample_count"] < 30
    assert event.metadata["anomaly"]["z_score"] is None
    assert "z_score" not in event.metadata
    assert score_market_significance(event)[1] == "fallback_fx_percent_move"


@pytest.mark.asyncio
async def test_zero_volatility_falls_back_even_when_event_is_large():
    payload = history()
    for item in payload:
        item["rate"] = 15.0
    payload[-1]["rate"] = 13.8
    event = await provider_for(payload).fx_move("SEK", "JPY")
    assert event.metadata["anomaly"]["fallback_reason"] == "zero_or_negligible_reference_volatility"
    assert "z_score" not in event.metadata
    assert event.change_pct == pytest.approx(-8)


@pytest.mark.asyncio
async def test_identical_duplicates_do_not_inflate_reference_sample_count():
    payload = history()
    baseline = await provider_for(payload).fx_move("SEK", "JPY")
    repeated = await provider_for(payload + payload[:20]).fx_move("SEK", "JPY")
    assert repeated.metadata["identical_duplicates_removed"] == 20
    assert repeated.metadata["anomaly"] == baseline.metadata["anomaly"]


@pytest.mark.asyncio
async def test_missing_target_anchor_fails_without_shortening_horizon():
    with pytest.raises(ValueError, match="on or before"):
        await provider_for([row("2026-09-10"), row("2026-09-11")]).fx_move("SEK", "JPY")


@pytest.mark.parametrize("bad_row", [
    row("2026-09-10", quote="USD"),
    row("2026-09-10", base="USD"),
    {"date": "2026-09-10", "rate": 15},
    row("2026-09-32"),
    row("20260910"),
    row("2026-09-10T00:00:00Z"),
    row("2026-09-15"),
    row("2020-01-01"),
    row("2026-09-10", 0),
    row("2026-09-10", -1),
    row("2026-09-10", "NaN"),
    row("2026-09-10", "Infinity"),
    row("2026-09-10", True),
    row("2026-09-10", None),
    row("2026-09-10", "bad"),
    "unexpected row",
])
@pytest.mark.asyncio
async def test_invalid_upstream_rows_fail_closed(bad_row):
    with pytest.raises(ValueError):
        await provider_for(history() + [bad_row]).fx_move("SEK", "JPY")


@pytest.mark.asyncio
async def test_conflicting_duplicates_fail_closed():
    payload = history()
    with pytest.raises(ValueError, match="conflicting"):
        await provider_for(payload + [{**payload[0], "rate": 2.0}]).fx_move("SEK", "JPY")


@pytest.mark.parametrize("base,quote,days", [
    ("SEK", "JPY", 1), ("SEK", "JPY", 91), ("SEK", "JPY", True),
    ("SEK", "JPY", 7.0), ("SEK", "JPY", "7"), ("SEK", "SEK", 7),
    ("sek", "SEK", 7), (" SEK", "JPY", 7), ("123", "JPY", 7),
    (None, "JPY", 7), ("SEK", "JP", 7),
])
@pytest.mark.asyncio
async def test_inputs_are_validated_before_io(base, quote, days):
    requests = []
    with pytest.raises(ValueError):
        await provider_for([], requests).fx_move(base, quote, days)
    assert requests == []


@pytest.mark.asyncio
async def test_http_error_is_preserved_and_empty_payload_rejected():
    with pytest.raises(httpx.HTTPStatusError):
        await provider_for({"message": "unavailable"}, status_code=503).fx_move("SEK", "JPY")
    with pytest.raises(ValueError, match="Not enough"):
        await provider_for([]).fx_move("SEK", "JPY")


@pytest.mark.asyncio
async def test_sparse_missing_horizon_endpoints_are_not_interpolated():
    # Ten-calendar-day observations cannot provide exact seven-day returns.
    payload = [row(date(2026, 1, 1) + timedelta(days=10 * index), 15 + index / 100) for index in range(25)]
    payload += [row("2026-09-04", 15), row("2026-09-11", 14)]
    event = await provider_for(payload).fx_move("SEK", "JPY")
    assert event.metadata["anomaly"]["sample_count"] == 0
    assert event.metadata["anomaly"]["fallback_reason"] == "insufficient_history"


@pytest.mark.asyncio
async def test_extreme_rates_cannot_produce_nonfinite_percentage():
    with pytest.raises(ValueError, match="numeric range"):
        await provider_for([row("2026-09-04", 1e-300), row("2026-09-11", 1e300)]).fx_move("SEK", "JPY")


@pytest.mark.asyncio
async def test_rolling_sample_count_is_bounded():
    event = await provider_for(history(days=390)).fx_move("SEK", "JPY")
    assert event.metadata["anomaly"]["sample_count"] == 252


@pytest.mark.parametrize("sample_count", [29, 30])
@pytest.mark.asyncio
async def test_minimum_history_boundary(sample_count):
    # Daily observations make the number of exact seven-day prior windows
    # deterministic: observations minus the event and reference horizons.
    count = sample_count + 14
    start = date(2026, 9, 11) - timedelta(days=count - 1)
    payload = [row(start + timedelta(days=index), 15 + math.sin(index / 3) / 10) for index in range(count)]
    event = await provider_for(payload).fx_move("SEK", "JPY")
    assert event.metadata["anomaly"]["sample_count"] == sample_count
    assert ("z_score" in event.metadata) is (sample_count == 30)


@pytest.mark.asyncio
async def test_query_dates_use_utc_not_local_calendar_date():
    provider = provider_for(history())
    provider.now = lambda: datetime(2026, 9, 14, 1, tzinfo=timezone(timedelta(hours=3)))
    event = await provider.fx_move("SEK", "JPY")
    assert event.metadata["query_end_date"] == "2026-09-13"
    assert event.metadata["latest_observation_age_days"] == 2


@pytest.mark.parametrize("age_days", [14, 15])
@pytest.mark.asyncio
async def test_stale_latest_observation_guard_boundary(age_days):
    latest = NOW.date() - timedelta(days=age_days)
    payload = [row(latest - timedelta(days=7), 15), row(latest, 14)]
    if age_days > 14:
        with pytest.raises(ValueError, match="more than 14 calendar days old"):
            await provider_for(payload).fx_move("SEK", "JPY")
    else:
        event = await provider_for(payload).fx_move("SEK", "JPY")
        assert event.metadata["latest_observation_age_days"] == 14
        assert any("14 calendar days old" in note for note in event.provenance.notes)


@pytest.mark.parametrize("gap_days", [7, 8])
@pytest.mark.asyncio
async def test_missing_baseline_guard_boundary(gap_days):
    latest = date(2026, 9, 11)
    baseline = latest - timedelta(days=7 + gap_days)
    payload = [row(baseline, 15), row(latest, 14)]
    if gap_days > 7:
        with pytest.raises(ValueError, match="more than 7 calendar days before"):
            await provider_for(payload).fx_move("SEK", "JPY")
    else:
        event = await provider_for(payload).fx_move("SEK", "JPY")
        assert event.metadata["anchor_gap_days"] == 7
        assert event.metadata["actual_calendar_days"] == 14


@pytest.mark.asyncio
async def test_frankfurter_weekend_start_backfill_is_retained_and_disclosed():
    # Observed live v2 behavior: from=2025-08-16 (Saturday) includes Friday.
    payload = [row("2025-08-15", 15.3711), *history()]
    requests = []
    event = await provider_for(payload, requests).fx_move("SEK", "JPY")
    assert requests[0].url.params["from"] == "2025-08-16"
    assert event.metadata["query_start_date"] == "2025-08-16"
    assert event.metadata["history_start_date"] == "2025-08-15"
    assert event.metadata["pre_query_observation_count"] == 1
    assert event.metadata["old_date"] == "2026-09-04"
    assert event.metadata["new_date"] == "2026-09-11"


@pytest.mark.parametrize("padding_days", [7, 8])
@pytest.mark.asyncio
async def test_start_backfill_is_bounded_to_seven_days(padding_days):
    query_start = NOW.date() - timedelta(days=394)
    payload = [row(query_start - timedelta(days=padding_days)), *history()]
    if padding_days > 7:
        with pytest.raises(ValueError, match="out-of-query"):
            await provider_for(payload).fx_move("SEK", "JPY")
    else:
        event = await provider_for(payload).fx_move("SEK", "JPY")
        assert event.metadata["pre_query_observation_count"] == 1
