"""Offline API-contract tests; every mocked observation below is synthetic."""
import csv
import io
import json
from datetime import date, datetime, timezone

import httpx
import pytest

from life_exchange_rate.models import Confidence, TranslateRequest
from life_exchange_rate.calculations import translate_event
from life_exchange_rate.providers.common import ProviderError
from life_exchange_rate.providers.energy import EnergyProvider
from life_exchange_rate.providers.fixtures import demo_profile
from life_exchange_rate.providers.policy_rate import PolicyRateProvider

NOW = datetime(2026, 1, 12, 15, 30, tzinfo=timezone.utc)
AS_OF = date(2026, 1, 12)


def policy_csv(records=None, **overrides):
    records = records if records is not None else [("2025-12-01", "2.00"), ("2025-12-11", "2.25"), ("2026-01-10", "2.50")]
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=["KEY", "TIME_PERIOD", "OBS_VALUE", "UNIT", "UNIT_MULT", "OBS_STATUS"])
    writer.writeheader()
    for day, value in records:
        writer.writerow({"KEY": PolicyRateProvider.SERIES_ID, "TIME_PERIOD": day, "OBS_VALUE": value, "UNIT": "PCPA", "UNIT_MULT": "0", "OBS_STATUS": "A", **overrides})
    return content.getvalue()


def energy_payload(records=None, **overrides):
    records = records if records is not None else [("2025-12-15", "75"), ("2026-01-02", "80"), ("2026-01-09", "88")]
    rows = [{"period": day, "value": value, "series": "RBRTE", "units": "Dollars per Barrel", **overrides} for day, value in records]
    return {"response": {"data": rows, "total": str(len(rows))}}


def policy_provider(content, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, text=content)
    return PolicyRateProvider(transport=httpx.MockTransport(handler), today=lambda: AS_OF, now=lambda: NOW)


def energy_provider(payload, calls=None, key="unit-test-key"):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=payload)
    return EnergyProvider(api_key=key, transport=httpx.MockTransport(handler), today=lambda: AS_OF, now=lambda: NOW)


@pytest.mark.asyncio
async def test_ecb_uses_requested_horizon_scope_and_source_dates():
    calls = []
    event = await policy_provider(policy_csv(), calls).policy_rate_move(30, "live")
    assert event.old_value == 2.25  # Not the first padding observation at 2.00.
    assert event.new_value == 2.5
    assert event.change_pct is None  # Policy moves are percentage points, even at zero/negative rates.
    assert event.metadata["change_basis_points"] == 25
    assert event.metadata["actual_window_days"] == 30
    assert event.metadata["observation_lag_days"] == 2
    assert event.affected_currencies == ["EUR"] and event.jurisdiction == "EA"
    assert event.observed_at.date() == date(2026, 1, 10)
    assert event.provenance.retrieved_at == NOW
    assert event.provenance.series_id == PolicyRateProvider.SERIES_ID
    assert calls[0].url.params["startPeriod"] == "2025-11-15"
    assert calls[0].url.params["endPeriod"] == AS_OF.isoformat()
    assert calls[0].url.params["format"] == "csvdata"
    impact = translate_event(TranslateRequest(event=event, profile=demo_profile()))
    assert impact.direct_effect_home is None  # Euro-area policy must not alter a SEK mortgage.


@pytest.mark.asyncio
@pytest.mark.parametrize("old,new", [("0", "0.25"), ("-0.5", "0"), ("2", "2")])
async def test_policy_zero_negative_and_unchanged_levels_are_valid(old, new):
    event = await policy_provider(policy_csv([("2025-12-11", old), ("2026-01-10", new)])).policy_rate_move(mode="live")
    assert event.metadata["change_basis_points"] == (float(new) - float(old)) * 100
    assert event.change_pct is None


@pytest.mark.asyncio
async def test_eia_queries_daily_brent_and_keeps_api_key_out_of_provenance():
    calls = []
    event = await energy_provider(energy_payload(), calls).oil_move(7, "live")
    assert (event.old_value, event.new_value) == (80, 88)
    assert event.change_pct == pytest.approx(10)
    assert event.window_start.date() == date(2026, 1, 2)
    assert event.window_end.date() == date(2026, 1, 9)
    assert event.provenance.retrieved_at == NOW
    assert event.provenance.series_id == "PET.RBRTE.D"
    params = calls[0].url.params
    assert params["frequency"] == "daily" and params["facets[series][]"] == "RBRTE"
    assert params["start"] == "2025-12-08" and params["end"] == AS_OF.isoformat()
    assert params["api_key"] == "unit-test-key"
    assert "unit-test-key" not in event.model_dump_json()
    assert "api_key" not in event.provenance.source_url


