"""Safe local operator provisioning for wallet-scoped Hosted credentials.

The command in this module is intentionally not an HTTP control plane.  The
operator authenticates through the host's OS boundary and supplies an
owner-only enrollment bundle.  Core's database remains authoritative for the
wallet identity; the registry is replaced atomically and never emits secrets.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator

from services.account_service.repository import AccountRepository
from services.funding_service.hosted_wallet_registry import (
    HostedWalletCredential,
    HostedWalletRegistry,
    HostedWalletRegistryError,
    MAX_REGISTRY_FILE_BYTES,
)


_BUNDLE_FIELDS = frozenset({"schema_version", "request_id", "credential"})
_CREDENTIAL_FIELDS = frozenset(
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
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_MODES = frozenset({0o400, 0o600})


class HostedWalletProvisioningError(ValueError):
    """A bounded error that never includes enrollment secrets."""


class _DuplicateKey(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError


def provisioning_preflight(
    environment: Mapping[str, str], *, bundle_path: str | os.PathLike[str] | None
) -> dict[str, object]:
    """Return only missing configuration field names, never supplied values."""

    required = {
        "CLINK_FUNDING_DATABASE_URL",
        "CLINK_HOSTED_WALLET_CREDENTIALS_FILE",
    }
    fields = {name for name in required if not environment.get(name, "").strip()}
    registry_path = environment.get("CLINK_HOSTED_WALLET_CREDENTIALS_FILE", "").strip()
    if registry_path and not Path(registry_path).is_absolute():
        fields.add("CLINK_HOSTED_WALLET_CREDENTIALS_FILE")
    if bundle_path is None or not os.fspath(bundle_path).strip():
        fields.add("bundle_file")
    names = sorted(fields)
    return {
        "status": "configuration_required" if names else "configuration_valid",
        "fields": names,
    }


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


def _validate_private_file(metadata: os.stat_result, *, maximum: int) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in _SAFE_MODES
        or metadata.st_size < 1
        or metadata.st_size > maximum
    ):
        raise OSError


def _read_private_file(path: Path) -> bytes:
    try:
        before = os.lstat(path)
        _validate_private_file(before, maximum=MAX_REGISTRY_FILE_BYTES)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            _validate_private_file(opened, maximum=MAX_REGISTRY_FILE_BYTES)
            if _stat_identity(before) != _stat_identity(opened):
                raise OSError
            payload = bytearray()
            while len(payload) <= MAX_REGISTRY_FILE_BYTES:
                chunk = os.read(descriptor, min(64 * 1024, MAX_REGISTRY_FILE_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            after = os.fstat(descriptor)
            current = os.lstat(path)
            _validate_private_file(after, maximum=MAX_REGISTRY_FILE_BYTES)
            _validate_private_file(current, maximum=MAX_REGISTRY_FILE_BYTES)
            if (
                len(payload) > MAX_REGISTRY_FILE_BYTES
                or _stat_identity(opened) != _stat_identity(after)
                or _stat_identity(after) != _stat_identity(current)
                or len(payload) != after.st_size
            ):
                raise OSError
            return bytes(payload)
        finally:
            os.close(descriptor)
    except (OSError, TypeError, ValueError):
        raise HostedWalletProvisioningError(
            "hosted wallet provisioning bundle is invalid or unavailable"
        ) from None


def _decode_bundle(path: Path) -> tuple[str, HostedWalletCredential]:
    try:
        parsed = json.loads(
            _read_private_file(path).decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
        if not isinstance(parsed, dict) or set(parsed) != _BUNDLE_FIELDS:
            raise ValueError
        if type(parsed["schema_version"]) is not int or parsed["schema_version"] != 1:
            raise ValueError
        request_id = parsed["request_id"]
        raw_credential = parsed["credential"]
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or not isinstance(raw_credential, dict)
            or set(raw_credential) != _CREDENTIAL_FIELDS
        ):
            raise ValueError
        credential = HostedWalletCredential(**raw_credential)
        if credential.state != "active":
            raise ValueError
        return request_id, credential
    except HostedWalletProvisioningError:
        raise
    except (
        HostedWalletRegistryError,
        _DuplicateKey,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
    ):
        raise HostedWalletProvisioningError(
            "hosted wallet provisioning bundle is invalid or unavailable"
        ) from None


@contextmanager
def _registry_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".provision.lock")
    descriptor = -1
    try:
        _validate_registry_parent(path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OSError
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except OSError:
        raise HostedWalletProvisioningError(
            "hosted wallet registry lock is invalid or unavailable"
        ) from None
    finally:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _record_payload(credential: HostedWalletCredential) -> dict[str, str]:
    return {
        "user_id": credential.user_id,
        "wallet_identity_id": credential.wallet_identity_id,
        "tenant_id": credential.tenant_id,
        "node_id": credential.node_id,
        "wallet_binding_id": credential.wallet_binding_id,
        "access_token": credential.access_token,
        "device_private_key": credential.device_private_key,
        "state": credential.state,
    }


def _validate_registry_parent(path: Path) -> None:
    try:
        metadata = os.stat(path.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise OSError
    except (OSError, TypeError, ValueError):
        raise HostedWalletProvisioningError(
            "hosted wallet registry directory is invalid or unavailable"
        ) from None


def _write_registry(path: Path, credentials: list[HostedWalletCredential]) -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "wallets": [_record_payload(item) for item in credentials],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_REGISTRY_FILE_BYTES:
        raise HostedWalletProvisioningError("hosted wallet registry is too large")
    parent = path.parent
    descriptor = -1
    temporary = ""
    try:
        _validate_registry_parent(path)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
        if path.exists() or path.is_symlink():
            current = os.lstat(path)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.geteuid()
                or current.st_nlink != 1
                or stat.S_IMODE(current.st_mode) not in _SAFE_MODES
            ):
                raise OSError
        os.replace(temporary, path)
        temporary = ""
        if _stat_identity(os.lstat(path)) != _stat_identity(os.fstat(descriptor)):
            raise OSError
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except HostedWalletProvisioningError:
        raise
    except (OSError, TypeError, ValueError):
        raise HostedWalletProvisioningError(
            "hosted wallet registry update failed"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class HostedWalletProvisioner:
    """Verify one Core wallet and safely install its Hosted enrollment."""

    def __init__(
        self,
        repository: AccountRepository,
        registry_path: str | os.PathLike[str],
    ) -> None:
        self._repository = repository
        self._registry_path = Path(os.fspath(registry_path))
        if not self._registry_path.is_absolute():
            raise HostedWalletProvisioningError(
                "hosted wallet registry path is invalid"
            )

    def provision(
        self,
        bundle_path: str | os.PathLike[str],
        *,
        replace_current: bool = False,
    ) -> dict[str, str]:
        request_id, incoming = self._verified_bundle(
            bundle_path,
            replace_current=replace_current,
        )
        with _registry_lock(self._registry_path):
            status, updated = self._plan(
                self._existing_credentials(),
                incoming,
                replace_current=replace_current,
            )
            if status != "unchanged":
                _write_registry(self._registry_path, updated)
        return self._result(request_id, incoming, status)

    def dry_run(
        self,
        bundle_path: str | os.PathLike[str],
        *,
        replace_current: bool = False,
    ) -> dict[str, str]:
        """Validate the complete operation and report it without writing."""

        request_id, incoming = self._verified_bundle(
            bundle_path,
            replace_current=replace_current,
        )
        _validate_registry_parent(self._registry_path)
        status, _updated = self._plan(
            self._existing_credentials(),
            incoming,
            replace_current=replace_current,
        )
        if status == "provisioned":
            status = "would_provision"
        elif status == "replaced":
            status = "would_replace"
        return self._result(request_id, incoming, status)

    def _verified_bundle(
        self,
        bundle_path: str | os.PathLike[str],
        *,
        replace_current: bool,
    ) -> tuple[str, HostedWalletCredential]:
        if type(replace_current) is not bool:
            raise HostedWalletProvisioningError("replacement flag is invalid")
        request_id, incoming = _decode_bundle(Path(os.fspath(bundle_path)))
        identity = self._repository.wallet_identity(incoming.wallet_identity_id)
        if (
            identity is None
            or identity.status != "active"
            or identity.user_id != incoming.user_id
            or identity.verified_at is None
            or not identity.proof_hash
        ):
            raise HostedWalletProvisioningError(
                "Core wallet identity is not active and verified"
            )
        return request_id, incoming

    def _existing_credentials(self) -> list[HostedWalletCredential]:
        if not (self._registry_path.exists() or self._registry_path.is_symlink()):
            return []
        try:
            return list(
                HostedWalletRegistry(
                    self._registry_path,
                    chain_targets={},
                )._operator_snapshot()
            )
        except HostedWalletRegistryError:
            raise HostedWalletProvisioningError(
                "hosted wallet registry is invalid or unavailable"
            ) from None

    @staticmethod
    def _plan(
        existing: list[HostedWalletCredential],
        incoming: HostedWalletCredential,
        *,
        replace_current: bool,
    ) -> tuple[str, list[HostedWalletCredential]]:
        exact = next((item for item in existing if item == incoming), None)
        if exact is not None and exact.state == "active":
            return "unchanged", existing

        enrollment = (incoming.tenant_id, incoming.node_id)
        collision = next(
            (
                item
                for item in existing
                if (item.tenant_id, item.node_id) == enrollment
                and item != incoming
            ),
            None,
        )
        same_enrollment_rotation = collision is not None and (
            collision.user_id == incoming.user_id
            and collision.wallet_identity_id == incoming.wallet_identity_id
            and collision.wallet_binding_id == incoming.wallet_binding_id
        )
        if collision is not None and not same_enrollment_rotation:
            raise HostedWalletProvisioningError(
                "Hosted enrollment is already claimed"
            )

        wallet_current = next(
            (
                item
                for item in existing
                if item.user_id == incoming.user_id
                and item.wallet_identity_id == incoming.wallet_identity_id
                and item.state == "active"
            ),
            None,
        )
        if (wallet_current is not None or same_enrollment_rotation) and not replace_current:
            raise HostedWalletProvisioningError(
                "hosted wallet credential requires explicit replacement"
            )

        updated: list[HostedWalletCredential] = []
        for item in existing:
            if same_enrollment_rotation and (
                item.tenant_id,
                item.node_id,
            ) == enrollment:
                # A credential rotation keeps Hosted identity stable.  Drop
                # the retired secret so capability recovery stays unambiguous.
                continue
            if item == wallet_current:
                updated.append(replace(item, state="recovery_only"))
            else:
                updated.append(item)
        status = (
            "replaced"
            if wallet_current is not None or same_enrollment_rotation
            else "provisioned"
        )
        updated.append(incoming)
        return status, updated

    @staticmethod
    def _result(
        request_id: str,
        credential: HostedWalletCredential,
        status: str,
    ) -> dict[str, str]:
        return {
            "request_id": request_id,
            "status": status,
            "user_id": credential.user_id,
            "wallet_identity_id": credential.wallet_identity_id,
            "tenant_id": credential.tenant_id,
            "node_id": credential.node_id,
            "wallet_binding_id": credential.wallet_binding_id,
        }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision one Core-verified Hosted wallet enrollment"
    )
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--replace-current", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    namespace = parser.parse_args(arguments)
    report = provisioning_preflight(os.environ, bundle_path=namespace.bundle)
    if report["status"] != "configuration_valid":
        print(json.dumps(report, sort_keys=True))
        return 2

    try:
        repository = AccountRepository(os.environ["CLINK_FUNDING_DATABASE_URL"])
        provisioner = HostedWalletProvisioner(
            repository,
            os.environ["CLINK_HOSTED_WALLET_CREDENTIALS_FILE"],
        )
        operation = provisioner.dry_run if namespace.dry_run else provisioner.provision
        result = operation(namespace.bundle, replace_current=namespace.replace_current)
    except HostedWalletProvisioningError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "hosted wallet provisioning failed",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
