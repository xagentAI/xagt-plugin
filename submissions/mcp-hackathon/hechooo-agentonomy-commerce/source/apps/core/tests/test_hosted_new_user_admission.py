from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.repository import AccountRepository
from services.account_service.schemas import PublicAccountSession, WalletIdentity
from services.account_service.service import AccountService
from services.funding_service.hosted_wallet_provisioning import (
    HostedWalletProvisioner,
    HostedWalletProvisioningError,
)
from services.funding_service.hosted_wallet_registry import (
    HostedWalletRegistry,
    HostedWalletRegistryError,
)
from services.funding_service.service import FundingService
from shared.config import AppConfig
from shared.hosted_facilitator_protocol import DeviceSigningKey


NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
POLYGON = "eip155:137"
TARGETS = {
    POLYGON: {
        "origin": "https://hosted.example",
        "server_public_jwk": DeviceSigningKey.generate().public_jwk,
        "executor_contract": "0x" + "33" * 20,
    }
}


def _public_session(user_id: str) -> PublicAccountSession:
    raw_token = f"test-account-session-token-{user_id}"
    return PublicAccountSession(
        public_account_session_id=f"public_account_session_{user_id}",
        token_digest=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        user_id=user_id,
        expires_at=NOW + timedelta(hours=1),
        created_at=NOW,
        updated_at=NOW,
    )


def _verify_wallet(
    repository: AccountRepository,
    service: AccountService,
    user_id: str,
    wallet,
) -> WalletIdentity:
    public_session = _public_session(user_id)
    repository.create_public_account_session(public_session)
    challenge = service.create_wallet_challenge(
        user_id,
        wallet.address,
        created_by_public_account_session_id=public_session.public_account_session_id,
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), wallet.key
    ).signature.hex()
    return service.verify_wallet_challenge(
        challenge.session_id,
        challenge.message_to_sign,
        signature,
    )


def _credential(
    identity: WalletIdentity,
    *,
    tenant_id: str,
    node_id: str,
    wallet_binding_id: str,
    access_token: str | None = None,
) -> dict[str, str]:
    device_key = DeviceSigningKey.generate()
    return {
        "user_id": identity.user_id,
        "wallet_identity_id": identity.wallet_identity_id,
        "tenant_id": tenant_id,
        "node_id": node_id,
        "wallet_binding_id": wallet_binding_id,
        "access_token": access_token or f"test-hosted-access-token-{identity.user_id}",
        "device_private_key": base64.b64encode(device_key.pkcs8_der).decode("ascii"),
        "state": "active",
    }


def _write_bundle(
    path: Path,
    credential: dict[str, str],
    *,
    request_id: str,
) -> None:
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


def _setup_verified_pair(tmp_path: Path) -> dict[str, object]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    repository = AccountRepository(database_url)
    service = AccountService(repository, domain="account.clink.test", clock=lambda: NOW)
    wallet_a = Account.create()
    wallet_b = Account.create()
    identity_a = _verify_wallet(repository, service, "user_a", wallet_a)
    identity_b = _verify_wallet(repository, service, "user_b", wallet_b)

    # Reopen the same temporary SQLite database before the operator boundary.
    repository.engine.dispose()
    reopened_repository = AccountRepository(database_url)
    reopened_service = AccountService(
        reopened_repository,
        domain="account.clink.test",
        clock=lambda: NOW,
    )
    registry_path = tmp_path / "hosted-wallets.json"
    provisioner = HostedWalletProvisioner(reopened_repository, registry_path)
    credential_a = _credential(
        identity_a,
        tenant_id="tenant_a",
        node_id="node_a",
        wallet_binding_id="binding_a",
        access_token="test-secret-access-token-a",
    )
    bundle_a = tmp_path / "provisioning-a.json"
    _write_bundle(bundle_a, credential_a, request_id="request_a")
    result_a = provisioner.provision(bundle_a)
    assert result_a == {
        "request_id": "request_a",
        "status": "provisioned",
        "user_id": "user_a",
        "wallet_identity_id": identity_a.wallet_identity_id,
        "tenant_id": "tenant_a",
        "node_id": "node_a",
        "wallet_binding_id": "binding_a",
    }
    return {
        "database_url": database_url,
        "repository": reopened_repository,
        "service": reopened_service,
        "wallet_a": wallet_a,
        "wallet_b": wallet_b,
        "identity_a": identity_a,
        "identity_b": identity_b,
        "registry_path": registry_path,
        "provisioner": provisioner,
        "credential_a": credential_a,
        "bundle_a": bundle_a,
    }


