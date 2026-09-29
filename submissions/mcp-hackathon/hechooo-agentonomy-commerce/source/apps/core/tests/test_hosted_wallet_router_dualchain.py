from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.funding_service.hosted_wallet_registry import (
    HostedWalletCredential,
    HostedWalletRegistryError,
)
from services.funding_service.service import FundingService
from shared.config import AppConfig
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HOSTED_CHAIN_PROFILES,
)
from shared.payment_capability import PaymentCapabilityV1


BASE = "eip155:8453"
POLYGON = "eip155:137"
EXECUTOR = "0x" + "33" * 20
HASH = "0x" + "44" * 32
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20


def _router_class():
    try:
        from services.funding_service.hosted_wallet_router import HostedWalletRouter
    except ImportError as exc:  # Red phase: the router is the new production API.
        pytest.fail(f"HostedWalletRouter is not implemented yet: {exc}")
    return HostedWalletRouter


def _device_private_key() -> str:
    return base64.b64encode(DeviceSigningKey.generate().pkcs8_der).decode("ascii")


def _record(
    *,
    user_id: str = "user_1",
    wallet_identity_id: str = "wallet_1",
    tenant_id: str = "tenant_1",
    node_id: str = "node_1",
    wallet_binding_id: str = "binding_1",
    access_token: str = "access-token-1",
    state: str = "active",
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "wallet_identity_id": wallet_identity_id,
        "tenant_id": tenant_id,
        "node_id": node_id,
        "wallet_binding_id": wallet_binding_id,
        "access_token": access_token,
        "device_private_key": _device_private_key(),
        "state": state,
    }


def _target(origin: str) -> dict[str, object]:
    return {
        "origin": origin,
        "server_public_jwk": DeviceSigningKey.generate().public_jwk,
        "executor_contract": EXECUTOR,
    }


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


def _capability(network: str, **updates: object) -> PaymentCapabilityV1:
    values: dict[str, object] = {
        "capability_id": f"capability_{network.rsplit(':', 1)[-1]}",
        "user_id": "user_1",
        "agent_id": "agent_1",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "wallet_identity_id": "wallet_1",
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
        "network": network,
        "asset_contract": HOSTED_CHAIN_PROFILES[network].token,
        "amount_atomic": "1000000",
        "pay_to": PAYEE,
        "executor_contract": EXECUTOR,
        "execution_scope_hash": HASH,
        "confirmation_mode": "user_approved",
        "revocation_id": HASH,
        "issued_at": 2_000_000_000,
        "expires_at": 2_000_000_060,
    }
    values.update(updates)
    return PaymentCapabilityV1(**values)


def _two_chain_router(tmp_path: Path):
    base_path = tmp_path / "base.json"
    polygon_path = tmp_path / "polygon.json"
    base_record = _record()
    polygon_record = _record(
        tenant_id="tenant_polygon",
        node_id="node_polygon",
        wallet_binding_id="binding_polygon",
        access_token="access-token-polygon",
    )
    _write_registry(base_path, [base_record])
    _write_registry(polygon_path, [polygon_record])
    targets = {
        BASE: _target("https://base.hosted.example"),
        POLYGON: _target("https://polygon.hosted.example"),
    }
    router = _router_class()(
        {BASE: base_path, POLYGON: polygon_path},
        chain_targets=targets,
    )
    return router, base_record, polygon_record, base_path, polygon_path, targets


def test_router_selects_independent_real_registry_files_by_network(tmp_path: Path):
    router, base_record, polygon_record, *_ = _two_chain_router(tmp_path)

    base = router.current(
        user_id="user_1", wallet_identity_id="wallet_1", network=BASE
    )
    polygon = router.current(
        user_id="user_1", wallet_identity_id="wallet_1", network=POLYGON
    )

    assert base == HostedWalletCredential(**base_record)
    assert polygon == HostedWalletCredential(**polygon_record)
    assert base.tenant_id != polygon.tenant_id
    assert router.configured_networks() == tuple(sorted((BASE, POLYGON)))


