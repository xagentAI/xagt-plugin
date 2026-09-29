from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from services.funding_service.hosted_wallet_registry import (
    HostedWalletCredential,
    HostedWalletRegistry,
    HostedWalletRegistryError,
)
from shared.hosted_facilitator_protocol import DeviceSigningKey
from shared.payment_capability import PaymentCapabilityV1


BASE = "eip155:8453"
POLYGON = "eip155:137"
EXECUTOR = "0x" + "33" * 20
HASH = "0x" + "44" * 32
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20


def _encoded_device_key() -> str:
    key = DeviceSigningKey.generate()
    return base64.b64encode(key.pkcs8_der).decode("ascii")


def _target(origin: str) -> dict[str, object]:
    return {
        "origin": origin,
        "server_public_jwk": DeviceSigningKey.generate().public_jwk,
        "executor_contract": EXECUTOR,
    }


TARGETS = {
    BASE: _target("https://base.hosted.example"),
    POLYGON: _target("https://polygon.hosted.example"),
}


def _record(
    *,
    user_id: str = "user_a",
    wallet_identity_id: str = "wallet_a",
    tenant_id: str = "tenant_a",
    node_id: str = "node_a",
    wallet_binding_id: str = "binding_a",
    access_token: str = "access-token-a",
    device_private_key: str | None = None,
    state: str = "active",
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "wallet_identity_id": wallet_identity_id,
        "tenant_id": tenant_id,
        "node_id": node_id,
        "wallet_binding_id": wallet_binding_id,
        "access_token": access_token,
        "device_private_key": device_private_key or _encoded_device_key(),
        "state": state,
    }


def _capability(**updates: object) -> PaymentCapabilityV1:
    values: dict[str, object] = {
        "capability_id": "capability_1",
        "user_id": "user_a",
        "agent_id": "agent_a",
        "tenant_id": "tenant_a",
        "node_id": "node_a",
        "wallet_binding_id": "binding_a",
        "wallet_identity_id": "wallet_a",
        "wallet_address": OWNER,
        "spending_grant_id": "grant_1",
        "spending_grant_hash": HASH,
        "asset_allowance_id": "allowance_1",
        "action_id": "action_1",
        "policy_decision_id": "policy_1",
        "policy_snapshot_hash": HASH,
        "risk_evidence_hash": HASH,
        "reservation_id": "reservation_1",
        "reservation_hash": HASH,
        "purchase_id": "purchase_1",
        "merchant_id": "merchant_1",
        "product": "marketplace",
        "venue": "clink_marketplace",
        "quote_hash": HASH,
        "payment_challenge_hash": HASH,
        "network": BASE,
        "asset_contract": "0x" + "55" * 20,
        "amount_atomic": "1000000",
        "pay_to": PAYEE,
        "executor_contract": EXECUTOR,
        "execution_scope_hash": HASH,
        "confirmation_mode": "policy_approved",
        "revocation_id": HASH,
        "issued_at": 2_000_000_000,
        "expires_at": 2_000_000_060,
    }
    values.update(updates)
    return PaymentCapabilityV1(**values)


