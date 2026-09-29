from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.account_service.repository import AccountRepository
from services.account_service.schemas import WalletIdentity
from services.funding_service.hosted_wallet_provisioning import (
    HostedWalletProvisioner,
    HostedWalletProvisioningError,
    main,
    provisioning_preflight,
)
from services.funding_service.hosted_wallet_registry import HostedWalletRegistry
from shared.hosted_facilitator_protocol import DeviceSigningKey


NOW = datetime(2026, 9, 4, tzinfo=UTC)
TARGETS = {
    "eip155:137": {
        "origin": "https://hosted.example",
        "server_public_jwk": DeviceSigningKey.generate().public_jwk,
        "executor_contract": "0x" + "33" * 20,
    }
}


def _wallet(
    *,
    status: str = "active",
    user_id: str = "user_a",
    proof_hash: str = "0xproof",
) -> WalletIdentity:
    return WalletIdentity(
        wallet_identity_id="wallet_a",
        user_id=user_id,
        wallet_address="0x" + "11" * 20,
        status=status,
        proof_hash=proof_hash,
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _credential(*, suffix: str = "a", user_id: str = "user_a") -> dict[str, str]:
    key = DeviceSigningKey.generate()
    return {
        "user_id": user_id,
        "wallet_identity_id": "wallet_a",
        "tenant_id": f"tenant_{suffix}",
        "node_id": f"node_{suffix}",
        "wallet_binding_id": f"binding_{suffix}",
        "access_token": f"secret-access-token-{suffix}",
        "device_private_key": base64.b64encode(key.pkcs8_der).decode("ascii"),
        "state": "active",
    }


def _bundle(path: Path, credential: dict[str, str], *, request_id: str = "request_1") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": request_id,
                "credential": credential,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _repository(tmp_path: Path, wallet: WalletIdentity | None = None) -> AccountRepository:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")
    if wallet is not None:
        repository.save_wallet_identity(wallet)
    return repository


def test_verified_wallet_provisioning_is_atomic_redacted_and_retry_safe(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path, _wallet())
    registry_path = tmp_path / "hosted-wallets.json"
    bundle_path = tmp_path / "provisioning.json"
    credential = _credential()
    _bundle(bundle_path, credential)
    provisioner = HostedWalletProvisioner(repository, registry_path)

    first = provisioner.provision(bundle_path)
    repeated = provisioner.provision(bundle_path)

    assert first == {
        "request_id": "request_1",
        "status": "provisioned",
        "user_id": "user_a",
        "wallet_identity_id": "wallet_a",
        "tenant_id": "tenant_a",
        "node_id": "node_a",
        "wallet_binding_id": "binding_a",
    }
    assert repeated == first | {"status": "unchanged"}
    assert "secret-access-token" not in repr(first)
    assert credential["device_private_key"] not in repr(first)
    assert oct(registry_path.stat().st_mode & 0o777) == "0o600"

    current = HostedWalletRegistry(
        registry_path, chain_targets=TARGETS
    ).current(user_id="user_a", wallet_identity_id="wallet_a")
    assert current.tenant_id == "tenant_a"
    assert current.access_token == "secret-access-token-a"


@pytest.mark.parametrize(
    ("wallet", "credential"),
    [
        (_wallet(status="revoked"), _credential()),
        (_wallet(proof_hash=""), _credential()),
        (_wallet(), _credential(user_id="user_b")),
        (None, _credential()),
    ],
)
def test_only_matching_active_core_wallet_can_be_provisioned(
    tmp_path: Path,
    wallet: WalletIdentity | None,
    credential: dict[str, str],
) -> None:
    repository = _repository(tmp_path, wallet)
    registry_path = tmp_path / "hosted-wallets.json"
    bundle_path = tmp_path / "provisioning.json"
    _bundle(bundle_path, credential)

    with pytest.raises(HostedWalletProvisioningError, match="wallet identity"):
        HostedWalletProvisioner(repository, registry_path).provision(bundle_path)

    assert not registry_path.exists()


def test_rotation_requires_explicit_replace_and_keeps_recovery_record(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path, _wallet())
    registry_path = tmp_path / "hosted-wallets.json"
    first_bundle = tmp_path / "first.json"
    next_bundle = tmp_path / "next.json"
    _bundle(first_bundle, _credential())
    _bundle(next_bundle, _credential(suffix="b"), request_id="request_2")
    provisioner = HostedWalletProvisioner(repository, registry_path)
    provisioner.provision(first_bundle)

    before = registry_path.read_bytes()
    with pytest.raises(HostedWalletProvisioningError, match="explicit replacement"):
        provisioner.provision(next_bundle)
    assert registry_path.read_bytes() == before

    result = provisioner.provision(next_bundle, replace_current=True)

    assert result["status"] == "replaced"
    registry = HostedWalletRegistry(registry_path, chain_targets=TARGETS)
    assert registry.current(user_id="user_a", wallet_identity_id="wallet_a").tenant_id == (
        "tenant_b"
    )
    records = registry._operator_snapshot()
    assert [(item.tenant_id, item.state) for item in records] == [
        ("tenant_a", "recovery_only"),
        ("tenant_b", "active"),
    ]


def test_same_enrollment_credential_rotation_replaces_in_place(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path, _wallet())
    registry_path = tmp_path / "hosted-wallets.json"
    first_bundle = tmp_path / "first.json"
    rotated_bundle = tmp_path / "rotated.json"
    first = _credential()
    rotated = dict(first)
    rotated["access_token"] = "secret-access-token-rotated"
    rotated["device_private_key"] = base64.b64encode(
        DeviceSigningKey.generate().pkcs8_der
    ).decode("ascii")
    _bundle(first_bundle, first)
    _bundle(rotated_bundle, rotated, request_id="request_2")
    provisioner = HostedWalletProvisioner(repository, registry_path)
    provisioner.provision(first_bundle)

    with pytest.raises(HostedWalletProvisioningError, match="explicit replacement"):
        provisioner.provision(rotated_bundle)

    result = provisioner.provision(rotated_bundle, replace_current=True)

    assert result["status"] == "replaced"
    records = HostedWalletRegistry(
        registry_path,
        chain_targets=TARGETS,
    )._operator_snapshot()
    assert len(records) == 1
    assert records[0].state == "active"
    assert records[0].tenant_id == first["tenant_id"]
    assert records[0].node_id == first["node_id"]
    assert records[0].wallet_binding_id == first["wallet_binding_id"]
    assert records[0].access_token == "secret-access-token-rotated"


def test_unsafe_or_malformed_bundle_fails_closed_without_secret_leakage(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path, _wallet())
    registry_path = tmp_path / "hosted-wallets.json"
    bundle_path = tmp_path / "provisioning.json"
    bundle_path.write_text(
        '{"schema_version":1,"request_id":"request_1",'
        '"request_id":"duplicate","credential":{"access_token":"leaked-secret"}}',
        encoding="utf-8",
    )
    os.chmod(bundle_path, 0o600)

    with pytest.raises(HostedWalletProvisioningError) as raised:
        HostedWalletProvisioner(repository, registry_path).provision(bundle_path)
    assert "leaked-secret" not in repr(raised.value)
    assert not registry_path.exists()

    _bundle(bundle_path, _credential())
    os.chmod(bundle_path, 0o644)
    with pytest.raises(HostedWalletProvisioningError, match="bundle"):
        HostedWalletProvisioner(repository, registry_path).provision(bundle_path)
    assert not registry_path.exists()


def test_preflight_reports_only_missing_field_names() -> None:
    report = provisioning_preflight(
        {
            "CLINK_FUNDING_DATABASE_URL": "",
            "CLINK_HOSTED_WALLET_CREDENTIALS_FILE": "/private/registry.json",
        },
        bundle_path=None,
    )

    assert report == {
        "status": "configuration_required",
        "fields": ["CLINK_FUNDING_DATABASE_URL", "bundle_file"],
    }
    assert "/private/registry.json" not in repr(report)


def test_preflight_rejects_relative_runtime_registry_path() -> None:
    report = provisioning_preflight(
        {
            "CLINK_FUNDING_DATABASE_URL": "sqlite+pysqlite:////private/core.sqlite3",
            "CLINK_HOSTED_WALLET_CREDENTIALS_FILE": "relative/registry.json",
        },
        bundle_path="/private/provisioning.json",
    )

    assert report == {
        "status": "configuration_required",
        "fields": ["CLINK_HOSTED_WALLET_CREDENTIALS_FILE"],
    }


def test_dry_run_performs_full_validation_without_writing_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _repository(tmp_path, _wallet())
    bundle_path = tmp_path / "provisioning.json"
    registry_path = tmp_path / "hosted-wallets.json"
    _bundle(bundle_path, _credential())
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
    )
    monkeypatch.setenv("CLINK_HOSTED_WALLET_CREDENTIALS_FILE", str(registry_path))

    assert main(["--bundle", str(bundle_path), "--dry-run"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "request_id": "request_1",
        "status": "would_provision",
        "user_id": "user_a",
        "wallet_identity_id": "wallet_a",
        "tenant_id": "tenant_a",
        "node_id": "node_a",
        "wallet_binding_id": "binding_a",
    }
    assert not registry_path.exists()


def test_dry_run_rejects_missing_bundle_instead_of_reporting_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
    )
    monkeypatch.setenv(
        "CLINK_HOSTED_WALLET_CREDENTIALS_FILE",
        str(tmp_path / "hosted-wallets.json"),
    )

    assert main(["--bundle", str(tmp_path / "missing.json"), "--dry-run"]) == 1

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "failed",
        "error": "hosted wallet provisioning bundle is invalid or unavailable",
    }