def test_router_uses_capability_network_and_rejects_foreign_chain_credentials(
    tmp_path: Path,
):
    router, *_ = _two_chain_router(tmp_path)
    base = router.current(
        user_id="user_1", wallet_identity_id="wallet_1", network=BASE
    )
    polygon = router.for_capability(
        _capability(
            POLYGON,
            tenant_id="tenant_polygon",
            node_id="node_polygon",
            wallet_binding_id="binding_polygon",
        )
    )

    assert polygon.tenant_id == "tenant_polygon"
    with pytest.raises(HostedWalletRegistryError, match="configured|chain"):
        router.client(base, POLYGON)
    with pytest.raises(HostedWalletRegistryError, match="capability"):
        router.for_capability(SimpleNamespace(network=BASE))


def test_router_recovery_only_is_readable_but_never_submission_eligible(
    tmp_path: Path,
):
    base_path = tmp_path / "base.json"
    _write_registry(base_path, [_record(state="recovery_only")])
    router = _router_class()(
        {BASE: base_path},
        chain_targets={BASE: _target("https://base.hosted.example")},
    )
    capability = _capability(BASE)

    assert router.for_capability(capability).state == "recovery_only"
    with pytest.raises(HostedWalletRegistryError, match="recovery-only"):
        router.for_capability(capability, for_submission=True)


def test_router_omitted_network_is_allowed_only_for_one_configured_target(
    tmp_path: Path,
):
    router, *_ = _two_chain_router(tmp_path)
    with pytest.raises(HostedWalletRegistryError, match="network|ambiguous"):
        router.current(user_id="user_1", wallet_identity_id="wallet_1")

    base_path = tmp_path / "only-base.json"
    _write_registry(base_path, [_record()])
    single = _router_class()(
        {BASE: base_path},
        chain_targets={BASE: _target("https://base.hosted.example")},
    )
    assert single.current(user_id="user_1", wallet_identity_id="wallet_1").tenant_id == (
        "tenant_1"
    )


def test_router_skips_missing_or_corrupt_network_without_cross_chain_fallback(
    tmp_path: Path,
):
    base_path = tmp_path / "base.json"
    polygon_path = tmp_path / "polygon.json"
    _write_registry(base_path, [_record()])
    polygon_path.write_text("{not-json", encoding="utf-8")
    os.chmod(polygon_path, 0o600)
    router = _router_class()(
        {BASE: base_path, POLYGON: polygon_path},
        chain_targets={
            BASE: _target("https://base.hosted.example"),
            POLYGON: _target("https://polygon.hosted.example"),
        },
    )

    assert router.configured_networks() == (BASE,)
    with pytest.raises(HostedWalletRegistryError, match="file|configured"):
        router.current(user_id="user_1", wallet_identity_id="wallet_1", network=POLYGON)

    _write_registry(base_path, [])
    assert router.configured_networks() == ()


def test_explicit_multi_file_config_is_strict_and_redacted(tmp_path: Path):
    paths = {
        BASE: str(tmp_path / "base.json"),
        POLYGON: str(tmp_path / "nested" / ".." / "polygon.json"),
    }
    targets = {BASE: _target("https://base.hosted.example"), POLYGON: _target("https://polygon.hosted.example")}
    config = AppConfig(
        clink_hosted_facilitator_chain_targets=targets,
        clink_hosted_wallet_credentials_files=paths,
    )

    assert set(config.clink_hosted_wallet_credentials_files) == {BASE, POLYGON}
    assert str(tmp_path) not in repr(config)
    described = config.describe()
    assert described["clink_hosted_wallet_credentials_files"] == "<redacted>"
    assert str(tmp_path) not in json.dumps(described)


@pytest.mark.parametrize(
    "value",
    [
        {"eip155:999": "/tmp/unknown.json"},
        {BASE: "relative.json"},
        {BASE: "/tmp/has\nnewline.json"},
        {BASE: "/tmp/one/../same.json", POLYGON: "/tmp/same.json"},
        {BASE: True},
    ],
)
def test_explicit_multi_file_config_rejects_bad_networks_and_paths(value):
    with pytest.raises(ValueError, match="CREDENTIALS_FILES|network|path"):
        AppConfig(clink_hosted_wallet_credentials_files=value)


def test_explicit_multi_file_config_requires_exact_target_key_match(tmp_path: Path):
    with pytest.raises(ValueError, match="target|credential|network"):
        AppConfig(
            clink_hosted_facilitator_chain_targets={BASE: _target("https://base.hosted.example")},
            clink_hosted_wallet_credentials_files={POLYGON: str(tmp_path / "polygon.json")},
        )


