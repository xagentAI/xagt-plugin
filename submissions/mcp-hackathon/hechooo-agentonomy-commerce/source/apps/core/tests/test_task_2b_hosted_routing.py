from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from services.action_policy_repository import ActionPolicyRepository
from services.action_service.schemas import AgentActionIntent
from services.account_service.app import _approval_targets
from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.account_service.service import AccountService
from services.funding_service.hosted_client import (
    HostedExecutionUnknown,
    HostedFacilitatorUnavailable,
    HostedFacilitatorClient,
)
from services.funding_service.hosted_routing import build_hosted_payment_challenge
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    SettleSpendingReservationRequest,
)
from services.funding_service.service import FundingService, ReservationProvenance
from services.policy_service.schemas import PolicyDecision
from shared.config import AppConfig
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HostedExecutionResponse,
    hosted_chain_profile,
)
from shared.payment_capability import PaymentCapabilityV1


BASE = "eip155:8453"
POLYGON = "eip155:137"
BASE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913".lower()
POLYGON_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cC03d5c3359".lower()
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
HASH = "0x" + "44" * 32
NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
RECEIPT_SIGNING_KEY = "task-2b-receipt-signing-key-" + "7" * 32


def _device_private_key() -> str:
    key = DeviceSigningKey.generate()
    return base64.b64encode(key.pkcs8_der).decode("ascii")


def _capability(network: str = BASE) -> PaymentCapabilityV1:
    token = BASE_TOKEN if network == BASE else POLYGON_TOKEN
    return PaymentCapabilityV1(
        capability_id="capability_1",
        user_id="user_1",
        agent_id="agent_1",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        wallet_identity_id="identity_1",
        wallet_address=OWNER,
        spending_grant_id="grant_1",
        spending_grant_hash=HASH,
        asset_allowance_id="allowance_1",
        action_id="action_1",
        policy_decision_id="policy_1",
        policy_snapshot_hash=HASH,
        risk_evidence_hash=HASH,
        reservation_id="reservation_1",
        reservation_hash=HASH,
        purchase_id="purchase_1",
        merchant_id="merchant_1",
        product="marketplace",
        venue="clink_marketplace",
        quote_hash=HASH,
        payment_challenge_hash=HASH,
        network=network,
        asset_contract=token,
        amount_atomic="1000000",
        pay_to=PAYEE,
        executor_contract=EXECUTOR,
        execution_scope_hash=HASH,
        confirmation_mode="user_approved",
        revocation_id=HASH,
        issued_at=100,
        expires_at=160,
    )


def _target(origin: str, *, executor: str = EXECUTOR) -> dict[str, object]:
    return {
        "origin": origin,
        "server_public_jwk": DeviceSigningKey.generate().public_jwk,
        "executor_contract": executor,
    }


def _hosted_config(tmp_path: Path, **updates) -> AppConfig:
    values = {
        "funding_database_url": f"sqlite+pysqlite:///{tmp_path / 'readiness.sqlite3'}",
        "clink_facilitator_mode": "hosted",
        "clink_live_funding": True,
        "risk_mode": "enforce",
        "misttrack_api_key": "test-key",
        "clink_hosted_facilitator_tenant_id": "tenant_1",
        "clink_hosted_facilitator_node_id": "node_1",
        "clink_hosted_facilitator_wallet_binding_id": "binding_1",
        "clink_hosted_facilitator_access_token": "access-token",
        "clink_hosted_facilitator_device_private_key": _device_private_key(),
    }
    values.update(updates)
    return AppConfig(**values)


def test_hosted_client_requires_an_explicit_chain_id():
    with pytest.raises(TypeError, match="chain_id"):
        HostedFacilitatorClient(
            origin="https://hosted.example",
            tenant_id="tenant_1",
            node_id="node_1",
            wallet_binding_id="binding_1",
            access_token="access-token",
            device_key=DeviceSigningKey.generate(),
            server_public_jwk=DeviceSigningKey.generate().public_jwk,
        )


def test_hosted_target_mapping_is_explicit_and_scalar_bridge_only_materializes_base(
    monkeypatch,
):
    monkeypatch.setenv(
        "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS",
        json.dumps({BASE: _target("https://base.hosted.example")}),
    )
    monkeypatch.setenv("CLINK_FACILITATOR_MODE", "hosted")

    config = AppConfig.from_env()

    assert config.clink_hosted_facilitator_chain_targets[BASE]["origin"] == (
        "https://base.hosted.example"
    )
    assert POLYGON not in config.clink_hosted_facilitator_chain_targets

    bridge = AppConfig(
        clink_facilitator_mode="hosted",
        clink_hosted_facilitator_url="https://legacy.hosted.example",
        clink_hosted_facilitator_server_public_jwk=json.dumps(
            DeviceSigningKey.generate().public_jwk
        ),
        clink_hosted_facilitator_device_private_key="device-secret",
    )
    assert set(bridge.clink_hosted_facilitator_chain_targets) == {BASE}
    assert bridge.clink_hosted_facilitator_chain_targets[BASE]["origin"] == (
        "https://legacy.hosted.example"
    )
    described = json.dumps(bridge.describe(), sort_keys=True)
    assert "legacy.hosted.example" in described
    assert "device-secret" not in described


