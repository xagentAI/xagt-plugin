from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.action_service.schemas import CreateActionIntentRequest,UpdateActionIntentRequest
from services.action_service.service import ActionService
from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService
from datetime import UTC,datetime
from decimal import Decimal

from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance,SpendingGrant,WalletIdentity
from services.funding_service.schemas import CreateSpendingReservationRequest,SpendingAuthorization
from services.funding_service.service import FundingService
from services.policy_service.schemas import EvaluateActionPolicyRequest
from services.policy_service.service import PolicyService
from shared.config import AppConfig


POLYGON_USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"

def auth():return SpendingAuthorization(spending_authorization_id="auth",user_id="u",agent_id="hermes",wallet_address="0x"+"1"*40,max_amount_usdc="1",per_order_limit_usdc="1",used_amount_usdc="0",remaining_amount_usdc="1",venue="clink_marketplace",chain="eip155:137",token="USDC",spender_address="0x"+"2"*40,purpose="marketplace",status="active",expires_at="2099-01-01T00:00:00Z",created_at="2026-01-01T00:00:00Z")


def risk_assessment(**updates):
    assessment = {
        "provider": "misttrack",
        "provider_endpoint": "v2/risk_score",
        "subject": "0x" + "3" * 40,
        "network": "eip155:137",
        "asset": "USDC",
        "coin": "USDC-Polygon",
        "decision": "allow",
        "mode": "enforce",
        "enforced": True,
        "mapping_version": "misttrack-policy-v1",
        "hold_score": 31,
        "deny_score": 71,
        "assessed_at": "2026-07-31T11:59:30Z",
        "expires_at": "2026-07-31T12:04:30Z",
    }
    assessment.update(updates)
    return assessment


def test_legacy_reserve_is_read_only_after_exact_provenance_validation(monkeypatch):
  with TemporaryDirectory() as d:
    monkeypatch.setenv("ACTION_INTENT_FILE",str(Path(d)/"actions.jsonl"));monkeypatch.setenv("POLICY_DECISION_FILE",str(Path(d)/"policy.jsonl"));monkeypatch.setenv("AUDIT_EVENT_FILE",str(Path(d)/"audit.jsonl"))
    scope={"purchase_id":"purchase","quote_hash":"0x"+"a"*64,"network":"eip155:137","asset":"USDC","amount_atomic":"1000000","destination":"0x"+"3"*40,"resource":"https://merchant.example/api"}
    config=AppConfig(funding_database_url=f"sqlite+pysqlite:///{Path(d)/'ledger.db'}")
    actions=ActionService(config=config);action=actions.create_intent(CreateActionIntentRequest(user_id="u",agent_id="hermes",action_type="marketplace_purchase",amount_usdc="1",merchant_id="merchant",metadata=scope))
    policy=PolicyService(config=config).evaluate(EvaluateActionPolicyRequest(action_id=action.action_id,user_id="u",agent_id="hermes",action_type="marketplace_purchase",amount_usdc="1",merchant_id="merchant",target_address=scope["destination"],chain=scope["network"],user_confirmed=True,metadata=scope))
    actions.update_intent(action.action_id,UpdateActionIntentRequest(state="policy_approved",policy_decision_id=policy.policy_decision_id))
    AuditService(database_url=config.funding_database_url).write_event(WriteAuditEventRequest(event_type="marketplace_purchase_policy_evaluated",source_service="clink_marketplace",action_id=action.action_id,user_id="u",agent_id="hermes",policy_decision_id=policy.policy_decision_id,payload={**scope,"merchant_id":"merchant","venue":"clink_marketplace"}))
    request=CreateSpendingReservationRequest(idempotency_key="purchase",spending_authorization_id="auth",action_id=action.action_id,policy_decision_id=policy.policy_decision_id,merchant_id="merchant",amount_usdc="1",venue="clink_marketplace",**scope)
    service=FundingService(config=config,storage_file=Path(d)/"funding.jsonl")
    with patch.object(service,"get_spending_authorization",return_value=auth()),pytest.raises(ValueError,match="legacy spending authorizations are read-only"):service.reserve_spending(request)
    forged=request.model_copy(update={"destination":"0x"+"4"*40,"purchase_id":"purchase2","idempotency_key":"purchase2"})
    with patch.object(service,"get_spending_authorization",return_value=auth()),pytest.raises(ValueError,match="scope mismatch"):service.reserve_spending(forged)