def _write_registry(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": 1, "wallets": records},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _registry(path: Path, records: list[dict[str, object]]) -> HostedWalletRegistry:
    _write_registry(path, records)
    return HostedWalletRegistry(path, chain_targets=TARGETS)


def test_two_users_on_one_chain_select_distinct_credentials(tmp_path: Path) -> None:
    path = tmp_path / "hosted-wallets.json"
    registry = _registry(
        path,
        [
            _record(),
            _record(
                user_id="user_b",
                wallet_identity_id="wallet_b",
                tenant_id="tenant_b",
                node_id="node_b",
                wallet_binding_id="binding_b",
                access_token="access-token-b",
            ),
        ],
    )

    first = registry.current(user_id="user_a", wallet_identity_id="wallet_a")
    second = registry.current(user_id="user_b", wallet_identity_id="wallet_b")

    assert first.access_token == "access-token-a"
    assert second.access_token == "access-token-b"
    assert registry.for_capability(_capability()) == first
    assert registry.for_capability(
        _capability(
            user_id="user_b",
            tenant_id="tenant_b",
            node_id="node_b",
            wallet_binding_id="binding_b",
            wallet_identity_id="wallet_b",
        )
    ) == second
    assert registry.configured_networks() == tuple(sorted((BASE, POLYGON)))


@pytest.mark.parametrize(
    "updates",
    [
        {"user_id": "user_b"},
        {"wallet_identity_id": "wallet_b"},
        {"tenant_id": "tenant_b"},
        {"node_id": "node_b"},
        {"wallet_binding_id": "binding_b"},
    ],
)
def test_capability_mismatch_never_falls_back_to_another_mapping(
    tmp_path: Path, updates: dict[str, str]
) -> None:
    registry = _registry(tmp_path / "hosted-wallets.json", [_record()])

    with pytest.raises(HostedWalletRegistryError, match="does not match capability"):
        registry.for_capability(_capability(**updates))


def test_recovery_only_matches_recovery_but_not_submission_and_missing_mapping_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hosted-wallets.json"
    registry = _registry(path, [_record(state="recovery_only")])

    with pytest.raises(HostedWalletRegistryError, match="not active"):
        registry.current(user_id="user_a", wallet_identity_id="wallet_a")
    assert registry.for_capability(_capability()).state == "recovery_only"
    with pytest.raises(HostedWalletRegistryError, match="recovery-only"):
        registry.for_capability(_capability(), for_submission=True)
    with pytest.raises(HostedWalletRegistryError, match="does not match capability"):
        registry.for_capability(
            _capability(wallet_identity_id="wallet_missing")
        )
    assert registry.configured_networks() == ()


def test_registry_reloads_after_atomic_replacement_and_revalidates_stale_client(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hosted-wallets.json"
    old = _record()
    registry = _registry(path, [old])
    original = registry.current(user_id="user_a", wallet_identity_id="wallet_a")

    replacement = tmp_path / "hosted-wallets.replacement.json"
    replacement_record = _record(access_token="access-token-replacement")
    _write_registry(replacement, [replacement_record])
    os.replace(replacement, path)

    current = registry.current(user_id="user_a", wallet_identity_id="wallet_a")
    assert current.access_token == "access-token-replacement"
    assert registry.for_capability(_capability()).access_token == (
        "access-token-replacement"
    )
    with pytest.raises(HostedWalletRegistryError, match="not configured"):
        registry.client(original, BASE)


def test_client_factory_receives_only_immutable_trusted_target_and_current_credential(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "hosted-wallets.json", [_record()])
    credential = registry.current(user_id="user_a", wallet_identity_id="wallet_a")
    calls: list[tuple[HostedWalletCredential, str, Mapping[str, object]]] = []

    def factory(
        supplied_credential: HostedWalletCredential,
        network: str,
        target: Mapping[str, object],
    ) -> object:
        calls.append((supplied_credential, network, target))
        return object()

    injected = HostedWalletRegistry(
        tmp_path / "hosted-wallets.json",
        chain_targets=TARGETS,
        client_factory=factory,
    )
    assert injected.client(credential, BASE) is not None
    assert calls[0][0] == credential
    assert calls[0][1] == BASE
    assert calls[0][2]["origin"] == "https://base.hosted.example"
    with pytest.raises(TypeError):
        calls[0][2]["origin"] = "https://untrusted.example"  # type: ignore[index]


def test_registry_accepts_owner_read_only_file_and_rejects_unsafe_modes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hosted-wallets.json"
    _write_registry(path, [_record()])
    os.chmod(path, 0o400)
    registry = HostedWalletRegistry(path, chain_targets=TARGETS)
    assert registry.current(user_id="user_a", wallet_identity_id="wallet_a").state == (
        "active"
    )

    os.chmod(path, 0o644)
    with pytest.raises(HostedWalletRegistryError, match="file"):
        registry.configured_networks()

    target = tmp_path / "target.json"
    _write_registry(target, [_record(access_token="target-secret")])
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(HostedWalletRegistryError, match="file") as raised:
        registry.configured_networks()
    assert "target-secret" not in repr(raised.value)
    assert target.read_text(encoding="utf-8").count("target-secret") == 1


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":1,"schema_version":1,"wallets":[]}',
        '{"schema_version":1,"wallets":[{"user_id":"u","user_id":"u",'
        '"wallet_identity_id":"w","tenant_id":"t","node_id":"n",'
        '"wallet_binding_id":"b","access_token":"secret-token",'
        '"device_private_key":"bad","state":"active"}]}',
        '{"schema_version":true,"wallets":[]}',
        '{"schema_version":1,"wallets":[],"extra":"nope"}',
    ],
)
def test_duplicate_keys_wrong_schema_and_unknown_fields_fail_without_secret_leakage(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "hosted-wallets.json"
    path.write_text(payload, encoding="utf-8")
    os.chmod(path, 0o600)
    registry = HostedWalletRegistry(path, chain_targets=TARGETS)

    with pytest.raises(HostedWalletRegistryError) as raised:
        registry.configured_networks()
    assert "secret-token" not in repr(raised.value)
    assert "bad" not in repr(raised.value)
    assert str(raised.value) in {
        "hosted wallet registry file is invalid or unavailable",
        "hosted wallet registry records are invalid",
    }


@pytest.mark.parametrize(
    "records",
    [
        [_record(), _record()],
        [_record(), _record(wallet_binding_id="binding_other")],
        [
            _record(),
            _record(
                user_id="user_b",
                wallet_identity_id="wallet_b",
                tenant_id="tenant_b",
                node_id="node_b",
                wallet_binding_id="binding_b",
            ),
        ],
    ],
)
def test_duplicate_enrollment_or_wallet_claims_fail_closed(
    tmp_path: Path, records: list[dict[str, object]]
) -> None:
    if records[1]["wallet_binding_id"] == "binding_b":
        records[1]["wallet_identity_id"] = "wallet_a"
    if records[1]["wallet_binding_id"] == "binding_other":
        records[1]["wallet_identity_id"] = "wallet_a"
    registry = _registry(tmp_path / "hosted-wallets.json", records)

    with pytest.raises(HostedWalletRegistryError, match="records"):
        registry.configured_networks()


def test_facilitator_tenant_and_node_cannot_be_claimed_by_two_wallets(
    tmp_path: Path,
) -> None:
    registry = _registry(
        tmp_path / "hosted-wallets.json",
        [
            _record(),
            _record(
                user_id="user_b",
                wallet_identity_id="wallet_b",
                wallet_binding_id="binding_b",
                access_token="access-token-b",
            ),
        ],
    )

    with pytest.raises(HostedWalletRegistryError, match="records"):
        registry.configured_networks()


def test_historical_recovery_records_are_allowed_but_active_is_unique(
    tmp_path: Path,
) -> None:
    records = [
        _record(state="recovery_only"),
        _record(
            tenant_id="tenant_current",
            node_id="node_current",
            wallet_binding_id="binding_current",
            access_token="current-token",
        ),
    ]
    registry = _registry(tmp_path / "hosted-wallets.json", records)

    assert registry.current(user_id="user_a", wallet_identity_id="wallet_a").access_token == (
        "current-token"
    )
    assert registry.configured_networks() == tuple(sorted((BASE, POLYGON)))


def test_credential_repr_and_client_errors_do_not_expose_secrets(
    tmp_path: Path,
) -> None:
    token = "super-secret-access-token"
    key = _encoded_device_key()
    registry = _registry(
        tmp_path / "hosted-wallets.json",
        [_record(access_token=token, device_private_key=key)],
    )
    credential = registry.current(user_id="user_a", wallet_identity_id="wallet_a")
    rendered = repr(credential)
    assert token not in rendered
    assert key not in rendered

    def bad_factory(
        _credential: HostedWalletCredential,
        _network: str,
        _target: Mapping[str, object],
    ) -> object:
        raise RuntimeError(f"factory leaked {token} {key}")

    bad = HostedWalletRegistry(
        tmp_path / "hosted-wallets.json",
        chain_targets=TARGETS,
        client_factory=bad_factory,
    )
    with pytest.raises(HostedWalletRegistryError) as raised:
        bad.client(credential, BASE)
    assert token not in repr(raised.value)
    assert key not in repr(raised.value)


def test_empty_valid_registry_is_a_safe_bootstrap(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "hosted-wallets.json", [])
    assert registry.configured_networks() == ()


def test_device_private_key_must_be_a_p256_pkcs8_key(tmp_path: Path) -> None:
    record = _record(device_private_key="0xnot-a-private-key")
    registry = _registry(tmp_path / "hosted-wallets.json", [record])

    with pytest.raises(HostedWalletRegistryError, match="records"):
        registry.configured_networks()


def test_non_mapping_capability_is_rejected_without_attribute_leakage(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "hosted-wallets.json", [_record()])

    with pytest.raises(HostedWalletRegistryError, match="capability"):
        registry.for_capability({"user_id": "user_a"})  # type: ignore[arg-type]
