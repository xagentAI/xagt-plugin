from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_utils import keccak

from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    PrepareProxyPaymentRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
    SpendFromSpendingAuthorizationRequest,
)
from services.funding_service.service import FundingService
from shared.config import AppConfig


NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)
TARGET = "0x1111111111111111111111111111111111111111"
OTHER_TARGET = "0x2222222222222222222222222222222222222222"
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BASE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
RELAYER_KEY = "0x" + "11" * 32
RECEIPT_SIGNING_KEY = "funding-risk-gate-test-key-" + "1" * 32


def _prediction_gateway_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "prediction-markets"
        / "services"
        / "funding_adapter_service"
        / "core_gateway.py"
    )
    module_name = "_clink_test_prediction_core_gateway"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Prediction funding gateway is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _prediction_funding_context_type():
    return _prediction_gateway_module().PredictionFundingContext


class PolicyLookup:
    def __init__(self, policy):
        self.policy = policy
        self.lookups: list[str] = []

    def get_decision(self, policy_decision_id: str):
        self.lookups.append(policy_decision_id)
        return self.policy

    def evaluate(self, _request):
        raise AssertionError("Funding must not evaluate policy or call MistTrack")


class AllowanceOnlyChain:
    def __init__(self) -> None:
        self.methods: list[str] = []

    def __call__(self, _network: str, method: str, _params: list):
        self.methods.append(method)
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_call":
            return hex(10_000_000)
        raise AssertionError(f"unexpected RPC after risk expiry: {method}")


class RiskWindowChain:
    def __init__(self, *, advance_during_gas=None) -> None:
        self.methods: list[str] = []
        self.advance_during_gas = advance_during_gas
        self.block_timestamp = int(NOW.timestamp())

    def __call__(self, _network: str, method: str, params: list):
        self.methods.append(method)
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_call":
            calldata = str(params[0].get("data") or "")
            authorization_state = keccak(
                text="authorizationState(address,bytes32)"
            )[:4].hex()
            if calldata.startswith("0x" + authorization_state):
                return "0x" + "0" * 64
            return hex(10_000_000)
        if method == "eth_getTransactionCount":
            return "0x1"
        if method == "eth_gasPrice":
            if self.advance_during_gas is not None:
                self.advance_during_gas()
                self.advance_during_gas = None
            return "0x1"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(self.block_timestamp)}
        if method == "eth_sendRawTransaction":
            raise AssertionError("expired risk must block eth_sendRawTransaction")
        if method in {"eth_getTransactionReceipt", "eth_getTransactionByHash"}:
            return None
        raise AssertionError(f"unexpected RPC: {method}")


class SuccessfulNativeChain(RiskWindowChain):
    def __init__(self) -> None:
        super().__init__()
        self.sent_raw: list[str] = []
        self.transactions: dict[str, dict] = {}

    def __call__(self, network: str, method: str, params: list):
        if method == "eth_sendRawTransaction":
            self.methods.append(method)
            raw_transaction = params[0]
            transaction_hash = "0x" + keccak(
                bytes.fromhex(raw_transaction.removeprefix("0x"))
            ).hex()
            self.sent_raw.append(raw_transaction)
            self.transactions[transaction_hash] = {"hash": transaction_hash}
            return transaction_hash
        if method == "eth_getTransactionReceipt":
            self.methods.append(method)
            return None
        if method == "eth_getTransactionByHash":
            self.methods.append(method)
            return self.transactions.get(params[0])
        return super().__call__(network, method, params)


def _request() -> CreateSpendingReservationRequest:
    return CreateSpendingReservationRequest(
        purchase_id="purchase_1",
        idempotency_key="purchase_1",
        authorization_rail="native_allowance",
        wallet_identity_id="wallet_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1",
        product="marketplace",
        action_id="action_1",
        policy_decision_id="policy_1",
        merchant_id="merchant_1",
        merchant_trust_tier="registry_verified",
        quote_hash="0x" + "a" * 64,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset=TOKEN,
        destination=TARGET,
        resource="https://merchant.example/api",
        venue="clink_marketplace",
    )