def test_registry_parent_must_not_be_group_or_world_writable(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path, _wallet())
    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir(mode=0o777)
    os.chmod(unsafe_parent, 0o777)
    bundle_path = tmp_path / "provisioning.json"
    _bundle(bundle_path, _credential())

    with pytest.raises(HostedWalletProvisioningError, match="registry"):
        HostedWalletProvisioner(
            repository,
            unsafe_parent / "hosted-wallets.json",
        ).provision(bundle_path)

    assert not (unsafe_parent / "hosted-wallets.json").exists()


def test_cli_redacts_unexpected_database_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = tmp_path / "provisioning.json"
    _bundle(bundle_path, _credential())
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        "postgresql+psycopg://operator:database-secret@example/core",
    )
    monkeypatch.setenv(
        "CLINK_HOSTED_WALLET_CREDENTIALS_FILE",
        str(tmp_path / "hosted-wallets.json"),
    )

    class FailingRepository:
        def __init__(self, _database_url: str) -> None:
            raise RuntimeError("database-secret")

    monkeypatch.setattr(
        "services.funding_service.hosted_wallet_provisioning.AccountRepository",
        FailingRepository,
    )

    assert main(["--bundle", str(bundle_path)]) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "status": "failed",
        "error": "hosted wallet provisioning failed",
    }
    assert "database-secret" not in output.out