def test_hosted_clients_bind_exact_chain_and_identity_before_transport(tmp_path: Path):
    device = DeviceSigningKey.generate()
    response = DeviceSigningKey.generate()
    client = HostedFacilitatorClient(
        chain_id=POLYGON,
        origin="https://polygon.hosted.example",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        access_token="access-token",
        device_key=device,
        server_public_jwk=response.public_jwk,
    )

    request = client.prepare_execution(
        _capability(POLYGON),
        request_id="request_1",
        idempotency_key="reservation_1",
        now=103,
    )
    assert request.envelope.chain_id == POLYGON
    assert client.chain_id == POLYGON
    assert client.origin == "https://polygon.hosted.example"

    with pytest.raises(ValueError, match="chain"):
        client.prepare_execution(
            _capability(BASE),
            request_id="request_2",
            idempotency_key="reservation_2",
            now=103,
        )

    drifted = _capability(POLYGON).model_copy(update={"tenant_id": "tenant_2"})
    with pytest.raises(ValueError, match="identity"):
        client.prepare_execution(
            drifted,
            request_id="request_3",
            idempotency_key="reservation_3",
            now=103,
        )


def test_funding_service_routes_durable_network_without_base_fallback(tmp_path: Path):
    response_base = DeviceSigningKey.generate()
    response_polygon = DeviceSigningKey.generate()
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'routing.sqlite3'}",
        clink_facilitator_mode="hosted",
        clink_hosted_facilitator_tenant_id="tenant_1",
        clink_hosted_facilitator_node_id="node_1",
        clink_hosted_facilitator_wallet_binding_id="binding_1",
        clink_hosted_facilitator_access_token="access-token",
        clink_hosted_facilitator_device_private_key=_device_private_key(),
        clink_hosted_facilitator_chain_targets={
            BASE: {
                "origin": "https://base.hosted.example",
                "server_public_jwk": response_base.public_jwk,
                "executor_contract": EXECUTOR,
            },
            POLYGON: {
                "origin": "https://polygon.hosted.example",
                "server_public_jwk": response_polygon.public_jwk,
                "executor_contract": EXECUTOR,
            },
        },
    )

    service = FundingService(config=config)

    assert set(service.hosted_clients) == {BASE, POLYGON}
    assert service.hosted_clients[BASE].chain_id == BASE
    assert service.hosted_clients[POLYGON].chain_id == POLYGON
    assert service.hosted_clients[BASE].origin == "https://base.hosted.example"
    assert service.hosted_clients[POLYGON].origin == "https://polygon.hosted.example"

    base_only = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'base-only.sqlite3'}",
        clink_facilitator_mode="hosted",
        clink_hosted_facilitator_tenant_id="tenant_1",
        clink_hosted_facilitator_node_id="node_1",
        clink_hosted_facilitator_wallet_binding_id="binding_1",
        clink_hosted_facilitator_access_token="access-token",
        clink_hosted_facilitator_device_private_key=_device_private_key(),
        clink_hosted_facilitator_chain_targets={
            BASE: {
                "origin": "https://base.hosted.example",
                "server_public_jwk": response_base.public_jwk,
                "executor_contract": EXECUTOR,
            }
        },
    )
    base_only_service = FundingService(config=base_only)
    with pytest.raises(ValueError, match="Polygon|target|configured"):
        base_only_service._require_hosted_client(POLYGON)


def test_legacy_scalar_hosted_readiness_only_advertises_base(tmp_path: Path):
    config = _hosted_config(
        tmp_path,
        clink_hosted_facilitator_url="https://legacy.hosted.example",
        clink_hosted_facilitator_server_public_jwk=json.dumps(
            DeviceSigningKey.generate().public_jwk
        ),
    )

    readiness = FundingService(config=config).get_funding_readiness()

    assert readiness["status"] == "not_ready"
    assert readiness["hosted_facilitator_ready"] is False
    assert readiness["supported_assets"] == {BASE: BASE_TOKEN}
    assert readiness["spender_addresses"] == {}
    assert readiness["spender_address"] is None
    assert not any(POLYGON in item for item in readiness["missing"])


def test_legacy_scalar_hosted_target_cannot_execute_without_executor(
    tmp_path: Path,
):
    config = _hosted_config(
        tmp_path,
        clink_hosted_facilitator_url="https://legacy.hosted.example",
        clink_hosted_facilitator_server_public_jwk=json.dumps(
            DeviceSigningKey.generate().public_jwk
        ),
    )

    service = FundingService(config=config)

    with pytest.raises(ValueError, match="executor"):
        service._require_hosted_client(BASE)