def _scope(request: CreateSpendingReservationRequest) -> dict:
    scope = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
        "authorization_rail": request.authorization_rail,
        "product": request.product,
        "wallet_identity_id": request.wallet_identity_id,
        "spending_grant_id": request.spending_grant_id,
        "asset_allowance_id": request.asset_allowance_id,
    }
    if request.merchant_trust_tier is not None:
        scope["merchant_trust_tier"] = request.merchant_trust_tier
    return scope


def _risk_assessment(**updates) -> dict:
    assessment = {
        "provider": "misttrack",
        "provider_endpoint": "v2/risk_score",
        "subject": TARGET,
        "network": "eip155:137",
        "asset": "USDC",
        "coin": "USDC-Polygon",
        "score": 10,
        "risk_level": "low",
        "indicators": [],
        "risk_details": [],
        "decision": "allow",
        "mode": "enforce",
        "enforced": True,
        "mapping_version": "misttrack-policy-v1",
        "hold_score": 31,
        "deny_score": 71,
        "assessed_at": (NOW - timedelta(seconds=30)).isoformat().replace(
            "+00:00", "Z"
        ),
        "expires_at": (NOW + timedelta(seconds=270)).isoformat().replace(
            "+00:00", "Z"
        ),
        "cache_hit": False,
        "response_sha256": "a" * 64,
    }
    assessment.update(updates)
    return assessment


def _bound_policy(
    request: CreateSpendingReservationRequest,
    *,
    assessment: dict | None = None,
    event_log: list[dict] | None = None,
):
    return SimpleNamespace(
        policy_decision_id=request.policy_decision_id,
        approved=True,
        decision="approved",
        action_id=request.action_id,
        action_type=(
            "funding_transfer"
            if request.product == "prediction_markets"
            else "marketplace_purchase"
        ),
        merchant_id=request.merchant_id,
        user_id="user_1",
        agent_id="hermes",
        amount_usdc=request.amount_usdc,
        target_address=request.destination,
        chain=request.network,
        risk_assessment=assessment,
        credit_model_assessment=None,
        event_log=event_log or [],
        metadata=_scope(request),
    )


def _action_and_audit(request: CreateSpendingReservationRequest):
    scope = _scope(request)
    is_prediction = request.product == "prediction_markets"
    action = SimpleNamespace(
        action_id=request.action_id,
        action_type="funding_transfer" if is_prediction else "marketplace_purchase",
        state="policy_approved",
        merchant_id=request.merchant_id,
        user_id="user_1",
        agent_id="hermes",
        amount_usdc=request.amount_usdc,
        policy_decision_id=request.policy_decision_id,
        metadata=scope,
    )
    event = SimpleNamespace(
        source_service=(
            "clink_prediction_markets" if is_prediction else "clink_marketplace"
        ),
        event_type=(
            "prediction_market_funding_policy_evaluated"
            if is_prediction
            else "marketplace_purchase_policy_evaluated"
        ),
        policy_decision_id=request.policy_decision_id,
        user_id="user_1",
        agent_id="hermes",
        payload={
            **scope,
            "merchant_id": request.merchant_id,
            "venue": request.venue,
        },
    )
    return action, event