def test_explicit_multi_file_config_cannot_fall_back_to_legacy_scalar(tmp_path: Path):
    with pytest.raises(ValueError, match="mutually exclusive|CREDENTIALS"):
        AppConfig(
            clink_hosted_wallet_credentials_file=str(tmp_path / "legacy.json"),
            clink_hosted_wallet_credentials_files={BASE: str(tmp_path / "base.json")},
        )


def test_env_multi_file_config_rejects_duplicate_json_keys(monkeypatch):
    monkeypatch.setenv(
        "CLINK_HOSTED_WALLET_CREDENTIALS_FILES",
        '{"eip155:8453":"/tmp/base.json","eip155:8453":"/tmp/other.json"}',
    )
    with pytest.raises(ValueError, match="CREDENTIALS_FILES"):
        AppConfig.from_env()


def test_funding_service_wires_multi_file_router_and_excludes_global_clients(
    tmp_path: Path,
):
    router, _base_record, _polygon_record, base_path, polygon_path, targets = (
        _two_chain_router(tmp_path)
    )
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}",
        clink_facilitator_mode="hosted",
        clink_hosted_facilitator_chain_targets=targets,
        clink_hosted_wallet_credentials_files={
            BASE: str(base_path),
            POLYGON: str(polygon_path),
        },
    )

    service = FundingService(config=config)

    assert service.hosted_wallet_registry is not None
    assert service.hosted_wallet_registry.__class__.__name__ == "HostedWalletRouter"
    assert service.hosted_clients == {}
    assert service.hosted_wallet_registry.current(
        user_id="user_1", wallet_identity_id="wallet_1", network=BASE
    ).tenant_id == "tenant_1"


def test_funding_readiness_uses_ready_networks_without_blocking_on_bad_polygon_file(
    tmp_path: Path,
):
    base_path = tmp_path / "base.json"
    polygon_path = tmp_path / "polygon.json"
    _write_registry(base_path, [_record()])
    targets = {
        BASE: _target("https://base.hosted.example"),
        POLYGON: _target("https://polygon.hosted.example"),
    }
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}",
        clink_facilitator_mode="hosted",
        clink_live_funding=True,
        risk_mode="enforce",
        misttrack_api_key="test-key",
        clink_hosted_facilitator_chain_targets=targets,
        clink_hosted_wallet_credentials_files={
            BASE: str(base_path),
            POLYGON: str(polygon_path),
        },
    )

    readiness = FundingService(config=config).get_funding_readiness()

    assert readiness["status"] == "ready"
    assert readiness["hosted_facilitator_ready"] is True
    assert readiness["ready_networks"] == [BASE]
    assert readiness["network_status"][BASE]["ready"] is True
    assert readiness["network_status"][POLYGON]["ready"] is False


def test_account_readiness_keeps_valid_base_when_polygon_enrollment_is_missing(
    tmp_path: Path,
):
    from test_hosted_wallet_routing import _scoped_context

    _repository, service, _row, _client, base_path, _record_value, _selected = (
        _scoped_context(tmp_path)
    )
    polygon_path = tmp_path / "polygon.json"
    _write_registry(polygon_path, [])
    targets = {
        BASE: service.config.clink_hosted_facilitator_chain_targets[BASE],
        POLYGON: _target("https://polygon.hosted.example"),
    }
    service.config.clink_hosted_facilitator_chain_targets = targets
    service.hosted_wallet_registry = _router_class()(
        {BASE: base_path, POLYGON: polygon_path},
        chain_targets=targets,
    )

    readiness = service.get_hosted_wallet_readiness("user_1")

    assert readiness["ready"] is True
    assert readiness["ready_networks"] == [BASE]
    assert readiness["network_status"][BASE] == {
        "ready": True,
        "reason_code": None,
    }
    assert readiness["network_status"][POLYGON] == {
        "ready": False,
        "reason_code": "HOSTED_ENROLLMENT_REQUIRED",
    }