def test_hosted_capability_issuance_rejects_executor_target_drift(tmp_path: Path):
    client = _RecordingHostedClient(BASE)
    _repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=BASE,
        hosted_clients={BASE: client},
    )
    service.config.clink_hosted_facilitator_chain_targets[BASE][
        "executor_contract"
    ] = "0x" + "99" * 20
    hosted_authorization = service._hosted_authorization(authorization)

    with pytest.raises(ValueError, match="executor"):
        service._hosted_capability(
            reserved["reservation_id"], hosted_authorization, require_reserved=True
        )

    with service.ledger.transaction() as transaction:
        capability = transaction.payment_capability_for_reservation(
            reserved["reservation_id"]
        )
    assert capability is None


def test_explicit_dual_chain_hosted_readiness_advertises_both_targets(
    tmp_path: Path,
):
    config = _hosted_config(
        tmp_path,
        clink_hosted_facilitator_chain_targets={
            BASE: _target("https://base.hosted.example"),
            POLYGON: _target("https://polygon.hosted.example"),
        },
    )

    readiness = FundingService(config=config).get_funding_readiness()

    assert readiness["status"] == "ready"
    assert readiness["hosted_facilitator_ready"] is True
    assert readiness["supported_assets"] == {
        BASE: BASE_TOKEN,
        POLYGON: POLYGON_TOKEN,
    }


def test_hosted_readiness_exposes_per_chain_executor_and_no_eoa_payer(
    tmp_path: Path,
):
    base_executor = "0x" + "33" * 20
    polygon_executor = "0x" + "55" * 20
    config = _hosted_config(
        tmp_path,
        clink_hosted_facilitator_chain_targets={
            BASE: _target("https://base.hosted.example", executor=base_executor),
            POLYGON: _target(
                "https://polygon.hosted.example", executor=polygon_executor
            ),
        },
    )

    readiness = FundingService(config=config).get_funding_readiness()

    assert readiness["status"] == "ready"
    assert readiness["spender_addresses"] == {
        BASE: base_executor,
        POLYGON: polygon_executor,
    }
    assert readiness["spender_address"] is None
    assert readiness["payer_address"] is None
    assert readiness["relayer_address"] is None
    assert readiness["automatic_payment_rail"] == "clink_hosted_executor"


def test_hosted_readiness_keeps_scalar_spender_for_one_chain(tmp_path: Path):
    executor = "0x" + "66" * 20
    config = _hosted_config(
        tmp_path,
        clink_hosted_facilitator_chain_targets={
            BASE: _target("https://base.hosted.example", executor=executor),
        },
    )

    readiness = FundingService(config=config).get_funding_readiness()

    assert readiness["spender_addresses"] == {BASE: executor}
    assert readiness["spender_address"] == executor


def test_hosted_target_requires_a_valid_executor_contract(tmp_path: Path):
    response_key = DeviceSigningKey.generate().public_jwk
    with pytest.raises(ValueError, match="executor"):
        AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'invalid-target.sqlite3'}",
            clink_facilitator_mode="hosted",
            clink_hosted_facilitator_chain_targets={
                BASE: {
                    "origin": "https://base.hosted.example",
                    "server_public_jwk": response_key,
                }
            },
        )


def test_hosted_account_approval_targets_reuse_chain_executors(tmp_path: Path):
    base_executor = "0x" + "33" * 20
    polygon_executor = "0x" + "55" * 20
    config = _hosted_config(
        tmp_path,
        clink_base_spender_address="",
        clink_polygon_spender_address="",
        clink_hosted_facilitator_chain_targets={
            BASE: _target("https://base.hosted.example", executor=base_executor),
            POLYGON: _target(
                "https://polygon.hosted.example", executor=polygon_executor
            ),
        },
    )
    service = AccountService(
        AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'account.sqlite3'}"),
        domain="account.clink.test",
    )

    targets = _approval_targets(config, service, None)

    assert targets == {
        BASE: {"token_address": BASE_TOKEN, "spender_address": base_executor},
        POLYGON: {
            "token_address": POLYGON_TOKEN,
            "spender_address": polygon_executor,
        },
    }

    with pytest.raises(ValueError, match="executor"):
        AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'malformed-target.sqlite3'}",
            clink_facilitator_mode="hosted",
            clink_hosted_facilitator_chain_targets={
                BASE: _target("https://base.hosted.example", executor="not-an-address"),
            },
        )


class _PolicyStub:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision

    def get_decision(self, _policy_decision_id: str) -> PolicyDecision:
        return self.decision