def _service(tmp_path, lookup: PolicyLookup, *, rpc_transport=None) -> FundingService:
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        clink_live_funding=True,
        clink_native_facilitator_enabled=True,
        clink_native_facilitator_relayer_private_key=RELAYER_KEY,
        clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        clink_polygon_usdc_address=TOKEN,
        clink_polygon_spender_address=Account.from_key(RELAYER_KEY).address,
        x402_payment_token_address=TOKEN,
        risk_mode="enforce",
        misttrack_api_key="test-key",
        risk_max_age_seconds=300,
    )
    service = FundingService(
        config=config,
        storage_file=tmp_path / "funding.jsonl",
        policy_service=lookup,
        rpc_transport=rpc_transport,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    return service


def _reserve_through_gate(service: FundingService, request):
    action, event = _action_and_audit(request)
    with patch(
        "services.funding_service.service.ActionService"
    ) as action_service, patch(
        "services.funding_service.service.AuditService"
    ) as audit_service, patch(
        "services.funding_service.service.PolicyService",
        side_effect=AssertionError("Funding must use its injected policy service"),
    ), patch.object(
        service,
        "_reserve_unified_spending",
        return_value={"state": "spending_reserved"},
    ):
        action_service.return_value.get_intent.return_value = action
        audit_service.return_value.get_trail.return_value = SimpleNamespace(
            events=[event]
        )
        return service.reserve_spending(request)


def _reserve_persisted(service: FundingService, request):
    action, event = _action_and_audit(request)
    with patch(
        "services.funding_service.service.ActionService"
    ) as action_service, patch(
        "services.funding_service.service.AuditService"
    ) as audit_service:
        action_service.return_value.get_intent.return_value = action
        audit_service.return_value.get_trail.return_value = SimpleNamespace(
            events=[event]
        )
        return service.reserve_spending(request)


def _proxy_requirement(request: CreateSpendingReservationRequest):
    return PrepareProxyPaymentRequest(
        payment_requirement={
            "scheme": "exact",
            "network": request.network,
            "asset": TOKEN,
            "amount_atomic": request.amount_atomic,
            "pay_to": request.destination,
            "resource": request.resource,
            "token_name": "USD Coin",
            "token_version": "2",
        }
    )


def _native_settlement_request(
    request: CreateSpendingReservationRequest,
    *,
    amount_atomic: str | None = None,
) -> SettleSpendingReservationRequest:
    return SettleSpendingReservationRequest(
        payment_authorization={
            "scheme": "exact",
            "network": request.network,
            "asset": request.asset,
            "amount_atomic": amount_atomic or request.amount_atomic,
            "pay_to": request.destination,
        }
    )


def test_live_funding_accepts_fresh_bound_allow_and_uses_injected_lookup(tmp_path):
    request = _request()
    lookup = PolicyLookup(_bound_policy(request, assessment=_risk_assessment()))
    service = _service(tmp_path, lookup)

    assert _reserve_through_gate(service, request)["state"] == "spending_reserved"
    assert lookup.lookups == [request.policy_decision_id]


def test_real_prediction_context_reserves_polygon_canonical_usdc_under_live_risk(
    tmp_path,
):
    context = _prediction_funding_context_type()(
        user_id="user_1",
        agent_id="hermes",
        operation_id="purchase_1",
        idempotency_key="purchase_1",
        resource="polymarket:funding:demo",
        wallet_identity_id="wallet_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1",
        amount_usdc="1",
        amount_atomic="1000000",
        token_address=TOKEN,
        destination=TARGET,
        quote_hash="0x" + "a" * 64,
    )
    request = _request().model_copy(
        update={
            "purchase_id": context.operation_id,
            "idempotency_key": context.idempotency_key,
            "product": "prediction_markets",
            "merchant_id": "polymarket",
            "merchant_trust_tier": "clink_verified",
            "asset": context.provenance["asset"],
            "destination": context.destination,
            "resource": context.resource,
            "venue": "polymarket",
        }
    )
    assert _scope(request) == context.provenance

    lookup = PolicyLookup(_bound_policy(request, assessment=_risk_assessment()))
    service = _service(tmp_path, lookup)
    _seed_authorization(service, request)

    reserved = _reserve_persisted(service, request)

    assert reserved["state"] == "spending_reserved"
    assert reserved["asset"] == TOKEN
    assert reserved["token_address"] == TOKEN


@pytest.mark.parametrize(
    "asset",
    [
        "USDC",
        "0x2222222222222222222222222222222222222222",
        BASE_TOKEN,
    ],
    ids=("symbol-not-token", "noncanonical-token", "base-token-on-polygon"),
)
def test_live_risk_gate_rejects_noncanonical_polygon_scope_asset(tmp_path, asset):
    request = _request().model_copy(update={"asset": asset})
    lookup = PolicyLookup(_bound_policy(request, assessment=_risk_assessment()))
    service = _service(tmp_path, lookup)

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(service, request)


@pytest.mark.parametrize(
    "assessment",
    [
        None,
        _risk_assessment(provider="alvin_legacy"),
        _risk_assessment(provider_endpoint="v1/decision"),
        _risk_assessment(mode="shadow"),
        _risk_assessment(enforced=False),
        _risk_assessment(mapping_version="misttrack-policy-v0"),
        _risk_assessment(hold_score=30),
        _risk_assessment(deny_score=70),
        _risk_assessment(hold_score=True),
        _risk_assessment(subject=OTHER_TARGET),
        _risk_assessment(network="eip155:8453"),
        _risk_assessment(asset="ETH"),
        _risk_assessment(coin="USDC-Base"),
        _risk_assessment(decision="deny"),
        _risk_assessment(decision="unavailable"),
        _risk_assessment(assessed_at="not-a-timestamp"),
        _risk_assessment(assessed_at="2026-07-31T11:59:30"),
        _risk_assessment(assessed_at="2026-07-31T12:00:01Z"),
        _risk_assessment(
            assessed_at="2026-07-31T11:59:30Z",
            expires_at="2026-07-31T11:59:30Z",
        ),
        _risk_assessment(expires_at="2026-07-31T12:00:00Z"),
        _risk_assessment(
            assessed_at="2026-07-31T11:54:59Z",
            expires_at="2026-07-31T12:00:01Z",
        ),
    ],
    ids=[
        "missing",
        "wrong-provider",
        "wrong-endpoint",
        "shadow",
        "not-enforced",
        "wrong-version",
        "wrong-hold-score",
        "wrong-deny-score",
        "noninteger-hold-score",
        "wrong-subject",
        "wrong-network",
        "wrong-asset",
        "wrong-coin",
        "deny",
        "unavailable",
        "malformed-time",
        "naive-time",
        "future-time",
        "nonpositive-window",
        "expired",
        "over-max-age",
    ],
)
def test_live_funding_rejects_untrusted_or_stale_risk_assessment(
    tmp_path, assessment
):
    request = _request()
    lookup = PolicyLookup(_bound_policy(request, assessment=assessment))
    service = _service(tmp_path, lookup)

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(service, request)


def test_live_funding_rejects_legacy_alvin_allow_without_current_risk(tmp_path):
    request = _request()
    policy = _bound_policy(request, assessment=None)
    policy.credit_model_assessment = {
        "mode": "enforce",
        "enforced": True,
        "decision": "allow",
    }
    service = _service(tmp_path, PolicyLookup(policy))

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(service, request)


def test_live_funding_rejects_risk_assessment_without_threshold_provenance(tmp_path):
    request = _request()
    assessment = _risk_assessment()
    assessment.pop("hold_score")
    assessment.pop("deny_score")
    service = _service(
        tmp_path,
        PolicyLookup(_bound_policy(request, assessment=assessment)),
    )

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(service, request)


def test_live_funding_rejects_noncanonical_destination_even_when_policy_matches(
    tmp_path,
):
    request = _request().model_copy(
        update={"destination": "0xAa11111111111111111111111111111111111111"}
    )
    assessment = _risk_assessment(subject=request.destination)
    lookup = PolicyLookup(_bound_policy(request, assessment=assessment))
    service = _service(tmp_path, lookup)

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(service, request)


def test_live_funding_accepts_hold_only_with_confirmation_on_same_policy(tmp_path):
    request = _request()
    confirmed = PolicyLookup(
        _bound_policy(
            request,
            assessment=_risk_assessment(decision="hold", score=31, risk_level="moderate"),
            event_log=[
                {
                    "event": "risk_hold_confirmed",
                    "created_at": "2026-07-31T11:59:50Z",
                }
            ],
        )
    )
    service = _service(tmp_path, confirmed)
    assert _reserve_through_gate(service, request)["state"] == "spending_reserved"

    unconfirmed = PolicyLookup(
        _bound_policy(
            request,
            assessment=_risk_assessment(decision="hold", score=31, risk_level="moderate"),
        )
    )
    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(_service(tmp_path, unconfirmed), request)


@pytest.mark.parametrize(
    "confirmation",
    [
        {"event": "risk_hold_confirmed"},
        {
            "event": "risk_hold_confirmed",
            "created_at": "2026-07-31T11:59:50",
        },
        {
            "event": "risk_hold_confirmed",
            "created_at": "2026-07-31T11:59:29Z",
        },
        {
            "event": "risk_hold_confirmed",
            "created_at": "2026-07-31T12:00:01Z",
        },
        {
            "event": "risk_hold_confirmed",
            "created_at": "2026-07-31T11:59:50Z",
            "unexpected": True,
        },
    ],
    ids=["missing-time", "naive-time", "before-assessment", "future", "extra-field"],
)
def test_live_funding_rejects_noncanonical_hold_confirmation(
    tmp_path, confirmation
):
    request = _request()
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(
            decision="hold", score=31, risk_level="moderate"
        ),
        event_log=[confirmation],
    )

    with pytest.raises(ValueError, match="risk assessment"):
        _reserve_through_gate(_service(tmp_path, PolicyLookup(policy)), request)