def test_unified_reserve_requires_exact_refs_in_action_policy_and_audit(monkeypatch):
  with TemporaryDirectory() as d:
    root=Path(d);database_url=f"sqlite+pysqlite:///{root/'core.sqlite3'}"
    monkeypatch.setenv("ACTION_INTENT_FILE",str(root/"actions.jsonl"));monkeypatch.setenv("POLICY_DECISION_FILE",str(root/"policy.jsonl"));monkeypatch.setenv("AUDIT_EVENT_FILE",str(root/"audit.jsonl"))
    now=datetime(2026,7,15,tzinfo=UTC);token="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359";spender="0x"+"2"*40
    repository=AccountRepository(database_url)
    repository.save_wallet_identity(WalletIdentity(wallet_identity_id="wallet_1",user_id="u",wallet_address="0x"+"a"*40,status="active",proof_hash="0xproof",verified_at=now,created_at=now,updated_at=now))
    repository.save_spending_grant(SpendingGrant(spending_grant_id="grant_1",wallet_identity_id="wallet_1",user_id="u",agent_id="hermes",status="active",max_amount_usdc=Decimal("5"),per_transaction_limit_usdc=Decimal("2"),daily_limit_usdc=Decimal("5"),product_scopes=["marketplace"],venue_scopes=["clink_marketplace"],merchant_scopes=["merchant"],network_scopes=["eip155:137"],asset_scopes=[token],starts_at=datetime(2026,7,1,tzinfo=UTC),expires_at=datetime(2026,8,1,tzinfo=UTC),created_at=now,updated_at=now))
    repository.save_asset_allowance(AssetAllowance(asset_allowance_id="allowance_1",wallet_identity_id="wallet_1",network="eip155:137",token_address=token,token_symbol="USDC",token_decimals=6,spender_address=spender,approved_amount_atomic=5_000_000,observed_allowance_atomic=5_000_000,status="active",confirmed_block=1,last_chain_check_at=now,created_at=now,updated_at=now))
    refs={"product":"marketplace","wallet_identity_id":"wallet_1","spending_grant_id":"grant_1","asset_allowance_id":"allowance_1"}
    scope={"purchase_id":"purchase","quote_hash":"0x"+"a"*64,"network":"eip155:137","asset":"USDC","amount_atomic":"1000000","destination":"0x"+"3"*40,"resource":"https://merchant.example/api","authorization_rail":"native_allowance","merchant_trust_tier":"clink_verified",**refs}
    config=AppConfig(funding_database_url=database_url)
    actions=ActionService(config=config);action=actions.create_intent(CreateActionIntentRequest(user_id="u",agent_id="hermes",action_type="marketplace_purchase",amount_usdc="1",merchant_id="merchant",metadata=scope))
    policy=PolicyService(config=config).evaluate(EvaluateActionPolicyRequest(action_id=action.action_id,user_id="u",agent_id="hermes",action_type="marketplace_purchase",amount_usdc="1",merchant_id="merchant",target_address=scope["destination"],chain=scope["network"],user_confirmed=True,metadata=scope))
    actions.update_intent(action.action_id,UpdateActionIntentRequest(state="policy_approved",policy_decision_id=policy.policy_decision_id))
    AuditService(database_url=config.funding_database_url).write_event(WriteAuditEventRequest(event_type="marketplace_purchase_policy_evaluated",source_service="clink_marketplace",action_id=action.action_id,user_id="u",agent_id="hermes",policy_decision_id=policy.policy_decision_id,payload={**scope,"merchant_id":"merchant","venue":"clink_marketplace"}))
    request=CreateSpendingReservationRequest(idempotency_key="purchase",action_id=action.action_id,policy_decision_id=policy.policy_decision_id,merchant_id="merchant",amount_usdc="1",venue="clink_marketplace",**scope)
    service=FundingService(config=config,storage_file=root/"funding.jsonl")
    service._utc_now=lambda:now.replace(tzinfo=None)

    assert service.reserve_spending(request)["authorization_path"]=="unified_grant"
    forged=request.model_copy(update={"spending_grant_id":"grant_2","purchase_id":"purchase2","idempotency_key":"purchase2"})
    with pytest.raises(ValueError,match="reference hint mismatch"):
      service.reserve_spending(forged)


