"""Safely export one enrolled Hosted credential for Core provisioning.

This module deliberately has no CLI or network surface.  It converts the
Node's active enrollment state into the small, owner-only input document used
by Core's operator provisioning command.  The exported document contains
secrets by design, so it is written atomically and is never returned, logged,
or included in an exception.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .hosted_enrollment import HostedEnrollmentBundle


MAX_CORE_PROVISIONING_BUNDLE_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,8192}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class HostedWalletBundleError(ValueError):
    """A bounded export failure that never contains a credential secret."""


def write_core_provisioning_bundle(
    bundle: HostedEnrollmentBundle,
    *,
    user_id: str,
    wallet_identity_id: str,
    request_id: str,
    output_path: str | os.PathLike[str],
) -> dict[str, str]:
    """Write one active enrollment in Core's provisioning-bundle format.

    ``output_path`` must be an absolute path in an existing directory owned by
    the effective user and not writable by group or world.  Existing targets,
    including symlinks and hard links, are rejected.  The return value contains
    only identifiers, status, and the absolute output path; the credential
    itself is never returned.
    """

    private_der = _validate_inputs(
        bundle,
        user_id=user_id,
        wallet_identity_id=wallet_identity_id,
        request_id=request_id,
    )
    output = _validated_output_path(output_path)
    payload = _encode_payload(
        bundle,
        private_der,
        user_id=user_id,
        wallet_identity_id=wallet_identity_id,
        request_id=request_id,
    )
    if len(payload) > MAX_CORE_PROVISIONING_BUNDLE_BYTES:
        raise HostedWalletBundleError(
            "Core provisioning bundle exceeds the size limit"
        )

    _write_private_file(output, payload)
    return {
        "status": "written",
        "path": str(output),
        "request_id": request_id,
        "user_id": user_id,
        "wallet_identity_id": wallet_identity_id,
        "tenant_id": bundle.tenant_id,
        "node_id": bundle.node_id,
        "wallet_binding_id": bundle.wallet_binding_id,
    }


def _validate_inputs(
    bundle: HostedEnrollmentBundle,
    *,
    user_id: str,
    wallet_identity_id: str,
    request_id: str,
) -> bytes:
    if type(bundle) is not HostedEnrollmentBundle or bundle.state != "active":
        raise HostedWalletBundleError(
            "only an active Hosted enrollment can be exported"
        )
    if (
        bundle.rotation_id is not None
        or bundle.pending_private_key_pkcs8_b64 is not None
        or bundle.pending_access_token is not None
        or bundle.rotation_prepared
        or bundle.revocation_pending
        or bundle.revocation_id is not None
    ):
        raise HostedWalletBundleError(
            "Hosted enrollment has a pending state and cannot be exported"
        )

    _identifier(user_id, "user_id")
    _identifier(wallet_identity_id, "wallet_identity_id")
    _identifier(bundle.wallet_binding_id, "wallet_binding_id")
    _identifier(bundle.tenant_id, "tenant_id")
    _identifier(bundle.node_id, "node_id")
    if type(request_id) is not str or _REQUEST_ID.fullmatch(request_id) is None:
        raise HostedWalletBundleError("request_id is invalid")
    if (
        type(bundle.access_token) is not str
        or _TOKEN.fullmatch(bundle.access_token) is None
    ):
        raise HostedWalletBundleError("access_token is invalid")
    return _decode_private_key(bundle.private_key_pkcs8_b64)


def _identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise HostedWalletBundleError(f"{field_name} is invalid")
    return value


def _decode_private_key(value: object) -> bytes:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_CORE_PROVISIONING_BUNDLE_BYTES
        or _BASE64URL.fullmatch(value) is None
    ):
        raise HostedWalletBundleError("device private key is invalid")
    try:
        encoded = value + "=" * (-len(value) % 4)
        der = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(der).rstrip(b"=").decode("ascii") != value:
            raise ValueError
        key = serialization.load_der_private_key(der, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
    except (TypeError, ValueError, UnicodeError):
        raise HostedWalletBundleError("device private key is invalid") from None
    return der


def _encode_payload(
    bundle: HostedEnrollmentBundle,
    private_der: bytes,
    *,
    user_id: str,
    wallet_identity_id: str,
    request_id: str,
) -> bytes:
    document: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "credential": {
            "user_id": user_id,
            "wallet_identity_id": wallet_identity_id,
            "tenant_id": bundle.tenant_id,
            "node_id": bundle.node_id,
            "wallet_binding_id": bundle.wallet_binding_id,
            "access_token": bundle.access_token,
            "device_private_key": (
                "base64:" + base64.b64encode(private_der).decode("ascii")
            ),
            "state": "active",
        },
    }
    try:
        # Core accepts this canonical, standard-base64 device-key spelling.
        return json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise HostedWalletBundleError(
            "Core provisioning bundle could not be encoded"
        ) from None


def _validated_output_path(value: object) -> Path:
    try:
        if isinstance(value, bytes):
            raise TypeError
        raw = os.fspath(value)
        if type(raw) is not str or not raw or not os.path.isabs(raw):
            raise ValueError
        if len(raw.encode("utf-8")) > 4096:
            raise ValueError
        output = Path(os.path.abspath(raw))
        _validate_parent(output.parent)
        _require_absent(output)
        return output
    except HostedWalletBundleError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise HostedWalletBundleError(
            "output path is invalid or already exists"
        ) from None


def _validate_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise OSError
        # Reject symlinked ancestors too.  The effective parent must be the
        # directory named by the caller, not a path redirected elsewhere.
        if parent.resolve(strict=True) != Path(
            os.path.abspath(os.fspath(parent))
        ):
            raise OSError
    except (OSError, RuntimeError, TypeError, ValueError):
        raise HostedWalletBundleError(
            "output directory is invalid or unavailable"
        ) from None


def _require_absent(output: Path) -> None:
    try:
        os.lstat(output)
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        raise HostedWalletBundleError(
            "output path is invalid or already exists"
        ) from None
    raise HostedWalletBundleError("output path is invalid or already exists")


def _write_private_file(output: Path, payload: bytes) -> None:
    parent = output.parent
    parent_fd = -1
    temporary_name: str | None = None
    descriptor = -1
    try:
        _validate_parent(parent)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        parent_fd = os.open(parent, flags)
        _validate_parent_descriptor(parent_fd)
        _require_absent(output)

        for _attempt in range(8):
            candidate = (
                f".{output.name}.tmp-{os.getpid()}-{secrets.token_hex(16)}"
            )
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor < 0 or temporary_name is None:
            raise OSError

        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
        _validate_file_descriptor(descriptor, expected_size=len(payload))
        os.close(descriptor)
        descriptor = -1

        # Check once more for a useful early error, but do not rely on this
        # check for publication: a caller may create the target immediately
        # afterwards.  The anchored hard-link below is the no-replace guard.
        _require_absent(output)
        os.link(
            temporary_name,
            output.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=parent_fd)
        temporary_name = None
        _validate_file(output, expected_size=len(payload))
        os.fsync(parent_fd)
    except HostedWalletBundleError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise HostedWalletBundleError(
            "Core provisioning bundle could not be written"
        ) from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                if parent_fd >= 0:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                else:
                    os.unlink(parent / temporary_name)
            except OSError:
                pass
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _validate_parent_descriptor(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise OSError


def _validate_file_descriptor(descriptor: int, *, expected_size: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != expected_size
        or expected_size > MAX_CORE_PROVISIONING_BUNDLE_BYTES
    ):
        raise OSError


def _validate_file(path: Path, *, expected_size: int) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != expected_size
        or expected_size > MAX_CORE_PROVISIONING_BUNDLE_BYTES
    ):
        raise OSError