def _execution_response(request, *, state: str) -> HostedExecutionResponse:
    envelope = request.envelope
    profile = hosted_chain_profile(envelope.chain_id)
    finalized = state == "finalized"
    reverted = state in {"reverted", "released"}
    receipt_observed = finalized or reverted
    released = state == "released"
    boundary_timestamp = envelope.expires_at
    values = {
        "request_id": envelope.request_id,
        "request_hash": request.request_hash,
        "idempotency_key": envelope.idempotency_key,
        "execution_id": f"execution_{profile.chain_id}",
        "capability_id": envelope.payment_capability_id,
        "capability_hash": envelope.payment_capability_hash,
        "reservation_id": envelope.reservation_id,
        "reservation_hash": envelope.reservation_hash,
        "purchase_id": envelope.purchase_id,
        "execution_scope_hash": envelope.execution_scope_hash,
        "owner": envelope.wallet_address,
        "payee": envelope.pay_to,
        "token": envelope.asset_contract,
        "amount_atomic": envelope.amount_atomic,
        "executor": envelope.executor_contract,
        "signer_epoch": 1,
        "owner_nonce": envelope.request_nonce,
        "deadline": envelope.expires_at,
        "chain_id": envelope.chain_id,
        "state": state,
        "transaction_hash": "0x" + f"{profile.chain_id % 256:02x}" * 32,
        "receipt_block_hash": "0x" + "bb" * 32 if receipt_observed else None,
        "receipt_block_number": 100 if receipt_observed else None,
        "safe_block_hash": "0x" + "cc" * 32 if receipt_observed else None,
        "safe_block_number": 102 if receipt_observed else None,
        "confirmations": profile.min_confirmation_depth if receipt_observed else 0,
        "failure_reason_code": (
            "SAFE_REVERT_RELEASE"
            if released
            else "ONCHAIN_REVERT" if reverted else None
        ),
        "issued_at": envelope.issued_at,
        "submitted_at": envelope.issued_at,
        "confirmed_at": envelope.issued_at + 1 if finalized else None,
        "finalized_at": envelope.issued_at + 2 if finalized else None,
        "reverted_at": envelope.issued_at + 2 if reverted else None,
        "reorg_reviewed_at": None,
        "released_at": boundary_timestamp if released else None,
        "expired_at": None,
        "watcher_version": (
            f"task-2b-{profile.chain_id}-watcher-v1"
            if receipt_observed
            else None
        ),
        "finality_boundary": (
            profile.finality_boundary if receipt_observed else None
        ),
        "release_evidence": (
            {
                "receipt_status": 0,
                "canonical_receipt": True,
                "finality_boundary_timestamp": boundary_timestamp,
                "capability_used": False,
                "owner_nonce_used": False,
                "payment_event_found": False,
                "transfer_event_found": False,
            }
            if released
            else None
        ),
        "server_key_id": "server-key",
    }
    return HostedExecutionResponse(**values)


class _RecordingHostedClient:
    def __init__(
        self,
        chain_id: str,
        *,
        submit_state: str = "submitted",
        recover_state: str = "submitted",
        recover_updates: dict | None = None,
        lookup_state: str | None = None,
        lookup_updates: dict | None = None,
        submit_unknown: bool = False,
        lookup_not_found: bool = False,
    ) -> None:
        self.chain_id = chain_id
        self.tenant_id = "tenant_1"
        self.node_id = "node_1"
        self.wallet_binding_id = "binding_1"
        self.submit_state = submit_state
        self.recover_state = recover_state
        self.recover_updates = recover_updates or {}
        self.lookup_state = lookup_state
        self.lookup_updates = lookup_updates or {}
        self.submit_unknown = submit_unknown
        self.lookup_not_found = lookup_not_found
        self.submit_calls = []
        self.recover_calls = []
        self.lookup_calls = []
        self._delegate = HostedFacilitatorClient(
            chain_id=chain_id,
            origin=f"https://{hosted_chain_profile(chain_id).chain_id}.hosted.example",
            tenant_id=self.tenant_id,
            node_id=self.node_id,
            wallet_binding_id=self.wallet_binding_id,
            access_token="access-token",
            device_key=DeviceSigningKey.generate(),
            server_public_jwk=DeviceSigningKey.generate().public_jwk,
            clock=lambda: int(NOW.timestamp()),
        )

    def prepare_execution(self, *args, **kwargs):
        return self._delegate.prepare_execution(*args, **kwargs)

    def submit(self, request):
        self.submit_calls.append(request)
        if self.submit_unknown:
            raise HostedExecutionUnknown(
                "hosted execution submission outcome is unknown"
            )
        return _execution_response(request, state=self.submit_state)

    def recover(self, request, execution_id: str):
        self.recover_calls.append((request, execution_id))
        response = _execution_response(request, state=self.recover_state)
        return response.model_copy(update=self.recover_updates)

    def recover_by_idempotency(self, request):
        self.lookup_calls.append(request)
        if self.lookup_not_found:
            from services.funding_service.hosted_client import HostedExecutionNotFound
            raise HostedExecutionNotFound("hosted execution was not found")
        if self.lookup_state is None:
            raise HostedFacilitatorUnavailable("lookup unavailable")
        response = _execution_response(request, state=self.lookup_state)
        return response.model_copy(update=self.lookup_updates)