def _seed_authorization(
    service: FundingService, request: CreateSpendingReservationRequest | None = None
) -> None:
    request = request or _request()
    repository = AccountRepository(service.config.funding_database_url)
    relayer = Account.from_key(RELAYER_KEY).address.lower()
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_1",
            user_id="user_1",
            wallet_address="0x" + "4" * 40,
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
            wallet_identity_id="wallet_1",
            user_id="user_1",
            agent_id="hermes",
            status="active",
            max_amount_usdc=Decimal("5"),
            per_transaction_limit_usdc=Decimal("2"),
            hourly_limit_usdc=Decimal("5"),
            daily_limit_usdc=Decimal("5"),
            product_scopes=[request.product],
            venue_scopes=[request.venue],
            merchant_scopes=[request.merchant_id],
            merchant_trust_scopes=(
                [request.merchant_trust_tier]
                if request.merchant_trust_tier is not None
                else ["registry_verified"]
            ),
            network_scopes=["eip155:137"],
            asset_scopes=[TOKEN],
            starts_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=1),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_asset_allowance(
        AssetAllowance(
            asset_allowance_id="allowance_1",
            wallet_identity_id="wallet_1",
            network="eip155:137",
            token_address=TOKEN,
            token_symbol="USDC",
            token_decimals=6,
            spender_address=relayer,
            approved_amount_atomic=10_000_000,
            observed_allowance_atomic=10_000_000,
            status="active",
            confirmed_block=1,
            last_chain_check_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )


def test_proxy_authorization_is_policy_rechecked_capped_and_rechecked_on_rotation(
    tmp_path,
):
    request = _request().model_copy(
        update={"authorization_rail": "clink_payer_proxy"}
    )
    lookup = PolicyLookup(_bound_policy(request, assessment=_risk_assessment()))
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)

    first = service.prepare_proxy_payment(
        reservation["reservation_id"], _proxy_requirement(request)
    )

    assert lookup.lookups == [request.policy_decision_id] * 2
    assert int(first["proxy_valid_before"]) == int(
        (NOW + timedelta(seconds=270)).timestamp()
    )
    assert first["payment_payload"]["payload"]["authorization"][
        "validBefore"
    ] == first["proxy_valid_before"]

    with service.ledger.transaction() as tx:
        current = tx.get(reservation["reservation_id"])
        expired = {
            **current,
            "proxy_valid_before": str(int(NOW.timestamp()) - 1),
        }
        service._put_reservation(tx, expired)

    rotated = service.prepare_proxy_payment(
        reservation["reservation_id"], _proxy_requirement(request)
    )

    assert lookup.lookups == [request.policy_decision_id] * 3
    assert rotated["proxy_nonce"] != first["proxy_nonce"]
    assert int(rotated["proxy_valid_before"]) == int(
        (NOW + timedelta(seconds=270)).timestamp()
    )