def _registry(path: Path) -> HostedWalletRegistry:
    return HostedWalletRegistry(path, chain_targets=TARGETS)


def _assert_exact_mapping(
    path: Path,
    identity: WalletIdentity,
    *,
    tenant_id: str,
    node_id: str,
    wallet_binding_id: str,
) -> None:
    current = _registry(path).current(
        user_id=identity.user_id,
        wallet_identity_id=identity.wallet_identity_id,
    )
    assert current.user_id == identity.user_id
    assert current.wallet_identity_id == identity.wallet_identity_id
    assert current.tenant_id == tenant_id
    assert current.node_id == node_id
    assert current.wallet_binding_id == wallet_binding_id


def test_two_verified_wallets_are_operator_admitted_without_cross_user_mapping(
    tmp_path: Path,
) -> None:
    fixture = _setup_verified_pair(tmp_path)
    repository = fixture["repository"]
    identity_a = fixture["identity_a"]
    identity_b = fixture["identity_b"]
    registry_path = fixture["registry_path"]
    provisioner = fixture["provisioner"]
    assert isinstance(repository, AccountRepository)
    assert isinstance(identity_a, WalletIdentity)
    assert isinstance(identity_b, WalletIdentity)
    assert isinstance(registry_path, Path)
    assert isinstance(provisioner, HostedWalletProvisioner)

    assert identity_a.user_id != identity_b.user_id
    assert identity_a.wallet_identity_id != identity_b.wallet_identity_id
    assert identity_a.wallet_address != identity_b.wallet_address
    assert repository.wallet_identity(identity_a.wallet_identity_id) == identity_a
    assert repository.wallet_identity(identity_b.wallet_identity_id) == identity_b
    _assert_exact_mapping(
        registry_path,
        identity_a,
        tenant_id="tenant_a",
        node_id="node_a",
        wallet_binding_id="binding_a",
    )

    with pytest.raises(HostedWalletRegistryError, match="not configured"):
        _registry(registry_path).current(
            user_id=identity_b.user_id,
            wallet_identity_id=identity_b.wallet_identity_id,
        )

    credential_b = _credential(
        identity_b,
        tenant_id="tenant_b",
        node_id="node_b",
        wallet_binding_id="binding_b",
        access_token="test-secret-access-token-b",
    )
    bundle_b = tmp_path / "provisioning-b.json"
    _write_bundle(bundle_b, credential_b, request_id="request_b")

    # A verified B identity still cannot claim A's tenant/node enrollment.
    duplicate_assignment = _credential(
        identity_b,
        tenant_id="tenant_a",
        node_id="node_a",
        wallet_binding_id="binding_b_collision",
        access_token="test-secret-collision-token",
    )
    duplicate_bundle = tmp_path / "provisioning-b-collision.json"
    _write_bundle(
        duplicate_bundle,
        duplicate_assignment,
        request_id="request_b_collision",
    )
    before_collision = registry_path.read_bytes()
    with pytest.raises(
        HostedWalletProvisioningError, match="already claimed"
    ) as collision_error:
        provisioner.provision(duplicate_bundle)
    assert registry_path.read_bytes() == before_collision
    assert duplicate_assignment["access_token"] not in repr(collision_error.value)
    assert duplicate_assignment["device_private_key"] not in repr(collision_error.value)

    # A bundle that labels A's verified identity as B is rejected by Core lookup.
    mismatched_identity = _credential(
        identity_a,
        tenant_id="tenant_b_mismatch",
        node_id="node_b_mismatch",
        wallet_binding_id="binding_b_mismatch",
        access_token="test-secret-mismatched-token",
    )
    mismatched_identity["user_id"] = identity_b.user_id
    mismatch_bundle = tmp_path / "provisioning-mismatch.json"
    _write_bundle(mismatch_bundle, mismatched_identity, request_id="request_mismatch")
    before_mismatch = registry_path.read_bytes()
    with pytest.raises(
        HostedWalletProvisioningError, match="Core wallet identity"
    ) as mismatch_error:
        provisioner.provision(mismatch_bundle)
    assert registry_path.read_bytes() == before_mismatch
    assert mismatched_identity["access_token"] not in repr(mismatch_error.value)
    assert mismatched_identity["device_private_key"] not in repr(mismatch_error.value)

    admitted_b = provisioner.provision(bundle_b)
    assert admitted_b["status"] == "provisioned"
    assert admitted_b["user_id"] == identity_b.user_id
    assert admitted_b["wallet_identity_id"] == identity_b.wallet_identity_id
    assert credential_b["access_token"] not in repr(admitted_b)
    assert credential_b["device_private_key"] not in repr(admitted_b)

    _assert_exact_mapping(
        registry_path,
        identity_a,
        tenant_id="tenant_a",
        node_id="node_a",
        wallet_binding_id="binding_a",
    )
    _assert_exact_mapping(
        registry_path,
        identity_b,
        tenant_id="tenant_b",
        node_id="node_b",
        wallet_binding_id="binding_b",
    )
    snapshot = _registry(registry_path)._operator_snapshot()
    assert len(snapshot) == 2
    assert {
        (item.user_id, item.wallet_identity_id, item.tenant_id, item.node_id)
        for item in snapshot
    } == {
        (identity_a.user_id, identity_a.wallet_identity_id, "tenant_a", "node_a"),
        (identity_b.user_id, identity_b.wallet_identity_id, "tenant_b", "node_b"),
    }

    before_retry = registry_path.read_bytes()
    repeated = provisioner.provision(bundle_b)
    assert repeated == admitted_b | {"status": "unchanged"}
    assert registry_path.read_bytes() == before_retry
    assert len(_registry(registry_path)._operator_snapshot()) == 2