def test_funding_capabilities_use_each_network_credential_without_resetting_grants(
    tmp_path: Path,
):
    from datetime import UTC, datetime
    from decimal import Decimal

    from services.account_service.repository import AccountRepository
    from services.action_policy_repository import ActionPolicyRepository
    from services.funding_service.ledger import FundingLedger
    from services.funding_service.schemas import IssuePaymentCapabilityRequest
    from test_payment_capability_issuance import (
        allowance as allowance_factory,
        fake_action,
        grant as grant_factory,
        identity,
        policy as policy_factory,
        reservation as reservation_factory,
    )

    database_url = f"sqlite+pysqlite:///{tmp_path / 'dualchain-ledger.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    action_repository = ActionPolicyRepository(database_url)
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    networks = (
        (BASE, "base", "tenant_base", "node_base", "binding_base", "0x" + "55" * 20),
        (
            POLYGON,
            "polygon",
            "tenant_polygon",
            "node_polygon",
            "binding_polygon",
            "0x" + "66" * 20,
        ),
    )
    targets: dict[str, dict[str, object]] = {}
    credential_paths: dict[str, Path] = {}
    policies: dict[str, object] = {}
    rows: dict[str, dict[str, object]] = {}
    grant_ids: dict[str, str] = {}
    for network, suffix, tenant, node, binding, executor in networks:
        token = HOSTED_CHAIN_PROFILES[network].token
        grant_id = f"grant_{suffix}"
        allowance_id = f"allowance_{suffix}"
        action_id = f"action_{suffix}"
        policy_id = f"policy_{suffix}"
        reservation_id = f"reservation_{suffix}"
        purchase_id = f"purchase_{suffix}"
        quote_hash = "0x" + ("7" if suffix == "base" else "8") * 64
        grant_ids[network] = grant_id
        repository.save_spending_grant(
            grant_factory(
                spending_grant_id=grant_id,
                network_scopes=[network],
                asset_scopes=[token],
                reserved_amount_usdc=Decimal("1"),
            )
        )
        repository.save_asset_allowance(
            allowance_factory(
                asset_allowance_id=allowance_id,
                network=network,
                token_address=token,
                spender_address=executor,
            )
        )
        row = reservation_factory(
            reservation_id=reservation_id,
            purchase_id=purchase_id,
            idempotency_key=f"idempotency_{suffix}",
            spending_grant_id=grant_id,
            asset_allowance_id=allowance_id,
            action_id=action_id,
            policy_decision_id=policy_id,
            quote_hash=quote_hash,
            network=network,
            asset=token,
            token_address=token,
            spender_address=executor,
            destination=PAYEE,
        )
        metadata = {
            "purchase_id": purchase_id,
            "quote_hash": quote_hash,
            "network": network,
            "asset": token,
            "amount_atomic": "1000000",
            "destination": PAYEE,
            "resource": "https://merchant.example/resource",
            "authorization_rail": "native_allowance",
            "product": "marketplace",
            "wallet_identity_id": "identity_1",
            "spending_grant_id": grant_id,
            "asset_allowance_id": allowance_id,
            "merchant_trust_tier": "registry_verified",
        }
        risk_assessment = {
            "provider": "misttrack",
            "provider_endpoint": "v2/risk_score",
            "mode": "enforce",
            "enforced": True,
            "mapping_version": "misttrack-policy-v1",
            "hold_score": 31,
            "deny_score": 71,
            "subject": PAYEE,
            "network": network,
            "asset": "USDC",
            "coin": "USDC-Base" if network == BASE else "USDC-Polygon",
            "decision": "allow",
            "assessed_at": "2026-08-25T11:59:00Z",
            "expires_at": "2026-08-25T12:04:00Z",
        }
        decision = policy_factory(
            policy_decision_id=policy_id,
            action_id=action_id,
            chain=network,
            target_address=PAYEE,
            metadata=metadata,
            risk_assessment=risk_assessment,
        )
        action = fake_action().model_copy(
            update={
                "action_id": action_id,
                "policy_decision_id": policy_id,
                "metadata": metadata,
            }
        )
        action_repository.create_policy_decision(decision.to_dict())
        action_repository.create_action_intent(action.to_dict())
        policies[policy_id] = decision
        rows[network] = row
        credential_path = tmp_path / f"{suffix}-wallets.json"
        _write_registry(
            credential_path,
            [
                _record(
                    wallet_identity_id="identity_1",
                    tenant_id=tenant,
                    node_id=node,
                    wallet_binding_id=binding,
                )
            ],
        )
        credential_paths[network] = credential_path
        targets[network] = _target(
            f"https://{suffix}.hosted.example",
        ) | {"executor_contract": executor}

    with FundingLedger(database_url).transaction() as transaction:
        for network, row in rows.items():
            transaction.put(
                "reservation",
                row["reservation_id"],
                row,
                purchase_id=row["purchase_id"],
                idempotency_key=row["idempotency_key"],
                action_id=row["action_id"],
                policy_decision_id=row["policy_decision_id"],
                reservation_id=row["reservation_id"],
            )

    class _PolicyMap:
        def get_decision(self, policy_id: str):
            return policies[policy_id]

    config = AppConfig(
        funding_database_url=database_url,
        clink_facilitator_mode="hosted",
        clink_live_funding=True,
        risk_mode="enforce",
        misttrack_api_key="test-key",
        clink_hosted_facilitator_chain_targets=targets,
        clink_hosted_wallet_credentials_files={
            network: str(path) for network, path in credential_paths.items()
        },
    )
    service = FundingService(config=config, policy_service=_PolicyMap())
    service._utc_now = lambda: now.replace(tzinfo=None)

    capabilities = {}
    for network, _suffix, tenant, node, binding, executor in networks:
        capabilities[network] = service.issue_payment_capability(
            rows[network]["reservation_id"],
            IssuePaymentCapabilityRequest(
                tenant_id=tenant,
                node_id=node,
                wallet_binding_id=binding,
                executor_contract=executor,
                payment_challenge_hash=HASH,
            ),
        )

    assert capabilities[BASE].network == BASE
    assert capabilities[BASE].tenant_id == "tenant_base"
    assert capabilities[BASE].executor_contract == "0x" + "55" * 20
    assert capabilities[POLYGON].network == POLYGON
    assert capabilities[POLYGON].tenant_id == "tenant_polygon"
    assert capabilities[POLYGON].executor_contract == "0x" + "66" * 20
    assert {
        grant.spending_grant_id: grant.reserved_amount_usdc
        for grant in repository.spending_grants("user_1")
    } == {grant_id: Decimal("1") for grant_id in grant_ids.values()}


