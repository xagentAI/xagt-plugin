from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from multiprocessing import get_context
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql

from services.account_service.repository import (
    AccountRepository,
    SpendingGrantDailyUsageRow,
    SpendingGrantRow,
)
from services.account_service.opc_service import OpcInstallationRow
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.account_service.service import AccountService
from services.audit_service.service import AuditService
from services.funding_service.ledger import (
    FundingLedger,
    FundingTransaction,
    LockRow,
)
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    FinalizeSpendingReservationRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
    SpendFromSpendingAuthorizationRequest,
    PrepareProxyPaymentRequest,
)
from services.funding_service.service import FundingService, ReservationProvenance
from shared.config import AppConfig


NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
RECEIPT_SIGNING_KEY = "funding-receipt-test-key-" + "1" * 32
SPENDER = "0x" + "2" * 40
PAYER = "0x" + "a" * 40
DESTINATION = "0x" + "3" * 40
ALTERNATE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
ALTERNATE_SPENDER = "0x" + "5" * 40
ALTERNATE_PAYER = "0x" + "6" * 40
ALTERNATE_DESTINATION = "0x" + "7" * 40
ACTOR = SimpleNamespace(user_id="user_1", agent_id="hermes")


class FundingPolicyService:
    def __init__(self) -> None:
        self.decisions = {}

    def get_decision(self, policy_decision_id: str):
        return self.decisions.get(policy_decision_id)

    def evaluate(self, _request):
        raise AssertionError("Funding must not evaluate policy or call MistTrack")


def funding_policy(request: CreateSpendingReservationRequest):
    metadata = {
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
    }
    if request.asset_allowance_id is not None:
        metadata["asset_allowance_id"] = request.asset_allowance_id
    if request.merchant_trust_tier is not None:
        metadata["merchant_trust_tier"] = request.merchant_trust_tier
    if request.authorization_rail == "external_x402":
        metadata["token_address"] = request.token_address
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
        amount_usdc=request.amount_usdc,
        merchant_id=request.merchant_id,
        user_id=ACTOR.user_id,
        agent_id=ACTOR.agent_id,
        target_address=request.destination,
        chain=request.network,
        metadata=metadata,
        risk_assessment={
            "provider": "misttrack",
            "provider_endpoint": "v2/risk_score",
            "subject": request.destination,
            "network": request.network,
            "asset": "USDC",
            "coin": {
                "eip155:137": "USDC-Polygon",
                "eip155:8453": "USDC-Base",
            }[request.network],
            "decision": "allow",
            "mode": "enforce",
            "enforced": True,
            "mapping_version": "misttrack-policy-v1",
            "hold_score": 31,
            "deny_score": 71,
            "assessed_at": "2026-07-15T11:59:30Z",
            "expires_at": "2026-07-15T12:04:30Z",
        },
        event_log=[],
    )


def install_funding_policy(
    service: FundingService, request: CreateSpendingReservationRequest
) -> None:
    if not isinstance(service.policy_service, FundingPolicyService):
        service.policy_service = FundingPolicyService()
    service.policy_service.decisions[request.policy_decision_id] = funding_policy(request)


def hold_sqlite_write_lock(database_path: str, ready, release) -> None:
    connection = sqlite3.connect(database_path, timeout=0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ready.set()
        release.wait(timeout=0.8)
        connection.commit()
    finally:
        connection.close()


def identity(**updates) -> WalletIdentity:
    values = {
        "wallet_identity_id": "wallet_identity_1",
        "user_id": "user_1",
        "wallet_address": PAYER,
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
        "spending_grant_id": "spending_grant_1",
        "wallet_identity_id": "wallet_identity_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "status": "active",
        "max_amount_usdc": Decimal("5"),
        "per_transaction_limit_usdc": Decimal("4"),
        "hourly_limit_usdc": Decimal("4"),
        "daily_limit_usdc": Decimal("5"),
        "used_amount_usdc": Decimal("0"),
        "reserved_amount_usdc": Decimal("0"),
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": ["merchant_1"],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:137"],
        "asset_scopes": [TOKEN],
        "starts_at": datetime(2026, 7, 1, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 1, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SpendingGrant(**values)


def allowance(**updates) -> AssetAllowance:
    values = {
        "asset_allowance_id": "asset_allowance_1",
        "wallet_identity_id": "wallet_identity_1",
        "network": "eip155:137",
        "token_address": TOKEN,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "spender_address": SPENDER,
        "approved_amount_atomic": 20_000_000,
        "observed_allowance_atomic": 20_000_000,
        "status": "active",
        "confirmed_block": 10,
        "last_chain_check_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return AssetAllowance(**values)


def reservation_request(
    purchase_id: str = "purchase_1", amount: str = "2", **updates
) -> CreateSpendingReservationRequest:
    values = {
        "purchase_id": purchase_id,
        "idempotency_key": purchase_id,
        "wallet_identity_id": "wallet_identity_1",
        "spending_grant_id": "spending_grant_1",
        "asset_allowance_id": "asset_allowance_1",
        "product": "marketplace",
        "action_id": f"action_{purchase_id}",
        "policy_decision_id": f"policy_{purchase_id}",
        "merchant_id": "merchant_1",
        "quote_hash": "0x" + "b" * 64,
        "amount_usdc": amount,
        "amount_atomic": str(Decimal(amount) * Decimal(1_000_000)),
        "network": "eip155:137",
        "asset": TOKEN,
        "destination": DESTINATION,
        "resource": "https://merchant.example/api",
        "venue": "clink_marketplace",
    }
    values.update(updates)
    if "asset" not in updates and values["network"] == "eip155:8453":
        values["asset"] = ALTERNATE_TOKEN
    if values.get("product") == "marketplace":
        values.setdefault("merchant_trust_tier", "registry_verified")
    return CreateSpendingReservationRequest(**values)


@pytest.fixture
def context(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance())
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        policy_service=FundingPolicyService(),
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    return repository, service


def snapshot(repository: AccountRepository):
    with repository.sessions() as session:
        row = session.get(SpendingGrantRow, "spending_grant_1")
        daily = session.query(SpendingGrantDailyUsageRow).all()
        return (
            row.status,
            row.used_amount_usdc,
            row.reserved_amount_usdc,
            [(item.usage_date, item.used_amount_usdc, item.reserved_amount_usdc) for item in daily],
        )


def grant_lifecycle(repository: AccountRepository) -> tuple[str, str | None]:
    with repository.sessions() as session:
        row = session.get(SpendingGrantRow, "spending_grant_1")
        return row.status, row.status_reason


def reserve(service: FundingService, request: CreateSpendingReservationRequest):
    install_funding_policy(service, request)
    unified_references = {
        "product": request.product,
        "wallet_identity_id": request.wallet_identity_id,
        "spending_grant_id": request.spending_grant_id,
        "asset_allowance_id": request.asset_allowance_id,
    }
    if request.opc_installation_id is not None:
        unified_references["opc_installation_id"] = request.opc_installation_id
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        product=request.product,
        unified_references=unified_references,
    )
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=provenance
    ):
        return service.reserve_spending(request)


def legacy_reservation_without_merchant_trust_tier(
    service: FundingService, reservation: dict
) -> dict:
    legacy = {
        key: value
        for key, value in reservation.items()
        if key != "merchant_trust_tier"
    }
    with service.ledger.transaction() as tx:
        return tx.put(
            "reservation",
            legacy["reservation_id"],
            legacy,
            purchase_id=legacy["purchase_id"],
            idempotency_key=legacy["idempotency_key"],
            action_id=legacy["action_id"],
            policy_decision_id=legacy["policy_decision_id"],
            reservation_id=legacy["reservation_id"],
        )


def reserve_external(
    service: FundingService,
    request: CreateSpendingReservationRequest,
    *,
    token_address: str = TOKEN,
):
    external_request = request.model_copy(
        update={
            "authorization_rail": "external_x402",
            "asset_allowance_id": None,
            "token_address": token_address,
        }
    )
    install_funding_policy(service, external_request)
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        product=external_request.product,
        unified_references={
            "product": external_request.product,
            "wallet_identity_id": external_request.wallet_identity_id,
            "spending_grant_id": external_request.spending_grant_id,
        },
        authorization_rail="external_x402",
    )
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=provenance
    ):
        return service.reserve_spending(external_request)


def reserve_proxy(
    service: FundingService,
    request: CreateSpendingReservationRequest,
):
    proxy_request = request.model_copy(
        update={"authorization_rail": "clink_payer_proxy"}
    )
    install_funding_policy(service, proxy_request)
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        product=proxy_request.product,
        unified_references={
            "product": proxy_request.product,
            "wallet_identity_id": proxy_request.wallet_identity_id,
            "spending_grant_id": proxy_request.spending_grant_id,
            "asset_allowance_id": proxy_request.asset_allowance_id,
        },
        authorization_rail="clink_payer_proxy",
    )
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=provenance
    ):
        return service.reserve_spending(proxy_request)