def test_revoked_verified_wallet_cannot_be_reprovisioned_and_is_not_ready(
    tmp_path: Path,
) -> None:
    fixture = _setup_verified_pair(tmp_path)
    repository = fixture["repository"]
    service = fixture["service"]
    identity_b = fixture["identity_b"]
    registry_path = fixture["registry_path"]
    provisioner = fixture["provisioner"]
    database_url = fixture["database_url"]
    assert isinstance(repository, AccountRepository)
    assert isinstance(service, AccountService)
    assert isinstance(identity_b, WalletIdentity)
    assert isinstance(registry_path, Path)
    assert isinstance(provisioner, HostedWalletProvisioner)
    assert isinstance(database_url, str)

    credential_b = _credential(
        identity_b,
        tenant_id="tenant_b",
        node_id="node_b",
        wallet_binding_id="binding_b",
        access_token="test-secret-access-token-b",
    )
    bundle_b = tmp_path / "provisioning-b.json"
    _write_bundle(bundle_b, credential_b, request_id="request_b")
    provisioner.provision(bundle_b)
    before_revoke = registry_path.read_bytes()

    revoked = service.revoke_wallet_identity(identity_b.wallet_identity_id)
    assert revoked.status == "revoked"
    reopened = AccountRepository(database_url)
    assert reopened.wallet_identity(identity_b.wallet_identity_id).status == "revoked"

    rotated_after_revoke = _credential(
        identity_b,
        tenant_id="tenant_b_rotated",
        node_id="node_b_rotated",
        wallet_binding_id="binding_b_rotated",
        access_token="test-secret-revoked-rotation-token",
    )
    rotated_bundle = tmp_path / "provisioning-b-after-revoke.json"
    _write_bundle(
        rotated_bundle,
        rotated_after_revoke,
        request_id="request_b_after_revoke",
    )
    with pytest.raises(
        HostedWalletProvisioningError, match="Core wallet identity"
    ) as revoked_error:
        HostedWalletProvisioner(reopened, registry_path).provision(rotated_bundle)
    assert registry_path.read_bytes() == before_revoke
    assert rotated_after_revoke["access_token"] not in repr(revoked_error.value)
    assert rotated_after_revoke["device_private_key"] not in repr(revoked_error.value)

    # Registry history remains available for exact recovery; it is not Core
    # revocation authority and must not be treated as fresh funding readiness.
    _assert_exact_mapping(
        registry_path,
        identity_b,
        tenant_id="tenant_b",
        node_id="node_b",
        wallet_binding_id="binding_b",
    )
    funding_config = AppConfig(
        clink_facilitator_mode="hosted",
        clink_hosted_wallet_credentials_file=str(registry_path),
        clink_hosted_facilitator_chain_targets=TARGETS,
        funding_database_url=database_url,
    )
    funding = FundingService(
        config=funding_config,
        storage_file=tmp_path / "funding-records.jsonl",
        hosted_wallet_registry=_registry(registry_path),
    )
    readiness = funding.get_hosted_wallet_readiness(identity_b.user_id)
    assert readiness["ready"] is False
    assert readiness["reason_code"] == "WALLET_NOT_READY"
