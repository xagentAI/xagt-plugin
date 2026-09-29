"""Route wallet-scoped Hosted credentials to one immutable chain registry.

The v1 registry format intentionally has no network field.  A dual-chain
deployment therefore composes one registry instance per trusted chain and
keeps the network choice at the Core reservation/capability boundary.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES
from shared.payment_capability import PaymentCapabilityV1

from services.funding_service.hosted_client import HostedFacilitatorClient
from services.funding_service.hosted_wallet_registry import (
    ClientFactory,
    HostedWalletCredential,
    HostedWalletRegistry,
    HostedWalletRegistryError,
)


def _normalized_registry_path(value: object) -> str:
    try:
        path = os.fspath(value)
    except (TypeError, ValueError, OSError):
        raise HostedWalletRegistryError(
            "hosted wallet router configuration is invalid"
        ) from None
    if (
        not isinstance(path, str)
        or not path
        or path != path.strip()
        or not Path(path).is_absolute()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or unicodedata.category(character).startswith("C")
            or unicodedata.category(character) in {"Zl", "Zp"}
            for character in path
        )
    ):
        raise HostedWalletRegistryError(
            "hosted wallet router configuration is invalid"
        )
    return os.path.normcase(os.path.normpath(path))


class HostedWalletRouter:
    """Compose independent wallet registries without cross-chain fallback."""

    def __init__(
        self,
        credential_files: Mapping[str, str | os.PathLike[str]],
        *,
        chain_targets: Mapping[str, Mapping[str, object]],
        client_factory: ClientFactory | None = None,
    ) -> None:
        if not isinstance(credential_files, Mapping) or not isinstance(
            chain_targets, Mapping
        ):
            raise HostedWalletRegistryError(
                "hosted wallet router configuration is invalid"
            )
        if client_factory is not None and not callable(client_factory):
            raise HostedWalletRegistryError(
                "hosted wallet router configuration is invalid"
            )

        paths: dict[str, str] = {}
        normalized_paths: set[str] = set()
        try:
            for network, raw_path in credential_files.items():
                if not isinstance(network, str) or network not in HOSTED_CHAIN_PROFILES:
                    raise ValueError
                path = _normalized_registry_path(raw_path)
                if path in normalized_paths:
                    raise ValueError
                normalized_paths.add(path)
                paths[network] = path
        except (HostedWalletRegistryError, TypeError, ValueError):
            raise HostedWalletRegistryError(
                "hosted wallet router configuration is invalid"
            ) from None

        if set(paths) != set(chain_targets):
            raise HostedWalletRegistryError(
                "hosted wallet router targets and credential files must match"
            )

        registries: dict[str, HostedWalletRegistry] = {}
        try:
            for network in sorted(paths):
                # The inner registry receives only the target for its own
                # network.  No target from another chain can be consulted by
                # its current/client operations.
                registries[network] = HostedWalletRegistry(
                    paths[network],
                    chain_targets={network: chain_targets[network]},
                    client_factory=client_factory,
                )
        except (HostedWalletRegistryError, KeyError, TypeError, ValueError):
            raise HostedWalletRegistryError(
                "hosted wallet router configuration is invalid"
            ) from None

        self._registries = MappingProxyType(registries)
        self._credential_files = MappingProxyType(paths)
        self._chain_targets = MappingProxyType(
            {
                network: registry.chain_targets[network]
                for network, registry in registries.items()
            }
        )

    @property
    def chain_targets(self) -> Mapping[str, Mapping[str, object]]:
        """Return the deeply immutable Core-trusted target mapping."""

        return self._chain_targets

    def current(
        self,
        *,
        user_id: str,
        wallet_identity_id: str,
        network: str | None = None,
    ) -> HostedWalletCredential:
        """Resolve an active credential in the explicitly selected network."""

        selected = self._select_network(network)
        return self._registries[selected].current(
            user_id=user_id,
            wallet_identity_id=wallet_identity_id,
            network=selected,
        )

    def for_capability(
        self,
        capability: PaymentCapabilityV1,
        *,
        for_submission: bool = False,
    ) -> HostedWalletCredential:
        """Resolve the capability's exact chain and enrollment."""

        if not isinstance(capability, PaymentCapabilityV1):
            raise HostedWalletRegistryError("hosted payment capability is invalid")
        selected = self._select_network(capability.network)
        return self._registries[selected].for_capability(
            capability,
            for_submission=for_submission,
        )

    def client(
        self,
        credential: HostedWalletCredential,
        network: str,
    ) -> HostedFacilitatorClient:
        """Build a client only after revalidating against that chain's file."""

        selected = self._select_network(network)
        return self._registries[selected].client(credential, selected)

    def configured_networks(self) -> tuple[str, ...]:
        """Return only networks whose own registry has an active mapping."""

        configured: list[str] = []
        for network, registry in self._registries.items():
            try:
                if network in registry.configured_networks():
                    configured.append(network)
            except HostedWalletRegistryError:
                # A broken or missing file is isolated to that chain.  The
                # caller must not infer a credential for it from another file.
                continue
        return tuple(sorted(configured))

    def _select_network(self, network: str | None) -> str:
        if network is None:
            if len(self._registries) != 1:
                raise HostedWalletRegistryError(
                    "hosted wallet network is ambiguous"
                )
            return next(iter(self._registries))
        if type(network) is not str or network not in self._registries:
            raise HostedWalletRegistryError("hosted wallet target is not configured")
        return network