def test_proxy_authorization_fails_closed_if_risk_expires_before_signing(tmp_path):
    request = _request().model_copy(
        update={"authorization_rail": "clink_payer_proxy"}
    )
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    lookup = PolicyLookup(policy)
    service = _service(tmp_path, lookup, rpc_transport=RiskWindowChain())
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)
    service._utc_now = lambda: (NOW + timedelta(seconds=31)).replace(tzinfo=None)

    with patch(
        "services.funding_service.service.Account.sign_message",
        side_effect=AssertionError("expired risk must block proxy signing"),
    ) as sign_message, pytest.raises(ValueError, match="risk assessment"):
        service.prepare_proxy_payment(
            reservation["reservation_id"], _proxy_requirement(request)
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("proxy_nonce") is None
    assert persisted.get("payment_payload") is None
    assert lookup.lookups == [request.policy_decision_id] * 2
    sign_message.assert_not_called()


def test_native_risk_expiry_during_transaction_build_rolls_back_before_send(
    tmp_path,
):
    request = _request()
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    lookup = PolicyLookup(policy)
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    chain.advance_during_gas = lambda: setattr(
        service,
        "_utc_now",
        lambda: (NOW + timedelta(seconds=31)).replace(tzinfo=None),
    )
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)

    with pytest.raises(ValueError, match="risk assessment"):
        service.settle_reservation(
            reservation["reservation_id"],
            SettleSpendingReservationRequest(
                payment_authorization={
                    "scheme": "exact",
                    "network": request.network,
                    "asset": request.asset,
                    "amount_atomic": request.amount_atomic,
                    "pay_to": request.destination,
                }
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("settlement_nonce") is None
    assert persisted.get("tx_hash") is None
    assert "eth_sendRawTransaction" not in chain.methods

    reconciled = service.reconcile_reservation(reservation["reservation_id"])
    assert reconciled["state"] == "spending_reserved"
    assert "eth_sendRawTransaction" not in chain.methods


def test_actual_native_send_boundary_rechecks_risk_and_isolates_nonce(tmp_path):
    request = _request()
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    service_box = {}

    class BoundaryLookup(PolicyLookup):
        def get_decision(self, policy_decision_id: str):
            result = super().get_decision(policy_decision_id)
            if len(self.lookups) == 5:
                service_box["service"]._utc_now = lambda: (
                    NOW + timedelta(seconds=31)
                ).replace(tzinfo=None)
            return result

    lookup = BoundaryLookup(policy)
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    service_box["service"] = service
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)

    with pytest.raises(ValueError, match="risk assessment"):
        service.settle_reservation(
            reservation["reservation_id"],
            SettleSpendingReservationRequest(
                payment_authorization={
                    "scheme": "exact",
                    "network": request.network,
                    "asset": request.asset,
                    "amount_atomic": request.amount_atomic,
                    "pay_to": request.destination,
                }
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "payment_submitted"
    assert persisted["budget_accounting_state"] == "reserved"
    assert persisted["risk_prebroadcast_blocked"] is True
    assert persisted["reconciliation_status"] == "manual_review_required"
    assert persisted["settlement_nonce"] == 1
    assert persisted["settlement_sender"] is not None
    assert persisted["tx_hash"].startswith("0x")
    assert persisted["settlement_transaction"]["nonce"] == 1
    assert "eth_sendRawTransaction" not in chain.methods

    service.reconcile_reservation(reservation["reservation_id"])
    assert "eth_sendRawTransaction" not in chain.methods


def test_prediction_gateway_accepts_actual_core_prebroadcast_rows(tmp_path):
    request = _request().model_copy(
        update={
            "product": "prediction_markets",
            "venue": "polymarket",
            "merchant_id": "polymarket",
            "merchant_trust_tier": "clink_verified",
            "resource": "polymarket:funding:demo",
        }
    )
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    lookup = PolicyLookup(policy)
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)
    observed: dict[str, dict] = {}
    authorize = service._authorize_native_broadcast

    def capture_prebroadcast_rows(row):
        observed["pending"] = service.get_reservation(row["reservation_id"])
        ready = authorize(row)
        observed["ready"] = service.get_reservation(row["reservation_id"])
        service._utc_now = lambda: (NOW + timedelta(seconds=31)).replace(
            tzinfo=None
        )
        return ready

    service._authorize_native_broadcast = capture_prebroadcast_rows
    with pytest.raises(ValueError, match="risk assessment"):
        service.settle_reservation(
            reservation["reservation_id"],
            _native_settlement_request(request),
        )
    observed["blocked"] = service.get_reservation(reservation["reservation_id"])

    parser = _prediction_gateway_module()._reservation
    serialized = {
        stage: json.loads(json.dumps(row))
        for stage, row in {"reserved": reservation, **observed}.items()
    }
    parsed = {
        stage: parser(row, reservation_id=reservation["reservation_id"])
        for stage, row in serialized.items()
    }

    assert not any(
        key.startswith("risk_prebroadcast_") for key in parsed["reserved"]
    )
    assert parsed["pending"]["risk_prebroadcast_state"] == "pending"
    assert parsed["ready"]["risk_prebroadcast_state"] == "ready"
    assert parsed["blocked"]["risk_prebroadcast_state"] == "blocked"
    assert parsed["blocked"]["risk_prebroadcast_blocked"] is True
    assert parsed["blocked"]["reconciliation_status"] == "manual_review_required"
    assert parsed["blocked"]["next_action"] == "operator_reconcile"
    assert "eth_sendRawTransaction" not in chain.methods


@pytest.mark.parametrize("operator_reconcile", [False, True], ids=["normal", "operator"])
def test_concurrent_reconcile_cannot_broadcast_while_final_risk_check_blocks(
    tmp_path,
    operator_reconcile,
):
    request = _request()
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    final_lookup_started = Event()
    allow_final_lookup_to_return = Event()
    service_box = {}

    class BarrierLookup(PolicyLookup):
        def get_decision(self, policy_decision_id: str):
            result = super().get_decision(policy_decision_id)
            if len(self.lookups) == 4:
                service_box["service"]._utc_now = lambda: (
                    NOW + timedelta(seconds=31)
                ).replace(tzinfo=None)
                final_lookup_started.set()
                if not allow_final_lookup_to_return.wait(timeout=5):
                    raise AssertionError("final risk lookup barrier timed out")
            return result

    lookup = BarrierLookup(policy)
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    service_box["service"] = service
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)
    settlement = _native_settlement_request(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        settle_future = executor.submit(
            service.settle_reservation,
            reservation["reservation_id"],
            settlement,
        )
        try:
            assert final_lookup_started.wait(timeout=5)
            pending = service.get_reservation(reservation["reservation_id"])
            reconcile_future = executor.submit(
                service.reconcile_reservation,
                reservation["reservation_id"],
                operator_reconcile=operator_reconcile,
            )
            concurrent_result = reconcile_future.result(timeout=5)
        finally:
            allow_final_lookup_to_return.set()
        with pytest.raises(ValueError, match="risk assessment"):
            settle_future.result(timeout=5)

    assert chain.methods.count("eth_sendRawTransaction") == 0
    assert pending["risk_prebroadcast_state"] == "pending"
    assert concurrent_result["risk_prebroadcast_state"] == "pending"

    isolated = service.get_reservation(reservation["reservation_id"])
    assert isolated["state"] == "payment_submitted"
    assert isolated["risk_prebroadcast_state"] == "blocked"
    assert isolated["risk_prebroadcast_blocked"] is True
    assert isolated["reconciliation_status"] == "manual_review_required"
    assert isolated["budget_accounting_state"] == "reserved"
    canonical_identity = (
        isolated["settlement_nonce"],
        isolated["tx_hash"],
        isolated["settlement_transaction"],
    )

    assert service.settle_reservation(
        reservation["reservation_id"], settlement
    ) == isolated
    assert service.reconcile_reservation(reservation["reservation_id"]) == isolated
    assert service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    ) == isolated
    with pytest.raises(ValueError, match="cannot be released"):
        service.release_reservation(
            reservation["reservation_id"],
            ReleaseSpendingReservationRequest(reason="risk expired"),
        )
    with pytest.raises(ValueError, match="different payment authorization"):
        service.settle_reservation(
            reservation["reservation_id"],
            _native_settlement_request(request, amount_atomic="999999"),
        )

    unchanged = service.get_reservation(reservation["reservation_id"])
    assert unchanged["budget_accounting_state"] == "reserved"
    assert (
        unchanged["settlement_nonce"],
        unchanged["tx_hash"],
        unchanged["settlement_transaction"],
    ) == canonical_identity
    assert chain.methods.count("eth_sendRawTransaction") == 0


@pytest.mark.parametrize("operator_reconcile", [False, True], ids=["normal", "operator"])
def test_exact_native_rebroadcast_rechecks_risk_immediately_before_send(
    tmp_path,
    operator_reconcile,
):
    request = _request()
    lookup = PolicyLookup(
        _bound_policy(request, assessment=_risk_assessment())
    )
    chain = SuccessfulNativeChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)

    pending = service.settle_reservation(
        reservation["reservation_id"], _native_settlement_request(request)
    )
    assert pending["state"] == "payment_submitted"
    assert len(chain.sent_raw) == 1

    chain.transactions.clear()
    service._utc_now = lambda: (NOW + timedelta(seconds=271)).replace(tzinfo=None)
    blocked = service.reconcile_reservation(
        reservation["reservation_id"],
        operator_reconcile=operator_reconcile,
    )

    assert len(chain.sent_raw) == 1
    assert blocked["state"] == "payment_submitted"
    assert blocked["risk_prebroadcast_state"] == "blocked"
    assert blocked["risk_prebroadcast_blocked"] is True
    assert blocked["reconciliation_status"] == "manual_review_required"
    assert blocked["budget_accounting_state"] == "reserved"


