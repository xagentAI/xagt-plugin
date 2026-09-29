from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pilot_gate import (
    PILOT_GATE_REASON_CODES,
    PLATFORM_DAILY_GAS_LIMIT,
    PLATFORM_PAUSED,
    TENANT_PAUSED,
    NODE_DAILY_GAS_LIMIT,
    NODE_DAILY_LIMIT,
    NODE_IN_FLIGHT_LIMIT,
    NODE_LIFETIME_LIMIT,
    NODE_PAUSED,
    PilotGatePolicy,
    utc_day,
    worst_case_gas_usd_micros,
)


def test_policy_uses_pilot_defaults_and_requires_a_positive_price_ceiling() -> None:
    policy = PilotGatePolicy(native_asset_usd_price_ceiling_micros=2_500_000)

    assert policy.max_in_flight_per_node == 10
    assert policy.max_accepted_per_node_utc_day == 50
    assert policy.max_accepted_per_node_lifetime == 250
    assert policy.max_gas_usd_micros_per_node_utc_day == 1_000_000
    assert policy.max_gas_usd_micros_platform_utc_day == 100_000_000
    assert policy.native_asset_usd_price_ceiling_micros == 2_500_000

    with pytest.raises(FrozenInstanceError):
        policy.max_in_flight_per_node = 11  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    [
        "max_in_flight_per_node",
        "max_accepted_per_node_utc_day",
        "max_accepted_per_node_lifetime",
        "max_gas_usd_micros_per_node_utc_day",
        "max_gas_usd_micros_platform_utc_day",
        "native_asset_usd_price_ceiling_micros",
    ],
)
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5])
def test_policy_rejects_non_positive_or_non_integer_values(
    field: str, value: object
) -> None:
    values = {"native_asset_usd_price_ceiling_micros": 1}
    values[field] = value

    with pytest.raises(ValueError, match=field):
        PilotGatePolicy(**values)


@pytest.mark.parametrize("timestamp", [True, False, 0, -1, 1.5])
def test_utc_day_rejects_non_positive_or_non_integer_timestamps(
    timestamp: object,
) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        utc_day(timestamp)


def test_utc_day_uses_unix_utc_day_boundaries() -> None:
    assert utc_day(1) == 0
    assert utc_day(86_399) == 0
    assert utc_day(86_400) == 1
    assert utc_day(172_801) == 2


@pytest.mark.parametrize(
    "values",
    [
        (0, 1_000_000_000, 2_500_000),
        (21_000, 0, 2_500_000),
        (21_000, 1_000_000_000, 0),
        (-1, 1_000_000_000, 2_500_000),
        (21_000, -1, 2_500_000),
        (21_000, 1_000_000_000, -1),
        (21_000, 1.5, 2_500_000),
        (21_000, True, 2_500_000),
    ],
)
def test_worst_case_gas_rejects_non_positive_or_non_integer_inputs(
    values: tuple[object, object, object],
) -> None:
    with pytest.raises(ValueError):
        worst_case_gas_usd_micros(*values)


def test_worst_case_gas_uses_integer_ceil_without_float_rounding() -> None:
    assert worst_case_gas_usd_micros(21_000, 1_000_000_000, 2_500_000) == 53
    assert worst_case_gas_usd_micros(1, 1, 1) == 1
    assert worst_case_gas_usd_micros(10**18, 1, 1) == 1
    assert worst_case_gas_usd_micros(10**18 + 1, 1, 1) == 2


def test_pilot_gate_reason_codes_are_stable() -> None:
    assert PILOT_GATE_REASON_CODES == frozenset(
        {
            PLATFORM_PAUSED,
            TENANT_PAUSED,
            NODE_PAUSED,
            NODE_IN_FLIGHT_LIMIT,
            NODE_DAILY_LIMIT,
            NODE_LIFETIME_LIMIT,
            NODE_DAILY_GAS_LIMIT,
            PLATFORM_DAILY_GAS_LIMIT,
        }
    )
