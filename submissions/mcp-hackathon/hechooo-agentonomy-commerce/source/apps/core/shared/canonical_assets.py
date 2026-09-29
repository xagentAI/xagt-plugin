from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from types import MappingProxyType


POLYGON_NETWORK = "eip155:137"
BASE_NETWORK = "eip155:8453"
AMOY_NETWORK = "eip155:80002"
PRODUCTION_USDC_ADDRESSES = {
    POLYGON_NETWORK: "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    BASE_NETWORK: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
}
AMOY_USDC_ADDRESS = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"


def _canonical_address(value: str) -> str:
    normalized = str(value).strip().lower()
    if re.fullmatch(r"0x[0-9a-f]{40}", normalized) is None:
        raise ValueError("canonical asset token_address must be an EVM address")
    return normalized


@dataclass(frozen=True)
class CanonicalAsset:
    network: str
    token_address: str
    token_symbol: str = "USDC"
    token_decimals: int = 6


class CanonicalAssetRegistry:
    """Validated source of truth for supported network/token pairs."""

    def __init__(self, assets: Mapping[str, Mapping[str, Any] | str]):
        validated: dict[str, CanonicalAsset] = {}
        for network, value in assets.items():
            if not isinstance(network, str) or not network.strip():
                raise ValueError("canonical asset network is required")
            values = {"token_address": value} if isinstance(value, str) else dict(value)
            symbol = str(values.get("token_symbol", "USDC")).strip()
            decimals = values.get("token_decimals", 6)
            if not symbol:
                raise ValueError("canonical asset token_symbol is required")
            if (
                not isinstance(decimals, int)
                or isinstance(decimals, bool)
                or not 0 <= decimals <= 255
            ):
                raise ValueError("canonical asset token_decimals are invalid")
            validated[network] = CanonicalAsset(
                network=network,
                token_address=_canonical_address(values.get("token_address", "")),
                token_symbol=symbol,
                token_decimals=decimals,
            )
        self._assets = MappingProxyType(validated)

    @classmethod
    def from_config(cls, config: Any) -> "CanonicalAssetRegistry":
        if getattr(config, "hosted_rehearsal_enabled", False):
            # The rehearsal is deliberately a single-network projection.  Do
            # not make Amoy and production assets available in the same Core
            # instance.
            return cls({AMOY_NETWORK: AMOY_USDC_ADDRESS})
        return cls(
            {
                POLYGON_NETWORK: (
                    config.clink_polygon_usdc_address
                    or PRODUCTION_USDC_ADDRESSES[POLYGON_NETWORK]
                ),
                BASE_NETWORK: (
                    config.clink_base_usdc_address
                    or PRODUCTION_USDC_ADDRESSES[BASE_NETWORK]
                ),
            }
        )

    @property
    def assets(self) -> Mapping[str, CanonicalAsset]:
        """Return a read-only view of the configured canonical pairs."""

        return self._assets

    def asset(self, network: str) -> CanonicalAsset:
        try:
            return self._assets[network]
        except KeyError as exc:
            raise ValueError(f"canonical asset network is unsupported: {network}") from exc

    def require_pair(self, network: str, token_address: str) -> CanonicalAsset:
        asset = self.asset(network)
        if _canonical_address(token_address) != asset.token_address:
            raise ValueError(
                f"canonical asset pair required for {network}: {asset.token_address}"
            )
        return asset

    def token_address(self, network: str) -> str:
        return self.asset(network).token_address