def proxy_requirement(**updates) -> PrepareProxyPaymentRequest:
    values = {
        "payment_requirement": {
            "scheme": "exact",
            "network": "eip155:137",
            "asset": TOKEN,
            "amount_atomic": "2000000",
            "pay_to": DESTINATION,
            "resource": "https://merchant.example/api",
            "token_name": "USD Coin",
            "token_version": "2",
        }
    }
    values.update(updates)
    return PrepareProxyPaymentRequest(**values)


def add_alternate_authorization_scope(repository: AccountRepository) -> dict:
    repository.save_wallet_identity(
        identity(
            wallet_identity_id="wallet_identity_2",
            user_id="user_2",
            wallet_address=ALTERNATE_PAYER,
        )
    )
    repository.save_spending_grant(
        grant(
            spending_grant_id="spending_grant_2",
            wallet_identity_id="wallet_identity_2",
            user_id="user_2",
            agent_id="apollo",
            product_scopes=["prediction_markets"],
            venue_scopes=["polymarket"],
            merchant_scopes=["merchant_2"],
            network_scopes=["eip155:8453"],
            asset_scopes=[ALTERNATE_TOKEN],
        )
    )
    repository.save_asset_allowance(
        allowance(
            asset_allowance_id="asset_allowance_2",
            wallet_identity_id="wallet_identity_2",
            network="eip155:8453",
            token_address=ALTERNATE_TOKEN,
            token_symbol="USDC.e",
            token_decimals=3,
            spender_address=ALTERNATE_SPENDER,
            approved_amount_atomic=20_000,
            observed_allowance_atomic=20_000,
        )
    )
    return {
        "user_id": "user_2",
        "agent_id": "apollo",
        "wallet_identity_id": "wallet_identity_2",
        "spending_grant_id": "spending_grant_2",
        "asset_allowance_id": "asset_allowance_2",
        "product": "prediction_markets",
        "venue": "polymarket",
        "merchant_id": "merchant_2",
        "network": "eip155:8453",
        "asset": "USDC.e",
        "token_address": ALTERNATE_TOKEN,
        "token_symbol": "USDC.e",
        "token_decimals": 3,
        "spender_address": ALTERNATE_SPENDER,
        "amount_usdc": "1",
        "amount_atomic": "1000",
        "destination": ALTERNATE_DESTINATION,
        "resource": "polymarket:alternate-funding",
    }


def test_reservation_request_treats_authorization_references_as_hints():
    unified = reservation_request()
    assert unified.spending_authorization_id is None
    assert reservation_request(spending_authorization_id="legacy_auth")
    assert CreateSpendingReservationRequest(
        **unified.model_dump(
            exclude={
                "wallet_identity_id",
                "spending_grant_id",
                "asset_allowance_id",
                "product",
            }
        )
    )
    with pytest.raises(ValidationError):
        CreateSpendingReservationRequest(
            **unified.model_dump(exclude={"asset_allowance_id"})
        )


def test_external_x402_reserves_grant_budget_without_asset_allowance(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'external-rail.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    service = FundingService(
        config=AppConfig(funding_database_url=database_url),
        storage_file=tmp_path / "legacy.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    request = reservation_request(
        authorization_rail="external_x402",
        asset_allowance_id=None,
        token_address=TOKEN,
    )
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        authorization_rail="external_x402",
        product="marketplace",
        unified_references={
            "product": "marketplace",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
        },
    )

    with patch.object(
        service, "_verify_marketplace_provenance", return_value=provenance
    ):
        reserved = service.reserve_spending(request)

    assert reserved["authorization_rail"] == "external_x402"
    assert reserved["asset_allowance_id"] is None
    assert repository.asset_allowances("wallet_identity_1") == []
    assert snapshot(repository)[2] == Decimal("2")


def test_proxy_reservation_requires_asset_allowance_reference():
    request = reservation_request(authorization_rail="clink_payer_proxy")
    assert request.asset_allowance_id == "asset_allowance_1"

    with pytest.raises(ValidationError, match="proxy allowance reference"):
        CreateSpendingReservationRequest(
            **request.model_dump(exclude={"asset_allowance_id"})
        )


def test_proxy_payment_is_signed_by_payer_and_prepare_is_idempotent(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())

    prepared = service.prepare_proxy_payment(
        reserved["reservation_id"], proxy_requirement()
    )
    replay = service.prepare_proxy_payment(
        reserved["reservation_id"], proxy_requirement()
    )

    assert prepared == replay
    assert prepared["state"] == "proxy_authorization_ready"
    assert prepared["payer_address"] == payer_address
    payload = prepared["payment_payload"]
    signable = encode_typed_data(full_message=payload["typed_data"])
    recovered = Account.recover_message(
        signable,
        signature=payload["payload"]["signature"],
    ).lower()
    assert recovered == payer_address
    assert payload["payload"]["authorization"] == {
        "from": payer_address,
        "to": DESTINATION,
        "value": "2000000",
        "validAfter": str(int(NOW.timestamp()) - 60),
        "validBefore": str(int(NOW.timestamp()) + 270),
        "nonce": prepared["proxy_nonce"],
    }
    assert prepared.get("reimbursement_tx_hash") is None


def test_proxy_prepare_rejects_merchant_challenge_drift(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy-drift.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())
    with service.ledger.transaction() as tx:
        current = tx.get(reserved["reservation_id"])
        current = tx.settle_unified_budget(current, now=NOW.replace(tzinfo=None))
        service._put_reservation(
            tx,
            {
                **current,
                "state": "payer_funded",
                "reimbursement_tx_hash": "0x" + "8" * 64,
            },
        )


