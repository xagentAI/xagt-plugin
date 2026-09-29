from __future__ import annotations

import base64
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/core"))
sys.path.insert(0, str(ROOT / "apps/node"))

from clink_node.config import NodeSettings, Profile
from clink_node.hosted_enrollment import (
    EnrollmentTrust,
    HostedEnrollmentBundle,
    HostedTargetTrust,
)
from shared.hosted_facilitator_protocol import DeviceSigningKey  # noqa: E402
from clink_node.paths import NodePaths
from clink_node.release_runtime import runtime_root
from clink_node.secrets import MemorySecretStore
from clink_node.hosted_release_runtime import (
    HostedReleaseMetadataError,
    HostedReleaseRuntime,
    build_core_hosted_projection,
    read_release_metadata,
    release_metadata_path,
)
from clink_node.runtime import ManagedEnvironmentBuilder


BASE_RESPONSE_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "axfR8uEsQkf4vOblY6RA8ncDfYEt6zOg9KE5RdiYwpY",
    "y": "T-NC4v4af5uO5-tKfA-eFivOM1drMV7Oy7ZAaDe_UfU",
}
POLYGON_RESPONSE_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "fPJ7GI0DT36KUjgDBLUaw8CJaeJ38hs1pgtI_EdmmXg",
    "y": "B3dVENuO0EApPZrGn3Qw27p9reY86YIpngS3nSJ4c9E",
}


def _trust() -> EnrollmentTrust:
    return EnrollmentTrust(
        enrollment_endpoint="https://enroll.agentonomy.example/v1/enrollments",
        targets={
            8453: HostedTargetTrust(
                chain_id=8453,
                endpoint="https://base.agentonomy.example",
                response_public_jwk=BASE_RESPONSE_JWK,
                executor_contract="0x" + "11" * 20,
            ),
            137: HostedTargetTrust(
                chain_id=137,
                endpoint="https://polygon.agentonomy.example",
                response_public_jwk=POLYGON_RESPONSE_JWK,
                executor_contract="0x" + "22" * 20,
            ),
        },
    )