@pytest.mark.parametrize(
    ("action_updates", "policy_updates", "error"),
    [
        ({"amount_usdc": "0.5"}, {}, "action scope mismatch"),
        ({}, {"amount_usdc": "0.5"}, "policy scope mismatch"),
        ({}, {"action_type": "funding_transfer"}, "policy scope mismatch"),
        ({"policy_decision_id": "policy_other"}, {}, "action scope mismatch"),
        ({"metadata": {"unexpected": "field"}}, {}, "action scope mismatch"),
    ],
)
def test_reserve_rejects_typed_provenance_mismatch(
    tmp_path, action_updates, policy_updates, error
):
    request = CreateSpendingReservationRequest(
        purchase_id="purchase",
        idempotency_key="purchase",
        spending_authorization_id="auth",
        action_id="action",
        policy_decision_id="policy",
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset="USDC",
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
    )
    scope = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
    }
    action_values = {
        "action_id": request.action_id,
        "action_type": "marketplace_purchase",
        "state": "policy_approved",
        "merchant_id": request.merchant_id,
        "user_id": "u",
        "agent_id": "hermes",
        "amount_usdc": "1.0",
        "policy_decision_id": request.policy_decision_id,
        "metadata": scope,
    }
    policy_values = {
        "policy_decision_id": request.policy_decision_id,
        "approved": True,
        "action_id": request.action_id,
        "action_type": "marketplace_purchase",
        "merchant_id": request.merchant_id,
        "user_id": "u",
        "agent_id": "hermes",
        "amount_usdc": "1.00",
        "target_address": request.destination,
        "chain": request.network,
        "metadata": scope,
    }
    action_values.update(action_updates)
    policy_values.update(policy_updates)
    event = SimpleNamespace(
        source_service="clink_marketplace",
        event_type="marketplace_purchase_policy_evaluated",
        policy_decision_id=request.policy_decision_id,
        user_id="u",
        agent_id="hermes",
        payload={**scope, "merchant_id": request.merchant_id, "venue": request.venue},
    )
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch(
        "services.funding_service.service.AuditService"
    ) as audits, patch.object(service, "get_spending_authorization", return_value=auth()):
        actions.return_value.get_intent.return_value = SimpleNamespace(**action_values)
        policies.return_value.get_decision.return_value = SimpleNamespace(**policy_values)
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        with pytest.raises(ValueError, match=error):
            service.reserve_spending(request)


@pytest.mark.parametrize(
    ("assessment", "denylist", "error"),
    [
        (
            risk_assessment(mode="shadow", enforced=False, decision="deny"),
            (),
            "risk assessment",
        ),
        (
            risk_assessment(),
            ("0x" + "3" * 40,),
            "destination is denied",
        ),
    ],
)
def test_live_funding_revalidates_policy_risk_and_current_destination_controls(
    tmp_path, assessment, denylist, error
):
    request = CreateSpendingReservationRequest(
        purchase_id="purchase",
        idempotency_key="purchase",
        spending_authorization_id="auth",
        action_id="action",
        policy_decision_id="policy",
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset=POLYGON_USDC,
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
    )
    scope = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
    }
    action = SimpleNamespace(
        action_id=request.action_id,
        action_type="marketplace_purchase",
        state="policy_approved",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        amount_usdc="1",
        policy_decision_id=request.policy_decision_id,
        metadata=scope,
    )
    policy = SimpleNamespace(
        policy_decision_id=request.policy_decision_id,
        approved=True,
        action_id=request.action_id,
        action_type="marketplace_purchase",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        amount_usdc="1",
        target_address=request.destination,
        chain=request.network,
        risk_assessment=assessment,
        event_log=[],
        metadata=scope,
    )
    event = SimpleNamespace(
        source_service="clink_marketplace",
        event_type="marketplace_purchase_policy_evaluated",
        policy_decision_id=request.policy_decision_id,
        user_id="u",
        agent_id="hermes",
        payload={**scope, "merchant_id": request.merchant_id, "venue": request.venue},
    )
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}",
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            funding_destination_denylist=denylist,
        )
    )
    service._utc_now = lambda: datetime(2026, 7, 31, 12)

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch(
        "services.funding_service.service.AuditService"
    ) as audits, pytest.raises(ValueError, match=error):
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        service._verify_marketplace_provenance(request)


def test_live_funding_accepts_an_explicitly_confirmed_risk_hold(tmp_path):
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}",
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
        )
    )
    service._utc_now = lambda: datetime(2026, 7, 31, 12)
    request = SimpleNamespace(
        destination="0x" + "3" * 40,
        network="eip155:137",
        asset=POLYGON_USDC,
    )
    policy = SimpleNamespace(
        approved=True,
        risk_assessment=risk_assessment(decision="hold"),
        event_log=[
            {
                "event": "risk_hold_confirmed",
                "created_at": "2026-07-31T11:59:50Z",
            }
        ],
    )

    service._require_fresh_misttrack_assessment(request, policy)


def test_live_funding_rejects_an_unconfirmed_risk_hold(tmp_path):
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}",
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
        )
    )
    service._utc_now = lambda: datetime(2026, 7, 31, 12)
    request = SimpleNamespace(
        destination="0x" + "3" * 40,
        network="eip155:137",
        asset=POLYGON_USDC,
    )
    policy = SimpleNamespace(
        approved=True,
        risk_assessment=risk_assessment(decision="hold"),
        event_log=[],
    )

    with pytest.raises(ValueError, match="risk assessment"):
        service._require_fresh_misttrack_assessment(request, policy)