def test_proxy_prepare_rejects_untrusted_token_domain_before_user_debit(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy-domain.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_name="USD Coin",
            x402_payment_token_version="2",
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())

    with pytest.raises(ValueError, match="token domain"):
        service.prepare_proxy_payment(
            reserved["reservation_id"],
            proxy_requirement(
                payment_requirement={
                    **proxy_requirement().payment_requirement.model_dump(),
                    "token_name": "USDC",
                }
            ),
        )

    persisted = service.get_reservation(reserved["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert snapshot(repository)[1:3] == (Decimal("0"), Decimal("2"))

    with pytest.raises(ValueError, match="merchant challenge drift"):
        service.prepare_proxy_payment(
            reserved["reservation_id"],
            proxy_requirement(
                payment_requirement={
                    **proxy_requirement().payment_requirement.model_dump(),
                    "pay_to": ALTERNATE_DESTINATION,
                }
            ),
        )


def test_proxy_funded_reservation_cannot_release_used_budget(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy-release.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())
    with service.ledger.transaction() as tx:
        current = tx.get(reserved["reservation_id"])
        current = tx.settle_unified_budget(current, now=NOW.replace(tzinfo=None))
        service._put_reservation(
            tx,
            {
                **current,
                "state": "payer_funded",
                "reimbursement_tx_hash": "0x" + "8" * 64,
            },
        )

    with pytest.raises(ValueError, match="submitted or settled"):
        service.release_reservation(
            reserved["reservation_id"],
            ReleaseSpendingReservationRequest(reason="merchant unavailable"),
        )

    assert snapshot(repository)[1:3] == (Decimal("2"), Decimal("0"))


def test_proxy_authorization_is_required_before_user_reimbursement(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy-ordering.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    chain = StaticPendingNonceChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())

    with pytest.raises(ValueError, match="reservation is spending_reserved"):
        service.settle_reservation(
            reserved["reservation_id"], SettleSpendingReservationRequest()
        )
    assert chain.sent == []

    prepared = service.prepare_proxy_payment(
        reserved["reservation_id"], proxy_requirement()
    )
    submitted = service.settle_reservation(
        reserved["reservation_id"], SettleSpendingReservationRequest()
    )
    ready = service._complete_native_reservation(submitted)

    assert prepared["state"] == "proxy_authorization_ready"
    assert submitted["state"] == "payment_submitted"
    assert ready["state"] == "proxy_payment_ready"
    assert ready["payment_payload"] == prepared["payment_payload"]
    assert ready["reimbursement_tx_hash"] == submitted["tx_hash"]
    assert snapshot(repository)[1:3] == (Decimal("2"), Decimal("0"))


def test_failed_proxy_payment_requires_fresh_authorization_nonce(tmp_path):
    payer = Account.create()
    payer_address = payer.address.lower()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'proxy-retry.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=payer_address))
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=payer.key.hex(),
            clink_polygon_spender_address=payer_address,
            x402_payment_token_address=TOKEN,
            clink_polygon_usdc_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_proxy(service, reservation_request())
    prepared = service.prepare_proxy_payment(
        reserved["reservation_id"], proxy_requirement()
    )
    reimbursement_hash = "0x" + "8" * 64
    merchant_hash = "0x" + "9" * 64
    with service.ledger.transaction() as tx:
        current = tx.get(reserved["reservation_id"])
        current = tx.settle_unified_budget(current, now=NOW.replace(tzinfo=None))
        submitted = {
            **current,
            "state": "payment_submitted",
            "reimbursement_tx_hash": reimbursement_hash,
            "merchant_tx_hash": merchant_hash,
            "tx_hash": merchant_hash,
            "settlement_rail": "clink_payer_proxy",
        }
        service._put_reservation(tx, submitted, tx_hash=merchant_hash)

    retryable = service._retryable_proxy_payment(submitted, "merchant tx failed")
    renewed = service.prepare_proxy_payment(
        reserved["reservation_id"], proxy_requirement()
    )

    assert retryable["state"] == "payer_funded"
    assert retryable["payment_payload"] is None
    assert renewed["state"] == "proxy_payment_ready"
    assert renewed["proxy_nonce"] != prepared["proxy_nonce"]


def test_reservation_rechecks_signed_merchant_trust_scope_atomically(context):
    repository, service = context
    with repository.sessions.begin() as session:
        row = session.get(SpendingGrantRow, "spending_grant_1")
        row.merchant_trust_scopes = ["clink_verified"]

    with pytest.raises(ValueError, match="MERCHANT_TRUST_SCOPE_MISMATCH"):
        reserve(
            service,
            reservation_request(merchant_trust_tier="registry_verified"),
        )


def test_marketplace_reservation_rejects_missing_merchant_trust_tier_without_budget_mutation(
    context,
):
    repository, service = context
    before = snapshot(repository)

    with pytest.raises(ValueError, match="MERCHANT_TRUST_SCOPE_MISMATCH"):
        reserve(service, reservation_request(merchant_trust_tier=None))

    assert snapshot(repository) == before


def test_unsubmitted_marketplace_lifecycle_rejects_legacy_missing_tier(context):
    repository, service = context
    reserved = reserve(service, reservation_request())
    legacy = legacy_reservation_without_merchant_trust_tier(service, reserved)

    with service.ledger.transaction() as tx:
        with pytest.raises(ValueError, match="MERCHANT_TRUST_SCOPE_MISMATCH"):
            tx.validate_unified_lifecycle(legacy, now=NOW)

    assert service.get_reservation(reserved["reservation_id"])["state"] == (
        "spending_reserved"
    )
    assert snapshot(repository)[2] == Decimal("2")


def test_executed_external_payment_reconciles_legacy_marketplace_without_tier(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy-executed.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    legacy = legacy_reservation_without_merchant_trust_tier(service, reserved)
    tx_hash = "0x" + keccak(text="legacy-executed").hex()
    observe_external_transaction(
        chain, tx_hash, legacy, receipt_status="0x1"
    )

    settled = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(legacy),
        ),
    )

    assert settled["state"] == "settled"
    assert snapshot(repository)[1:] == (
        Decimal("2"),
        Decimal("0"),
        [(NOW.date(), Decimal("2"), Decimal("0"))],
    )


def test_unverified_external_hash_cannot_bypass_marketplace_trust_admission(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy-unverified.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(funding_database_url=database_url),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    legacy = legacy_reservation_without_merchant_trust_tier(service, reserved)
    tx_hash = "0x" + keccak(text="legacy-unverified").hex()
    observe_external_transaction(chain, tx_hash, legacy)

    with pytest.raises(ValueError, match="MERCHANT_TRUST_SCOPE_MISMATCH"):
        service.finalize_external_payment(
            reserved["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(legacy),
            ),
        )

    persisted = service.get_reservation(reserved["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert snapshot(repository)[2] == Decimal("2")


def test_prediction_market_reservation_allows_missing_merchant_trust_tier(context):
    repository, service = context
    repository.save_spending_grant(
        grant(
            product_scopes=["prediction_markets"],
            venue_scopes=["clink_marketplace"],
        )
    )

    reserved = reserve(
        service,
        reservation_request(product="prediction_markets", merchant_trust_tier=None),
    )

    assert reserved["state"] == "spending_reserved"
    assert reserved.get("merchant_trust_tier") is None


def test_two_concurrent_four_usdc_reservations_only_allow_one(context):
    repository, service = context
    requests = [reservation_request(f"purchase_{index}", "4") for index in range(2)]
    for item in requests:
        install_funding_policy(service, item)
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        product=requests[0].product,
        unified_references={
            "product": requests[0].product,
            "wallet_identity_id": requests[0].wallet_identity_id,
            "spending_grant_id": requests[0].spending_grant_id,
            "asset_allowance_id": requests[0].asset_allowance_id,
        },
    )
    # One shared fixture lifetime: nested thread-local patch.object contexts
    # on the same instance race while restoring/deleting the mocked method.
    with patch.object(service, "_verify_marketplace_provenance", return_value=provenance):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(service.reserve_spending, item) for item in requests]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result()["state"])
        except ValueError as exc:
            outcomes.append(str(exc))

    assert outcomes.count("spending_reserved") == 1
    assert sum("BUDGET_EXCEEDED" in item for item in outcomes) == 1
    assert snapshot(repository)[2:] == (
        Decimal("4"),
        [(NOW.date(), Decimal("0"), Decimal("4"))],
    )


@pytest.mark.parametrize(
    ("network", "token_address"),
    [
        ("eip155:137", ALTERNATE_TOKEN),
        ("eip155:8453", TOKEN),
        ("eip155:137", "0x" + "9" * 40),
    ],
)
def test_reservation_rejects_noncanonical_network_token_pair_before_budget_mutation(
    tmp_path, network, token_address
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'canonical-reserve.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(
        grant(
            network_scopes=["eip155:137", "eip155:8453"],
            asset_scopes=[TOKEN, ALTERNATE_TOKEN, "0x" + "9" * 40],
        )
    )
    repository.save_asset_allowance(
        allowance(network=network, token_address=token_address)
    )
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_polygon_usdc_address=TOKEN,
            clink_base_usdc_address=ALTERNATE_TOKEN,
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match="canonical asset"):
        reserve(
            service,
            reservation_request(
                network=network,
                asset=token_address,
                token_address=token_address,
            ),
        )

    assert snapshot(repository)[2] == Decimal("0")


def test_release_restores_grant_and_daily_budget_idempotently(context):
    repository, service = context
    row = reserve(service, reservation_request())

    released = service.release_reservation(
        row["reservation_id"], ReleaseSpendingReservationRequest(reason="cancelled")
    )
    replay = service.release_reservation(
        row["reservation_id"], ReleaseSpendingReservationRequest(reason="different")
    )

    assert released == replay
    assert released["state"] == "released"
    assert snapshot(repository)[1:] == (
        Decimal("0"),
        Decimal("0"),
        [(NOW.date(), Decimal("0"), Decimal("0"))],
    )


@pytest.mark.parametrize("status", ["paused", "revoked", "expired"])
def test_reserve_rechecks_grant_status_and_expiry(context, status):
    repository, service = context
    current = grant(status=status)
    if status == "expired":
        current = grant(
            status="active",
            starts_at=datetime(2026, 6, 1, tzinfo=UTC),
            expires_at=datetime(2026, 7, 15, 11, tzinfo=UTC),
        )
    repository.save_spending_grant(current)

    with pytest.raises(ValueError, match="SPENDING_GRANT_REQUIRED"):
        reserve(service, reservation_request())
    assert snapshot(repository)[2] == Decimal("0")


def test_opc_reservation_rechecks_exact_active_installation_before_budget_commit(
    context,
):
    repository, service = context
    with repository._write_session() as session:
        session.add(
            OpcInstallationRow(
                installation_id="opc_install_exact",
                public_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y"},
                public_jwk_thumbprint="opc-thumbprint-exact",
                label="Pilot Linux",
                status="active",
                scope="payments",
                user_id="user_1",
                wallet_identity_id="wallet_identity_1",
                spending_grant_id="spending_grant_1",
                consent_expires_at=NOW + timedelta(days=1),
                consent_hash="f" * 64,
                approved_at=NOW - timedelta(minutes=1),
                revoked_at=None,
                created_at=NOW - timedelta(minutes=1),
                updated_at=NOW - timedelta(minutes=1),
            )
        )

    reserved = reserve(
        service,
        reservation_request(opc_installation_id="opc_install_exact"),
    )

    assert reserved["opc_installation_id"] == "opc_install_exact"
    assert snapshot(repository)[2] == Decimal("2")


