from __future__ import annotations

import base64
import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/node"))

import clink_node.hosted_wallet_bundle as hosted_wallet_bundle  # noqa: E402
from clink_node.hosted_enrollment import HostedEnrollmentBundle  # noqa: E402
from clink_node.hosted_wallet_bundle import (  # noqa: E402
    HostedWalletBundleError,
    write_core_provisioning_bundle,
)


def _active_bundle() -> tuple[HostedEnrollmentBundle, bytes, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    access_token = "access-token-secret-should-not-be-returned"
    encoded_key = base64.urlsafe_b64encode(der).rstrip(b"=").decode("ascii")
    return (
        HostedEnrollmentBundle(
            state="active",
            wallet_binding_id="wallet_binding_1",
            tenant_id="tenant_1",
            node_id="node_1",
            credential_epoch=1,
            private_key_pkcs8_b64=encoded_key,
            access_token=access_token,
            trust_fingerprint="a" * 64,
        ),
        der,
        access_token,
    )


def _output_dir(tmp_path: Path) -> Path:
    os.chmod(tmp_path, 0o700)
    directory = tmp_path / "provisioning"
    directory.mkdir(mode=0o700)
    return directory


def test_active_bundle_writes_core_provisioning_shape_without_secrets(
    tmp_path: Path,
) -> None:
    bundle, der, access_token = _active_bundle()
    output = _output_dir(tmp_path) / "credential.json"

    result = write_core_provisioning_bundle(
        bundle,
        user_id="user_1",
        wallet_identity_id="wallet_identity_1",
        request_id="trace_20260904_01",
        output_path=output,
    )

    assert result == {
        "status": "written",
        "path": str(output),
        "request_id": "trace_20260904_01",
        "user_id": "user_1",
        "wallet_identity_id": "wallet_identity_1",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_binding_1",
    }
    assert output.is_absolute()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "request_id", "credential"}
    assert payload["schema_version"] == 1
    assert payload["request_id"] == "trace_20260904_01"
    assert payload["credential"] == {
        "user_id": "user_1",
        "wallet_identity_id": "wallet_identity_1",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_binding_1",
        "access_token": access_token,
        "device_private_key": "base64:" + base64.b64encode(der).decode("ascii"),
        "state": "active",
    }
    assert access_token not in repr(result)
    assert bundle.private_key_pkcs8_b64 not in repr(result)


@pytest.mark.parametrize("state", ["enrollment_pending", "rotation_pending", "revocation_pending"])
def test_non_active_enrollment_states_are_rejected_without_writing(
    tmp_path: Path,
    state: str,
) -> None:
    bundle, _der, access_token = _active_bundle()
    if state == "enrollment_pending":
        bundle = replace(
            bundle,
            state=state,
            tenant_id="",
            node_id="",
            credential_epoch=0,
            invite_digest="b" * 64,
        )
    elif state == "rotation_pending":
        pending_key = ec.generate_private_key(ec.SECP256R1())
        pending_der = pending_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        bundle = replace(
            bundle,
            state=state,
            rotation_id="rotation_1",
            pending_private_key_pkcs8_b64=base64.urlsafe_b64encode(pending_der)
            .rstrip(b"=")
            .decode("ascii"),
            pending_access_token="pending-token-secret-should-not-be-returned",
        )
    else:
        bundle = replace(
            bundle,
            state=state,
            revocation_pending=True,
            revocation_id="revocation_1",
        )
    output = _output_dir(tmp_path) / "credential.json"

    with pytest.raises(HostedWalletBundleError) as caught:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_1",
            output_path=output,
        )

    assert not output.exists()
    assert access_token not in str(caught.value)
    assert bundle.private_key_pkcs8_b64 not in str(caught.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", ""),
        ("user_id", "user with spaces"),
        ("wallet_identity_id", "wallet/identity"),
        ("request_id", "trace\nforbidden"),
        ("request_id", ""),
    ],
)
def test_invalid_identity_or_request_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    bundle, _der, access_token = _active_bundle()
    output = _output_dir(tmp_path) / "credential.json"
    kwargs: dict[str, object] = {
        "user_id": "user_1",
        "wallet_identity_id": "wallet_identity_1",
        "request_id": "trace_1",
        "output_path": output,
    }
    kwargs[field] = value

    with pytest.raises(HostedWalletBundleError) as caught:
        write_core_provisioning_bundle(bundle, **kwargs)  # type: ignore[arg-type]

    assert not output.exists()
    assert access_token not in str(caught.value)