def test_unified_action_cannot_use_legacy_authorization_path(tmp_path):
    request = CreateSpendingReservationRequest(
        purchase_id="purchase",
        idempotency_key="purchase",
        spending_authorization_id="legacy_auth",
        action_id="action",
        policy_decision_id="policy",
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset="USDC",
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
    )
    refs = {
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
        "authorization_rail": "native_allowance",
    }
    common = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
    }
    action = SimpleNamespace(
        action_id=request.action_id,
        action_type="marketplace_purchase",
        state="policy_approved",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        amount_usdc="1",
        policy_decision_id=request.policy_decision_id,
        metadata={**common, **refs},
    )
    policy = SimpleNamespace(
        policy_decision_id=request.policy_decision_id,
        approved=True,
        action_id=request.action_id,
        action_type="marketplace_purchase",
        amount_usdc="1",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        metadata={**common, **refs},
    )
    event = SimpleNamespace(
        source_service="clink_marketplace",
        event_type="marketplace_purchase_policy_evaluated",
        policy_decision_id=request.policy_decision_id,
        user_id="u",
        agent_id="hermes",
        payload={**common, **refs, "merchant_id": request.merchant_id, "venue": request.venue},
    )
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch(
        "services.funding_service.service.AuditService"
    ) as audits, patch.object(service, "get_spending_authorization", return_value=auth()):
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        with pytest.raises(ValueError, match="unified action cannot use legacy"):
            service.reserve_spending(request)


def test_external_x402_provenance_binds_rail_and_token_without_allowance(tmp_path):
    token = "0x" + "1" * 40
    request = CreateSpendingReservationRequest(
        purchase_id="purchase",
        idempotency_key="purchase",
        authorization_rail="external_x402",
        wallet_identity_id="wallet_1",
        spending_grant_id="grant_1",
        product="marketplace",
        action_id="action",
        policy_decision_id="policy",
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset="USDC",
        token_address=token,
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
    )
    scope = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
        "authorization_rail": "external_x402",
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "token_address": token,
    }
    action = SimpleNamespace(
        action_id="action",
        action_type="marketplace_purchase",
        state="policy_approved",
        merchant_id="merchant",
        user_id="u",
        agent_id="hermes",
        amount_usdc="1",
        policy_decision_id="policy",
        metadata=scope,
    )
    policy = SimpleNamespace(
        policy_decision_id="policy",
        approved=True,
        action_id="action",
        action_type="marketplace_purchase",
        amount_usdc="1",
        merchant_id="merchant",
        user_id="u",
        agent_id="hermes",
        target_address=request.destination,
        chain=request.network,
        metadata=scope,
    )
    event = SimpleNamespace(
        source_service="clink_marketplace",
        event_type="marketplace_purchase_policy_evaluated",
        policy_decision_id="policy",
        user_id="u",
        agent_id="hermes",
        payload={**scope, "merchant_id": "merchant", "venue": "clink_marketplace"},
    )
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch("services.funding_service.service.AuditService") as audits:
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        provenance = service._verify_marketplace_provenance(request)

    assert provenance.authorization_rail == "external_x402"
    assert "asset_allowance_id" not in provenance.unified_references

    forged = request.model_copy(update={"authorization_rail": "native_allowance"})
    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies:
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        with pytest.raises(ValueError, match="rail hint mismatch"):
            service._verify_marketplace_provenance(forged)


def test_legacy_authorization_cannot_reserve_after_actor_validation(tmp_path):
    request = CreateSpendingReservationRequest(
        purchase_id="purchase",
        idempotency_key="purchase",
        spending_authorization_id="legacy_auth",
        action_id="action",
        policy_decision_id="policy",
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset="USDC",
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
    )
    scope = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
    }
    action = SimpleNamespace(
        action_id=request.action_id,
        action_type="marketplace_purchase",
        state="policy_approved",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        amount_usdc="1",
        policy_decision_id=request.policy_decision_id,
        metadata=scope,
    )
    policy = SimpleNamespace(
        policy_decision_id=request.policy_decision_id,
        approved=True,
        action_id=request.action_id,
        action_type="marketplace_purchase",
        amount_usdc="1",
        merchant_id=request.merchant_id,
        user_id="u",
        agent_id="hermes",
        target_address=request.destination,
        chain=request.network,
        metadata=scope,
    )
    event = SimpleNamespace(
        source_service="clink_marketplace",
        event_type="marketplace_purchase_policy_evaluated",
        policy_decision_id=request.policy_decision_id,
        user_id="u",
        agent_id="hermes",
        payload={**scope, "merchant_id": request.merchant_id, "venue": request.venue},
    )
    mismatched = auth().model_copy(update={"user_id": "attacker"})
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'ledger.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch(
        "services.funding_service.service.AuditService"
    ) as audits, patch.object(
        service, "get_spending_authorization", return_value=mismatched
    ):
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        with pytest.raises(ValueError, match="legacy spending authorizations are read-only"):
            service.reserve_spending(request)