@pytest.mark.asyncio
async def test_weekend_baseline_uses_prior_published_day():
    event = await energy_provider(energy_payload([("2026-01-02", "80"), ("2026-01-11", "88")])).oil_move(7, "live")
    assert event.metadata["target_start_date"] == "2026-01-04"
    assert event.metadata["actual_window_days"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,method", [(PolicyRateProvider, "policy_rate_move"), (EnergyProvider, "oil_move")])
async def test_fixture_is_offline_deterministic_and_never_official(provider, method):
    def forbidden_network(request):
        raise AssertionError("fixture mode must make no network requests")
    instance = provider(transport=httpx.MockTransport(forbidden_network), today=lambda: AS_OF, now=lambda: NOW)
    event = await getattr(instance, method)(mode="fixture")
    repeat = await getattr(instance, method)(mode="fixture")
    assert event == repeat
    assert event.metadata["synthetic"] is True
    assert event.metadata["fallback_used"] is False
    assert event.confidence == Confidence.SCENARIO
    assert event.evidence_url is None and event.provenance.source_url is None
    assert event.provenance.source_type == "synthetic_fixture"
    assert event.observed_at.date() == date(2025, 12, 31)
    full_year = await getattr(instance, method)(365, "fixture")
    assert full_year.metadata["actual_window_days"] == 365


@pytest.mark.asyncio
async def test_missing_eia_key_has_explicit_fallback_and_live_fails():
    provider = energy_provider({}, key="")
    event = await provider.oil_move()
    assert event.metadata["fallback_used"] is True
    assert event.metadata["fallback_reason"] == "EIA_API_KEY is not configured"
    assert event.change_pct == pytest.approx(15)
    with pytest.raises(ProviderError, match="EIA_API_KEY is not configured"):
        await provider.oil_move(mode="live")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 429, 500])
async def test_http_failures_are_sanitized_and_fallback_labeled(status):
    secret = "do-not-expose-this-key"
    def fail(request):
        return httpx.Response(status, text=f"Error at {request.url}; {secret}", headers={"Location": f"https://example.com/{secret}"})
    provider = EnergyProvider(api_key=secret, transport=httpx.MockTransport(fail), now=lambda: NOW)
    event = await provider.oil_move()
    assert event.metadata["fallback_used"] is True
    assert secret not in event.model_dump_json()
    with pytest.raises(ProviderError) as error:
        await provider.oil_move(mode="live")
    assert secret not in str(error.value)
    assert str(status) in str(error.value)


@pytest.mark.asyncio
async def test_transport_error_does_not_echo_request_url():
    def fail(request):
        raise httpx.ConnectError(f"private message {request.url}", request=request)
    provider = EnergyProvider(api_key="hidden-key", transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderError, match="could not be reached") as error:
        await provider.oil_move(mode="live")
    assert "hidden-key" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "not,csv\n1,2", policy_csv([], UNIT="PCPA"), policy_csv(UNIT="USD"), policy_csv(UNIT_MULT="2"),
    policy_csv(KEY="FM.D.US.USD.INVALID"), policy_csv(OBS_STATUS="M"),
    policy_csv([("2025-12-11", "2"), ("2026-01-10", "nan")]),
    policy_csv([("2025-12-11", ""), ("2026-01-10", "2")]),
    policy_csv([("2025-12-11", "2"), ("2026-01-10", "2"), ("2026-01-10", "3")]),
    policy_csv([("2025-12-11", "2"), ("2026-01-13", "3")]),
    policy_csv([("2025-10-01", "2"), ("2025-12-01", "3")]),
    policy_csv([("2025-12-12", "2"), ("2026-01-10", "3")]),
    policy_csv([("2025-12-11", "2"), ("2026-W02-1", "3")]),
    policy_csv().replace("OBS_STATUS", "OBS_VALUE"),
])
async def test_ecb_rejects_missing_invalid_duplicate_future_stale_or_short_windows(content):
    provider = policy_provider(content)
    with pytest.raises(ProviderError):
        await provider.policy_rate_move(mode="live")
    assert (await provider.policy_rate_move()).metadata["fallback_used"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    None, {}, {"error": "remote-key-sensitive-message"}, {"response": {"data": []}},
    energy_payload(series="RWTC"), energy_payload(units="Dollars per Gallon"),
    energy_payload([("2026-01-02", "0"), ("2026-01-09", "88")]),
    energy_payload([("2026-01-02", "80"), ("2026-01-09", "inf")]),
    energy_payload([("2026-01-02", "80"), ("2026-01-09", None)]),
    energy_payload([("2026-01-02", "80"), ("2026-01-09", "88"), ("2026-01-09", "90")]),
    energy_payload([("2026-01-02", "80"), ("2026-01-13", "88")]),
    energy_payload([("2026-01-02", "80"), ("2026-W02-1", "88")]),
    {"response": {"total": "5001", "data": energy_payload()["response"]["data"]}},
])
async def test_eia_rejects_bad_shapes_values_units_duplicates_and_truncation(payload):
    provider = energy_provider(payload)
    with pytest.raises(ProviderError):
        await provider.oil_move(mode="live")
    event = await provider.oil_move()
    assert event.metadata["fallback_used"] is True
    assert "remote-key-sensitive-message" not in event.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("lookback", [0, 366, True, 2.5])
async def test_bad_request_does_not_silently_fallback(lookback):
    with pytest.raises(ValueError, match="lookback_days"):
        await energy_provider({}).oil_move(lookback, "live_or_fixture")
    with pytest.raises(ValueError, match="lookback_days"):
        await policy_provider("").policy_rate_move(lookback, "fixture")


@pytest.mark.asyncio
async def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="mode"):
        await energy_provider({}).oil_move(mode="automatic")