@pytest.mark.parametrize("value", ["{}", " ", ""])
def test_explicit_empty_env_mapping_never_falls_back_to_legacy(monkeypatch, value):
    monkeypatch.setenv("CLINK_HOSTED_WALLET_CREDENTIALS_FILES", value)
    monkeypatch.setenv("CLINK_HOSTED_WALLET_CREDENTIALS_FILE", "/tmp/legacy.json")
    with pytest.raises(ValueError, match="CREDENTIALS_FILES"):
        AppConfig.from_env()


@pytest.mark.parametrize("use_router", [False, True])
def test_disabled_live_funding_never_reports_wallet_or_network_ready(tmp_path, use_router):
    from test_hosted_wallet_routing import _scoped_context

    _, service, _, _, path, _, _ = _scoped_context(tmp_path)
    if use_router:
        service.hosted_wallet_registry = _router_class()(
            {BASE: path}, chain_targets=service.config.clink_hosted_facilitator_chain_targets,
        )
    service.config.clink_live_funding = False
    funding = service.get_funding_readiness()
    assert funding["hosted_facilitator_ready"] is True  # local configuration only
    assert funding["ready_networks"] == []
    assert funding["network_status"][BASE]["ready"] is False
    wallet = service.get_hosted_wallet_readiness("user_1")
    assert wallet["ready"] is False
    assert wallet["reason_code"] == "HOSTED_SERVICE_NOT_READY"