@pytest.mark.parametrize(
    ("status", "wallet_identity_id", "spending_grant_id", "consent_expires_at"),
    [
        ("consent_required", "wallet_identity_1", "spending_grant_1", NOW + timedelta(days=1)),
        ("active", "wallet_identity_other", "spending_grant_1", NOW + timedelta(days=1)),
        ("active", "wallet_identity_1", "spending_grant_other", NOW + timedelta(days=1)),
        ("active", "wallet_identity_1", "spending_grant_1", NOW),
    ],
)
def test_opc_reservation_rejects_stale_or_cross_authority_installation(
    context,
    status,
    wallet_identity_id,
    spending_grant_id,
    consent_expires_at,
):
    repository, service = context
    if wallet_identity_id == "wallet_identity_other":
        repository.save_wallet_identity(
            identity(
                wallet_identity_id="wallet_identity_other",
                wallet_address=ALTERNATE_PAYER,
                user_id="user_2",
            )
        )
    if spending_grant_id == "spending_grant_other":
        repository.save_spending_grant(
            grant(spending_grant_id="spending_grant_other")
        )
    with repository._write_session() as session:
        session.add(
            OpcInstallationRow(
                installation_id="opc_install_stale",
                public_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y"},
                public_jwk_thumbprint="opc-thumbprint-stale",
                label="Pilot Linux",
                status=status,
                scope="payments",
                user_id="user_1",
                wallet_identity_id=wallet_identity_id,
                spending_grant_id=spending_grant_id,
                consent_expires_at=consent_expires_at,
                consent_hash="e" * 64,
                approved_at=NOW - timedelta(minutes=1),
                revoked_at=None,
                created_at=NOW - timedelta(minutes=1),
                updated_at=NOW - timedelta(minutes=1),
            )
        )

    with pytest.raises(ValueError, match="OPC installation authority"):
        reserve(
            service,
            reservation_request(opc_installation_id="opc_install_stale"),
        )
    assert snapshot(repository)[2] == Decimal("0")


def test_reserve_rejects_cross_user_and_amount_atomic_mismatch(context):
    repository, service = context
    with patch.object(
        service,
        "_verify_marketplace_provenance",
        return_value=ReservationProvenance(
            action=SimpleNamespace(user_id="user_2", agent_id="hermes"),
            authorization_path="unified_grant",
            product="marketplace",
            unified_references={
                "product": "marketplace",
                "wallet_identity_id": "wallet_identity_1",
                "spending_grant_id": "spending_grant_1",
                "asset_allowance_id": "asset_allowance_1",
            },
        ),
    ), pytest.raises(ValueError, match="wallet identity|grant user"):
        service.reserve_spending(reservation_request())
    with pytest.raises(ValueError, match="amount_atomic"):
        reserve(service, reservation_request(amount_atomic="2000001"))
    assert snapshot(repository)[2] == Decimal("0")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_reserve_rejects_non_finite_decimal_amounts(context, amount):
    _, service = context

    with pytest.raises(ValueError, match="finite"):
        reserve(service, reservation_request(amount=amount, amount_atomic="0"))


def test_reservation_replay_cannot_change_unified_references(context):
    repository, service = context
    original = reserve(service, reservation_request())
    repository.save_spending_grant(
        grant(spending_grant_id="spending_grant_2")
    )

    with pytest.raises(ValueError, match="immutable scope"):
        reserve(
            service,
            reservation_request(spending_grant_id="spending_grant_2"),
        )
    assert service.get_reservation(original["reservation_id"])["spending_grant_id"] == (
        "spending_grant_1"
    )


def test_unified_reservation_uses_action_refs_when_request_omits_hints(context):
    _, service = context
    hinted = reservation_request()
    request = hinted.model_copy(
        update={
            "wallet_identity_id": None,
            "spending_grant_id": None,
            "asset_allowance_id": None,
            "product": None,
        }
    )
    provenance = ReservationProvenance(
        action=ACTOR,
        authorization_path="unified_grant",
        product="marketplace",
        unified_references={
            "product": "marketplace",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
            "asset_allowance_id": "asset_allowance_1",
        },
    )

    with patch.object(
        service, "_verify_marketplace_provenance", return_value=provenance
    ):
        first = service.reserve_spending(request)
        replay = service.reserve_spending(request)

    assert replay == first
    assert first["product"] == "marketplace"
    assert first["spending_grant_id"] == "spending_grant_1"


def test_reservation_failure_rolls_back_budget_and_daily_usage(context):
    repository, service = context
    with patch.object(FundingTransaction, "put", side_effect=RuntimeError("write failed")):
        with pytest.raises(RuntimeError, match="write failed"):
            reserve(service, reservation_request())

    assert snapshot(repository)[1:] == (Decimal("0"), Decimal("0"), [])


def test_authoritative_ledger_allows_unified_update_but_rejects_legacy_mutation(
    context,
):
    _, service = context
    reserved = reserve(service, reservation_request())

    with service.ledger.transaction() as tx:
        updated = {**reserved, "last_reconciliation_error": "still unified"}
        assert service._put_reservation(tx, updated) == updated

    legacy_mutation = {
        **updated,
        "authorization_path": "legacy",
        "last_reconciliation_error": "forged legacy mutation",
    }
    with pytest.raises(ValueError, match="legacy spending authorizations are read-only"):
        with service.ledger.transaction() as tx:
            tx.put(
                "reservation",
                reserved["reservation_id"],
                legacy_mutation,
                purchase_id=reserved["purchase_id"],
                idempotency_key=reserved["idempotency_key"],
                action_id=reserved["action_id"],
                policy_decision_id=reserved["policy_decision_id"],
                reservation_id=reserved["reservation_id"],
            )

    assert service.get_reservation(reserved["reservation_id"]) == updated


def test_authoritative_ledger_rejects_valid_unified_scope_substitution(context):
    repository, service = context
    alternate_scope = add_alternate_authorization_scope(repository)
    reserved = reserve(service, reservation_request())
    replacement = {**reserved, **alternate_scope}

    with pytest.raises(ValueError, match="immutable reservation provenance"):
        with service.ledger.transaction() as tx:
            tx.put(
                "reservation",
                reserved["reservation_id"],
                replacement,
                purchase_id=reserved["purchase_id"],
                idempotency_key=reserved["idempotency_key"],
                action_id=reserved["action_id"],
                policy_decision_id=reserved["policy_decision_id"],
                reservation_id=reserved["reservation_id"],
            )

    assert service.get_reservation(reserved["reservation_id"]) == reserved
    with repository.sessions() as session:
        grants = {
            item.spending_grant_id: item.reserved_amount_usdc
            for item in session.query(SpendingGrantRow).all()
        }
        daily = session.query(SpendingGrantDailyUsageRow).all()
    assert grants == {
        "spending_grant_1": Decimal("2"),
        "spending_grant_2": Decimal("0"),
    }
    assert [
        (item.spending_grant_id, item.reserved_amount_usdc) for item in daily
    ] == [("spending_grant_1", Decimal("2"))]


def test_reservation_does_not_decrement_observed_allowance(context):
    repository, service = context

    reserve(service, reservation_request())

    assert repository.asset_allowance("asset_allowance_1").observed_allowance_atomic == 20_000_000


def test_reservation_recomputes_deterministic_core_selection(context):
    repository, service = context
    repository.save_spending_grant(
        grant(spending_grant_id="spending_grant_2")
    )
    forged = reservation_request(spending_grant_id="spending_grant_2")

    with service.ledger.transaction() as tx:
        selection = tx.reserve_unified_budget(
            forged,
            actor_user_id=ACTOR.user_id,
            actor_agent_id=ACTOR.agent_id,
            amount=Decimal("2"),
            now=NOW,
            reservation_id="reserve_recompute_selection",
            canonical_token_address=TOKEN,
        )

    assert selection["spending_grant_id"] == "spending_grant_1"
    assert snapshot(repository)[2] == Decimal("2")
    with repository.sessions() as session:
        forged_grant = session.get(SpendingGrantRow, "spending_grant_2")
        assert forged_grant.reserved_amount_usdc == Decimal("0")


def test_reservation_selection_ignores_lower_id_wrong_spender(context):
    repository, service = context
    repository.save_asset_allowance(
        allowance(
            asset_allowance_id="asset_allowance_0",
            spender_address="0x" + "9" * 40,
        )
    )
    request = reservation_request()

    with service.ledger.transaction() as tx:
        selection = tx.reserve_unified_budget(
            request,
            actor_user_id=ACTOR.user_id,
            actor_agent_id=ACTOR.agent_id,
            amount=Decimal("2"),
            now=NOW,
            reservation_id="reserve_spender_selection",
            canonical_token_address=TOKEN,
            expected_selection={
                "wallet_identity_id": "wallet_identity_1",
                "spending_grant_id": "spending_grant_1",
                "asset_allowance_id": "asset_allowance_1",
            },
        )

    assert selection["asset_allowance_id"] == "asset_allowance_1"
    assert selection["spender_address"] == SPENDER


def test_postgresql_grant_and_daily_usage_queries_lock_rows():
    statements = []
    session = SimpleNamespace(scalar=lambda statement: statements.append(statement))
    transaction = FundingTransaction(session, "postgresql")

    transaction._locked(SpendingGrantRow, "spending_grant_1")
    transaction._locked_daily_usage("spending_grant_1", NOW.date())

    compiled = [
        str(statement.compile(dialect=postgresql.dialect())) for statement in statements
    ]
    assert len(compiled) == 2
    assert all("FOR UPDATE" in statement for statement in compiled)


