"""Wallet-scoped Hosted facilitator credentials.

The registry is an operator-provisioned, read-only mapping from a verified Core
wallet identity to one Hosted enrollment.  It deliberately keeps chain trust
configuration separate from wallet records: origins, response keys and
executor contracts come only from Core configuration, while the JSON file
contains only the enrollment identity and its credentials.

Every public resolution reads and validates the file again.  This is
intentional.  A replacement or removal of an operator mapping must take effect
for the next credential or client selection without restarting Core.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import httpx

from services.account_service.schemas import canonicalize_evm_address
from services.funding_service.hosted_client import (
    HostedFacilitatorClient,
    _trusted_server_jwk,
)
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HOSTED_CHAIN_PROFILES,
)
from shared.payment_capability import PaymentCapabilityV1


MAX_REGISTRY_FILE_BYTES = 1024 * 1024

_ALLOWED_FILE_MODES = frozenset({0o400, 0o600})
_ROOT_FIELDS = frozenset({"schema_version", "wallets"})
_RECORD_FIELDS = frozenset(
    {
        "user_id",
        "wallet_identity_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "access_token",
        "device_private_key",
        "state",
    }
)
_TARGET_FIELDS = frozenset(
    {
        "origin",
        "server_public_jwk",
        "trusted_response_jwk",
        "response_public_jwk",
        "executor_contract",
    }
)
_RESPONSE_JWK_FIELDS = frozenset(
    {"server_public_jwk", "trusted_response_jwk", "response_public_jwk"}
)
_STATES = frozenset({"active", "recovery_only"})
_IDENTIFIER_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
)
_MAX_IDENTIFIER_LENGTH = 256
_MAX_ACCESS_TOKEN_LENGTH = 8192
_MAX_DEVICE_KEY_LENGTH = 64 * 1024
_MAX_ORIGIN_LENGTH = 2048


class HostedWalletRegistryError(ValueError):
    """A bounded, secret-free Hosted wallet registry failure."""


class _DuplicateJSONKey(ValueError):
    """Internal marker for strict JSON parsing."""


def _duplicate_key_rejector(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(character not in _IDENTIFIER_CHARS for character in value)
    ):
        raise ValueError
    return value


def _access_token(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_ACCESS_TOKEN_LENGTH
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ValueError
    return value


def _decode_device_key(value: object) -> DeviceSigningKey:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_DEVICE_KEY_LENGTH
        or value != value.strip()
    ):
        raise ValueError
    encoded = value
    if encoded.startswith("base64:"):
        encoded = encoded.removeprefix("base64:")
    try:
        if encoded.startswith("0x"):
            der = bytes.fromhex(encoded[2:])
        else:
            der = base64.b64decode(encoded, validate=True)
        return DeviceSigningKey.from_pkcs8_der(der)
    except (binascii.Error, TypeError, ValueError):
        raise ValueError from None


def _origin(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_ORIGIN_LENGTH:
        raise ValueError
    normalized = value.rstrip("/")
    try:
        parsed = httpx.URL(normalized)
        host = parsed.host
        parsed.port
    except (TypeError, ValueError, httpx.InvalidURL):
        raise ValueError from None
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError
    if parsed.scheme == "http":
        hostname = host.rstrip(".").lower()
        if hostname != "localhost":
            try:
                if not ipaddress.ip_address(hostname).is_loopback:
                    raise ValueError
            except ValueError:
                raise ValueError from None
    return normalized


def _target_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    if set(value) - _TARGET_FIELDS:
        raise ValueError
    response_fields = set(value) & _RESPONSE_JWK_FIELDS
    if len(response_fields) != 1:
        raise ValueError
    if "origin" not in value or "executor_contract" not in value:
        raise ValueError
    try:
        normalized_executor = canonicalize_evm_address(value["executor_contract"])
    except (TypeError, ValueError):
        raise ValueError from None
    if normalized_executor == "0x" + "0" * 40:
        raise ValueError
    try:
        normalized_jwk = _trusted_server_jwk(value[next(iter(response_fields))])
    except (TypeError, ValueError, KeyError, RecursionError):
        raise ValueError from None
    normalized = {
        "origin": _origin(value["origin"]),
        "server_public_jwk": MappingProxyType(dict(normalized_jwk)),
        "executor_contract": normalized_executor,
    }
    return MappingProxyType(normalized)


def _chain_targets(value: object) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise ValueError
    normalized: dict[str, Mapping[str, object]] = {}
    for network, target in value.items():
        if not isinstance(network, str) or network not in HOSTED_CHAIN_PROFILES:
            raise ValueError
        try:
            normalized[network] = _target_mapping(target)
        except (TypeError, ValueError, KeyError, RecursionError):
            raise ValueError from None
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class HostedWalletCredential:
    """One immutable operator-provisioned Hosted wallet enrollment."""

    user_id: str
    wallet_identity_id: str
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    access_token: str = field(repr=False)
    device_private_key: str = field(repr=False)
    state: Literal["active", "recovery_only"] = "active"

    def __post_init__(self) -> None:
        try:
            for value in (
                self.user_id,
                self.wallet_identity_id,
                self.tenant_id,
                self.node_id,
                self.wallet_binding_id,
            ):
                _identifier(value)
            _access_token(self.access_token)
            _decode_device_key(self.device_private_key)
            if not isinstance(self.state, str) or self.state not in _STATES:
                raise ValueError
        except (TypeError, ValueError):
            raise HostedWalletRegistryError(
                "hosted wallet credential is invalid"
            ) from None


ClientFactory = Callable[
    [HostedWalletCredential, str, Mapping[str, object]],
    object,
]


class HostedWalletRegistry:
    """Resolve wallet-scoped Hosted credentials from a strict local file."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        chain_targets: Mapping[str, Mapping[str, object]],
        client_factory: ClientFactory | None = None,
    ) -> None:
        try:
            self._path = Path(os.fspath(path))
            self._chain_targets = _chain_targets(chain_targets)
        except (TypeError, ValueError, OSError):
            raise HostedWalletRegistryError(
                "hosted wallet registry configuration is invalid"
            ) from None
        if client_factory is not None and not callable(client_factory):
            raise HostedWalletRegistryError(
                "hosted wallet registry configuration is invalid"
            )
        self._client_factory = client_factory

    @property
    def chain_targets(self) -> Mapping[str, Mapping[str, object]]:
        """Return the deeply immutable Core-trusted chain target projection."""

        return self._chain_targets

    def current(
        self,
        *,
        user_id: str,
        wallet_identity_id: str,
        network: str | None = None,
    ) -> HostedWalletCredential:
        """Return the active credential for one verified wallet identity.

        ``network`` is optional for compatibility with the original scalar
        registry.  When supplied, it is only a supported-target selector; the
        credential record format remains network-neutral.
        """

        self._validate_selector(user_id, wallet_identity_id)
        if network is not None and (
            type(network) is not str or network not in self._chain_targets
        ):
            raise HostedWalletRegistryError("hosted wallet target is not configured")
        records = self._load_records()
        matches = [
            record
            for record in records
            if record.user_id == user_id
            and record.wallet_identity_id == wallet_identity_id
        ]
        active = [record for record in matches if record.state == "active"]
        if active:
            return active[0]
        if matches:
            raise HostedWalletRegistryError(
                "hosted wallet credential is not active"
            )
        raise HostedWalletRegistryError(
            "hosted wallet credential is not configured"
        )

    def for_capability(
        self,
        capability: PaymentCapabilityV1,
        *,
        for_submission: bool = False,
    ) -> HostedWalletCredential:
        """Resolve the exact enrollment named by a Core payment capability."""

        fields = self._capability_fields(capability)
        if type(for_submission) is not bool:
            raise HostedWalletRegistryError("hosted payment capability is invalid")
        records = self._load_records()
        matches = [
            record
            for record in records
            if all(getattr(record, field_name) == value for field_name, value in fields)
        ]
        if not matches:
            raise HostedWalletRegistryError(
                "hosted wallet credential does not match capability"
            )
        credential = matches[0]
        if for_submission and credential.state != "active":
            raise HostedWalletRegistryError(
                "hosted wallet credential is recovery-only"
            )
        return credential

    def client(
        self,
        credential: HostedWalletCredential,
        network: str,
    ) -> HostedFacilitatorClient:
        """Build a Hosted client only after revalidating the current mapping."""

        if not isinstance(credential, HostedWalletCredential):
            raise HostedWalletRegistryError("hosted wallet credential is invalid")
        if not isinstance(network, str):
            raise HostedWalletRegistryError("hosted wallet target is not configured")
        target = self._chain_targets.get(network)
        if target is None:
            raise HostedWalletRegistryError("hosted wallet target is not configured")
        if not any(
            current == credential for current in self._load_records()
        ):
            raise HostedWalletRegistryError(
                "hosted wallet credential is not configured"
            )
        try:
            if self._client_factory is not None:
                # The injectable factory is intentionally test-only; its
                # return value follows the public client contract at runtime.
                return self._client_factory(credential, network, target)  # type: ignore[return-value]
            return self._default_client(credential, network, target)
        except HostedWalletRegistryError:
            raise HostedWalletRegistryError(
                "hosted wallet client construction failed"
            ) from None
        except Exception:
            raise HostedWalletRegistryError(
                "hosted wallet client construction failed"
            ) from None

    def configured_networks(self) -> tuple[str, ...]:
        """Return trusted targets when at least one active mapping is present."""

        records = self._load_records()
        if not any(record.state == "active" for record in records):
            return ()
        return tuple(sorted(self._chain_targets))

    def _operator_snapshot(self) -> tuple[HostedWalletCredential, ...]:
        """Return secrets only to the local OS-authenticated provisioner."""

        return self._load_records()

    @staticmethod
    def _validate_selector(user_id: object, wallet_identity_id: object) -> None:
        try:
            _identifier(user_id)
            _identifier(wallet_identity_id)
        except (TypeError, ValueError):
            raise HostedWalletRegistryError(
                "hosted wallet selector is invalid"
            ) from None

    @staticmethod
    def _capability_fields(
        capability: object,
    ) -> tuple[tuple[str, str], ...]:
        if isinstance(capability, Mapping) or capability is None:
            raise HostedWalletRegistryError("hosted payment capability is invalid")
        field_names = (
            "user_id",
            "wallet_identity_id",
            "tenant_id",
            "node_id",
            "wallet_binding_id",
        )
        try:
            values = tuple((name, _identifier(getattr(capability, name))) for name in field_names)
        except (AttributeError, TypeError, ValueError):
            raise HostedWalletRegistryError(
                "hosted payment capability is invalid"
            ) from None
        return values

    def _load_records(self) -> tuple[HostedWalletCredential, ...]:
        payload = self._read_file()
        try:
            parsed = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_duplicate_key_rejector,
                parse_constant=_reject_json_constant,
            )
        except (
            _DuplicateJSONKey,
            UnicodeDecodeError,
            TypeError,
            ValueError,
            RecursionError,
        ):
            raise HostedWalletRegistryError(
                "hosted wallet registry file is invalid or unavailable"
            ) from None
        if (
            not isinstance(parsed, dict)
            or set(parsed) != _ROOT_FIELDS
            or type(parsed.get("schema_version")) is not int
            or parsed.get("schema_version") != 1
            or not isinstance(parsed.get("wallets"), list)
        ):
            raise HostedWalletRegistryError(
                "hosted wallet registry file is invalid or unavailable"
            )

        records: list[HostedWalletCredential] = []
        try:
            for raw_record in parsed["wallets"]:
                if not isinstance(raw_record, dict) or set(raw_record) != _RECORD_FIELDS:
                    raise ValueError
                records.append(HostedWalletCredential(**raw_record))
            self._validate_record_claims(records)
        except (TypeError, ValueError, HostedWalletRegistryError):
            raise HostedWalletRegistryError(
                "hosted wallet registry records are invalid"
            ) from None
        return tuple(records)

    @staticmethod
    def _validate_record_claims(
        records: list[HostedWalletCredential],
    ) -> None:
        enrollment_keys: set[tuple[str, str]] = set()
        wallet_owners: dict[str, str] = {}
        active_wallets: set[tuple[str, str]] = set()
        for record in records:
            enrollment_key = (
                record.tenant_id,
                record.node_id,
            )
            if enrollment_key in enrollment_keys:
                raise ValueError
            enrollment_keys.add(enrollment_key)

            existing_owner = wallet_owners.get(record.wallet_identity_id)
            if existing_owner is not None and existing_owner != record.user_id:
                raise ValueError
            wallet_owners[record.wallet_identity_id] = record.user_id

            wallet_key = (record.user_id, record.wallet_identity_id)
            if record.state == "active":
                if wallet_key in active_wallets:
                    raise ValueError
                active_wallets.add(wallet_key)

    def _read_file(self) -> bytes:
        try:
            before = os.lstat(self._path)
            self._validate_file_stat(before)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(self._path, flags)
            try:
                opened = os.fstat(descriptor)
                self._validate_file_stat(opened)
                if self._stat_identity(before) != self._stat_identity(opened):
                    raise OSError
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = os.read(
                        descriptor,
                        min(64 * 1024, MAX_REGISTRY_FILE_BYTES + 1 - total),
                    )
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_REGISTRY_FILE_BYTES:
                        raise OSError
                after = os.fstat(descriptor)
                current_path = os.lstat(self._path)
                self._validate_file_stat(after)
                self._validate_file_stat(current_path)
                if (
                    self._stat_identity(opened) != self._stat_identity(after)
                    or self._stat_identity(after) != self._stat_identity(current_path)
                    or total != after.st_size
                ):
                    raise OSError
                return b"".join(chunks)
            finally:
                os.close(descriptor)
        except HostedWalletRegistryError:
            raise
        except (OSError, ValueError, TypeError):
            raise HostedWalletRegistryError(
                "hosted wallet registry file is invalid or unavailable"
            ) from None

    @staticmethod
    def _validate_file_stat(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) not in _ALLOWED_FILE_MODES
            or metadata.st_size < 0
            or metadata.st_size > MAX_REGISTRY_FILE_BYTES
        ):
            raise HostedWalletRegistryError(
                "hosted wallet registry file is invalid or unavailable"
            )

    @staticmethod
    def _stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_uid,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    @staticmethod
    def _default_client(
        credential: HostedWalletCredential,
        network: str,
        target: Mapping[str, object],
    ) -> HostedFacilitatorClient:
        device_key = _decode_device_key(credential.device_private_key)
        return HostedFacilitatorClient(
            chain_id=network,
            origin=target["origin"],
            tenant_id=credential.tenant_id,
            node_id=credential.node_id,
            wallet_binding_id=credential.wallet_binding_id,
            access_token=credential.access_token,
            device_key=device_key,
            server_public_jwk=target["server_public_jwk"],
        )
