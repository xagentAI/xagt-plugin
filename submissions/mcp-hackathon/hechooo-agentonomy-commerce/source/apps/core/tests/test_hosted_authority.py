from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from services.funding_service.service import FundingService
from services.funding_service.schemas import (
    HostedExecutionAuthorityRequest,
    HostedPreflightAuthorityRequest,
)
from shared.payment_capability import PaymentCapabilityV1


HASH = "0x" + "44" * 32
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913".lower()
EXECUTOR = "0x" + "33" * 20
RELAYER = "0x" + "55" * 20


def capability() -> PaymentCapabilityV1:
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
        network="eip155:8453",
        asset_contract=TOKEN,
        amount_atomic="1000000",
        pay_to=PAYEE,
        executor_contract=EXECUTOR,
        execution_scope_hash=HASH,
        confirmation_mode="user_approved",
        revocation_id=HASH,
        issued_at=100,
        expires_at=160,
    )


class Transaction:
    def __init__(self, row: dict, cap: PaymentCapabilityV1, lifecycle_error=None) -> None:
        self.row = row
        self.cap = cap
        self.lifecycle_error = lifecycle_error

    def get(self, _reservation_id: str) -> dict:
        return dict(self.row)

    def payment_capability_for_reservation(self, _reservation_id: str):
        return self.cap

    def validate_unified_lifecycle(self, _row: dict, *, now):
        if self.lifecycle_error is not None:
            raise self.lifecycle_error
        return (None, None, None)


class Ledger:
    def __init__(self, row: dict, cap: PaymentCapabilityV1, lifecycle_error=None) -> None:
        self.transaction_value = Transaction(row, cap, lifecycle_error)

    @contextmanager
    def transaction(self):
        yield self.transaction_value


def row(cap: PaymentCapabilityV1, *, state: str = "spending_reserved") -> dict:
    return {
        "reservation_id": cap.reservation_id,
        "purchase_id": cap.purchase_id,
        "idempotency_key": "idempotency_1",
        "action_id": cap.action_id,
        "policy_decision_id": cap.policy_decision_id,
        "quote_hash": cap.quote_hash,
        "merchant_id": cap.merchant_id,
        "state": state,
        "budget_accounting_state": "reserved",
        "authorization_path": "unified_grant",
        "wallet_identity_id": cap.wallet_identity_id,
        "spending_grant_id": cap.spending_grant_id,
        "authorization_rail": "native_allowance",
        "product": "marketplace",
        "network": "eip155:8453",
        "token_address": TOKEN,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "amount_atomic": cap.amount_atomic,
        "destination": cap.pay_to,
        "asset_allowance_id": cap.asset_allowance_id,
        "spender_address": EXECUTOR,
        "single_submission": False,
        "replacement_forbidden": False,
        "hosted_request_id": "request_1",
        "hosted_request_hash": HASH,
        "hosted_request_nonce": HASH,
    }


def request(cap: PaymentCapabilityV1) -> HostedExecutionAuthorityRequest:
    return HostedExecutionAuthorityRequest(
        tenant_id=cap.tenant_id,
        node_id=cap.node_id,
        wallet_binding_id=cap.wallet_binding_id,
        capability_id=cap.capability_id,
        capability_hash=cap.capability_hash,
        reservation_id=cap.reservation_id,
        reservation_hash=cap.reservation_hash,
        purchase_id=cap.purchase_id,
        request_id="request_1",
        request_hash=HASH,
        request_nonce=HASH,
        idempotency_key="idempotency_1",
        chain_id="eip155:8453",
        owner=cap.wallet_address,
        payee=cap.pay_to,
        token=cap.asset_contract,
        amount_atomic=cap.amount_atomic,
        executor=cap.executor_contract,
        signer_epoch=1,
        deadline=cap.expires_at,
        execution_scope_hash=cap.execution_scope_hash,
        execution_digest=HASH,
        relayer_address=RELAYER,
        payment_challenge_hash=cap.payment_challenge_hash,
    )


def preflight_request(cap: PaymentCapabilityV1) -> HostedPreflightAuthorityRequest:
    return HostedPreflightAuthorityRequest(
        protocol_version="clink-hosted-v1",
        audience="hosted-facilitator",
        http_method="POST",
        http_path="/v1/preflight",
        request_id="request_1",
        request_hash=HASH,
        idempotency_key="idempotency_1",
        tenant_id=cap.tenant_id,
        node_id=cap.node_id,
        wallet_binding_id=cap.wallet_binding_id,
        payment_capability_version=cap.capability_version,
        payment_capability_id=cap.capability_id,
        payment_capability_hash=cap.capability_hash,
        wallet_identity_id=cap.wallet_identity_id,
        wallet_address=cap.wallet_address,
        spending_grant_id=cap.spending_grant_id,
        spending_grant_hash=cap.spending_grant_hash,
        asset_allowance_id=cap.asset_allowance_id,
        reservation_id=cap.reservation_id,
        reservation_hash=cap.reservation_hash,
        action_id=cap.action_id,
        policy_decision_id=cap.policy_decision_id,
        policy_snapshot_hash=cap.policy_snapshot_hash,
        risk_evidence_hash=cap.risk_evidence_hash,
        purchase_id=cap.purchase_id,
        merchant_id=cap.merchant_id,
        quote_hash=cap.quote_hash,
        payment_challenge_hash=cap.payment_challenge_hash,
        chain_id=cap.network,
        asset_contract=cap.asset_contract,
        amount_atomic=cap.amount_atomic,
        pay_to=cap.pay_to,
        executor_contract=cap.executor_contract,
        execution_scope_hash=cap.execution_scope_hash,
        request_nonce=HASH,
        issued_at=cap.issued_at,
        expires_at=cap.expires_at,
    )