def _metadata_document(trust: EnrollmentTrust | None = None) -> dict[str, object]:
    trust = trust or _trust()
    targets = [
        {
            "chain_id": chain_id,
            "chain": f"eip155:{chain_id}",
            "token": (
                "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
                if chain_id == 8453
                else "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
            ),
            "origin": trust.targets[chain_id].endpoint,
            "response_public_jwk": dict(
                trust.targets[chain_id].response_public_jwk
            ),
            "response_key_id": trust.targets[chain_id].response_key_id,
            "executor_contract": trust.targets[chain_id].executor_contract,
        }
        for chain_id in (8453, 137)
    ]
    return {
        "schema_version": 1,
        "version": "0.1.0",
        "platform": "linux-x86_64",
        "entrypoint": "payload/bin/clink-launcher",
        "source_date_epoch": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "files": [],
        "hosted_enrollment": {
            "schema_version": 1,
            "enrollment_endpoint": trust.enrollment_endpoint,
            "targets": targets,
        },
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _runtime_tree(tmp_path: Path) -> tuple[Path, Path]:
    app_root = tmp_path / "versions" / "0.1.0" / "payload" / "app"
    app_root.mkdir(parents=True)
    return app_root, app_root.parents[1] / "release-metadata.json"


def _write_metadata(
    app_root: Path,
    document: dict[str, object] | None = None,
) -> dict[str, str]:
    metadata = release_metadata_path({"CLINK_RUNTIME_ROOT": str(app_root)})
    metadata.write_bytes(_canonical_json(document or _metadata_document()))
    metadata.chmod(0o644)
    return {"CLINK_RUNTIME_ROOT": str(app_root)}


def _bundle_bytes(
    trust: EnrollmentTrust,
    *,
    state: str = "active",
    trust_fingerprint: str | None = None,
) -> bytes:
    private_key = ec.generate_private_key(ec.SECP256R1())
    der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    bundle = HostedEnrollmentBundle(
        state=state,  # type: ignore[arg-type]
        wallet_binding_id="wallet_binding_1",
        tenant_id="tenant_1" if state != "enrollment_pending" else "",
        node_id="node_1" if state != "enrollment_pending" else "",
        credential_epoch=1 if state != "enrollment_pending" else 0,
        private_key_pkcs8_b64=base64.urlsafe_b64encode(der)
        .rstrip(b"=")
        .decode("ascii"),
        access_token="a" * 43,
        trust_fingerprint=trust_fingerprint or trust.trust_fingerprint,
        invite_digest="a" * 64 if state == "enrollment_pending" else None,
    )
    return _canonical_json(
        {
            "schema_version": 1,
            "state": bundle.state,
            "wallet_binding_id": bundle.wallet_binding_id,
            "tenant_id": bundle.tenant_id,
            "node_id": bundle.node_id,
            "credential_epoch": bundle.credential_epoch,
            "private_key_pkcs8_b64": bundle.private_key_pkcs8_b64,
            "access_token": bundle.access_token,
            "trust_fingerprint": bundle.trust_fingerprint,
            "invite_digest": bundle.invite_digest,
            "rotation_id": bundle.rotation_id,
            "pending_private_key_pkcs8_b64": bundle.pending_private_key_pkcs8_b64,
            "pending_access_token": bundle.pending_access_token,
            "rotation_prepared": bundle.rotation_prepared,
            "revocation_pending": bundle.revocation_pending,
            "revocation_id": bundle.revocation_id,
        }
    )


def test_release_metadata_is_read_from_resolved_payload_parent(tmp_path: Path) -> None:
    app_root, metadata = _runtime_tree(tmp_path)
    env = _write_metadata(app_root)

    assert runtime_root(env) == app_root.resolve()
    assert release_metadata_path(env) == metadata
    assert read_release_metadata(metadata)["schema_version"] == 1


def test_release_metadata_limit_matches_bundle_control_member_contract() -> None:
    from clink_node.hosted_release_runtime import _MAX_RELEASE_METADATA_BYTES

    assert _MAX_RELEASE_METADATA_BYTES == 8 * 1024 * 1024


def test_release_metadata_accepts_canonical_control_member_under_8_mib(
    tmp_path: Path,
) -> None:
    app_root, metadata = _runtime_tree(tmp_path)
    document = {"padding": "x" * (1 * 1024 * 1024)}
    encoded = _canonical_json(document)
    assert 1 * 1024 * 1024 < len(encoded) < 8 * 1024 * 1024
    metadata.write_bytes(encoded)

    assert read_release_metadata(metadata) == document


def test_release_metadata_rejects_control_member_over_8_mib(
    tmp_path: Path,
) -> None:
    _app_root, metadata = _runtime_tree(tmp_path)
    with metadata.open("wb") as handle:
        handle.truncate(8 * 1024 * 1024 + 1)

    with pytest.raises(HostedReleaseMetadataError, match="size limit"):
        read_release_metadata(metadata)


def test_active_enrollment_projects_only_core_hosted_credentials(
    tmp_path: Path,
) -> None:
    app_root, _ = _runtime_tree(tmp_path)
    env = _write_metadata(app_root)
    trust = _trust()
    store = MemorySecretStore(
        {"hosted-enrollment-v1": _bundle_bytes(trust)}
    )

    projection = build_core_hosted_projection(store, env=env)

    assert projection["CLINK_FACILITATOR_MODE"] == "hosted"
    assert projection["CLINK_LIVE_FUNDING"] == "true"
    assert projection["CLINK_NATIVE_FACILITATOR_ENABLED"] == "false"
    assert projection["CLINK_HOSTED_FACILITATOR_TENANT_ID"] == "tenant_1"
    assert projection["CLINK_HOSTED_FACILITATOR_NODE_ID"] == "node_1"
    assert (
        projection["CLINK_HOSTED_FACILITATOR_WALLET_BINDING_ID"]
        == "wallet_binding_1"
    )
    assert projection["CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN"] == "a" * 43
    encoded_device_key = projection["CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY"]
    assert encoded_device_key.startswith("base64:")
    device_key = DeviceSigningKey.from_pkcs8_der(
        base64.b64decode(
            encoded_device_key.removeprefix("base64:"),
            validate=True,
        )
    )
    assert device_key.public_jwk["crv"] == "P-256"
    targets = json.loads(projection["CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS"])
    assert set(targets) == {"eip155:8453", "eip155:137"}
    assert targets["eip155:8453"]["origin"] == "https://base.agentonomy.example"
    assert targets["eip155:137"]["origin"] == "https://polygon.agentonomy.example"
    assert targets["eip155:8453"]["executor_contract"] == (
        "0x" + "11" * 20
    )
    assert targets["eip155:137"]["executor_contract"] == "0x" + "22" * 20
    assert "CLINK_HOSTED_FACILITATOR_URL" not in projection
    assert "CLINK_HOSTED_FACILITATOR_SERVER_PUBLIC_JWK" not in projection
    assert "CLINK_POLYGON_RPC_URL" not in projection
    assert "CLINK_BASE_RPC_URL" not in projection
    assert "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY" not in projection
    assert "CLINK_FUNDING_DATABASE_URL" not in projection


def test_pending_or_untrusted_enrollment_keeps_hosted_disabled(tmp_path: Path) -> None:
    app_root, _ = _runtime_tree(tmp_path)
    env = _write_metadata(app_root)
    trust = _trust()

    for encoded in (
        None,
        _bundle_bytes(trust, state="enrollment_pending"),
        _bundle_bytes(trust, trust_fingerprint="f" * 64),
    ):
        store = MemorySecretStore(
            {} if encoded is None else {"hosted-enrollment-v1": encoded}
        )
        assert build_core_hosted_projection(store, env=env) == {}


def test_release_metadata_missing_or_malformed_fails_closed(tmp_path: Path) -> None:
    app_root, metadata = _runtime_tree(tmp_path)
    env = {"CLINK_RUNTIME_ROOT": str(app_root)}

    with pytest.raises(HostedReleaseMetadataError):
        HostedReleaseRuntime(env=env).load_trust()

    metadata.write_bytes(b'{"schema_version":1,"schema_version":1}')
    metadata.chmod(0o644)
    with pytest.raises(HostedReleaseMetadataError, match="duplicate"):
        HostedReleaseRuntime(env=env).load_trust()


def test_release_metadata_symlink_is_rejected(tmp_path: Path) -> None:
    app_root, metadata = _runtime_tree(tmp_path)
    target = tmp_path / "metadata-target.json"
    target.write_bytes(_canonical_json(_metadata_document()))
    metadata.symlink_to(target)

    with pytest.raises(HostedReleaseMetadataError, match="regular"):
        read_release_metadata(metadata)


def test_hosted_target_token_and_key_thumbprint_are_checked(tmp_path: Path) -> None:
    app_root, _ = _runtime_tree(tmp_path)
    base = _metadata_document()
    wrong_token = json.loads(json.dumps(base))
    wrong_token["hosted_enrollment"]["targets"][0]["token"] = (
        "0x" + "1" * 40
    )
    env = _write_metadata(app_root, wrong_token)
    with pytest.raises(HostedReleaseMetadataError, match="token"):
        HostedReleaseRuntime(env=env).load_trust()

    wrong_key = json.loads(json.dumps(base))
    wrong_key["hosted_enrollment"]["targets"][0]["response_key_id"] = "A" * 43
    _write_metadata(app_root, wrong_key)
    with pytest.raises(HostedReleaseMetadataError, match="thumbprint"):
        HostedReleaseRuntime(env=env).load_trust()

    wrong_executor = json.loads(json.dumps(base))
    wrong_executor["hosted_enrollment"]["targets"][0]["executor_contract"] = (
        "0x" + "00" * 20
    )
    _write_metadata(app_root, wrong_executor)
    with pytest.raises(HostedReleaseMetadataError, match="trust"):
        HostedReleaseRuntime(env=env).load_trust()


def test_release_builder_clears_user_hosted_and_live_configuration(
    tmp_path: Path,
) -> None:
    app_root, _ = _runtime_tree(tmp_path)
    env = _write_metadata(app_root)
    env.update(
        {
            "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN": "attacker-token",
            "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY": "attacker-key",
            "CLINK_FACILITATOR_MODE": "native",
            "CLINK_LIVE_FUNDING": "true",
            "CLINK_NATIVE_FACILITATOR_ENABLED": "true",
            "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY": "private-key",
            "PREDICTION_MARKETS_LIVE_MODE": "true",
        }
    )
    paths = NodePaths.from_home(tmp_path / ".clink")
    settings = replace(
        NodeSettings.defaults(Profile.PERSONAL, paths=paths),
        release_mode=True,
    )
    store = MemorySecretStore(
        {"hosted-enrollment-v1": _bundle_bytes(_trust())}
    )

    managed = ManagedEnvironmentBuilder(
        settings,
        store,
        base_env=env,
    ).build()

    assert managed["CLINK_FACILITATOR_MODE"] == "hosted"
    assert managed["CLINK_LIVE_FUNDING"] == "true"
    assert managed["CLINK_NATIVE_FACILITATOR_ENABLED"] == "false"
    assert managed["CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN"] == "a" * 43
    assert managed["PREDICTION_MARKETS_LIVE_MODE"] == "false"
    assert "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY" not in managed