def test_relative_output_and_unsafe_parent_are_rejected(tmp_path: Path) -> None:
    bundle, _der, access_token = _active_bundle()
    with pytest.raises(HostedWalletBundleError) as relative_error:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_1",
            output_path="relative/credential.json",
        )
    assert access_token not in str(relative_error.value)

    unsafe = tmp_path / "group-writable"
    unsafe.mkdir(mode=0o700)
    os.chmod(unsafe, 0o770)
    with pytest.raises(HostedWalletBundleError) as parent_error:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_1",
            output_path=unsafe / "credential.json",
        )
    assert access_token not in str(parent_error.value)


def test_symlinked_output_parent_is_rejected(tmp_path: Path) -> None:
    bundle, _der, access_token = _active_bundle()
    real_parent = _output_dir(tmp_path)
    redirected = tmp_path / "redirected"
    redirected.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(HostedWalletBundleError) as caught:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_1",
            output_path=redirected / "credential.json",
        )

    assert access_token not in str(caught.value)
    assert not (real_parent / "credential.json").exists()


@pytest.mark.parametrize("kind", ["regular", "symlink", "hardlink"])
def test_existing_targets_are_never_overwritten(
    tmp_path: Path,
    kind: str,
) -> None:
    bundle, _der, access_token = _active_bundle()
    directory = _output_dir(tmp_path)
    output = directory / "credential.json"
    original = directory / "original.txt"
    original.write_text("do-not-overwrite", encoding="utf-8")
    if kind == "regular":
        output.write_text("existing", encoding="utf-8")
    elif kind == "symlink":
        output.symlink_to(original)
    else:
        output.hardlink_to(original)

    with pytest.raises(HostedWalletBundleError) as caught:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_1",
            output_path=output,
        )

    assert access_token not in str(caught.value)
    assert original.read_text(encoding="utf-8") == "do-not-overwrite"
    if kind == "symlink":
        assert output.is_symlink()
    else:
        assert output.read_text(encoding="utf-8") in {"existing", "do-not-overwrite"}


@pytest.mark.parametrize("kind", ["regular", "symlink", "hardlink"])
def test_target_created_after_absence_check_is_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A target appearing during publish must make the export fail closed."""

    bundle, _der, access_token = _active_bundle()
    directory = _output_dir(tmp_path)
    output = directory / "credential.json"
    original = directory / "attacker.txt"
    original.write_text("attacker-controlled", encoding="utf-8")
    absence_checks = 0
    real_require_absent = hosted_wallet_bundle._require_absent

    def create_target_after_check(path: Path) -> None:
        nonlocal absence_checks
        real_require_absent(path)
        absence_checks += 1
        if absence_checks != 3:
            return
        if kind == "regular":
            path.write_text("attacker-controlled", encoding="utf-8")
        elif kind == "symlink":
            path.symlink_to(original)
        else:
            path.hardlink_to(original)

    monkeypatch.setattr(
        hosted_wallet_bundle,
        "_require_absent",
        create_target_after_check,
    )

    with pytest.raises(HostedWalletBundleError) as caught:
        write_core_provisioning_bundle(
            bundle,
            user_id="user_1",
            wallet_identity_id="wallet_identity_1",
            request_id="trace_race_1",
            output_path=output,
        )

    assert absence_checks == 3
    assert access_token not in str(caught.value)
    assert bundle.private_key_pkcs8_b64 not in str(caught.value)
    assert original.read_text(encoding="utf-8") == "attacker-controlled"
    if kind == "regular":
        assert output.read_text(encoding="utf-8") == "attacker-controlled"
    elif kind == "symlink":
        assert output.is_symlink()
        assert output.resolve() == original
    else:
        assert output.read_text(encoding="utf-8") == "attacker-controlled"
    assert not list(directory.glob(".credential.json.tmp-*"))