def test_postgresql_reservation_lifecycle_read_locks_the_reservation_row():
    statements = []

    class Session:
        def get(self, *_args):
            return None

        def scalar(self, statement):
            statements.append(statement)
            return None

    transaction = FundingTransaction(Session(), "postgresql")

    assert transaction.get("reserve_1") is None
    assert len(statements) == 1
    compiled = str(
        statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FOR UPDATE" in compiled


def test_missing_global_funding_lock_fails_closed(tmp_path):
    ledger = FundingLedger(f"sqlite+pysqlite:///{tmp_path / 'missing-lock.sqlite3'}")
    with ledger.sessions.begin() as session:
        session.query(LockRow).delete()

    with pytest.raises(RuntimeError, match="global funding lock"):
        with ledger.transaction():
            pass


def test_sqlite_funding_transactions_begin_immediately(tmp_path):
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'immediate.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(service.ledger.engine, "before_cursor_execute", capture)
    try:
        with service.ledger.transaction():
            pass
    finally:
        event.remove(service.ledger.engine, "before_cursor_execute", capture)

    assert any(statement == "BEGIN IMMEDIATE" for statement in statements)


def test_sqlite_cross_process_contention_has_bounded_retry(tmp_path):
    database_path = tmp_path / "contended.sqlite3"
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{database_path}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    context = get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=hold_sqlite_write_lock,
        args=(str(database_path), ready, release),
    )
    process.start()
    try:
        assert ready.wait(timeout=2)
        with pytest.raises(ValueError, match="busy after 5 attempts"):
            with service.ledger.transaction() as tx:
                tx.put("test", "contended", {"value": 1})
    finally:
        release.set()
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)

    assert process.exitcode == 0
    with service.ledger.transaction() as tx:
        assert tx.get("contended") is None


def test_prediction_market_funding_uses_product_specific_provenance(tmp_path):
    service = FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'prediction.sqlite3'}"
        ),
        storage_file=tmp_path / "funding.jsonl",
    )
    request = reservation_request(
        product="prediction_markets",
        venue="polymarket",
        merchant_id="polymarket",
        resource="polymarket:funding",
        opc_installation_id="opc_prediction_installation",
    )
    expected = {
        "purchase_id": request.purchase_id,
        "quote_hash": request.quote_hash,
        "network": request.network,
        "asset": request.asset,
        "amount_atomic": request.amount_atomic,
        "destination": request.destination,
        "resource": request.resource,
        "authorization_rail": "native_allowance",
        "product": request.product,
        "wallet_identity_id": request.wallet_identity_id,
        "spending_grant_id": request.spending_grant_id,
        "asset_allowance_id": request.asset_allowance_id,
        "opc_installation_id": request.opc_installation_id,
    }
    action = SimpleNamespace(
        action_id=request.action_id,
        action_type="funding_transfer",
        state="policy_approved",
        merchant_id="polymarket",
        user_id="user_1",
        agent_id="hermes",
        amount_usdc=request.amount_usdc,
        policy_decision_id=request.policy_decision_id,
        metadata=expected,
    )
    policy = SimpleNamespace(
        policy_decision_id=request.policy_decision_id,
        approved=True,
        action_id=request.action_id,
        action_type="funding_transfer",
        amount_usdc=request.amount_usdc,
            merchant_id="polymarket",
            user_id="user_1",
            agent_id="hermes",
            target_address=request.destination,
            chain=request.network,
            metadata=expected,
    )
    event = SimpleNamespace(
        source_service="clink_prediction_markets",
        event_type="prediction_market_funding_policy_evaluated",
        policy_decision_id=request.policy_decision_id,
        user_id="user_1",
        agent_id="hermes",
        payload={**expected, "merchant_id": "polymarket", "venue": "polymarket"},
    )

    with patch("services.funding_service.service.ActionService") as actions, patch(
        "services.funding_service.service.PolicyService"
    ) as policies, patch("services.funding_service.service.AuditService") as audits:
        actions.return_value.get_intent.return_value = action
        policies.return_value.get_decision.return_value = policy
        service.policy_service = policies.return_value
        audits.return_value.get_trail.return_value = SimpleNamespace(events=[event])
        resolved = service._verify_marketplace_provenance(request)
        with pytest.raises(ValueError, match="OPC installation reference"):
            service._verify_marketplace_provenance(
                request.model_copy(
                    update={"opc_installation_id": "opc_other_installation"}
                )
            )

    assert resolved.action is action
    assert resolved.authorization_path == "unified_grant"
    assert resolved.unified_references["opc_installation_id"] == (
        "opc_prediction_installation"
    )


def test_daily_usage_uses_utc_date_boundary(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'boundary.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(
        grant(
            max_amount_usdc=Decimal("10"),
            per_transaction_limit_usdc=Decimal("4"),
            hourly_limit_usdc=Decimal("4"),
            daily_limit_usdc=Decimal("4"),
        )
    )
    repository.save_asset_allowance(allowance())
    service = FundingService(
        config=AppConfig(funding_database_url=database_url),
        storage_file=tmp_path / "funding.jsonl",
    )
    service._utc_now = lambda: datetime(2026, 7, 15, 22, 59, 0)
    reserve(service, reservation_request("purchase_day_1", "4"))
    service._utc_now = lambda: datetime(2026, 7, 16, 0, 0, 0)

    reserve(service, reservation_request("purchase_day_2", "4"))

    assert snapshot(repository)[3] == [
        (datetime(2026, 7, 15).date(), Decimal("0"), Decimal("4")),
        (datetime(2026, 7, 16).date(), Decimal("0"), Decimal("4")),
    ]


def test_rolling_hour_limit_counts_reserved_and_releases_immediately(context):
    _repository, service = context
    first = reserve(service, reservation_request("purchase_hour_1", "2"))

    with pytest.raises(ValueError, match="HOURLY_LIMIT_EXCEEDED"):
        reserve(service, reservation_request("purchase_hour_2", "3"))

    service.release_reservation(
        first["reservation_id"], ReleaseSpendingReservationRequest(reason="cancelled")
    )
    second = reserve(service, reservation_request("purchase_hour_2", "3"))

    assert second["budget_accounting_state"] == "reserved"


def test_rolling_hour_limit_expires_after_sixty_minutes(context):
    _repository, service = context
    reserve(service, reservation_request("purchase_hour_1", "2"))
    service._utc_now = lambda: (NOW + timedelta(minutes=61)).replace(tzinfo=None)

    second = reserve(service, reservation_request("purchase_hour_2", "3"))

    assert second["budget_accounting_state"] == "reserved"


class ExternalChain:
    def __init__(self):
        self.receipts = {}
        self.transactions = {}

    def __call__(self, network, method, params):
        assert network == "eip155:137"
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(params[0])
        if method == "eth_getTransactionByHash":
            return self.transactions.get(params[0])
        if method == "eth_blockNumber":
            return "0x20"
        raise AssertionError(method)


class StaticPendingNonceChain:
    def __init__(self):
        self.pending_nonces = {"eip155:137": 7, "eip155:8453": 7}
        self.transactions = {}
        self.sent = []

    def __call__(self, network, method, params):
        if method == "eth_chainId":
            return "0x89" if network == "eip155:137" else "0x2105"
        if method == "eth_call":
            return hex(20_000_000)
        if method == "eth_getTransactionCount":
            return hex(self.pending_nonces[network])
        if method == "eth_gasPrice":
            return "0x1"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method == "eth_sendRawTransaction":
            raw = params[0]
            tx_hash = "0x" + keccak(
                bytes.fromhex(raw.removeprefix("0x"))
            ).hex()
            self.sent.append((network, raw))
            self.transactions[tx_hash] = {"hash": tx_hash}
            return tx_hash
        if method == "eth_getTransactionReceipt":
            return None
        if method == "eth_getTransactionByHash":
            return self.transactions.get(params[0])
        raise AssertionError(method)


def external_proof(reservation: dict, amount_atomic: str | None = None) -> dict:
    return {
        "network": reservation["network"],
        "asset": reservation["asset"],
        "amount_atomic": amount_atomic or reservation["amount_atomic"],
        "pay_to": reservation["destination"],
        "nonce": reservation["nonce"],
        "valid_after": reservation["valid_after"],
        "valid_before": reservation["valid_before"],
    }


def external_calldata(
    amount: int = 2_000_000, *, reservation: dict | None = None
) -> str:
    address = lambda value: value.removeprefix("0x").rjust(64, "0")
    uint = lambda value: hex(value)[2:].rjust(64, "0")
    words = (
        address(PAYER),
        address(DESTINATION),
        uint(amount),
        uint(int(reservation["valid_after"]) if reservation else 0),
        uint(int(reservation["valid_before"]) if reservation else 2**256 - 1),
        reservation["nonce"].removeprefix("0x") if reservation else "11" * 32,
        uint(27),
        "22" * 32,
        "33" * 32,
    )
    return "0xe3ee160e" + "".join(words)