def test_prediction_prebroadcast_risk_failure_isolates_signed_transaction(
    tmp_path,
):
    request = _request().model_copy(
        update={
            "product": "prediction_markets",
            "venue": "polymarket",
            "merchant_id": "polymarket",
            "merchant_trust_tier": None,
            "resource": "polymarket:funding:demo",
        }
    )
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    service_box = {}

    class BoundaryLookup(PolicyLookup):
        def get_decision(self, policy_decision_id: str):
            result = super().get_decision(policy_decision_id)
            if len(self.lookups) == 4:
                service_box["service"]._utc_now = lambda: (
                    NOW + timedelta(seconds=31)
                ).replace(tzinfo=None)
            return result

    lookup = BoundaryLookup(policy)
    chain = RiskWindowChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    service_box["service"] = service
    _seed_authorization(service, request)
    reservation = _reserve_persisted(service, request)
    assert reservation["single_submission"] is True

    with pytest.raises(ValueError, match="risk assessment"):
        service.settle_reservation(
            reservation["reservation_id"],
            SettleSpendingReservationRequest(
                payment_authorization={
                    "scheme": "exact",
                    "network": request.network,
                    "asset": request.asset,
                    "amount_atomic": request.amount_atomic,
                    "pay_to": request.destination,
                }
            ),
        )

    isolated = service.get_reservation(reservation["reservation_id"])
    assert isolated["state"] == "payment_submitted"
    assert isolated["risk_prebroadcast_blocked"] is True
    assert isolated["reconciliation_status"] == "manual_review_required"
    assert isolated["budget_accounting_state"] == "reserved"
    assert isolated["tx_hash"].startswith("0x")
    assert isolated["settlement_nonce"] == 1
    assert isolated["settlement_transaction"]["nonce"] == 1
    assert "eth_sendRawTransaction" not in chain.methods

    assert service.reconcile_reservation(reservation["reservation_id"]) == isolated
    assert service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    ) == isolated
    assert "eth_sendRawTransaction" not in chain.methods