def _hosted_settlement_context(
    tmp_path: Path,
    *,
    network: str,
    hosted_clients: dict[str, _RecordingHostedClient],
    targets: dict[str, dict[str, object]] | None = None,
):
    token = hosted_chain_profile(network).token
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hosted-settlement.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="identity_1",
            user_id="user_1",
            wallet_address=OWNER,
            status="active",
            proof_hash="0xproof",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_spending_grant(
        SpendingGrant(
            spending_grant_id="grant_1",
            wallet_identity_id="identity_1",
            user_id="user_1",
            agent_id="hermes",
            status="active",
            max_amount_usdc=Decimal("5"),
            per_transaction_limit_usdc=Decimal("2"),
            hourly_limit_usdc=Decimal("4"),
            daily_limit_usdc=Decimal("5"),
            used_amount_usdc=Decimal("0"),
            reserved_amount_usdc=Decimal("0"),
            product_scopes=["marketplace"],
            venue_scopes=["clink_marketplace"],
            merchant_scopes=["merchant_1"],
            merchant_trust_scopes=["registry_verified"],
            notification_mode="silent_under_limits",
            network_scopes=[network],
            asset_scopes=[token],
            starts_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(minutes=5),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_asset_allowance(
        AssetAllowance(
            asset_allowance_id="allowance_1",
            wallet_identity_id="identity_1",
            network=network,
            token_address=token,
            token_symbol="USDC",
            token_decimals=6,
            spender_address=EXECUTOR,
            approved_amount_atomic=5_000_000,
            observed_allowance_atomic=5_000_000,
            status="active",
            confirmed_block=100,
            last_chain_check_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    metadata = {
        "purchase_id": "purchase_1",
        "quote_hash": HASH,
        "network": network,
        "asset": token,
        "amount_atomic": "1000000",
        "destination": PAYEE,
        "resource": "https://merchant.example/resource",
        "authorization_rail": "native_allowance",
        "product": "marketplace",
        "wallet_identity_id": "identity_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
        "merchant_trust_tier": "registry_verified",
    }
    decision = PolicyDecision(
        policy_decision_id="policy_1",
        action_id="action_1",
        approved=True,
        decision="approved",
        reason_code="within_policy",
        user_id="user_1",
        agent_id="hermes",
        action_type="marketplace_purchase",
        amount_usdc="1",
        merchant_id="merchant_1",
        target_address=PAYEE,
        chain=network,
        evaluated_at="2026-08-25T11:59:00Z",
        authorization_approved=True,
        risk_assessment={
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
        },
        metadata=metadata,
    )
    action = AgentActionIntent(
        action_id="action_1",
        user_id="user_1",
        agent_id="hermes",
        action_type="marketplace_purchase",
        state="policy_approved",
        amount_usdc="1",
        merchant_id="merchant_1",
        policy_decision_id="policy_1",
        metadata=metadata,
        created_at="2026-08-25T12:00:00Z",
        updated_at="2026-08-25T12:00:00Z",
    )
    action_repository = ActionPolicyRepository(database_url)
    action_repository.create_policy_decision(decision.to_dict())
    action_repository.create_action_intent(action.to_dict())
    config = _hosted_config(
        tmp_path,
        funding_database_url=database_url,
        clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        clink_base_usdc_address=BASE_TOKEN,
        clink_polygon_usdc_address=POLYGON_TOKEN,
        clink_base_spender_address=EXECUTOR,
        clink_polygon_spender_address=EXECUTOR,
        clink_hosted_facilitator_chain_targets=targets
        or {
            BASE: _target("https://base.hosted.example"),
            POLYGON: _target("https://polygon.hosted.example"),
        },
    )
    service = FundingService(
        config=config,
        policy_service=_PolicyStub(decision),
        hosted_clients=hosted_clients,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reservation_request = CreateSpendingReservationRequest(
        purchase_id="purchase_1",
        idempotency_key="reservation_idempotency_1",
        wallet_identity_id="identity_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1",
        product="marketplace",
        action_id="action_1",
        policy_decision_id="policy_1",
        merchant_id="merchant_1",
        merchant_trust_tier="registry_verified",
        quote_hash=HASH,
        amount_usdc="1",
        amount_atomic="1000000",
        network=network,
        asset=token,
        destination=PAYEE,
        resource="https://merchant.example/resource",
        venue="clink_marketplace",
    )
    reserved = service._reserve_unified_spending(
        reservation_request,
        Decimal("1"),
        ReservationProvenance(
            action=action,
            authorization_path="unified_grant",
            product="marketplace",
            unified_references={
                "product": "marketplace",
                "wallet_identity_id": "identity_1",
                "spending_grant_id": "grant_1",
                "asset_allowance_id": "allowance_1",
            },
        ),
    )
    authorization = SettleSpendingReservationRequest(
        payment_authorization={
            "kind": "hosted_execution",
            "tenant_id": "tenant_1",
            "node_id": "node_1",
            "wallet_binding_id": "binding_1",
            "executor_contract": EXECUTOR,
            "payment_challenge_hash": HASH,
        }
    )
    return repository, service, reserved, authorization


def _exact_business_authorization(network: str) -> SettleSpendingReservationRequest:
    return SettleSpendingReservationRequest(
        payment_authorization={
            "scheme": "exact",
            "network": network,
            "asset": hosted_chain_profile(network).token,
            "amount_atomic": "1000000",
            "pay_to": PAYEE,
        }
    )


@pytest.mark.parametrize("network", [BASE, POLYGON])
def test_allowance_business_intent_automatically_uses_hosted_execution(
    tmp_path: Path,
    network: str,
):
    clients = {
        BASE: _RecordingHostedClient(BASE),
        POLYGON: _RecordingHostedClient(POLYGON),
    }
    _repository, service, reserved, _legacy_authorization = (
        _hosted_settlement_context(
            tmp_path,
            network=network,
            hosted_clients=clients,
        )
    )
    request = _exact_business_authorization(network)

    submitted = service.settle_reservation(reserved["reservation_id"], request)

    assert submitted["state"] == "payment_submitted"
    assert submitted["settlement_rail"] == "hosted"
    assert len(clients[network].submit_calls) == 1
    other_network = POLYGON if network == BASE else BASE
    assert clients[other_network].submit_calls == []
    with service.ledger.transaction() as transaction:
        row = transaction.get(reserved["reservation_id"])
        capability = transaction.payment_capability_for_reservation(
            reserved["reservation_id"]
        )
    assert capability is not None
    assert capability.payment_challenge_hash == build_hosted_payment_challenge(
        request.payment_authorization, row
    )


def test_automatic_hosted_unknown_reuses_business_intent_without_a_second_post(
    tmp_path: Path,
):
    client = _RecordingHostedClient(BASE, submit_unknown=True)
    _repository, service, reserved, _legacy_authorization = (
        _hosted_settlement_context(
            tmp_path,
            network=BASE,
            hosted_clients={BASE: client},
            targets={BASE: _target("https://base.hosted.example")},
        )
    )
    request = _exact_business_authorization(BASE)

    unknown = service.settle_reservation(reserved["reservation_id"], request)
    replay = service.settle_reservation(reserved["reservation_id"], request)

    assert unknown["hosted_status"] == replay["hosted_status"] == "submission_unknown"
    assert len(client.submit_calls) == 1


def test_automatic_hosted_replay_rejects_a_changed_business_intent(
    tmp_path: Path,
):
    client = _RecordingHostedClient(BASE, submit_unknown=True)
    _repository, service, reserved, _legacy_authorization = (
        _hosted_settlement_context(
            tmp_path,
            network=BASE,
            hosted_clients={BASE: client},
            targets={BASE: _target("https://base.hosted.example")},
        )
    )
    request = _exact_business_authorization(BASE)
    service.settle_reservation(reserved["reservation_id"], request)
    changed = request.model_copy(
        update={
            "payment_authorization": {
                **request.payment_authorization,
                "pay_to": "0x" + "55" * 20,
            }
        }
    )

    with pytest.raises(ValueError, match="destination|authorization"):
        service.settle_reservation(reserved["reservation_id"], changed)
    assert len(client.submit_calls) == 1


def test_automatic_hosted_replay_accepts_a_canonical_equivalent_intent(
    tmp_path: Path,
):
    client = _RecordingHostedClient(BASE, submit_unknown=True)
    _repository, service, reserved, _legacy_authorization = (
        _hosted_settlement_context(
            tmp_path,
            network=BASE,
            hosted_clients={BASE: client},
            targets={BASE: _target("https://base.hosted.example")},
        )
    )
    request = _exact_business_authorization(BASE)
    first = service.settle_reservation(reserved["reservation_id"], request)
    equivalent = request.model_copy(
        update={
            "payment_authorization": {
                **request.payment_authorization,
                "asset": "0x"
                + request.payment_authorization["asset"][2:].upper(),
                "pay_to": "0x"
                + request.payment_authorization["pay_to"][2:].upper(),
            }
        }
    )

    replay = service.settle_reservation(reserved["reservation_id"], equivalent)

    assert first["hosted_status"] == replay["hosted_status"]
    assert len(client.submit_calls) == 1


def test_proxy_reimbursement_is_not_automatically_treated_as_hosted_direct_pay(
    tmp_path: Path,
):
    service = FundingService(
        config=_hosted_config(
            tmp_path,
            clink_hosted_facilitator_chain_targets={
                BASE: _target("https://base.hosted.example")
            },
        ),
        hosted_clients={BASE: _RecordingHostedClient(BASE)},
    )

    assert service._hosted_selected_for_business(
        {"authorization_rail": "clink_payer_proxy", "settlement_rail": None},
        has_hosted_capability=False,
    ) is False
    assert service._hosted_selected_for_business(
        {"authorization_rail": "clink_payer_proxy", "settlement_rail": "hosted"},
        has_hosted_capability=False,
    ) is True


@pytest.mark.parametrize("network", [BASE, POLYGON])
def test_settle_and_restart_reconcile_route_only_to_durable_network(
    tmp_path: Path,
    network: str,
):
    first_clients = {
        BASE: _RecordingHostedClient(BASE),
        POLYGON: _RecordingHostedClient(POLYGON),
    }
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=network,
        hosted_clients=first_clients,
    )

    submitted = service.settle_reservation(reserved["reservation_id"], authorization)

    other_network = POLYGON if network == BASE else BASE
    assert submitted["state"] == "payment_submitted"
    assert len(first_clients[network].submit_calls) == 1
    assert first_clients[other_network].submit_calls == []
    assert first_clients[BASE].recover_calls == []
    assert first_clients[POLYGON].recover_calls == []

    restarted_clients = {
        BASE: _RecordingHostedClient(BASE, recover_state="finalized"),
        POLYGON: _RecordingHostedClient(POLYGON, recover_state="finalized"),
    }
    restarted = FundingService(
        config=service.config,
        policy_service=service.policy_service,
        hosted_clients=restarted_clients,
    )
    restarted._utc_now = lambda: NOW.replace(tzinfo=None)

    settled = restarted.settle_reservation(
        reserved["reservation_id"], authorization
    )
    replay = restarted.settle_reservation(reserved["reservation_id"], authorization)

    assert settled["state"] == replay["state"] == "settled"
    assert settled["budget_accounting_state"] == "settled"
    assert settled["receipt"]["status"] == "settled"
    assert restarted_clients[BASE].submit_calls == []
    assert restarted_clients[POLYGON].submit_calls == []
    assert len(restarted_clients[network].recover_calls) == 1
    assert restarted_clients[other_network].recover_calls == []
    assert len(first_clients[network].submit_calls) == 1
    updated_grant = repository.spending_grant("grant_1")
    assert updated_grant.used_amount_usdc == Decimal("1")
    assert updated_grant.reserved_amount_usdc == Decimal("0")
    receipts = restarted._load_latest("receipt")
    assert list(receipts) == [settled["receipt_id"]]
    with restarted.ledger.transaction() as transaction:
        capability = transaction.payment_capability_for_reservation(
            reserved["reservation_id"]
        )
    assert capability is not None
    assert capability.network == network


def test_missing_polygon_target_fails_closed_without_any_network_call(
    tmp_path: Path,
):
    base_client = _RecordingHostedClient(BASE)
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=POLYGON,
        hosted_clients={BASE: base_client},
        targets={BASE: _target("https://base.hosted.example")},
    )

    for _attempt in range(2):
        with pytest.raises(ValueError, match="target|configured"):
            service.settle_reservation(reserved["reservation_id"], authorization)

    assert base_client.submit_calls == []
    assert base_client.recover_calls == []
    with service.ledger.transaction() as transaction:
        row = transaction.get(reserved["reservation_id"])
    assert row["state"] == "spending_reserved"
    assert row["budget_accounting_state"] == "reserved"
    assert service._load_latest("receipt") == {}
    updated_grant = repository.spending_grant("grant_1")
    assert updated_grant.used_amount_usdc == Decimal("0")
    assert updated_grant.reserved_amount_usdc == Decimal("1")


def test_unknown_post_response_is_durable_and_never_causes_a_second_post(
    tmp_path: Path,
):
    client = _RecordingHostedClient(BASE, submit_unknown=True)
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=BASE,
        hosted_clients={BASE: client},
        targets={BASE: _target("https://base.hosted.example")},
    )

    unknown = service.settle_reservation(reserved["reservation_id"], authorization)
    replay = service.settle_reservation(reserved["reservation_id"], authorization)

    assert unknown["hosted_status"] == replay["hosted_status"] == "submission_unknown"
    assert unknown["state"] == replay["state"] == "spending_reserved"
    assert unknown["budget_accounting_state"] == "reserved"
    assert len(client.submit_calls) == 1
    assert client.recover_calls == []
    assert service._load_latest("receipt") == {}
    updated_grant = repository.spending_grant("grant_1")
    assert updated_grant.used_amount_usdc == Decimal("0")
    assert updated_grant.reserved_amount_usdc == Decimal("1")


def test_unknown_without_execution_id_recovers_by_idempotency_lookup_only(
    tmp_path: Path,
):
    first_client = _RecordingHostedClient(BASE, submit_unknown=True)
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=BASE,
        hosted_clients={BASE: first_client},
        targets={BASE: _target("https://base.hosted.example")},
    )

    unknown = service.settle_reservation(reserved["reservation_id"], authorization)
    assert unknown["hosted_execution_id"] is None

    lookup_client = _RecordingHostedClient(BASE, lookup_state="finalized")
    restarted = FundingService(
        config=service.config,
        policy_service=service.policy_service,
        hosted_clients={BASE: lookup_client},
    )
    restarted._utc_now = lambda: NOW.replace(tzinfo=None)

    settled = restarted.settle_reservation(reserved["reservation_id"], authorization)
    replay = restarted.settle_reservation(reserved["reservation_id"], authorization)

    assert settled["state"] == replay["state"] == "settled"
    assert settled["budget_accounting_state"] == "settled"
    assert settled["receipt"]["status"] == "settled"
    assert len(first_client.submit_calls) == 1
    assert first_client.lookup_calls == []
    assert lookup_client.submit_calls == []
    assert len(lookup_client.lookup_calls) == 1
    assert lookup_client.recover_calls == []
    assert len(restarted._load_latest("receipt")) == 1
    updated_grant = repository.spending_grant("grant_1")
    assert updated_grant.used_amount_usdc == Decimal("1")
    assert updated_grant.reserved_amount_usdc == Decimal("0")


def test_real_ledger_safe_revert_release_is_atomic_indexed_and_terminal(
    tmp_path: Path,
):
    client = _RecordingHostedClient(BASE)
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=BASE,
        hosted_clients={BASE: client},
        targets={BASE: _target("https://base.hosted.example")},
    )
    submitted = service.settle_reservation(reserved["reservation_id"], authorization)
    assert submitted["state"] == "payment_submitted"
    prepared = client.submit_calls[0]
    reverted = _execution_response(prepared, state="reverted")
    released_response = _execution_response(prepared, state="released")

    held = service._apply_hosted_response(reserved["reservation_id"], reverted)
    assert held["state"] == "payment_submitted"
    assert held["budget_accounting_state"] == "reserved"

    service._utc_now = lambda: datetime.fromtimestamp(
        released_response.deadline + 1, UTC
    ).replace(tzinfo=None)
    released = service._apply_hosted_response(
        reserved["reservation_id"], released_response
    )
    stale = service._apply_hosted_response(reserved["reservation_id"], reverted)

    assert released["state"] == stale["state"] == "released"
    assert released["budget_accounting_state"] == "released"
    with service.ledger.transaction() as transaction:
        indexed = transaction.by_tx_hash(released_response.transaction_hash)
    assert indexed["reservation_id"] == reserved["reservation_id"]
    grant = repository.spending_grant("grant_1")
    assert grant.used_amount_usdc == Decimal("0")
    assert grant.reserved_amount_usdc == Decimal("0")

    changed = released_response.model_copy(
        update={"safe_block_hash": "0x" + "dd" * 32}
    )
    with pytest.raises(ValueError, match="release evidence"):
        service._apply_hosted_response(reserved["reservation_id"], changed)
    grant_after_failed_replay = repository.spending_grant("grant_1")
    assert grant_after_failed_replay.used_amount_usdc == Decimal("0")
    assert grant_after_failed_replay.reserved_amount_usdc == Decimal("0")