def observe_external_transaction(
    chain: ExternalChain,
    tx_hash: str,
    reservation: dict,
    *,
    amount: int = 2_000_000,
    receipt_status: str | None = None,
) -> None:
    chain.transactions[tx_hash] = {
        "hash": tx_hash,
        "to": reservation["token_address"],
        "input": external_calldata(amount=amount, reservation=reservation),
    }
    if receipt_status is not None:
        chain.receipts[tx_hash] = {
            "transactionHash": tx_hash,
            "status": receipt_status,
            "blockNumber": "0x20",
        }


def test_native_nonce_allocation_is_durable_atomic_and_network_isolated(tmp_path):
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    database_url = f"sqlite+pysqlite:///{tmp_path / 'relayer-nonces.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(
        grant(
            max_amount_usdc=Decimal("10"),
            per_transaction_limit_usdc=Decimal("10"),
            hourly_limit_usdc=Decimal("10"),
            daily_limit_usdc=Decimal("10"),
            network_scopes=["eip155:137", "eip155:8453"],
            asset_scopes=[TOKEN, ALTERNATE_TOKEN],
        )
    )
    repository.save_asset_allowance(allowance(spender_address=relayer))
    repository.save_asset_allowance(
        allowance(
            asset_allowance_id="asset_allowance_base",
            network="eip155:8453",
            token_address=ALTERNATE_TOKEN,
            spender_address=relayer,
        )
    )
    chain = StaticPendingNonceChain()
    shared_policy_service = FundingPolicyService()

    def funding_service():
        service = FundingService(
            config=AppConfig(
                funding_database_url=database_url,
                clink_live_funding=True,
                risk_mode="enforce",
                misttrack_api_key="test-key",
                clink_native_facilitator_enabled=True,
                clink_native_facilitator_relayer_private_key=relayer_key,
                clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            ),
            storage_file=tmp_path / "funding.jsonl",
            rpc_transport=chain,
            policy_service=shared_policy_service,
        )
        service._utc_now = lambda: NOW.replace(tzinfo=None)
        return service

    first_service = funding_service()
    second_service = funding_service()
    first = reserve(
        first_service,
        reservation_request("purchase_nonce_1", "1"),
    )
    second = reserve(
        first_service,
        reservation_request(
            "purchase_nonce_2", "1", destination=ALTERNATE_DESTINATION
        ),
    )
    base = reserve(
        first_service,
        reservation_request(
            "purchase_nonce_base",
            "1",
            network="eip155:8453",
            asset_allowance_id="asset_allowance_base",
            destination="0x" + "8" * 40,
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                service.settle_reservation,
                reservation["reservation_id"],
                SettleSpendingReservationRequest(),
            )
            for service, reservation in (
                (first_service, first),
                (second_service, second),
            )
        ]
        polygon_results = [future.result() for future in futures]

    base_result = funding_service().settle_reservation(
        base["reservation_id"], SettleSpendingReservationRequest()
    )

    assert sorted(result["settlement_nonce"] for result in polygon_results) == [7, 8]
    assert base_result["settlement_nonce"] == 7
    with first_service.ledger.engine.connect() as connection:
        nonce_rows = connection.execute(
            text(
                "SELECT network, relayer_address, next_nonce "
                "FROM funding_relayer_nonces ORDER BY network"
            )
        ).all()
    assert nonce_rows == [
        ("eip155:137", relayer.lower(), 9),
        ("eip155:8453", relayer.lower(), 8),
    ]


def test_native_settlement_uses_selected_allowance_token_and_decimals(
    tmp_path,
):
    custom_token = TOKEN
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    database_url = f"sqlite+pysqlite:///{tmp_path / 'selected-native.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant(asset_scopes=[custom_token]))
    repository.save_asset_allowance(
        allowance(
            token_address=custom_token,
            token_decimals=3,
            spender_address=relayer,
            approved_amount_atomic=20_000,
            observed_allowance_atomic=20_000,
        )
    )
    captured = {}

    def rpc(network, method, _params):
        assert network == "eip155:137"
        return {
            "eth_chainId": "0x89",
            "eth_getTransactionCount": "0x1",
            "eth_gasPrice": "0x1",
            "eth_estimateGas": "0x186a0",
        }[method]

    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            x402_payment_token_address=TOKEN,
            x402_payment_token_decimals=6,
            clink_native_facilitator_relayer_private_key=relayer_key,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=rpc,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve(
        service,
        reservation_request(amount_atomic="2000"),
    )
    authorization = service._reservation_authorization(reserved)
    spend = SpendFromSpendingAuthorizationRequest(
        spending_authorization_id=authorization.spending_authorization_id,
        amount_usdc="2",
        destination=DESTINATION,
    )

    def sign(transaction, _private_key):
        captured.update(transaction)
        return SimpleNamespace(raw_transaction=b"signed")

    with patch("services.funding_service.service.Account.sign_transaction", side_effect=sign):
        service._prepare_native_transaction(authorization, spend)

    assert captured["to"].lower() == custom_token
    assert int(captured["data"][-64:], 16) == 2_000


@pytest.mark.parametrize(
    ("network", "token_address"),
    [
        ("eip155:137", ALTERNATE_TOKEN),
        ("eip155:8453", TOKEN),
        ("eip155:137", "0x" + "9" * 40),
    ],
)
def test_settlement_revalidates_stored_canonical_pair_before_chain_io(
    context, network, token_address
):
    repository, service = context
    reserved = reserve(service, reservation_request(token_address=TOKEN))
    with service.ledger.engine.begin() as connection:
        payload = connection.execute(
            text("SELECT payload FROM funding_ledger_records WHERE record_id = :id"),
            {"id": reserved["reservation_id"]},
        ).scalar_one()
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload["network"] = network
        payload["token_address"] = token_address
        connection.execute(
            text(
                "UPDATE funding_ledger_records SET payload = :payload "
                "WHERE record_id = :id"
            ),
            {"payload": json.dumps(payload), "id": reserved["reservation_id"]},
        )
        connection.execute(
            text(
                "UPDATE spending_grants SET asset_scopes = :assets, "
                "network_scopes = :networks "
                "WHERE spending_grant_id = 'spending_grant_1'"
            ),
            {
                "assets": json.dumps([TOKEN, ALTERNATE_TOKEN, "0x" + "9" * 40]),
                "networks": json.dumps(["eip155:137", "eip155:8453"]),
            },
        )
        connection.execute(
            text(
                "UPDATE asset_allowances SET network = :network, token_address = :token "
                "WHERE asset_allowance_id = 'asset_allowance_1'"
            ),
            {"network": network, "token": token_address},
        )
    rpc_calls = []
    service.rpc_transport = lambda network, method, params: rpc_calls.append(
        (network, method, params)
    )

    with pytest.raises(ValueError, match="canonical asset"):
        service.settle_reservation(
            reserved["reservation_id"], SettleSpendingReservationRequest()
        )

    assert rpc_calls == []
    assert snapshot(repository)[2] == Decimal("2")


@pytest.mark.parametrize(
    ("network", "token_address"),
    [
        ("eip155:137", ALTERNATE_TOKEN),
        ("eip155:8453", TOKEN),
        ("eip155:137", "0x" + "9" * 40),
    ],
)
def test_external_finalize_revalidates_canonical_pair_before_chain_io_and_state_write(
    context, network, token_address
):
    _, service = context
    reserved = reserve_external(service, reservation_request())
    with service.ledger.engine.begin() as connection:
        payload = connection.execute(
            text("SELECT payload FROM funding_ledger_records WHERE record_id = :id"),
            {"id": reserved["reservation_id"]},
        ).scalar_one()
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload["network"] = network
        payload["token_address"] = token_address
        connection.execute(
            text(
                "UPDATE funding_ledger_records SET payload = :payload "
                "WHERE record_id = :id"
            ),
            {"payload": json.dumps(payload), "id": reserved["reservation_id"]},
        )
        connection.execute(
            text(
                "UPDATE spending_grants SET asset_scopes = :assets, "
                "network_scopes = :networks "
                "WHERE spending_grant_id = 'spending_grant_1'"
            ),
            {
                "assets": json.dumps([TOKEN, ALTERNATE_TOKEN, "0x" + "9" * 40]),
                "networks": json.dumps(["eip155:137", "eip155:8453"]),
            },
        )
    rpc_calls = []
    service.rpc_transport = lambda rpc_network, method, params: rpc_calls.append(
        (rpc_network, method, params)
    )

    with pytest.raises(ValueError, match="canonical asset"):
        service.finalize_external_payment(
            reserved["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash="0x" + "d" * 64,
                payment_response={
                    **external_proof(reserved),
                    "network": network,
                },
            ),
        )

    persisted = service.get_reservation(reserved["reservation_id"])
    assert rpc_calls == []
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("tx_hash") is None