def test_risk_expiry_between_reservation_and_first_settlement_blocks_before_nonce(
    tmp_path,
):
    request = _request()
    policy = _bound_policy(
        request,
        assessment=_risk_assessment(expires_at="2026-07-31T12:00:30Z"),
    )
    lookup = PolicyLookup(policy)
    chain = AllowanceOnlyChain()
    service = _service(tmp_path, lookup, rpc_transport=chain)
    _seed_authorization(service)
    action, event = _action_and_audit(request)
    with patch("services.funding_service.service.ActionService") as action_service, patch(
        "services.funding_service.service.AuditService"
    ) as audit_service, patch(
        "services.funding_service.service.PolicyService", return_value=lookup
    ):
        action_service.return_value.get_intent.return_value = action
        audit_service.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        reservation = service.reserve_spending(request)

    service._utc_now = lambda: (NOW + timedelta(seconds=31)).replace(tzinfo=None)
    with patch(
        "services.funding_service.service.Account.sign_transaction",
        side_effect=AssertionError("expired risk must block signing"),
    ), pytest.raises(ValueError, match="risk assessment"):
        service.settle_reservation(
            reservation["reservation_id"],
            SettleSpendingReservationRequest(
                payment_authorization={
                    "scheme": "exact",
                    "network": request.network,
                    "asset": request.asset,
                    "amount_atomic": request.amount_atomic,
                    "pay_to": request.destination,
                }
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("settlement_nonce") is None
    assert persisted.get("tx_hash") is None
    assert chain.methods == ["eth_chainId", "eth_call"]


def test_legacy_direct_spending_stops_before_policy_or_risk_lookup(tmp_path):
    lookup = PolicyLookup(None)
    service = _service(tmp_path, lookup)

    with pytest.raises(ValueError, match="legacy spending authorizations are read-only"):
        service.spend_from_spending_authorization(
            SpendFromSpendingAuthorizationRequest(
                spending_authorization_id="spend_auth_test",
                amount_usdc="1",
                destination=TARGET,
                resource="https://merchant.example/paid-resource",
            )
        )

    assert lookup.lookups == []