def service_for(cap: PaymentCapabilityV1, *, state: str = "spending_reserved") -> FundingService:
    service = FundingService.__new__(FundingService)
    service.ledger = Ledger(row(cap, state=state), cap)
    service._utc_now = lambda: datetime.fromtimestamp(120, tz=UTC)
    return service


def service_for_with_lifecycle_error(cap: PaymentCapabilityV1, error: Exception) -> FundingService:
    service = FundingService.__new__(FundingService)
    service.ledger = Ledger(row(cap), cap, lifecycle_error=error)
    service._utc_now = lambda: datetime.fromtimestamp(120, tz=UTC)
    return service


def test_core_preflight_returns_durable_scope_without_execution_binding_or_mutation() -> None:
    cap = capability()
    service = service_for(cap)
    service.ledger.transaction_value.row.pop("hosted_request_id", None)
    service.ledger.transaction_value.row.pop("hosted_request_hash", None)
    service.ledger.transaction_value.row.pop("hosted_request_nonce", None)

    result = service.authorize_hosted_preflight(
        cap.reservation_id, preflight_request(cap)
    )

    assert result.payment_capability_hash == cap.capability_hash
    assert result.amount_atomic == cap.amount_atomic
    assert result.payment_challenge_hash == cap.payment_challenge_hash
    assert service.ledger.transaction_value.row["state"] == "spending_reserved"


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "payment_capability_id",
        "payment_capability_hash",
        "wallet_identity_id",
        "spending_grant_id",
        "spending_grant_hash",
        "asset_allowance_id",
        "reservation_id",
        "reservation_hash",
        "action_id",
        "policy_decision_id",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "purchase_id",
        "merchant_id",
        "quote_hash",
        "payment_challenge_hash",
        "chain_id",
        "asset_contract",
        "amount_atomic",
        "pay_to",
        "executor_contract",
        "execution_scope_hash",
        "issued_at",
        "expires_at",
    ],
)
def test_core_preflight_rejects_each_capability_scope_mutation(field: str) -> None:
    cap = capability()
    service = service_for(cap)
    values = {
        "tenant_id": "tenant_other",
        "node_id": "node_other",
        "wallet_binding_id": "binding_other",
        "payment_capability_id": "capability_other",
        "payment_capability_hash": "0x" + "55" * 32,
        "wallet_identity_id": "identity_other",
        "spending_grant_id": "grant_other",
        "spending_grant_hash": "0x" + "55" * 32,
        "asset_allowance_id": "allowance_other",
        "reservation_id": "reservation_other",
        "reservation_hash": "0x" + "55" * 32,
        "action_id": "action_other",
        "policy_decision_id": "policy_other",
        "policy_snapshot_hash": "0x" + "55" * 32,
        "risk_evidence_hash": "0x" + "55" * 32,
        "purchase_id": "purchase_other",
        "merchant_id": "merchant_other",
        "quote_hash": "0x" + "55" * 32,
        "payment_challenge_hash": "0x" + "55" * 32,
        "chain_id": "eip155:137",
        "asset_contract": "0x" + "66" * 20,
        "amount_atomic": "2000000",
        "pay_to": "0x" + "66" * 20,
        "executor_contract": "0x" + "66" * 20,
        "execution_scope_hash": "0x" + "55" * 32,
        "issued_at": 101,
        "expires_at": 159,
    }
    with pytest.raises(ValueError, match="scope|reservation"):
        service.authorize_hosted_preflight(
            cap.reservation_id,
            preflight_request(cap).model_copy(update={field: values[field]}),
        )


def test_core_preflight_requires_live_lifecycle() -> None:
    cap = capability()
    service = service_for_with_lifecycle_error(
        cap, ValueError("active spending grant required before payment submission")
    )

    with pytest.raises(ValueError, match="active spending grant"):
        service.authorize_hosted_preflight(cap.reservation_id, preflight_request(cap))


def test_core_preflight_rejects_reserved_state_or_idempotency_drift() -> None:
    cap = capability()
    released = service_for(cap, state="released")
    with pytest.raises(ValueError, match="active reservation"):
        released.authorize_hosted_preflight(cap.reservation_id, preflight_request(cap))

    service = service_for(cap)
    with pytest.raises(ValueError, match="idempotency"):
        service.authorize_hosted_preflight(
            cap.reservation_id,
            preflight_request(cap).model_copy(update={"idempotency_key": "other"}),
        )


def test_core_authority_returns_durable_scope_without_mutating_reservation() -> None:
    cap = capability()
    service = service_for(cap)

    result = service.authorize_hosted_execution(cap.reservation_id, request(cap))

    assert result.capability_hash == cap.capability_hash
    assert result.amount_atomic == cap.amount_atomic
    assert result.payment_challenge_hash == cap.payment_challenge_hash
    assert service.ledger.transaction_value.row["state"] == "spending_reserved"


def test_core_authority_rejects_mutated_scope_and_stale_or_released_reservation() -> None:
    cap = capability()
    service = service_for(cap)
    with pytest.raises(ValueError, match="scope"):
        service.authorize_hosted_execution(
            cap.reservation_id,
            request(cap).model_copy(update={"amount_atomic": "2000000"}),
        )

    for state in ("released", "settled", "finalized"):
        stale = service_for(cap, state=state)
        with pytest.raises(ValueError, match="active reservation"):
            stale.authorize_hosted_execution(cap.reservation_id, request(cap))


def test_core_authority_rejects_request_binding_mutation() -> None:
    cap = capability()
    service = service_for(cap)
    with pytest.raises(ValueError, match="request binding"):
        service.authorize_hosted_execution(
            cap.reservation_id,
            request(cap).model_copy(update={"request_nonce": "0x" + "55" * 32}),
        )