def test_receipt_signature_binds_token_address_and_legacy_receipts_are_read_only(
    context,
):
    _, service = context
    service.config.clink_receipt_signing_key = "receipt-signing-secret-" + "2" * 32
    reserved = reserve(service, reservation_request(token_address=TOKEN))
    tx_hash = "0x" + "c" * 64
    receipt_id = f"fund_receipt_{reserved['reservation_id']}"
    with service.ledger.transaction() as tx:
        current = tx.get(reserved["reservation_id"])
        pending = {
            **current,
            "state": "payment_submitted",
            "tx_hash": tx_hash,
            "receipt_id": receipt_id,
        }
        service._put_reservation(tx, pending, tx_hash=tx_hash)
        authorization = service._reservation_authorization(pending, tx=tx)
        receipt = service._record_spending_receipt(
            authorization=authorization,
            request=SpendFromSpendingAuthorizationRequest(
                spending_authorization_id=authorization.spending_authorization_id,
                amount_usdc=pending["amount_usdc"],
                destination=pending["destination"],
                resource=pending["resource"],
            ),
            tx_hash=tx_hash,
            receipt_id=receipt_id,
            tx=tx,
        )

    assert receipt.token_address == TOKEN
    assert receipt.metadata["receipt_scope"]["token_address"] == TOKEN
    assert service.verify_receipt_signature(receipt) is True
    with service.ledger.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT token_address FROM funding_ledger_records "
                "WHERE record_id = :id"
            ),
            {"id": receipt.receipt_id},
        ).scalar_one() == TOKEN
    assert (
        service.verify_receipt_signature(
            receipt.model_copy(update={"token_address": ALTERNATE_TOKEN})
        )
        is False
    )
    assert (
        service.verify_receipt_signature(receipt.model_copy(update={"token_address": None}))
        is False
    )


@pytest.mark.parametrize("sink", ["receipt", "native-prepare"])
def test_unified_sinks_reject_mismatched_authoritative_references_before_io(
    context, sink
):
    _, service = context
    reserved = reserve(service, reservation_request())
    authorization = service._reservation_authorization(reserved).model_copy(
        update={
            "metadata": {
                **service._reservation_authorization(reserved).metadata,
                "asset_allowance_id": "asset_allowance_forged",
            }
        }
    )
    request = SpendFromSpendingAuthorizationRequest(
        spending_authorization_id=authorization.spending_authorization_id,
        amount_usdc=reserved["amount_usdc"],
        destination=reserved["destination"],
        resource=reserved["resource"],
    )
    rpc_calls = []
    service.config.clink_native_facilitator_relayer_private_key = "0x" + "44" * 32
    service.rpc_transport = lambda network, method, params: rpc_calls.append(
        (network, method, params)
    )
    jsonl_before = service.storage_file.read_bytes() if service.storage_file.exists() else b""

    with pytest.raises(ValueError, match="unified authorization provenance"):
        if sink == "receipt":
            service._record_spending_receipt(
                authorization,
                request,
                "0x" + "c" * 64,
                receipt_id="fund_receipt_mismatched_refs",
            )
        else:
            service._prepare_native_transaction(authorization, request)

    jsonl_after = service.storage_file.read_bytes() if service.storage_file.exists() else b""
    assert jsonl_after == jsonl_before
    assert rpc_calls == []


def pending_native_reservation(service: FundingService) -> dict:
    reserved = reserve(service, reservation_request())
    tx_hash = "0x" + "d" * 64
    pending = {
        **reserved,
        "state": "payment_submitted",
        "settlement_rail": "clink_allowance",
        "settlement_sender": SPENDER,
        "settlement_nonce": 1,
        "tx_hash": tx_hash,
        "receipt_id": f"fund_receipt_{reserved['reservation_id']}",
        "reconciliation_status": "pending",
        "next_action": "reconcile_payment",
    }
    with service.ledger.transaction() as tx:
        service._put_reservation(tx, pending, tx_hash=tx_hash)
    return pending


@pytest.mark.parametrize("rpc_path", ["receipt", "rebroadcast"])
def test_native_reconciliation_rejects_forged_caller_scope_before_io(
    context, rpc_path
):
    repository, service = context
    alternate_scope = add_alternate_authorization_scope(repository)
    pending = pending_native_reservation(service)
    forged = {**pending, **alternate_scope}
    rpc_calls = []

    def rpc(network, method, params):
        rpc_calls.append((network, method, params))
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_getTransactionReceipt":
            return None
        if method == "eth_getTransactionByHash":
            return {"hash": params[0]} if rpc_path == "receipt" else None
        if method == "eth_getTransactionCount":
            return "0x1"
        if method == "eth_sendRawTransaction":
            return pending["tx_hash"]
        raise AssertionError(method)

    service.rpc_transport = rpc
    jsonl_before = service.storage_file.read_bytes() if service.storage_file.exists() else b""

    with pytest.raises(ValueError, match="immutable reservation provenance"):
        service._reconcile_native_reservation(forged)

    jsonl_after = service.storage_file.read_bytes() if service.storage_file.exists() else b""
    assert service.get_reservation(pending["reservation_id"]) == pending
    assert jsonl_after == jsonl_before
    assert rpc_calls == []


def test_native_reconciliation_accepts_exact_caller_and_stored_scope(context):
    _, service = context
    pending = pending_native_reservation(service)
    rpc_calls = []

    def rpc(network, method, params):
        rpc_calls.append((network, method, params))
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_getTransactionReceipt":
            return None
        if method == "eth_getTransactionByHash":
            return {"hash": params[0]}
        raise AssertionError(method)

    service.rpc_transport = rpc

    result = service._reconcile_native_reservation(dict(pending))

    assert result["reservation_id"] == pending["reservation_id"]
    assert [(network, method) for network, method, _params in rpc_calls] == [
        ("eip155:137", "eth_chainId"),
        ("eip155:137", "eth_getTransactionReceipt"),
        ("eip155:137", "eth_chainId"),
        ("eip155:137", "eth_getTransactionByHash"),
    ]


def test_native_settlement_rejects_mutated_allowance_scope(tmp_path):
    selected_token = TOKEN
    redirected_token = "0x" + "5" * 40
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    database_url = f"sqlite+pysqlite:///{tmp_path / 'mutated-native.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant(asset_scopes=[selected_token]))
    repository.save_asset_allowance(
        allowance(
            token_address=selected_token,
            token_decimals=3,
            spender_address=relayer,
            approved_amount_atomic=20_000,
            observed_allowance_atomic=20_000,
        )
    )

    def rpc(network, method, params):
        assert network == "eip155:137"
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_getTransactionCount":
            return "0x1"
        if method == "eth_gasPrice":
            return "0x1"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0].removeprefix("0x"))
            return "0x" + keccak(raw).hex()
        if method == "eth_getTransactionReceipt":
            return None
        if method == "eth_getTransactionByHash":
            return {"hash": params[0]}
        raise AssertionError(method)

    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            x402_payment_token_address=TOKEN,
            x402_payment_token_decimals=6,
            clink_native_facilitator_relayer_private_key=relayer_key,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=rpc,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve(service, reservation_request(amount_atomic="2000"))
    repository.save_asset_allowance(
        allowance(
            token_address=redirected_token,
            token_decimals=6,
            spender_address=relayer,
            approved_amount_atomic=20_000_000,
            observed_allowance_atomic=20_000_000,
        )
    )

    with patch(
        "services.funding_service.service.Account.sign_transaction",
        return_value=SimpleNamespace(raw_transaction=b"signed"),
    ), pytest.raises(ValueError, match="immutable allowance scope changed"):
        service.settle_reservation(
            reserved["reservation_id"], SettleSpendingReservationRequest()
        )

    persisted = service.get_reservation(reserved["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted["token_address"] == selected_token
    assert persisted["token_decimals"] == 3
    assert persisted["spender_address"].lower() == relayer.lower()
    assert persisted["amount_atomic"] == "2000"


def test_external_reconciliation_uses_grant_token_without_allowance(tmp_path):
    custom_token = TOKEN
    database_url = f"sqlite+pysqlite:///{tmp_path / 'selected-external.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant(asset_scopes=[custom_token]))
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            x402_payment_token_decimals=6,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(
        service,
        reservation_request(amount_atomic="2000000"),
        token_address=custom_token,
    )
    tx_hash = "0x" + keccak(text="selected-token").hex()
    observe_external_transaction(
        chain, tx_hash, reserved, amount=2_000_000, receipt_status="0x1"
    )

    settled = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reserved),
        ),
    )

    assert settled["state"] == "settled"