@pytest.mark.parametrize(
    ("response_updates", "message"),
    [
        ({"chain_id": BASE}, "scope"),
        ({"token": BASE_TOKEN}, "scope|token"),
        ({"finality_boundary": "safe"}, "finality boundary"),
        ({"confirmations": 2}, "confirmations"),
    ],
)
def test_polygon_recovery_rejects_cross_chain_or_weak_finality_without_settling(
    tmp_path: Path,
    response_updates: dict,
    message: str,
):
    first_client = _RecordingHostedClient(POLYGON)
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=POLYGON,
        hosted_clients={POLYGON: first_client},
        targets={POLYGON: _target("https://polygon.hosted.example")},
    )
    submitted = service.settle_reservation(reserved["reservation_id"], authorization)
    assert submitted["state"] == "payment_submitted"

    recovery_client = _RecordingHostedClient(
        POLYGON,
        recover_state="finalized",
        recover_updates=response_updates,
    )
    restarted = FundingService(
        config=service.config,
        policy_service=service.policy_service,
        hosted_clients={POLYGON: recovery_client},
    )
    restarted._utc_now = lambda: NOW.replace(tzinfo=None)

    for _attempt in range(2):
        with pytest.raises(ValueError, match=message):
            restarted.settle_reservation(reserved["reservation_id"], authorization)

    assert len(first_client.submit_calls) == 1
    assert recovery_client.submit_calls == []
    assert len(recovery_client.recover_calls) == 2
    with restarted.ledger.transaction() as transaction:
        row = transaction.get(reserved["reservation_id"])
    assert row["state"] == "payment_submitted"
    assert row["budget_accounting_state"] == "reserved"
    assert restarted._load_latest("receipt") == {}
    updated_grant = repository.spending_grant("grant_1")
    assert updated_grant.used_amount_usdc == Decimal("0")
    assert updated_grant.reserved_amount_usdc == Decimal("1")