@pytest.mark.parametrize("network", [BASE, POLYGON])
@pytest.mark.parametrize("unknown", [False, True])
def test_real_ledger_router_pins_credentials_executor_and_recovery(tmp_path, network, unknown):
    from dataclasses import replace
    from decimal import Decimal
    from test_hosted_wallet_routing import _scoped_context
    from test_task_2b_hosted_routing import NOW, _exact_business_authorization

    repository, original, row, client, path, record, _ = _scoped_context(
        tmp_path, network=network, submit_unknown=unknown,
    )
    other = POLYGON if network == BASE else BASE
    other_path = tmp_path / "other-chain.json"
    _write_registry(other_path, [_record(
        wallet_identity_id="identity_1", tenant_id="foreign_tenant",
        node_id="foreign_node", wallet_binding_id="foreign_binding",
    )])
    targets = dict(original.config.clink_hosted_facilitator_chain_targets)
    targets[other] = {**_target("https://other.hosted.example"),
                      "executor_contract": "0x" + "55" * 20}
    selected = []

    def factory(credential, chain, target):
        selected.append((credential, chain, target))
        assert chain == network
        assert credential.tenant_id == record["tenant_id"]
        assert target["executor_contract"] == EXECUTOR
        return client

    router = _router_class()(
        {network: path, other: other_path}, chain_targets=targets,
        client_factory=factory,
    )
    service = FundingService(
        config=replace(original.config, clink_hosted_wallet_credentials_file="",
                       clink_hosted_wallet_credentials_files={network: str(path), other: str(other_path)},
                       clink_hosted_facilitator_chain_targets=targets),
        policy_service=original.policy_service, hosted_wallet_registry=router,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    request = _exact_business_authorization(network)
    result = service.settle_reservation(row["reservation_id"], request)
    assert len(client.submit_calls) == 1
    with service.ledger.transaction() as tx:
        capability = tx.payment_capability_for_reservation(row["reservation_id"])
    assert capability.network == network
    assert capability.executor_contract == EXECUTOR
    assert capability.tenant_id == record["tenant_id"]
    grant = repository.spending_grant("grant_1")
    assert grant.max_amount_usdc == Decimal("5")
    assert grant.used_amount_usdc == Decimal("0")
    assert grant.reserved_amount_usdc == Decimal("1")
    if unknown:
        assert result["hosted_submission_unknown"] is True
        _write_registry(path, [
            {**record, "state": "recovery_only"},
            _record(wallet_identity_id="identity_1", tenant_id="rotated_tenant",
                    node_id="rotated_node", wallet_binding_id="rotated_binding"),
        ])
        replay = service.settle_reservation(row["reservation_id"], request)
        assert replay["hosted_submission_unknown"] is True
        assert len(client.submit_calls) == 1
        assert len(client.lookup_calls) == 1
        assert selected[-1][0].state == "recovery_only"
        assert selected[-1][1] == network
        with pytest.raises(ValueError, match="recovery-only"):
            service._require_hosted_client(network, capability=capability, for_submission=True)
    else:
        assert result["state"] == "payment_submitted"
    after = repository.spending_grant("grant_1")
    assert (after.max_amount_usdc, after.used_amount_usdc, after.reserved_amount_usdc) == (
        Decimal("5"), Decimal("0"), Decimal("1"),
    )


@pytest.mark.parametrize("network", ["eip155:999", "8453", "", 8453, []])
def test_runtime_selector_rejects_unknown_or_malformed_network(tmp_path, network):
    router, *_ = _two_chain_router(tmp_path)
    with pytest.raises(HostedWalletRegistryError, match="target"):
        router.current(user_id="user_1", wallet_identity_id="wallet_1", network=network)


def test_wallet_readiness_keeps_ready_base_when_polygon_not_enrolled(tmp_path):
    from dataclasses import replace
    from test_hosted_wallet_routing import _scoped_context

    _, original, _, _, path, _, _ = _scoped_context(tmp_path)
    targets = {**original.config.clink_hosted_facilitator_chain_targets,
               POLYGON: _target("https://polygon.hosted.example")}
    files = {BASE: str(path), POLYGON: str(tmp_path / "not-enrolled.json")}
    service = FundingService(config=replace(
        original.config, clink_hosted_wallet_credentials_file="",
        clink_hosted_wallet_credentials_files=files,
        clink_hosted_facilitator_chain_targets=targets,
    ), policy_service=original.policy_service)
    readiness = service.get_hosted_wallet_readiness("user_1")
    assert readiness["ready"] is True
    assert readiness["ready_networks"] == [BASE]
    assert readiness["network_status"][POLYGON] == {
        "ready": False, "reason_code": "HOSTED_ENROLLMENT_REQUIRED",
    }
