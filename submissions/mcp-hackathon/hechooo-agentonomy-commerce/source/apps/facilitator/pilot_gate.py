"""Small, dependency-free policy helpers for the Hosted pilot gate."""

from __future__ import annotations

from dataclasses import dataclass


SECONDS_PER_UTC_DAY = 86_400
WEI_PER_NATIVE_UNIT = 10**18

PLATFORM_PAUSED = "platform_paused"
TENANT_PAUSED = "tenant_paused"
NODE_PAUSED = "node_paused"
NODE_IN_FLIGHT_LIMIT = "node_in_flight_limit"
NODE_DAILY_LIMIT = "node_daily_limit"
NODE_LIFETIME_LIMIT = "node_lifetime_limit"
NODE_DAILY_GAS_LIMIT = "node_daily_gas_limit"
PLATFORM_DAILY_GAS_LIMIT = "platform_daily_gas_limit"

PILOT_GATE_REASON_CODES = frozenset(
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


class PilotGateDenied(RuntimeError):
    """Stable, secret-free denial raised by the durable Hosted gate."""

    def __init__(self, reason_code: str) -> None:
        if reason_code not in PILOT_GATE_REASON_CODES:
            raise ValueError("pilot gate reason code is invalid")
        self.reason_code = reason_code
        super().__init__(reason_code)


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotGatePolicy:
    """Immutable admission and gas ceilings for the Hosted pilot."""

    native_asset_usd_price_ceiling_micros: int
    max_in_flight_per_node: int = 10
    max_accepted_per_node_utc_day: int = 50
    max_accepted_per_node_lifetime: int = 250
    max_gas_usd_micros_per_node_utc_day: int = 1_000_000
    max_gas_usd_micros_platform_utc_day: int = 100_000_000

    def __post_init__(self) -> None:
        for field_name in (
            "max_in_flight_per_node",
            "max_accepted_per_node_utc_day",
            "max_accepted_per_node_lifetime",
            "max_gas_usd_micros_per_node_utc_day",
            "max_gas_usd_micros_platform_utc_day",
            "native_asset_usd_price_ceiling_micros",
        ):
            _positive_int(getattr(self, field_name), field_name=field_name)


def utc_day(timestamp: object) -> int:
    """Return the Unix UTC day for a strictly positive integer timestamp."""

    timestamp_value = _positive_int(timestamp, field_name="timestamp")
    return timestamp_value // SECONDS_PER_UTC_DAY


def worst_case_gas_usd_micros(
    gas_limit: object,
    max_fee_per_gas_wei: object,
    price_ceiling_micros: object,
) -> int:
    """Calculate a conservative gas cost in USD micro-units using integer math."""

    gas_limit_value = _positive_int(gas_limit, field_name="gas_limit")
    max_fee_value = _positive_int(
        max_fee_per_gas_wei, field_name="max_fee_per_gas_wei"
    )
    price_ceiling_value = _positive_int(
        price_ceiling_micros, field_name="price_ceiling_micros"
    )
    numerator = gas_limit_value * max_fee_value * price_ceiling_value
    return (numerator + WEI_PER_NATIVE_UNIT - 1) // WEI_PER_NATIVE_UNIT