@pytest.mark.parametrize("lifecycle", ["identity", "grant"])
def test_external_submission_revalidates_unified_lifecycle(tmp_path, lifecycle):
    database_url = f"sqlite+pysqlite:///{tmp_path / f'{lifecycle}.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(funding_database_url=database_url),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    tx_hash = "0x" + "9" * 64
    observe_external_transaction(chain, tx_hash, reserved)
    if lifecycle == "identity":
        repository.save_wallet_identity(identity(status="revoked"))
        error = "wallet identity"
    elif lifecycle == "grant":
        repository.save_spending_grant(
            grant(status="revoked", reserved_amount_usdc=Decimal("2"))
        )
        error = "spending grant"

    with pytest.raises(ValueError, match=error):
        service.finalize_external_payment(
            reserved["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(reserved),
            ),
        )

    assert service.get_reservation(reserved["reservation_id"])["state"] == "spending_reserved"


@pytest.mark.parametrize("revocation", ["identity", "grant"])
def test_executed_external_payment_reconciles_once_after_authorization_revocation(
    tmp_path, revocation
):
    database_url = f"sqlite+pysqlite:///{tmp_path / f'executed-{revocation}.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    tx_hash = "0x" + keccak(text=f"executed-{revocation}").hex()
    observe_external_transaction(chain, tx_hash, reserved, receipt_status="0x1")

    if revocation == "identity":
        AccountService(
            repository, domain="account.example", clock=lambda: NOW
        ).revoke_wallet_identity("wallet_identity_1")
    else:
        repository.revoke_spending_grant("spending_grant_1", NOW)

    settled = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reserved),
        ),
    )
    replay = service.reconcile_reservation(reserved["reservation_id"])

    with pytest.raises(ValueError, match="WALLET_IDENTITY_REQUIRED|SPENDING_GRANT_REQUIRED"):
        reserve_external(service, reservation_request("purchase_after_revocation"))

    reconciliation_events = [
        event
        for event in AuditService(database_url=database_url)
        .get_trail(user_id="user_1")
        .events
        if event.event_type
        == "external_payment_reconciled_after_authorization_revocation"
    ]
    assert settled["state"] == replay["state"] == "settled"
    assert snapshot(repository)[1:] == (
        Decimal("2"),
        Decimal("0"),
        [(NOW.date(), Decimal("2"), Decimal("0"))],
    )
    assert len(service.ledger.list_records("receipt")) == 1
    assert len(reconciliation_events) == 1
    assert reconciliation_events[0].tx_hash == tx_hash
    assert reconciliation_events[0].payload["reservation_id"] == reserved["reservation_id"]


def test_native_submission_revalidates_unified_lifecycle(context):
    repository, service = context
    reserved = reserve(service, reservation_request())
    repository.save_spending_grant(
        grant(status="paused", reserved_amount_usdc=Decimal("2"))
    )
    prepared = {
        "tx_hash": "0x" + "8" * 64,
        "raw_transaction": "0xsigned",
        "relayer": "0x" + "7" * 40,
        "nonce": 1,
    }

    with patch.object(service, "_prepare_native_transaction", return_value=prepared):
        with pytest.raises(ValueError, match="spending grant"):
            service.settle_reservation(
                reserved["reservation_id"], SettleSpendingReservationRequest()
            )

    assert service.get_reservation(reserved["reservation_id"])["state"] == "spending_reserved"


@pytest.mark.parametrize(
    ("allowance_result", "expected_status"),
    [("0x0", "revoked"), (RuntimeError("RPC offline"), "stale")],
)
def test_native_submission_refreshes_allowance_before_signing_and_fails_closed(
    tmp_path, allowance_result, expected_status
):
    relayer_key = "0x" + "11" * 32
    relayer = Account.from_key(relayer_key).address
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-submit.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance(spender_address=relayer))
    calls = []

    def rpc(network, method, params):
        calls.append((network, method))
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_call":
            if isinstance(allowance_result, Exception):
                raise allowance_result
            return allowance_result
        if method == "eth_getTransactionCount":
            return "0x1"
        if method == "eth_gasPrice":
            return "0x1"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method == "eth_sendRawTransaction":
            return "0x" + keccak(bytes.fromhex(params[0].removeprefix("0x"))).hex()
        if method == "eth_getTransactionReceipt":
            return None
        if method == "eth_getTransactionByHash":
            return {"hash": params[0]}
        raise AssertionError(method)

    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            clink_live_funding=True,
            risk_mode="enforce",
            misttrack_api_key="test-key",
            clink_native_facilitator_enabled=True,
            clink_native_facilitator_relayer_private_key=relayer_key,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        ),
        storage_file=tmp_path / "legacy.jsonl",
        rpc_transport=rpc,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve(service, reservation_request())

    with patch(
        "services.funding_service.service.Account.sign_transaction",
        return_value=SimpleNamespace(raw_transaction=b"signed"),
    ) as sign_transaction, pytest.raises(ValueError, match="allowance"):
        service.settle_reservation(
            reserved["reservation_id"], SettleSpendingReservationRequest()
        )

    persisted = repository.asset_allowance("asset_allowance_1")
    assert persisted.status == expected_status
    events = AuditService(database_url=database_url).get_trail(user_id="user_1").events
    assert [(event.event_type, event.payload["status"]) for event in events] == [
        ("allowance_refreshed", expected_status)
    ]
    assert sign_transaction.call_count == 0
    methods = [method for _network, method in calls]
    assert "eth_getTransactionCount" not in methods
    assert "eth_sendRawTransaction" not in methods


@pytest.mark.parametrize(
    ("status", "status_reason", "expected_status", "expected_reason"),
    [
        ("exhausted", "budget_exhausted", "active", None),
        ("paused", "user_paused", "paused", "user_paused"),
        ("revoked", "user_revoked", "revoked", "user_revoked"),
    ],
)
def test_release_preserves_or_restores_grant_lifecycle(
    context, status, status_reason, expected_status, expected_reason
):
    repository, service = context
    reserved = reserve(service, reservation_request())
    repository.save_spending_grant(
        grant(
            status=status,
            status_reason=status_reason,
            reserved_amount_usdc=Decimal("2"),
        )
    )

    service.release_reservation(
        reserved["reservation_id"], ReleaseSpendingReservationRequest(reason="cancelled")
    )

    assert grant_lifecycle(repository) == (expected_status, expected_reason)


def test_settlement_preserves_revocation_when_budget_becomes_exhausted(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'revoked-exhausted.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(
        grant(
            per_transaction_limit_usdc=Decimal("5"),
            hourly_limit_usdc=Decimal("5"),
            daily_limit_usdc=Decimal("5"),
        )
    )
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request(amount="5"))
    tx_hash = "0x" + keccak(text="revoked-exhausted").hex()
    observe_external_transaction(chain, tx_hash, reserved, amount=5_000_000)
    pending = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reserved, "5000000"),
        ),
    )
    repository.revoke_spending_grant("spending_grant_1", NOW)
    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }

    settled = service.reconcile_reservation(reserved["reservation_id"])

    assert pending["state"] == "payment_submitted"
    assert settled["state"] == "settled"
    assert grant_lifecycle(repository) == ("revoked", "user_revoked")


def test_reconcile_settles_budget_once_and_finalize_does_not_charge_again(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'settle.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    tx_hash = "0x" + keccak(text="settled").hex()
    proof = external_proof(reserved)
    observe_external_transaction(chain, tx_hash, reserved, receipt_status="0x1")

    settled = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(transaction_hash=tx_hash, payment_response=proof),
    )
    replay = service.reconcile_reservation(reserved["reservation_id"])
    finalized = service.finalize_reservation(
        reserved["reservation_id"],
        FinalizeSpendingReservationRequest(delivery_status="delivered"),
    )
    finalize_replay = service.finalize_reservation(
        reserved["reservation_id"],
        FinalizeSpendingReservationRequest(delivery_status="changed"),
    )

    assert settled["state"] == replay["state"] == "settled"
    assert finalized == finalize_replay
    assert snapshot(repository)[1:] == (
        Decimal("2"),
        Decimal("0"),
        [(NOW.date(), Decimal("2"), Decimal("0"))],
    )


def test_payment_submitted_can_reconcile_after_grant_revocation(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'revoked-settle.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    chain = ExternalChain()
    service = FundingService(
        config=AppConfig(
            funding_database_url=database_url,
            x402_payment_token_address=TOKEN,
            clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
            native_min_confirmations=1,
        ),
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    reserved = reserve_external(service, reservation_request())
    tx_hash = "0x" + keccak(text="pending-then-revoked").hex()
    proof = external_proof(reserved)
    observe_external_transaction(chain, tx_hash, reserved)

    pending = service.finalize_external_payment(
        reserved["reservation_id"],
        FinalizeExternalPaymentRequest(transaction_hash=tx_hash, payment_response=proof),
    )
    repository.save_spending_grant(
        grant(status="revoked", reserved_amount_usdc=Decimal("2"))
    )
    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }
    settled = service.reconcile_reservation(reserved["reservation_id"])

    assert pending["state"] == "payment_submitted"
    assert settled["state"] == "settled"
    assert snapshot(repository)[:3] == (
        "revoked",
        Decimal("2"),
        Decimal("0"),
    )
