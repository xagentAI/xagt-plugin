from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.action_policy_repository import ActionPolicyRepository
from services.action_service.schemas import AgentActionIntent
from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.funding_service.ledger import FundingLedger, LedgerRow
from services.funding_service.schemas import IssuePaymentCapabilityRequest
from services.funding_service.service import FundingService
from services.policy_service.schemas import PolicyDecision
from shared.config import AppConfig


NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PAYEE = "0x" + "33" * 20
EXECUTOR = "0x" + "44" * 20
WALLET = "0x" + "11" * 20
QUOTE_HASH = "0x" + "55" * 32
CHALLENGE_HASH = "0x" + "66" * 32


class PolicyStub:
    def __init__(self, policy) -> None:
        self.policy = policy

    def get_decision(self, _policy_decision_id: str):
        return self.policy


def identity(**updates) -> WalletIdentity:
    values = {
        "wallet_identity_id": "identity_1",
        "user_id": "user_1",
        "wallet_address": WALLET,
        "status": "active",
        "proof_hash": "0xproof",
        "verified_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return WalletIdentity(**values)


def grant(**updates) -> SpendingGrant:
    values = {
        "spending_grant_id": "grant_1",
        "wallet_identity_id": "identity_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "status": "active",
        "max_amount_usdc": Decimal("5"),
        "per_transaction_limit_usdc": Decimal("2"),
        "hourly_limit_usdc": Decimal("4"),
        "daily_limit_usdc": Decimal("5"),
        "used_amount_usdc": Decimal("0"),
        "reserved_amount_usdc": Decimal("1"),
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": ["merchant_1"],
        "merchant_trust_scopes": ["registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:8453"],
        "asset_scopes": [TOKEN],
        "starts_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(minutes=5),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SpendingGrant(**values)


def allowance(**updates) -> AssetAllowance:
    values = {
        "asset_allowance_id": "allowance_1",
        "wallet_identity_id": "identity_1",
        "network": "eip155:8453",
        "token_address": TOKEN,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "spender_address": EXECUTOR,
        "approved_amount_atomic": 5_000_000,
        "observed_allowance_atomic": 5_000_000,
        "status": "active",
        "confirmed_block": 100,
        "last_chain_check_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return AssetAllowance(**values)


def reservation(**updates) -> dict:
    values = {
        "reservation_id": "reservation_1",
        "purchase_id": "purchase_1",
        "idempotency_key": "reservation_idempotency_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "wallet_identity_id": "identity_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
        "product": "marketplace",
        "action_id": "action_1",
        "policy_decision_id": "policy_1",
        "merchant_id": "merchant_1",
        "merchant_trust_tier": "registry_verified",
        "quote_hash": QUOTE_HASH,
        "amount_usdc": "1",
        "amount_atomic": "1000000",
        "network": "eip155:8453",
        "asset": TOKEN,
        "token_address": TOKEN,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "spender_address": EXECUTOR,
        "destination": PAYEE,
        "resource": "https://merchant.example/resource",
        "venue": "clink_marketplace",
        "authorization_rail": "native_allowance",
        "authorization_path": "unified_grant",
        "authorization_source": "core",
        "spending_authorization_id": None,
        "single_submission": False,
        "replacement_forbidden": False,
        "budget_accounting_state": "reserved",
        "state": "spending_reserved",
        "receipt_id": None,
        "tx_hash": None,
        "settlement_transaction": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    values.update(updates)
    return values


def policy(**updates):
    values = {
        "policy_decision_id": "policy_1",
        "action_id": "action_1",
        "approved": True,
        "decision": "approved",
        "reason_code": "within_policy",
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "marketplace_purchase",
        "amount_usdc": "1",
        "merchant_id": "merchant_1",
        "target_address": PAYEE,
        "chain": "eip155:8453",
        "evaluated_at": "2026-08-25T11:59:00Z",
        "authorization_approved": True,
        "risk_assessment": {
            "provider": "misttrack",
            "provider_endpoint": "v2/risk_score",
            "mode": "enforce",
            "enforced": True,
            "mapping_version": "misttrack-policy-v1",
            "hold_score": 31,
            "deny_score": 71,
            "subject": PAYEE,
            "network": "eip155:8453",
            "asset": "USDC",
            "coin": "USDC-Base",
            "decision": "allow",
            "assessed_at": "2026-08-25T11:59:00Z",
            "expires_at": "2026-08-25T12:04:00Z",
        },
        "metadata": {
            "purchase_id": "purchase_1",
            "quote_hash": QUOTE_HASH,
            "network": "eip155:8453",
            "asset": TOKEN,
            "amount_atomic": "1000000",
            "destination": PAYEE,
            "resource": "https://merchant.example/resource",
            "authorization_rail": "native_allowance",
            "product": "marketplace",
            "wallet_identity_id": "identity_1",
            "spending_grant_id": "grant_1",
            "asset_allowance_id": "allowance_1",
            "merchant_trust_tier": "registry_verified",
        },
    }
    values.update(updates)
    return PolicyDecision(**values)


def hosted_request(**updates) -> IssuePaymentCapabilityRequest:
    values = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "executor_contract": EXECUTOR,
        "payment_challenge_hash": CHALLENGE_HASH,
    }
    values.update(updates)
    return IssuePaymentCapabilityRequest(**values)


@pytest.fixture
def context(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance())
    action_policy_repository = ActionPolicyRepository(database_url)
    action_policy_repository.create_policy_decision(policy().to_dict())
    action_policy_repository.create_action_intent(fake_action().to_dict())
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
        ),
        policy_service=PolicyStub(policy()),
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    with service.ledger.transaction() as transaction:
        transaction.put(
            "reservation",
            "reservation_1",
            reservation(),
            purchase_id="purchase_1",
            idempotency_key="reservation_idempotency_1",
            action_id="action_1",
            policy_decision_id="policy_1",
            reservation_id="reservation_1",
        )
    return repository, service


def fake_action(state: str = "policy_approved"):
    return AgentActionIntent(
        action_id="action_1",
        user_id="user_1",
        agent_id="hermes",
        action_type="marketplace_purchase",
        state=state,
        amount_usdc="1",
        merchant_id="merchant_1",
        policy_decision_id="policy_1",
        metadata=policy().metadata,
        created_at=NOW.isoformat().replace("+00:00", "Z"),
        updated_at=NOW.isoformat().replace("+00:00", "Z"),
    )


def test_issue_derives_authoritative_core_scope_and_exactly_replays(context):
    _repository, service = context
    first = service.issue_payment_capability("reservation_1", hosted_request())
    replay = service.issue_payment_capability("reservation_1", hosted_request())

    assert first == replay
    assert first.user_id == "user_1"
    assert first.wallet_identity_id == "identity_1"
    assert first.wallet_address == WALLET
    assert first.asset_contract == TOKEN
    assert first.amount_atomic == "1000000"
    assert first.pay_to == PAYEE
    assert first.network == "eip155:8453"
    assert first.executor_contract == EXECUTOR
    assert first.payment_challenge_hash == CHALLENGE_HASH
    assert first.reservation_hash == "0x767675b0702ef60ae6d0c013643b24962631c275bbb1ea7748745cb1b011950d"
    assert first.expires_at - first.issued_at <= 60


def test_issue_request_cannot_select_core_owned_fields() -> None:
    with pytest.raises(ValueError, match="extra"):
        hosted_request(amount_atomic="999")


def test_policy_projection_without_optional_event_fields_is_normalized() -> None:
    projected = SimpleNamespace(
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
        chain="eip155:8453",
        risk_assessment=None,
        metadata={},
    )

    normalized = FundingService._payment_capability_policy(projected)

    assert normalized.approved is True
    assert normalized.policy_decision_id == "policy_1"


def test_issue_rejects_amount_above_executor_uint256(context):
    _repository, service = context
    with service.ledger.sessions.begin() as session:
        row = session.get(LedgerRow, "reservation_1")
        payload = dict(row.payload)
        payload["amount_atomic"] = str(2**256)
        row.payload = payload

    with pytest.raises(ValueError, match="uint256"):
        service.issue_payment_capability("reservation_1", hosted_request())


def test_issue_rejects_wrong_executor_and_wrong_replay_identity(context):
    _repository, service = context
    with pytest.raises(ValueError, match="executor|spender"):
        service.issue_payment_capability(
            "reservation_1",
            hosted_request(executor_contract="0x" + "99" * 20),
        )
    first = service.issue_payment_capability("reservation_1", hosted_request())
    with pytest.raises(
        ValueError, match="tenant|binding|conflict|immutable|scope|authority"
    ):
        service.issue_payment_capability(
            "reservation_1", hosted_request(tenant_id="tenant_2")
        )
    assert first.tenant_id == "tenant_1"


@pytest.mark.parametrize("state", ["released", "payment_submitted", "settled"])
def test_issue_rejects_non_reserved_lifecycle(context, state):
    _repository, service = context
    with service.ledger.transaction() as transaction:
        current = transaction.get("reservation_1")
        current["state"] = state
        current["budget_accounting_state"] = (
            "released" if state == "released" else "settled"
        )
        transaction.put(
            "reservation",
            "reservation_1",
            current,
            purchase_id="purchase_1",
            idempotency_key="reservation_idempotency_1",
            action_id="action_1",
            policy_decision_id="policy_1",
            reservation_id="reservation_1",
        )

    with pytest.raises(ValueError, match="reserved|state|submission|settled"):
        service.issue_payment_capability("reservation_1", hosted_request())


def test_expired_capability_is_terminal_and_never_replaced(context):
    _repository, service = context
    first = service.issue_payment_capability("reservation_1", hosted_request())
    service._utc_now = lambda: (NOW + timedelta(minutes=6)).replace(tzinfo=None)
    with pytest.raises(ValueError, match="expired|terminal"):
        service.issue_payment_capability("reservation_1", hosted_request())

    with service.ledger.transaction() as transaction:
        stored = transaction.payment_capability_for_reservation("reservation_1")
    assert stored == first


def test_issue_requires_action_policy_decision_id(context):
    _repository, service = context
    action_policy_repository = ActionPolicyRepository(service.config.funding_database_url)
    action_policy_repository.update_action_intent(
        "action_1",
        lambda payload: {**payload, "policy_decision_id": None},
    )

    with pytest.raises(ValueError, match="policy"):
        service.issue_payment_capability("reservation_1", hosted_request())


def test_nonexpired_replay_rejects_mutated_spending_grant_authority(context):
    repository, service = context
    first = service.issue_payment_capability("reservation_1", hosted_request())

    repository.reduce_spending_grant(
        "grant_1",
        NOW,
        per_transaction_limit_usdc=Decimal("1.5"),
    )

    with pytest.raises(ValueError, match="authority|immutable|conflict|mismatch"):
        service.issue_payment_capability("reservation_1", hosted_request())

    with service.ledger.transaction() as transaction:
        stored = transaction.payment_capability_for_reservation("reservation_1")
    assert stored == first


def test_nonexpired_replay_rejects_mutated_action_authority(context):
    _repository, service = context
    first = service.issue_payment_capability("reservation_1", hosted_request())
    action_policy_repository = ActionPolicyRepository(service.config.funding_database_url)
    action_policy_repository.update_action_intent(
        "action_1",
        lambda payload: {**payload, "amount_usdc": "1.5"},
    )

    with pytest.raises(ValueError, match="action|scope|mismatch"):
        service.issue_payment_capability("reservation_1", hosted_request())

    with service.ledger.transaction() as transaction:
        stored = transaction.payment_capability_for_reservation("reservation_1")
    assert stored == first
