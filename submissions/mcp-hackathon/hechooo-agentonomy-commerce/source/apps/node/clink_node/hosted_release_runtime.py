from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .hosted_enrollment import (
    EnrollmentConflict,
    EnrollmentTrust,
    HostedEnrollmentManager,
    HostedTargetTrust,
)
from .release_runtime import runtime_root
from .secrets import SecretStore


# Keep this equal to bundle_contract.MAX_CONTROL_MEMBER_SIZE.  The release
# payload cannot import build-time scripts, so the value is duplicated here.
_MAX_RELEASE_METADATA_BYTES = 8 * 1024 * 1024
_HOSTED_ENROLLMENT_KEYS = frozenset(
    {"schema_version", "enrollment_endpoint", "targets"}
)
_HOSTED_TARGET_KEYS = frozenset(
    {
        "chain_id",
        "chain",
        "token",
        "origin",
        "response_public_jwk",
        "response_key_id",
        "executor_contract",
    }
)
_HOSTED_PRODUCTION_TARGETS = {
    8453: {
        "chain": "eip155:8453",
        "token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    },
    137: {
        "chain": "eip155:137",
        "token": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    },
}
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class HostedReleaseMetadataError(ValueError):
    """The signed release metadata cannot establish Hosted trust."""


def release_metadata_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the metadata beside the resolved version payload."""

    return runtime_root(env).parents[1] / "release-metadata.json"


def read_release_metadata(path: Path) -> dict[str, object]:
    """Read one bounded, regular, duplicate-free canonical metadata file."""

    path = Path(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise HostedReleaseMetadataError(
            f"release metadata is unavailable: {path}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise HostedReleaseMetadataError(
            f"release metadata must be a regular file: {path}"
        )
    if metadata.st_size > _MAX_RELEASE_METADATA_BYTES:
        raise HostedReleaseMetadataError("release metadata exceeds the size limit")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HostedReleaseMetadataError(
            f"release metadata cannot be opened: {path}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise HostedReleaseMetadataError(
                f"release metadata must be a stable regular file: {path}"
            )
        raw = _read_bounded(descriptor)
    finally:
        os.close(descriptor)

    document = _parse_canonical_json(raw)
    if not isinstance(document, dict):
        raise HostedReleaseMetadataError("release metadata must be an object")
    return document


def load_release_enrollment_trust(
    env: Mapping[str, str] | None = None,
) -> EnrollmentTrust:
    """Load the exact Base/Polygon trust pins shipped with the release."""

    document = read_release_metadata(release_metadata_path(env))
    return _enrollment_trust(document)


class HostedReleaseRuntime:
    """Project an enrolled release into Core's private Hosted environment."""

    def __init__(self, *, env: Mapping[str, str] | None = None) -> None:
        self._env = dict(os.environ if env is None else env)

    @property
    def metadata_path(self) -> Path:
        return release_metadata_path(self._env)

    def load_trust(self) -> EnrollmentTrust:
        return load_release_enrollment_trust(self._env)

    def core_projection(self, secret_store: SecretStore) -> dict[str, str]:
        trust = self.load_trust()
        manager = HostedEnrollmentManager(
            secret_store=secret_store,
            transport=_MetadataOnlyTransport(trust.enrollment_endpoint),
            trust=trust,
        )
        try:
            bundle = manager.current()
        except (EnrollmentConflict, TypeError, ValueError):
            # A stale, corrupt, or trust-mismatched local bundle must not turn
            # into a different credential.  The Node remains usable with the
            # Hosted rail disabled until enrollment is repaired.
            return {}
        if bundle is None or bundle.state != "active":
            return {}
        if bundle.trust_fingerprint != trust.trust_fingerprint:
            return {}
        return _core_projection(bundle, trust)


def build_core_hosted_projection(
    secret_store: SecretStore,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the internal Core-only Hosted environment for a release."""

    return HostedReleaseRuntime(env=env).core_projection(secret_store)


class _MetadataOnlyTransport:
    """Satisfy the enrollment manager's read-only endpoint binding check."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint


def _enrollment_trust(document: Mapping[str, object]) -> EnrollmentTrust:
    if type(document.get("schema_version")) is not int or document.get(
        "schema_version"
    ) != 1:
        raise HostedReleaseMetadataError(
            "release metadata schema_version must be 1"
        )
    if document.get("platform") != "linux-x86_64":
        raise HostedReleaseMetadataError(
            "release metadata platform must be linux-x86_64"
        )
    hosted = document.get("hosted_enrollment")
    if not isinstance(hosted, Mapping) or set(hosted) != _HOSTED_ENROLLMENT_KEYS:
        raise HostedReleaseMetadataError(
            "release metadata hosted enrollment is missing or invalid"
        )
    if type(hosted.get("schema_version")) is not int or hosted.get(
        "schema_version"
    ) != 1:
        raise HostedReleaseMetadataError(
            "hosted enrollment schema_version must be 1"
        )

    raw_targets = hosted.get("targets")
    if not isinstance(raw_targets, list) or len(raw_targets) != 2:
        raise HostedReleaseMetadataError(
            "hosted enrollment must contain exactly Base and Polygon targets"
        )
    targets: dict[int, HostedTargetTrust] = {}
    for raw_target in raw_targets:
        if (
            not isinstance(raw_target, Mapping)
            or set(raw_target) != _HOSTED_TARGET_KEYS
        ):
            raise HostedReleaseMetadataError(
                "hosted target has unknown or missing fields"
            )
        chain_id = raw_target.get("chain_id")
        if type(chain_id) is not int or chain_id not in _HOSTED_PRODUCTION_TARGETS:
            raise HostedReleaseMetadataError(
                "hosted target chain is not production"
            )
        if chain_id in targets:
            raise HostedReleaseMetadataError("hosted target chain is duplicated")
        expected = _HOSTED_PRODUCTION_TARGETS[chain_id]
        if raw_target.get("chain") != expected["chain"]:
            raise HostedReleaseMetadataError("hosted target chain is not canonical")
        if raw_target.get("token") != expected["token"]:
            raise HostedReleaseMetadataError("hosted target token is not canonical")
        try:
            target = HostedTargetTrust(
                chain_id=chain_id,
                endpoint=raw_target["origin"],  # type: ignore[arg-type]
                response_public_jwk=raw_target[
                    "response_public_jwk"
                ],  # type: ignore[arg-type]
                executor_contract=raw_target["executor_contract"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HostedReleaseMetadataError(
                "hosted target trust is invalid"
            ) from exc
        if raw_target.get("response_key_id") != target.response_key_id:
            raise HostedReleaseMetadataError(
                "hosted response key thumbprint does not match"
            )
        targets[chain_id] = target
    if set(targets) != set(_HOSTED_PRODUCTION_TARGETS):
        raise HostedReleaseMetadataError(
            "hosted enrollment must contain exact Base and Polygon targets"
        )
    try:
        return EnrollmentTrust(
            enrollment_endpoint=hosted["enrollment_endpoint"],  # type: ignore[arg-type]
            targets=targets,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HostedReleaseMetadataError(
            "hosted enrollment trust is invalid"
        ) from exc


def _core_projection(bundle: Any, trust: EnrollmentTrust) -> dict[str, str]:
    try:
        private_der = _decode_unpadded_base64url(bundle.private_key_pkcs8_b64)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise HostedReleaseMetadataError(
            "active enrollment device key is invalid"
        ) from exc
    targets = {
        f"eip155:{chain_id}": {
            "origin": trust.targets[chain_id].endpoint,
            "executor_contract": trust.targets[chain_id].executor_contract,
            "server_public_jwk": dict(
                trust.targets[chain_id].response_public_jwk
            ),
        }
        for chain_id in (8453, 137)
    }
    return {
        "CLINK_FACILITATOR_MODE": "hosted",
        "CLINK_LIVE_FUNDING": "true",
        "CLINK_NATIVE_FACILITATOR_ENABLED": "false",
        "CLINK_HOSTED_FACILITATOR_TENANT_ID": bundle.tenant_id,
        "CLINK_HOSTED_FACILITATOR_NODE_ID": bundle.node_id,
        "CLINK_HOSTED_FACILITATOR_WALLET_BINDING_ID": bundle.wallet_binding_id,
        "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN": bundle.access_token,
        "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY": (
            "base64:" + base64.b64encode(private_der).decode("ascii")
        ),
        "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS": json.dumps(
            targets,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _decode_unpadded_base64url(value: object) -> bytes:
    if not isinstance(value, str) or _BASE64URL.fullmatch(value) is None:
        raise ValueError("base64url value is invalid")
    decoded = base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError("base64url value is not canonical")
    return decoded


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= _MAX_RELEASE_METADATA_BYTES:
        chunk = os.read(
            descriptor,
            min(64 * 1024, _MAX_RELEASE_METADATA_BYTES + 1 - total),
        )
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_RELEASE_METADATA_BYTES:
            break
    if total > _MAX_RELEASE_METADATA_BYTES:
        raise HostedReleaseMetadataError("release metadata exceeds the size limit")
    return b"".join(chunks)


def _parse_canonical_json(raw: bytes) -> object:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, _DuplicateJSONKey):
            raise HostedReleaseMetadataError(
                "release metadata contains duplicate keys"
            ) from exc
        raise HostedReleaseMetadataError("release metadata is invalid JSON") from exc
    if _canonical_json(document) != raw:
        raise HostedReleaseMetadataError("release metadata is not canonical JSON")
    return document


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HostedReleaseMetadataError(
            "release metadata cannot be canonicalized"
        ) from exc
