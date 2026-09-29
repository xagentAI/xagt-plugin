from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import anyio
import httpx
from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from eth_utils import keccak
import rlp

from services.account_service.repository import (
    AccountRepository,
    AuditEventRow,
    SpendingGrantRow,
)
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    FinalizeProxyPaymentRequest,
    FundingReceipt,
    PrepareProxyPaymentRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
)
from services.funding_service.ledger import FundingTransaction, LedgerRow
from services.funding_service.service import FundingService, ReservationProvenance
from shared.config import AppConfig
from shared.evm_rpc import RpcSubmissionRejected


RELAYER_KEY = "0x" + "11" * 32
RECEIPT_SIGNING_KEY = "funding-receipt-test-key-" + "1" * 32
TOKEN = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
DESTINATION = "0x" + "3" * 40
PAYER = "0x" + "2" * 40
TRANSFER_WITH_AUTHORIZATION_SELECTOR = "e3ee160e"
NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
UNSET = object()
NATIVE_PROVENANCE = ReservationProvenance(
    action=SimpleNamespace(user_id="user_1", agent_id="hermes"),
    authorization_path="unified_grant",
    authorization_rail="native_allowance",
    product="marketplace",
    unified_references={
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
    },
)
PREDICTION_NATIVE_PROVENANCE = ReservationProvenance(
    action=SimpleNamespace(user_id="user_1", agent_id="hermes"),
    authorization_path="unified_grant",
    authorization_rail="native_allowance",
    product="prediction_markets",
    unified_references={
        "product": "prediction_markets",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
    },
)
EXTERNAL_PROVENANCE = ReservationProvenance(
    action=SimpleNamespace(user_id="user_1", agent_id="hermes"),
    authorization_path="unified_grant",
    authorization_rail="external_x402",
    product="marketplace",
    unified_references={
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
    },
)
PROXY_PROVENANCE = ReservationProvenance(
    action=SimpleNamespace(user_id="user_1", agent_id="hermes"),
    authorization_path="unified_grant",
    authorization_rail="clink_payer_proxy",
    product="marketplace",
    unified_references={
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
    },
)


class StaticPolicyService:
    def __init__(self, policy) -> None:
        self.policy = policy
        self.lookups: list[str] = []

    def get_decision(self, policy_decision_id: str):
        self.lookups.append(policy_decision_id)
        return self.policy

    def evaluate(self, _request):
        raise AssertionError("Funding must not evaluate policy or call MistTrack")


class FailingPolicyService:
    def get_decision(self, _policy_decision_id: str):
        raise AssertionError("submitted payment recovery must not read policy")

    def evaluate(self, _request):
        raise AssertionError("submitted payment recovery must not evaluate policy")


def policy_for_reservation(request: CreateSpendingReservationRequest):
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
        user_id="user_1",
        agent_id="hermes",
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


class ReceiptMap(dict):
    def __setitem__(self, tx_hash, receipt):
        if not isinstance(receipt, dict):
            super().__setitem__(tx_hash, receipt)
            return
        value = dict(receipt)
        value.setdefault("transactionHash", tx_hash)
        super().__setitem__(tx_hash, value)


class Chain:
    def __init__(self) -> None:
        self.latest = 32
        self.latest_timestamp = int(NOW.timestamp())
        self.authorization_used = False
        self.authorization_state_result: str | None = None
        self.latest_block_result: object = UNSET
        self.nonce = 1
        self.allowance = 10_000_000
        self.raise_after_send = False
        self.reject_before_send: Exception | str | None = None
        self.fail_nonce = False
        self.hide_transactions = False
        self.receipt_on_send: dict | None = None
        self.sent_raw: list[str] = []
        self.rpc_calls: list[str] = []
        self.transactions: dict[str, dict] = {}
        self.receipts: dict[str, dict] = ReceiptMap()

    def __call__(self, network: str, method: str, params: list):
        assert network == "eip155:137"
        self.rpc_calls.append(method)
        if method == "eth_chainId":
            return "0x89"
        if method == "eth_call":
            data = str(params[0].get("data") or "")
            selector = keccak(
                text="authorizationState(address,bytes32)"
            )[:4].hex()
            if data.startswith("0x" + selector):
                assert params[1] == hex(self.latest)
                return self.authorization_state_result or (
                    "0x" + format(int(self.authorization_used), "064x")
                )
            return hex(self.allowance)
        if method == "eth_getBlockByNumber":
            assert params == ["finalized", False]
            return {
                "number": hex(self.latest),
                "timestamp": hex(self.latest_timestamp),
            }
        if method == "eth_getTransactionCount":
            if self.fail_nonce:
                raise RuntimeError("nonce RPC unavailable")
            return hex(self.nonce)
        if method == "eth_gasPrice":
            return hex(1_000_000_000)
        if method == "eth_estimateGas":
            return hex(100_000)
        if method == "eth_sendRawTransaction":
            if self.reject_before_send:
                if isinstance(self.reject_before_send, Exception):
                    raise self.reject_before_send
                raise RuntimeError(self.reject_before_send)
            raw = params[0]
            tx_hash = "0x" + keccak(bytes.fromhex(raw.removeprefix("0x"))).hex()
            self.sent_raw.append(raw)
            decoded = rlp.decode(
                bytes.fromhex(raw.removeprefix("0x")), Transaction
            )
            self.transactions[tx_hash] = {
                "hash": tx_hash,
                "from": Account.recover_transaction(raw),
                "nonce": hex(decoded.nonce),
                "to": "0x" + decoded.to.hex(),
                "input": "0x" + decoded.data.hex(),
            }
            self.nonce += 1
            if self.receipt_on_send is not None:
                self.receipts[tx_hash] = dict(self.receipt_on_send)
            if self.raise_after_send:
                self.raise_after_send = False
                raise RuntimeError("connection reset after transaction submission")
            return tx_hash
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(params[0])
        if method == "eth_getTransactionByHash":
            if self.hide_transactions:
                return None
            return self.transactions.get(params[0])
        if method == "eth_blockNumber":
            return (
                self.latest_block_result
                if self.latest_block_result is not UNSET
                else hex(self.latest)
            )
        raise AssertionError(f"unexpected RPC method: {method}")


def seed_unified_authorization(
    database_url: str, *, include_allowance: bool, product: str = "marketplace"
) -> None:
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_1",
            user_id="user_1",
            wallet_address=PAYER,
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
            max_amount_usdc=Decimal("20"),
            per_transaction_limit_usdc=Decimal("20"),
            daily_limit_usdc=Decimal("20"),
            product_scopes=[product],
            venue_scopes=["clink_marketplace"],
            merchant_scopes=["merchant_1"],
            network_scopes=["eip155:137"],
            asset_scopes=[TOKEN],
            starts_at=datetime(2026, 7, 1, tzinfo=UTC),
            expires_at=datetime(2026, 8, 1, tzinfo=UTC),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    if include_allowance:
        repository.save_asset_allowance(
            AssetAllowance(
                asset_allowance_id="allowance_1",
                wallet_identity_id="wallet_1",
                network="eip155:137",
                token_address=TOKEN,
                token_symbol="USDC",
                token_decimals=6,
                spender_address=Account.from_key(RELAYER_KEY).address,
                approved_amount_atomic=10_000_000,
                observed_allowance_atomic=10_000_000,
                status="active",
                confirmed_block=1,
                last_chain_check_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def reservation_request(
    purchase_id: str = "purchase_1",
    *,
    authorization_rail: str = "external_x402",
    amount_usdc: str = "3",
    product: str = "marketplace",
) -> CreateSpendingReservationRequest:
    uses_allowance = authorization_rail in {"native_allowance", "clink_payer_proxy"}
    return CreateSpendingReservationRequest(
        purchase_id=purchase_id,
        idempotency_key=purchase_id,
        authorization_rail=authorization_rail,
        wallet_identity_id="wallet_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1" if uses_allowance else None,
        token_address=None if uses_allowance else TOKEN,
        product=product,
        action_id=f"action_{purchase_id}",
        policy_decision_id=f"policy_{purchase_id}",
        merchant_id="merchant_1",
        quote_hash="0x" + "a" * 64,
        amount_usdc=amount_usdc,
        amount_atomic=str(int(Decimal(amount_usdc) * 1_000_000)),
        network="eip155:137",
        asset=TOKEN.lower(),
        merchant_trust_tier=(
            "clink_verified" if product == "marketplace" else None
        ),
        destination=DESTINATION,
        resource="https://merchant.example/api",
        venue="clink_marketplace",
    )


def service_and_reservation(
    tmp_path,
    chain: Chain,
    purchase_id="purchase_1",
    *,
    min_confirmations=1,
    reconciliation_max_attempts=12,
    reconciliation_max_age_seconds=3600,
    authorization_rail="external_x402",
    amount_usdc="3",
    product="marketplace",
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}"
    seed_unified_authorization(
        database_url,
        include_allowance=authorization_rail in {"native_allowance", "clink_payer_proxy"},
        product=product,
    )
    config = AppConfig(
        funding_database_url=database_url,
        clink_live_funding=authorization_rail in {"native_allowance", "clink_payer_proxy"},
        clink_native_facilitator_enabled=authorization_rail in {"native_allowance", "clink_payer_proxy"},
        clink_native_facilitator_relayer_private_key=RELAYER_KEY,
        clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        x402_payment_token_address=TOKEN,
        risk_mode="enforce",
        misttrack_api_key="test-key",
        native_min_confirmations=min_confirmations,
        payment_reconciliation_max_attempts=reconciliation_max_attempts,
        payment_reconciliation_max_age_seconds=reconciliation_max_age_seconds,
    )
    request = reservation_request(
        purchase_id,
        authorization_rail=authorization_rail,
        amount_usdc=amount_usdc,
        product=product,
    )
    policy_service = StaticPolicyService(policy_for_reservation(request))
    service = FundingService(
        config=config,
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=chain,
        policy_service=policy_service,
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    with patch.object(
        service,
        "_verify_marketplace_provenance",
        return_value=(
            PROXY_PROVENANCE
            if authorization_rail == "clink_payer_proxy"
            else PREDICTION_NATIVE_PROVENANCE
            if product == "prediction_markets"
            else NATIVE_PROVENANCE
            if authorization_rail == "native_allowance"
            else EXTERNAL_PROVENANCE
        ),
    ):
        reservation = service.reserve_spending(request)
    return service, reservation


def native_payment_authorization(
    amount_usdc: str = "3",
) -> SettleSpendingReservationRequest:
    return SettleSpendingReservationRequest(
        payment_authorization={
            "scheme": "exact",
            "network": "eip155:137",
            "asset": TOKEN.lower(),
            "amount_atomic": str(int(Decimal(amount_usdc) * 1_000_000)),
            "pay_to": DESTINATION,
        }
    )


def external_proof(reservation: dict | None = None) -> dict:
    challenge = reservation or {
        "nonce": "0x" + "11" * 32,
        "valid_after": "0",
        "valid_before": str(2**256 - 1),
    }
    return {
        "network": "eip155:137",
        "asset": TOKEN.lower(),
        "amount_atomic": "3000000",
        "pay_to": DESTINATION,
        "nonce": challenge["nonce"],
        "valid_after": challenge["valid_after"],
        "valid_before": challenge["valid_before"],
        "signature": "0xsigned",
    }


def test_external_payment_input_is_immediately_canonicalized_and_discards_extras():
    request = FinalizeExternalPaymentRequest(
        transaction_hash="0x" + "70" * 32,
        payment_response={
            **external_proof(),
            "headers": {"PAYMENT-SIGNATURE": "header-secret"},
            "merchant_payload": {"nested": {"secret": "merchant-secret"}},
            "proof": "proof-secret",
        },
    )

    serialized = request.model_dump()["payment_response"]
    assert serialized == {
        "network": "eip155:137",
        "asset": TOKEN.lower(),
        "amount_atomic": "3000000",
        "pay_to": DESTINATION,
        "nonce": "0x" + "11" * 32,
        "valid_after": "0",
        "valid_before": str(2**256 - 1),
    }
    assert "secret" not in json.dumps(request.model_dump()).lower()


def test_external_reservations_issue_unique_bounded_eip3009_challenges(tmp_path):
    chain = Chain()
    service, first = service_and_reservation(tmp_path, chain, "purchase_1")
    with patch.object(
        service,
        "_verify_marketplace_provenance",
        return_value=EXTERNAL_PROVENANCE,
    ):
        second = service.reserve_spending(reservation_request("purchase_2"))

    now_epoch = int(NOW.timestamp())
    for reservation in (first, second):
        assert reservation["nonce"].startswith("0x")
        assert len(reservation["nonce"]) == 66
        int(reservation["nonce"][2:], 16)
        assert int(reservation["valid_after"]) <= now_epoch
        assert int(reservation["valid_before"]) > now_epoch
        assert 0 < int(reservation["valid_before"]) - int(
            reservation["valid_after"]
        ) <= 3600
    assert first["nonce"] != second["nonce"]


def test_external_reservation_challenge_is_immutable(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)

    with pytest.raises(ValueError, match="immutable reservation"):
        with service.ledger.transaction() as tx:
            current = tx.get(reservation["reservation_id"])
            service._put_reservation(
                tx,
                {**current, "nonce": "0x" + "ff" * 32},
            )


def eip3009_calldata(
    *,
    payer: str = PAYER,
    recipient: str = DESTINATION,
    amount: int = 3_000_000,
    valid_after: int = 0,
    valid_before: int = 2**256 - 1,
    nonce: str = "0x" + "11" * 32,
) -> str:
    address_word = lambda value: value.removeprefix("0x").rjust(64, "0")
    uint_word = lambda value: hex(value)[2:].rjust(64, "0")
    words = (
        address_word(payer),
        address_word(recipient),
        uint_word(amount),
        uint_word(valid_after),
        uint_word(valid_before),
        nonce.removeprefix("0x"),
        uint_word(27),
        "22" * 32,
        "33" * 32,
    )
    return "0x" + TRANSFER_WITH_AUTHORIZATION_SELECTOR + "".join(words)


def replace_calldata_word(calldata: str, index: int, word: str) -> str:
    start = 10 + (index * 64)
    return calldata[:start] + word + calldata[start + 64 :]


def successful_external_transaction(
    chain: Chain,
    tx_hash: str,
    *,
    reservation: dict | None = None,
    calldata: str | None = None,
) -> None:
    if calldata is None and reservation is not None:
        calldata = eip3009_calldata(
            valid_after=int(reservation["valid_after"]),
            valid_before=int(reservation["valid_before"]),
            nonce=reservation["nonce"],
        )
    chain.transactions[tx_hash] = {
        "hash": tx_hash,
        "to": TOKEN,
        "input": calldata or eip3009_calldata(),
    }
    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }


def test_proxy_payment_finalizes_once_without_second_user_debit(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="clink_payer_proxy",
    )
    reimbursement_hash = "0x" + "81" * 32
    with service.ledger.transaction() as tx:
        current = tx.get(reservation["reservation_id"])
        current = tx.settle_unified_budget(current, now=NOW.replace(tzinfo=None))
        service._put_reservation(
            tx,
            {
                **current,
                "state": "payer_funded",
                "reimbursement_tx_hash": reimbursement_hash,
                "reconciliation_status": "settled",
                "next_action": "prepare_proxy_payment",
            },
            tx_hash=reimbursement_hash,
        )
    prepared = service.prepare_proxy_payment(
        reservation["reservation_id"],
        PrepareProxyPaymentRequest(**{
            "payment_requirement": {
                "scheme": "exact",
                "network": "eip155:137",
                "asset": TOKEN,
                "amount_atomic": "3000000",
                "pay_to": DESTINATION,
                "resource": "https://merchant.example/api",
                "token_name": "USD Coin",
                "token_version": "2",
            }
        }),
    )
    merchant_hash = "0x" + "82" * 32
    calldata = eip3009_calldata(
        payer=prepared["payer_address"],
        amount=3_000_000,
        valid_after=int(prepared["proxy_valid_after"]),
        valid_before=int(prepared["proxy_valid_before"]),
        nonce=prepared["proxy_nonce"],
    )
    successful_external_transaction(chain, merchant_hash, calldata=calldata)
    request = FinalizeProxyPaymentRequest(
        transaction_hash=merchant_hash,
        payment_response={
            "network": "eip155:137",
            "asset": TOKEN,
            "amount_atomic": "3000000",
            "pay_to": DESTINATION,
            "nonce": prepared["proxy_nonce"],
            "valid_after": prepared["proxy_valid_after"],
            "valid_before": prepared["proxy_valid_before"],
        },
    )

    settled = service.finalize_proxy_payment(reservation["reservation_id"], request)
    replay = service.finalize_proxy_payment(reservation["reservation_id"], request)

    assert settled == replay
    assert settled["state"] == "settled"
    assert settled["tx_hash"] == merchant_hash
    assert settled["reimbursement_tx_hash"] == reimbursement_hash
    assert settled["receipt"]["tx_hash"] == merchant_hash
    repository = AccountRepository(service.config.funding_database_url)
    with repository.sessions() as session:
        grant_row = session.get(SpendingGrantRow, "grant_1")
        assert grant_row.used_amount_usdc == Decimal("3")
        assert grant_row.reserved_amount_usdc == Decimal("0")


def test_expired_proxy_authorization_rotates_only_when_chain_proves_unused(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="clink_payer_proxy",
    )
    reimbursement_hash = "0x" + "83" * 32
    with service.ledger.transaction() as tx:
        current = tx.get(reservation["reservation_id"])
        current = tx.settle_unified_budget(current, now=NOW.replace(tzinfo=None))
        service._put_reservation(
            tx,
            {
                **current,
                "state": "payer_funded",
                "reimbursement_tx_hash": reimbursement_hash,
            },
            tx_hash=reimbursement_hash,
        )
    request = PrepareProxyPaymentRequest(
        payment_requirement={
            "scheme": "exact",
            "network": "eip155:137",
            "asset": TOKEN,
            "amount_atomic": "3000000",
            "pay_to": DESTINATION,
            "resource": "https://merchant.example/api",
            "token_name": "USD Coin",
            "token_version": "2",
        }
    )
    prepared = service.prepare_proxy_payment(reservation["reservation_id"], request)
    service._proxy_authorization_expired = lambda _reservation: True
    chain.latest_timestamp = int(prepared["proxy_valid_before"]) + 1

    chain.authorization_used = True
    with pytest.raises(ValueError, match="already consumed"):
        service.prepare_proxy_payment(reservation["reservation_id"], request)

    chain.authorization_state_result = "0"
    with pytest.raises(RuntimeError, match="authorizationState result is invalid"):
        service.prepare_proxy_payment(reservation["reservation_id"], request)

    chain.authorization_state_result = None
    chain.authorization_used = False
    renewed = service.prepare_proxy_payment(reservation["reservation_id"], request)
    assert renewed["proxy_nonce"] != prepared["proxy_nonce"]


@pytest.mark.parametrize(
    "rpc_result",
    [
        "rpc_error",
        None,
        {},
        {"hash": "requested", "to": TOKEN},
        {"hash": "requested", "input": "valid"},
        {"hash": "mismatched", "to": TOKEN, "input": "valid"},
    ],
    ids=(
        "rpc-error",
        "missing-transaction",
        "missing-all-fields",
        "missing-input",
        "missing-to",
        "mismatched-hash",
    ),
)
def test_external_finalize_requires_complete_hash_bound_transaction_before_mutation(
    tmp_path, rpc_result
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "76" * 32
    calldata = eip3009_calldata(
        valid_after=int(reservation["valid_after"]),
        valid_before=int(reservation["valid_before"]),
        nonce=reservation["nonce"],
    )
    original_rpc_call = service._rpc_call

    def rpc_call(network, method, params):
        if method != "eth_getTransactionByHash":
            return original_rpc_call(network, method, params)
        if rpc_result == "rpc_error":
            raise RuntimeError("transaction lookup unavailable")
        if not isinstance(rpc_result, dict):
            return rpc_result
        observed = dict(rpc_result)
        observed["hash"] = {
            "requested": tx_hash,
            "mismatched": "0x" + "77" * 32,
        }.get(observed.get("hash"), observed.get("hash"))
        if observed.get("input") == "valid":
            observed["input"] = calldata
        return observed

    with patch.object(service, "_rpc_call", side_effect=rpc_call):
        with pytest.raises(
            ValueError,
            match="external payment transaction does not match reservation challenge",
        ):
            service.finalize_external_payment(
                reservation["reservation_id"],
                FinalizeExternalPaymentRequest(
                    transaction_hash=tx_hash,
                    payment_response=external_proof(reservation),
                ),
            )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted["tx_hash"] is None
    with service.ledger.transaction() as tx:
        assert tx.by_tx_hash(tx_hash) is None


def test_external_eip3009_calldata_is_decoded_before_settlement(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    assert service.config.clink_live_funding is False
    assert service.config.clink_native_facilitator_enabled is False
    tx_hash = "0x" + "71" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)

    settled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash, payment_response=external_proof(reservation)
        ),
    )

    assert settled["state"] == "settled"
    assert settled["reconciliation_status"] == "settled"
    proof_identity = {
        "transaction_hash": tx_hash,
        **service._canonical_external_payment_scope(external_proof(reservation)),
    }
    expected_hash = "0x" + keccak(
        json.dumps(
            proof_identity, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hex()
    assert settled["payment_proof_hash"] == expected_hash


def test_external_eip3009_accepts_cdp_facilitator_attribution_suffix(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "72" * 32
    attribution_suffix = (
        "a161776a6364705f666163696c31"
        "000e0280218021802180218021802180218021"
    )
    calldata = eip3009_calldata(
        valid_after=int(reservation["valid_after"]),
        valid_before=int(reservation["valid_before"]),
        nonce=reservation["nonce"],
    ) + attribution_suffix
    successful_external_transaction(chain, tx_hash, calldata=calldata)

    settled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )

    assert settled["state"] == "settled"
    assert settled["tx_hash"] == tx_hash


@pytest.mark.parametrize(
    "attribution_suffix",
    [
        "a161776a6364705f666163696c31",
        (
            "a161776a6364705f666163696c31"
            "000e0280218021802180218021802180218021"
            "deadbeef"
        ),
    ],
    ids=("truncated", "extra-bytes"),
)
def test_external_eip3009_rejects_malformed_cdp_attribution_suffix(
    tmp_path, attribution_suffix
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + keccak(text=attribution_suffix).hex()
    calldata = eip3009_calldata(
        valid_after=int(reservation["valid_after"]),
        valid_before=int(reservation["valid_before"]),
        nonce=reservation["nonce"],
    ) + attribution_suffix
    successful_external_transaction(chain, tx_hash, calldata=calldata)

    with pytest.raises(ValueError, match="does not match reservation challenge"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(reservation),
            ),
        )


@pytest.mark.parametrize(
    "invalid_hash_field",
    [
        "missing-receipt-hash",
        "mismatched-receipt-hash",
        "missing-transaction-hash",
        "mismatched-transaction-hash",
    ],
)
def test_external_reconciliation_requires_receipt_and_transaction_hash_authority(
    tmp_path, invalid_hash_field
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "78" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    chain.receipts.pop(tx_hash)

    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    assert pending["state"] == "payment_submitted"

    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }
    if invalid_hash_field == "missing-receipt-hash":
        chain.receipts[tx_hash].pop("transactionHash")
    elif invalid_hash_field == "mismatched-receipt-hash":
        chain.receipts[tx_hash]["transactionHash"] = "0x" + "79" * 32
    elif invalid_hash_field == "missing-transaction-hash":
        chain.transactions[tx_hash].pop("hash")
    else:
        chain.transactions[tx_hash]["hash"] = "0x" + "79" * 32

    reconciled = service.reconcile_reservation(reservation["reservation_id"])

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled["next_action"] == "operator_reconcile"
    assert reconciled["tx_hash"] == tx_hash
    assert reconciled.get("receipt") is None


@pytest.mark.parametrize(
    "block_number",
    [None, "0x_20", "0x020", "0xA", "32", 32],
    ids=(
        "missing",
        "underscore",
        "leading-zero",
        "uppercase",
        "decimal-string",
        "non-string",
    ),
)
def test_external_success_receipt_with_invalid_block_number_never_settles(
    tmp_path, block_number
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "7d" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    if block_number is None:
        chain.receipts[tx_hash].pop("blockNumber")
    else:
        chain.receipts[tx_hash]["blockNumber"] = block_number

    reconciled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled["next_action"] == "operator_reconcile"
    assert reconciled["tx_hash"] == tx_hash
    assert reconciled["budget_accounting_state"] == "reserved"
    assert reconciled.get("receipt") is None
    grant = AccountRepository(service.config.funding_database_url).spending_grant(
        "grant_1"
    )
    assert grant.reserved_amount_usdc == Decimal("3")
    assert grant.used_amount_usdc == Decimal("0")


@pytest.mark.parametrize(
    "latest_block",
    [None, "0x_20", "0x020", "0xA", "32", 32],
    ids=(
        "missing",
        "underscore",
        "leading-zero",
        "uppercase",
        "decimal-string",
        "non-string",
    ),
)
def test_external_success_receipt_with_invalid_latest_block_never_settles(
    tmp_path, latest_block
):
    chain = Chain()
    chain.latest_block_result = latest_block
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "7c" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)

    reconciled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled["next_action"] == "operator_reconcile"
    assert reconciled["tx_hash"] == tx_hash
    assert reconciled["budget_accounting_state"] == "reserved"
    assert reconciled.get("receipt") is None
    grant = AccountRepository(service.config.funding_database_url).spending_grant(
        "grant_1"
    )
    assert grant.reserved_amount_usdc == Decimal("3")
    assert grant.used_amount_usdc == Decimal("0")


@pytest.mark.parametrize("corruption", ["missing-input", "scope-mismatch"])
def test_external_success_receipt_with_unverifiable_scope_never_allows_repayment(
    tmp_path, corruption
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "7e" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    chain.receipts.pop(tx_hash)
    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    assert pending["state"] == "payment_submitted"

    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }
    if corruption == "missing-input":
        chain.transactions[tx_hash].pop("input")
    else:
        chain.transactions[tx_hash]["input"] = eip3009_calldata(
            amount=2_000_000,
            valid_after=int(reservation["valid_after"]),
            valid_before=int(reservation["valid_before"]),
            nonce=reservation["nonce"],
        )

    reconciled = service.reconcile_reservation(reservation["reservation_id"])

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled["next_action"] == "operator_reconcile"
    assert reconciled["tx_hash"] == tx_hash
    assert reconciled.get("receipt") is None

    replacement_hash = "0x" + "7f" * 32
    successful_external_transaction(
        chain, replacement_hash, reservation=reservation
    )
    with pytest.raises(ValueError, match="different transaction is pending"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=replacement_hash,
                payment_response=external_proof(reservation),
            ),
        )


@pytest.mark.parametrize(
    "rpc_failure",
    [
        "receipt-rpc-error",
        "malformed-receipt",
        "transaction-rpc-error",
        "missing-transaction",
    ],
)
def test_external_reconciliation_reserves_pending_only_for_not_yet_mined_receipt(
    tmp_path, rpc_failure
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "7c" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    chain.receipts.pop(tx_hash)
    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    assert pending["reconciliation_status"] == "pending"

    chain.receipts[tx_hash] = {
        "transactionHash": tx_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }
    if rpc_failure == "malformed-receipt":
        chain.receipts[tx_hash] = "malformed"
    elif rpc_failure == "missing-transaction":
        chain.transactions.pop(tx_hash)
    original_rpc_call = service._rpc_call

    def rpc_call(network, method, params):
        if rpc_failure == "receipt-rpc-error" and method == "eth_getTransactionReceipt":
            raise RuntimeError("receipt lookup unavailable")
        if (
            rpc_failure == "transaction-rpc-error"
            and method == "eth_getTransactionByHash"
        ):
            raise RuntimeError("transaction lookup unavailable")
        return original_rpc_call(network, method, params)

    with patch.object(service, "_rpc_call", side_effect=rpc_call):
        reconciled = service.reconcile_reservation(reservation["reservation_id"])

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled["next_action"] == "operator_reconcile"
    assert reconciled["tx_hash"] == tx_hash
    assert reconciled.get("receipt") is None


@pytest.mark.parametrize(
    ("live_enabled", "facilitator_enabled", "message"),
    [
        (False, True, "CLINK_LIVE_FUNDING"),
        (True, False, "CLINK_NATIVE_FACILITATOR_ENABLED"),
    ],
)
def test_native_kill_switch_blocks_before_any_rpc_or_nonce_allocation(
    tmp_path, live_enabled, facilitator_enabled, message
):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    service.config.clink_live_funding = live_enabled
    service.config.clink_native_facilitator_enabled = facilitator_enabled

    with pytest.raises(RuntimeError, match=message):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert chain.rpc_calls == []
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("settlement_nonce") is None


def test_native_settlement_requires_receipt_authority_before_any_rpc(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    service.config.clink_receipt_signing_key = ""

    with pytest.raises(RuntimeError, match="CLINK_RECEIPT_SIGNING_KEY is required"):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert chain.rpc_calls == []
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("settlement_nonce") is None


@pytest.mark.parametrize(
    "disabled_field",
    [
        "clink_live_funding",
        "clink_native_facilitator_enabled",
    ],
)
def test_missing_native_transaction_does_not_rebroadcast_when_native_is_disabled(
    tmp_path, disabled_field
):
    chain = Chain()
    chain.raise_after_send = True
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    assert pending["state"] == "payment_submitted"
    assert len(chain.sent_raw) == 1

    original_transaction = chain.transactions[pending["tx_hash"]]
    chain.transactions.clear()
    chain.nonce = int(pending["settlement_nonce"])
    setattr(service.config, disabled_field, False)
    sends_before_reconcile = chain.rpc_calls.count("eth_sendRawTransaction")

    blocked = service.reconcile_reservation(reservation["reservation_id"])

    assert blocked["state"] == "payment_submitted"
    assert blocked["reconciliation_status"] == "manual_review_required"
    assert blocked["last_reconciliation_error"] == (
        "native transaction cannot be found; replacement is forbidden"
    )
    assert chain.rpc_calls.count("eth_sendRawTransaction") == sends_before_reconcile
    assert len(chain.sent_raw) == 1

    setattr(service.config, disabled_field, True)
    chain.transactions[pending["tx_hash"]] = original_transaction
    chain.receipts[pending["tx_hash"]] = {"status": "0x1", "blockNumber": "0x20"}
    settled_native = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )
    assert settled_native["state"] == "settled"

    external_dir = tmp_path / "external"
    external_dir.mkdir()
    external_chain = Chain()
    external_service, external_reservation = service_and_reservation(
        external_dir, external_chain
    )
    external_hash = "0x" + "7b" * 32
    successful_external_transaction(
        external_chain, external_hash, reservation=external_reservation
    )
    external_chain.receipts.pop(external_hash)
    pending_external = external_service.finalize_external_payment(
        external_reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=external_hash,
            payment_response=external_proof(external_reservation),
        ),
    )
    assert external_service.config.clink_live_funding is False
    assert external_service.config.clink_native_facilitator_enabled is False
    assert pending_external["state"] == "payment_submitted"

    external_chain.receipts[external_hash] = {
        "transactionHash": external_hash,
        "status": "0x1",
        "blockNumber": "0x20",
    }
    settled_external = external_service.reconcile_reservation(
        external_reservation["reservation_id"]
    )
    assert settled_external["state"] == "settled"
    assert "eth_sendRawTransaction" not in external_chain.rpc_calls


def test_native_credentials_are_guarded_by_kill_switch(tmp_path):
    chain = Chain()
    service, _reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    service.config.clink_native_facilitator_enabled = False

    with pytest.raises(RuntimeError, match="CLINK_NATIVE_FACILITATOR_ENABLED"):
        service._native_relayer_credentials()


def test_partial_allowance_stays_active_and_funds_smaller_later_payment(tmp_path):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x1", "blockNumber": "0x20"}
    service, first = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        amount_usdc="2",
    )

    first_settled = service.settle_reservation(
        first["reservation_id"], native_payment_authorization("2")
    )
    chain.allowance = 8_000_000
    second_request = reservation_request(
        "purchase_2",
        authorization_rail="native_allowance",
        amount_usdc="3",
    )
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=NATIVE_PROVENANCE
    ):
        second = service.reserve_spending(second_request)
    service.policy_service.policy = policy_for_reservation(second_request)
    second_settled = service.settle_reservation(
        second["reservation_id"], native_payment_authorization("3")
    )

    persisted_allowance = AccountRepository(
        service.config.funding_database_url
    ).asset_allowance("allowance_1")
    assert first_settled["state"] == second_settled["state"] == "settled"
    assert persisted_allowance.status == "active"
    assert persisted_allowance.observed_allowance_atomic == 8_000_000
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=NATIVE_PROVENANCE
    ):
        with pytest.raises(ValueError, match="ASSET_ALLOWANCE_REQUIRED"):
            service.reserve_spending(
                reservation_request(
                    "purchase_3",
                    authorization_rail="native_allowance",
                    amount_usdc="9",
                )
            )


def test_native_submission_requires_allowance_for_exact_reservation_amount(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    chain.allowance = 2_000_000

    with pytest.raises(ValueError, match="insufficient before submission"):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    persisted_allowance = AccountRepository(
        service.config.funding_database_url
    ).asset_allowance("allowance_1")
    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted_allowance.status == "active"
    assert persisted_allowance.observed_allowance_atomic == 2_000_000
    assert persisted["state"] == "spending_reserved"
    assert persisted.get("settlement_nonce") is None
    assert "eth_getTransactionCount" not in chain.rpc_calls
    assert "eth_sendRawTransaction" not in chain.rpc_calls


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("nonce", "0x" + "99" * 32),
        ("valid_after", str(int(NOW.timestamp()) - 61)),
        ("valid_before", str(int(NOW.timestamp()) + 901)),
    ],
)
def test_external_proof_requires_exact_reservation_challenge_before_rpc(
    tmp_path, field, replacement
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    proof = {**external_proof(reservation), field: replacement}

    with pytest.raises(ValueError, match="external payment scope mismatch"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash="0x" + "72" * 32,
                payment_response=proof,
            ),
        )

    assert chain.rpc_calls == []


@pytest.mark.parametrize(
    ("word_index", "replacement", "message"),
    [
        (3, hex(int(NOW.timestamp()) - 61)[2:].rjust(64, "0"), "validAfter"),
        (4, hex(int(NOW.timestamp()) + 901)[2:].rjust(64, "0"), "validBefore"),
        (5, "99" * 32, "nonce"),
    ],
)
def test_external_calldata_requires_exact_reservation_challenge(
    tmp_path, word_index, replacement, message
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    calldata = eip3009_calldata(
        valid_after=int(reservation["valid_after"]),
        valid_before=int(reservation["valid_before"]),
        nonce=reservation["nonce"],
    )
    calldata = replace_calldata_word(calldata, word_index, replacement)
    tx_hash = "0x" + keccak(text=calldata).hex()
    successful_external_transaction(chain, tx_hash, calldata=calldata)

    with pytest.raises(ValueError, match="does not match reservation challenge"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(reservation),
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted["tx_hash"] is None


def test_legacy_external_reservation_without_challenge_fails_closed_before_rpc(
    tmp_path,
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    with service.ledger.sessions.begin() as session:
        row = session.get(LedgerRow, reservation["reservation_id"])
        row.payload = {
            key: value
            for key, value in row.payload.items()
            if key not in {"nonce", "valid_after", "valid_before"}
        }

    with pytest.raises(ValueError, match="legacy reservation is read-only"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash="0x" + "73" * 32,
                payment_response=external_proof(reservation),
            ),
        )

    assert chain.rpc_calls == []


def test_historical_external_transfer_cannot_be_claimed_by_another_reservation(
    tmp_path,
):
    chain = Chain()
    service, first = service_and_reservation(tmp_path, chain)
    with patch.object(
        service,
        "_verify_marketplace_provenance",
        return_value=EXTERNAL_PROVENANCE,
    ):
        second = service.reserve_spending(reservation_request("purchase_2"))
    tx_hash = "0x" + "74" * 32
    successful_external_transaction(chain, tx_hash, reservation=first)

    with pytest.raises(ValueError, match="does not match reservation challenge"):
        service.finalize_external_payment(
            second["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(second),
            ),
        )

    settled = service.finalize_external_payment(
        first["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(first),
        ),
    )
    assert settled["state"] == "settled"


def test_receipt_authority_uses_only_independent_signing_key(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    service.config.clink_internal_api_token = "internal-api-secret"
    service.config.clink_receipt_signing_key = "receipt-signing-secret-" + "2" * 32
    tx_hash = "0x" + "75" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)

    settled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    receipt = FundingReceipt.model_validate(settled["receipt"])

    service.config.clink_internal_api_token = "rotated-internal-api-secret"
    assert service.verify_receipt_signature(receipt) is True
    service.config.clink_receipt_signing_key = (
        "rotated-receipt-signing-secret-" + "3" * 32
    )
    assert service.verify_receipt_signature(receipt) is False


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    [
        ("receipt_id", "fund_receipt_forged"),
        ("reservation_id", "reserve_forged"),
        ("spending_authorization_id", "grant_forged"),
        ("spending_grant_id", "grant_forged"),
        ("asset_allowance_id", "allowance_forged"),
        ("wallet_identity_id", "wallet_forged"),
        ("authorization_rail", "external_x402"),
        ("user_id", "user_forged"),
        ("agent_id", "agent_forged"),
        ("action_id", "action_forged"),
        ("policy_decision_id", "policy_forged"),
        ("purchase_id", "purchase_forged"),
        ("merchant_id", "merchant_forged"),
        ("quote_hash", "0x" + "f" * 64),
        ("wallet_address", "0x" + "4" * 40),
        ("destination", "0x" + "5" * 40),
        ("resource", "https://attacker.example/resource"),
        ("amount_usdc", "4"),
        ("amount_atomic", "4000000"),
        ("venue", "forged_venue"),
        ("product", "prediction_markets"),
        ("chain", "eip155:8453"),
        ("token", "FORGED"),
        ("token_address", "0x" + "6" * 40),
        ("token_decimals", 18),
        ("tx_hash", "0x" + "7" * 64),
        ("status", "pending"),
        ("next_action", "forged_action"),
        ("created_at", "2026-07-15T12:01:00Z"),
    ],
)
def test_receipt_signature_binds_complete_authorization_and_audit_provenance(
    tmp_path, field, mutated_value
):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x1", "blockNumber": "0x20"}
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    settled = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    receipt = FundingReceipt.model_validate(settled["receipt"])

    if field in FundingReceipt.model_fields:
        tampered = receipt.model_copy(update={field: mutated_value})
    else:
        assert field in receipt.metadata
        tampered = receipt.model_copy(
            update={"metadata": {**receipt.metadata, field: mutated_value}}
        )

    assert service.verify_receipt_signature(receipt) is True
    assert service.verify_receipt_signature(tampered) is False


def test_receipt_signature_binds_event_log(tmp_path):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x1", "blockNumber": "0x20"}
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    settled = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    receipt = FundingReceipt.model_validate(settled["receipt"])
    tampered = receipt.model_copy(
        update={
            "event_log": [
                {**receipt.event_log[0], "status": "forged"},
                *receipt.event_log[1:],
            ]
        }
    )

    assert service.verify_receipt_signature(receipt) is True
    assert service.verify_receipt_signature(tampered) is False


@pytest.mark.parametrize(
    ("receipt_key", "internal_token"),
    [
        ("", "internal-api-token-" + "4" * 32),
        ("short-receipt-key", "internal-api-token-" + "4" * 32),
        (
            "replace-with-a-different-long-random-secret",
            "internal-api-token-" + "4" * 32,
        ),
        ("shared-authority-secret-" + "5" * 32, "shared-authority-secret-" + "5" * 32),
    ],
    ids=("missing", "weak", "placeholder", "internal-token-reuse"),
)
def test_settlement_never_persists_unsigned_or_non_independent_receipt(
    tmp_path, receipt_key, internal_token
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    service.config.clink_receipt_signing_key = receipt_key
    service.config.clink_internal_api_token = internal_token
    tx_hash = "0x" + "7a" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)

    with pytest.raises(RuntimeError, match="CLINK_RECEIPT_SIGNING_KEY"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(reservation),
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "payment_submitted"
    assert persisted.get("receipt") is None
    assert service._load_latest("receipt") == {}


def test_external_payment_secrets_never_reach_api_database_or_audit(
    tmp_path, monkeypatch
):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + "73" * 32
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    sensitive_values = {
        "signature-secret",
        "header-secret",
        "merchant-secret",
        "nested-secret",
        "proof-secret",
    }
    payment_response = {
        **external_proof(reservation),
        "signature": "signature-secret",
        "headers": {"PAYMENT-SIGNATURE": "header-secret"},
        "merchant_payload": {
            "api_key": "merchant-secret",
            "nested": {"secret": "nested-secret"},
        },
        "proof": "proof-secret",
    }
    config = service.config
    config.clink_internal_api_token = "test-internal-token"
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL", config.funding_database_url)
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "test-internal-token")
    import services.funding_service.app as funding_app

    monkeypatch.setattr(funding_app, "SERVICE", service)
    monkeypatch.setattr(funding_app, "APP_CONFIG", config)
    app = funding_app.create_app()

    async def call_api():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer test-internal-token"},
        ) as client:
            finalized = await client.post(
                "/funding/spending-reservations/"
                f"{reservation['reservation_id']}/external-finalize",
                json={
                    "transaction_hash": tx_hash,
                    "payment_response": payment_response,
                },
            )
            loaded = await client.get(
                f"/funding/spending-reservations/{reservation['reservation_id']}"
            )
            invalid = await client.post(
                "/funding/spending-reservations/"
                f"{reservation['reservation_id']}/external-finalize",
                json={
                    "transaction_hash": tx_hash,
                    "payment_response": {
                        "signature": "signature-secret",
                        "headers": {"PAYMENT-SIGNATURE": "header-secret"},
                        "merchant_payload": {"api_key": "merchant-secret"},
                    },
                },
            )
            return finalized, loaded, invalid

    finalized, loaded, invalid = anyio.run(call_api)
    with service.ledger.sessions() as session:
        persisted = session.get(LedgerRow, reservation["reservation_id"]).payload
        audit_payloads = [row.payload for row in session.query(AuditEventRow).all()]

    serialized_outputs = json.dumps(
        {
            "finalized": finalized.json(),
            "loaded": loaded.json(),
            "invalid": invalid.json(),
            "persisted": persisted,
            "audit": audit_payloads,
        },
        sort_keys=True,
    )
    assert finalized.status_code == loaded.status_code == 200
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "request could not be completed"}
    assert "external_payment_response" not in persisted
    assert persisted["payment_proof_hash"].startswith("0x")
    for secret in sensitive_values:
        assert secret not in serialized_outputs


def test_legacy_external_payment_payload_is_redacted_on_read(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    with service.ledger.sessions.begin() as session:
        row = session.get(LedgerRow, reservation["reservation_id"])
        row.payload = {
            **row.payload,
            "external_payment_response": {
                **external_proof(reservation),
                "signature": "legacy-signature-secret",
            },
        }

    loaded = service.get_reservation(reservation["reservation_id"])

    assert "external_payment_response" not in loaded
    assert "legacy-signature-secret" not in json.dumps(loaded)


@pytest.mark.parametrize(
    "calldata",
    [
        "0xdeadbeef" + eip3009_calldata()[10:],
        eip3009_calldata(payer="0x" + "4" * 40),
        eip3009_calldata(recipient="0x" + "5" * 40)
        + DESTINATION.removeprefix("0x").rjust(64, "0"),
        eip3009_calldata(amount=1) + hex(3_000_000)[2:].rjust(64, "0"),
        eip3009_calldata()[:-2],
        eip3009_calldata() + "00" * 32,
        eip3009_calldata() + "a161776a6364705f666163696c31",
        eip3009_calldata()
        + "a161776a6364705f666163696c31"
        + "000e0280218021802180218021802180218021"
        + "deadbeef",
        "0xdeadbeef" + eip3009_calldata().removeprefix("0x"),
        replace_calldata_word(
            eip3009_calldata(),
            0,
            ("01" * 12) + PAYER.removeprefix("0x"),
        ),
        replace_calldata_word(
            eip3009_calldata(),
            6,
            hex(256)[2:].rjust(64, "0"),
        ),
    ],
    ids=(
        "unknown-selector-with-scope-words",
        "wrong-payer",
        "wrong-recipient-with-forged-tail",
        "wrong-amount-with-forged-tail",
        "truncated-arguments",
        "trailing-word",
        "truncated-cdp-attribution",
        "cdp-attribution-with-extra-bytes",
        "valid-call-at-wrong-offset",
        "nonzero-address-padding",
        "uint8-overflow",
    ),
)
def test_external_forged_calldata_cannot_settle(tmp_path, calldata):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    tx_hash = "0x" + keccak(text=calldata).hex()
    successful_external_transaction(chain, tx_hash, calldata=calldata)

    with pytest.raises(ValueError, match="does not match reservation challenge"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=tx_hash,
                payment_response=external_proof(reservation),
            ),
        )

    persisted = service.get_reservation(reservation["reservation_id"])
    assert persisted["state"] == "spending_reserved"
    assert persisted["tx_hash"] is None


def test_native_ambiguous_submit_persists_identity_and_reconciles_once(tmp_path):
    chain = Chain()
    chain.raise_after_send = True
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert pending["state"] == "payment_submitted"
    assert pending["reconciliation_status"] == "pending"
    assert pending["next_action"] == "reconcile_payment"
    assert pending["settlement_rail"] == "clink_allowance"
    assert pending["tx_hash"].startswith("0x")
    assert "settlement_raw_transaction" not in pending
    assert len(chain.sent_raw) == 1

    with service.ledger.sessions() as session:
        durable = session.get(LedgerRow, reservation["reservation_id"])
        assert "settlement_raw_transaction" not in durable.payload
        assert chain.sent_raw[0] not in json.dumps(durable.payload)

    transaction_identity = {
        "tx_hash": pending["tx_hash"],
        "settlement_sender": pending["settlement_sender"],
        "settlement_nonce": pending["settlement_nonce"],
        "settlement_transaction": pending["settlement_transaction"],
    }
    nonce_lookups = chain.rpc_calls.count("eth_getTransactionCount")
    service.policy_service = FailingPolicyService()
    with patch(
        "services.funding_service.service.Account.sign_transaction",
        side_effect=AssertionError("submitted payment recovery must not sign again"),
    ) as sign_transaction:
        repeated = service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )
    assert repeated["state"] == "payment_submitted"
    assert {
        key: repeated[key] for key in transaction_identity
    } == transaction_identity
    assert chain.rpc_calls.count("eth_getTransactionCount") == nonce_lookups
    sign_transaction.assert_not_called()
    assert len(chain.sent_raw) == 1

    chain.receipts[pending["tx_hash"]] = {
        "status": "0x1",
        "blockNumber": "0x20",
    }
    settled = service.reconcile_reservation(reservation["reservation_id"])
    replay = service.reconcile_reservation(reservation["reservation_id"])

    assert settled["state"] == replay["state"] == "settled"
    assert settled["reconciliation_status"] == "settled"
    assert len(chain.sent_raw) == 1
    updated = AccountRepository(service.config.funding_database_url).spending_grant(
        "grant_1"
    )
    assert updated.used_amount_usdc == Decimal("3")
    receipts = service._load_latest("receipt")
    assert list(receipts) == [settled["receipt_id"]]
    assert not service.storage_file.exists()
    restarted = FundingService(
        config=service.config,
        storage_file=service.storage_file,
        rpc_transport=chain,
    )
    assert restarted._load_latest("receipt") == receipts


def test_native_confirmed_failure_becomes_retryable_without_reusing_transaction(tmp_path):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x0", "blockNumber": "0x20"}
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )

    retryable = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert retryable["state"] == "spending_reserved"
    assert retryable["reconciliation_status"] == "retryable"
    assert retryable["next_action"] == "retry_settlement"
    assert len(retryable["failed_tx_hashes"]) == 1

    chain.receipt_on_send = {"status": "0x1", "blockNumber": "0x20"}
    settled = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert settled["state"] == "settled"
    assert len(chain.sent_raw) == 2
    assert chain.sent_raw[0] != chain.sent_raw[1]


def test_prediction_definite_rejection_seals_canonical_transaction_and_forbids_replacement(
    tmp_path,
):
    chain = Chain()
    chain.reject_before_send = RpcSubmissionRejected("insufficient_funds")
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )

    failed = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert failed["single_submission"] is True
    assert failed["state"] == "spending_reserved"
    assert failed["reconciliation_status"] == "failed"
    assert failed["next_action"] == "release_reservation"
    assert failed["replacement_forbidden"] is True
    assert failed["tx_hash"].startswith("0x")
    assert failed["settlement_sender"] == failed["settlement_transaction"]["from"]
    assert failed["settlement_nonce"] == failed["settlement_transaction"]["nonce"]
    assert failed["failed_tx_hashes"] == [failed["tx_hash"]]
    assert failed["failed_submission_evidence"] == [
        {
            "kind": "definite_rpc_rejection",
            "reason_code": "insufficient_funds",
            "tx_hash": failed["tx_hash"],
            "relayer": failed["settlement_sender"],
            "nonce": failed["settlement_nonce"],
            "recorded_at": "2026-07-15T12:00:00Z",
        }
    ]
    calls_after_failure = list(chain.rpc_calls)

    with pytest.raises(ValueError, match="single-submission.*replacement"):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    assert chain.rpc_calls == calls_after_failure
    released = service.release_reservation(
        reservation["reservation_id"],
        ReleaseSpendingReservationRequest(reason="definite_rejection"),
    )
    assert released["state"] == "released"
    assert released["tx_hash"] == failed["tx_hash"]
    assert released["settlement_transaction"] == failed["settlement_transaction"]
    assert released["replacement_forbidden"] is True
    assert released["failed_submission_evidence"] == failed[
        "failed_submission_evidence"
    ]


def test_prediction_submission_does_not_classify_plain_exception_text_as_definite(
    tmp_path,
):
    chain = Chain()
    secret = "https://rpc.example/private-key"
    chain.reject_before_send = f"insufficient funds for gas; upstream={secret}"
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert pending["state"] == "payment_submitted"
    assert pending["replacement_forbidden"] is False
    assert not pending.get("failed_submission_evidence")
    assert secret not in json.dumps(pending)


def test_prediction_reconciliation_transport_failure_is_persisted_redacted(tmp_path):
    chain = Chain()
    chain.raise_after_send = True
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    secret = "https://rpc.example/private-key 0xdeadbeef"

    def unavailable(_network, _method, _params):
        raise RuntimeError(secret)

    service.rpc_transport = unavailable
    reconciled = service.reconcile_reservation(reservation["reservation_id"])

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["last_reconciliation_error"] == (
        "native settlement reconciliation lookup failed"
    )
    assert secret not in json.dumps(reconciled)


def test_prediction_failed_receipt_keeps_failure_evidence_and_cannot_resettle(
    tmp_path,
):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x0", "blockNumber": "0x20"}
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )

    failed = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert failed["single_submission"] is True
    assert failed["state"] == "spending_reserved"
    assert failed["reconciliation_status"] == "failed"
    assert failed["replacement_forbidden"] is True
    assert failed["failed_submission_evidence"][0]["kind"] == "failed_receipt"
    assert failed["failed_submission_evidence"][0]["reason_code"] == "onchain_revert"
    assert failed["failed_submission_evidence"][0]["tx_hash"] == failed["tx_hash"]
    original = {
        key: failed[key]
        for key in (
            "tx_hash",
            "settlement_sender",
            "settlement_nonce",
            "settlement_transaction",
        )
    }
    calls_after_failure = list(chain.rpc_calls)

    with pytest.raises(ValueError, match="single-submission.*replacement"):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    assert chain.rpc_calls == calls_after_failure
    persisted = service.get_reservation(reservation["reservation_id"])
    assert {key: persisted[key] for key in original} == original


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("single_submission", False),
        ("replacement_forbidden", False),
        ("tx_hash", "0x" + "88" * 32),
        ("settlement_sender", "0x" + "44" * 20),
        ("settlement_nonce", 99),
        ("settlement_transaction", None),
        ("failed_submission_evidence", []),
    ],
)
def test_prediction_sealed_failure_record_rejects_authoritative_mutation(
    tmp_path, field, replacement
):
    chain = Chain()
    chain.reject_before_send = RpcSubmissionRejected("insufficient_funds")
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    failed = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    with pytest.raises(
        ValueError,
        match="immutable reservation|require single submission",
    ):
        with service.ledger.transaction() as tx:
            service._put_reservation(tx, {**failed, field: replacement})

    assert service.get_reservation(reservation["reservation_id"]) == failed


@pytest.mark.parametrize(
    "tamper",
    [
        "mapping",
        "string",
        "integer",
        "none",
        "empty",
        "second_evidence",
        "kind",
        "reason_code",
        "recorded_at",
        "state",
        "reconciliation_status",
        "next_action",
        "replacement_forbidden",
        "evidence_tx_hash",
        "evidence_relayer",
        "evidence_nonce",
    ],
)
def test_prediction_persisted_failure_requires_one_fully_bound_evidence_record(
    tmp_path, tamper
):
    chain = Chain()
    chain.reject_before_send = RpcSubmissionRejected("insufficient_funds")
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    failed = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    evidence = dict(failed["failed_submission_evidence"][0])
    changes = {}
    if tamper == "mapping":
        changes["failed_submission_evidence"] = {}
    elif tamper == "string":
        changes["failed_submission_evidence"] = ""
    elif tamper == "integer":
        changes["failed_submission_evidence"] = 0
    elif tamper == "none":
        changes["failed_submission_evidence"] = None
    elif tamper == "empty":
        changes["failed_submission_evidence"] = []
    elif tamper == "second_evidence":
        changes["failed_submission_evidence"] = [evidence, dict(evidence)]
    elif tamper == "kind":
        changes["failed_submission_evidence"] = [
            {**evidence, "kind": "operator_note"}
        ]
    elif tamper == "reason_code":
        changes["failed_submission_evidence"] = [
            {**evidence, "reason_code": "unknown_reason"}
        ]
    elif tamper == "recorded_at":
        changes["failed_submission_evidence"] = [
            {**evidence, "recorded_at": "2026-07-15T12:00:00+00:00"}
        ]
    elif tamper == "state":
        changes["state"] = "payment_submitted"
    elif tamper == "reconciliation_status":
        changes["reconciliation_status"] = "pending"
    elif tamper == "next_action":
        changes["next_action"] = "retry_settlement"
    elif tamper == "replacement_forbidden":
        changes["replacement_forbidden"] = False
    elif tamper == "evidence_tx_hash":
        changes["failed_submission_evidence"] = [
            {**evidence, "tx_hash": "0x" + "8" * 64}
        ]
    elif tamper == "evidence_relayer":
        changes["failed_submission_evidence"] = [
            {**evidence, "relayer": "0x" + "4" * 40}
        ]
    else:
        changes["failed_submission_evidence"] = [{**evidence, "nonce": 99}]

    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, failed["reservation_id"])
        stored.payload = {**stored.payload, **changes}

    with pytest.raises(ValueError, match="single-submission failure"):
        with service.ledger.transaction() as tx:
            corrupted = tx.get(failed["reservation_id"])
            service._put_reservation(tx, corrupted, tx_hash=corrupted["tx_hash"])


@pytest.mark.parametrize(
    "tamper",
    [
        "partial_initial",
        "payment_missing_hash",
        "payment_missing_sender",
        "payment_missing_nonce",
        "payment_missing_projection",
        "reserved_complete_without_failure",
        "released_complete_without_failure",
        "payment_without_canonical",
        "settled_without_canonical",
        "finalized_without_canonical",
    ],
)
def test_prediction_persisted_state_requires_complete_canonical_submission_binding(
    tmp_path, tamper
):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    if tamper == "partial_initial":
        current = reservation
        changes = {"tx_hash": "0x" + "8" * 64}
    else:
        chain.raise_after_send = True
        current = service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )
        changes = {}
        if tamper == "payment_missing_hash":
            changes["tx_hash"] = None
        elif tamper == "payment_missing_sender":
            changes["settlement_sender"] = None
        elif tamper == "payment_missing_nonce":
            changes["settlement_nonce"] = None
        elif tamper == "payment_missing_projection":
            changes["settlement_transaction"] = None
        elif tamper == "reserved_complete_without_failure":
            changes.update(
                {
                    "state": "spending_reserved",
                    "replacement_forbidden": False,
                    "failed_submission_evidence": [],
                }
            )
        elif tamper == "released_complete_without_failure":
            changes.update(
                {
                    "state": "released",
                    "replacement_forbidden": False,
                    "failed_submission_evidence": [],
                }
            )
        else:
            changes["state"] = {
                "payment_without_canonical": "payment_submitted",
                "settled_without_canonical": "settled",
                "finalized_without_canonical": "finalized",
            }[tamper]
            changes.update(
                {
                    "tx_hash": None,
                    "settlement_sender": None,
                    "settlement_nonce": None,
                    "settlement_transaction": None,
                }
            )

    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, current["reservation_id"])
        stored.payload = {**stored.payload, **changes}

    with pytest.raises(ValueError, match="single-submission"):
        with service.ledger.transaction() as tx:
            corrupted = tx.get(current["reservation_id"])
            service._put_reservation(
                tx,
                corrupted,
                tx_hash=corrupted.get("tx_hash"),
            )


def test_prediction_release_revalidates_state_before_releasing_budget(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, reservation["reservation_id"])
        stored.payload = {**stored.payload, "tx_hash": "0x" + "8" * 64}

    with patch.object(
        FundingTransaction,
        "release_unified_budget",
        side_effect=AssertionError("budget release must not run"),
    ):
        with pytest.raises(ValueError, match="single-submission"):
            service.release_reservation(
                reservation["reservation_id"],
                ReleaseSpendingReservationRequest(reason="cancelled"),
            )


@pytest.mark.parametrize("drift", ["projection_relayer", "projection_nonce"])
def test_prediction_failure_release_revalidates_canonical_projection_before_budget(
    tmp_path, drift
):
    chain = Chain()
    chain.reject_before_send = RpcSubmissionRejected("insufficient_funds")
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    failed = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, failed["reservation_id"])
        projection = dict(stored.payload["settlement_transaction"])
        if drift == "projection_relayer":
            projection["from"] = "0x" + "4" * 40
        else:
            projection["nonce"] += 1
        stored.payload = {**stored.payload, "settlement_transaction": projection}

    with patch.object(
        FundingTransaction,
        "release_unified_budget",
        side_effect=AssertionError("budget release must not run"),
    ):
        with pytest.raises(ValueError, match="single-submission .* binding"):
            service.release_reservation(
                reservation["reservation_id"],
                ReleaseSpendingReservationRequest(reason="definite_rejection"),
            )


def test_prediction_pending_rebroadcast_uses_only_the_sealed_projection(tmp_path):
    chain = Chain()
    chain.raise_after_send = True
    chain.hide_transactions = True
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    repeated = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert pending["single_submission"] is True
    assert pending["state"] == repeated["state"] == "payment_submitted"
    assert repeated["replacement_forbidden"] is False
    assert repeated["tx_hash"] == pending["tx_hash"]
    assert repeated["settlement_nonce"] == pending["settlement_nonce"]
    assert repeated["settlement_transaction"] == pending["settlement_transaction"]
    assert len(set(chain.sent_raw)) == 1
    assert "settlement_raw_transaction" not in repeated


@pytest.mark.parametrize(
    "drift",
    ["projection", "relayer", "nonce", "hash"],
)
def test_prediction_rebroadcast_drift_requires_manual_review(tmp_path, drift):
    chain = Chain()
    chain.reject_before_send = "connection reset before broadcast"
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        authorization_rail="native_allowance",
        product="prediction_markets",
    )
    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, pending["reservation_id"])
        payload = dict(stored.payload)
        if drift == "projection":
            payload["settlement_transaction"] = {
                **payload["settlement_transaction"],
                "gas": payload["settlement_transaction"]["gas"] + 1,
            }
        elif drift == "relayer":
            payload["settlement_sender"] = "0x" + "44" * 20
        elif drift == "nonce":
            payload["settlement_nonce"] += 1
        else:
            payload["tx_hash"] = "0x" + "99" * 32
        stored.payload = payload
    chain.reject_before_send = None

    reviewed = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )

    assert reviewed["state"] == "payment_submitted"
    assert reviewed["reconciliation_status"] == "manual_review_required"
    assert reviewed["next_action"] == "operator_reconcile"
    assert chain.sent_raw == []


def test_native_missing_transaction_rebroadcasts_the_same_transaction(tmp_path):
    chain = Chain()
    chain.raise_after_send = True
    chain.hide_transactions = True
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    repeated = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert pending["state"] == repeated["state"] == "payment_submitted"
    assert repeated["reconciliation_status"] == "pending"
    assert repeated["next_action"] == "reconcile_payment"
    assert "settlement_raw_transaction" not in repeated
    assert len(chain.sent_raw) == 3
    assert len(set(chain.sent_raw)) == 1


def test_native_missing_transaction_rebroadcasts_without_exposing_signed_bytes(tmp_path):
    chain = Chain()
    chain.raise_after_send = True
    chain.hide_transactions = True
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    chain.nonce = pending["settlement_nonce"]

    reviewed = service.reconcile_reservation(reservation["reservation_id"])
    reviewed_again = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )

    assert reviewed["reconciliation_status"] == "pending"
    assert reviewed_again["reconciliation_status"] == "pending"
    assert "settlement_raw_transaction" not in reviewed
    assert len(chain.sent_raw) == 4
    assert len(set(chain.sent_raw)) == 1
    assert chain.rpc_calls.count("eth_sendRawTransaction") == 4


def test_native_crash_window_reconstructs_and_rebroadcasts_the_exact_transaction(
    tmp_path,
):
    chain = Chain()
    chain.reject_before_send = "connection reset before broadcast"
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    persisted = service.get_reservation(reservation["reservation_id"])
    chain.reject_before_send = None

    recovered = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )

    assert pending["state"] == "payment_submitted"
    assert "settlement_raw_transaction" not in persisted
    assert persisted["settlement_transaction"]["nonce"] == persisted["settlement_nonce"]
    assert len(chain.sent_raw) == 1
    assert "0x" + keccak(bytes.fromhex(chain.sent_raw[0][2:])).hex() == persisted["tx_hash"]
    assert recovered["tx_hash"] == persisted["tx_hash"]


def test_native_reconstruction_hash_mismatch_requires_manual_review(tmp_path):
    chain = Chain()
    chain.reject_before_send = "connection reset before broadcast"
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    with service.ledger.sessions.begin() as session:
        stored = session.get(LedgerRow, pending["reservation_id"])
        stored.payload = {
            **stored.payload,
            "settlement_transaction": {
                **stored.payload["settlement_transaction"],
                "gas": stored.payload["settlement_transaction"]["gas"] + 1,
            },
        }
    chain.reject_before_send = None

    reviewed = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )

    assert pending["state"] == "payment_submitted"
    assert reviewed["state"] == "payment_submitted"
    assert reviewed["reconciliation_status"] == "manual_review_required"
    assert "hash does not match" in reviewed["manual_review_reason"]
    assert chain.sent_raw == []


@pytest.mark.parametrize(
    "tamper",
    [
        "receipt_hash",
        "sender",
        "nonce",
        "token_target",
        "calldata_destination",
        "calldata_amount",
        "missing_transaction",
    ],
)
def test_native_settlement_requires_exact_onchain_evidence(tmp_path, tamper):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    tx_hash = pending["tx_hash"]
    chain.receipts[tx_hash] = {"status": "0x1", "blockNumber": "0x20"}

    if tamper == "receipt_hash":
        chain.receipts[tx_hash]["transactionHash"] = "0x" + "99" * 32
    elif tamper == "sender":
        chain.transactions[tx_hash]["from"] = "0x" + "44" * 20
    elif tamper == "nonce":
        chain.transactions[tx_hash]["nonce"] = "0x99"
    elif tamper == "token_target":
        chain.transactions[tx_hash]["to"] = "0x" + "55" * 20
    elif tamper == "calldata_destination":
        chain.transactions[tx_hash]["input"] = replace_calldata_word(
            chain.transactions[tx_hash]["input"], 1, "00" * 12 + "66" * 20
        )
    elif tamper == "calldata_amount":
        chain.transactions[tx_hash]["input"] = replace_calldata_word(
            chain.transactions[tx_hash]["input"], 2, hex(1)[2:].rjust(64, "0")
        )
    else:
        chain.transactions[tx_hash] = {}

    reconciled = service.reconcile_reservation(reservation["reservation_id"])

    assert reconciled["state"] == "payment_submitted"
    assert reconciled["reconciliation_status"] == "manual_review_required"
    assert reconciled.get("receipt") is None


def test_native_pre_submit_and_definite_rejection_remain_safely_retryable(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, authorization_rail="native_allowance"
    )
    chain.fail_nonce = True

    with pytest.raises(RuntimeError, match="nonce RPC unavailable"):
        service.settle_reservation(
            reservation["reservation_id"], native_payment_authorization()
        )

    chain.fail_nonce = False
    assert service.reconcile_reservation(reservation["reservation_id"])[
        "reconciliation_status"
    ] == "retryable"
    chain.reject_before_send = RpcSubmissionRejected("insufficient_funds")
    rejected = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    assert rejected["state"] == "spending_reserved"
    assert rejected["reconciliation_status"] == "retryable"
    assert rejected["settlement_nonce"] == 1
    assert len(chain.sent_raw) == 0

    chain.reject_before_send = None
    retried = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    assert retried["state"] == "payment_submitted"
    assert retried["settlement_nonce"] == rejected["settlement_nonce"]
    assert len(chain.sent_raw) == 1


def test_external_pending_binding_retries_after_failure_and_blocks_tx_replay(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(tmp_path, chain)
    pending_hash = "0x" + "b" * 64
    successful_external_transaction(chain, pending_hash, reservation=reservation)
    chain.receipts.pop(pending_hash)

    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=pending_hash,
            payment_response=external_proof(reservation),
        ),
    )

    assert pending["state"] == "payment_submitted"
    assert pending["reconciliation_status"] == "pending"
    assert pending["tx_hash"] == pending_hash

    other_hash = "0x" + "c" * 64
    successful_external_transaction(chain, other_hash, reservation=reservation)
    with pytest.raises(ValueError, match="different transaction is pending"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=other_hash,
                payment_response=external_proof(reservation),
            ),
        )

    chain.receipts[pending_hash] = {
        "transactionHash": pending_hash,
        "status": "0x0",
        "blockNumber": "0x20",
    }
    retryable = service.reconcile_reservation(reservation["reservation_id"])
    assert retryable["state"] == "spending_reserved"
    assert retryable["reconciliation_status"] == "retryable"

    settled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=other_hash,
            payment_response=external_proof(reservation),
        ),
    )
    assert settled["state"] == "settled"
    assert settled["tx_hash"] == other_hash

    with patch.object(
        service, "_verify_marketplace_provenance", return_value=EXTERNAL_PROVENANCE
    ):
        second = service.reserve_spending(reservation_request("purchase_2"))
    with pytest.raises(ValueError, match="transaction is already bound"):
        service.finalize_external_payment(
            second["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=pending_hash,
                payment_response=external_proof(second),
            ),
        )
    with pytest.raises(ValueError, match="transaction is already bound"):
        service.finalize_external_payment(
            second["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=other_hash,
                payment_response=external_proof(second),
            ),
        )

    replay_hash = "0x" + "d" * 64
    successful_external_transaction(chain, replay_hash, reservation=second)
    distinct_payment = service.finalize_external_payment(
        second["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=replay_hash,
            payment_response=external_proof(second),
        ),
    )
    assert distinct_payment["state"] == "settled"


def test_external_tx_hash_casing_and_proof_decoration_cannot_replay_across_reservations(
    tmp_path,
):
    chain = Chain()
    service, first = service_and_reservation(tmp_path, chain)
    canonical_hash = "0x" + "ab" * 32
    successful_external_transaction(chain, canonical_hash, reservation=first)
    first_proof = {**external_proof(first), "merchant_note": "first"}

    settled = service.finalize_external_payment(
        first["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=canonical_hash,
            payment_response=first_proof,
        ),
    )
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=EXTERNAL_PROVENANCE
    ):
        second = service.reserve_spending(reservation_request("purchase_2"))

    with pytest.raises(ValueError, match="transaction is already bound"):
        service.finalize_external_payment(
            second["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash="0x" + "AB" * 32,
                payment_response={
                    **external_proof(second),
                    "merchant_note": "second",
                },
            ),
        )

    assert settled["tx_hash"] == canonical_hash
    assert service.get_reservation(first["reservation_id"])["state"] == "settled"
    assert service.get_reservation(second["reservation_id"])["state"] == "spending_reserved"


def test_native_failed_receipt_waits_for_required_confirmations_before_retry(tmp_path):
    chain = Chain()
    chain.receipt_on_send = {"status": "0x0", "blockNumber": "0x20"}
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        min_confirmations=2,
        authorization_rail="native_allowance",
    )

    pending = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    repeated = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )

    assert pending["state"] == repeated["state"] == "payment_submitted"
    assert repeated["reconciliation_status"] == "pending"
    assert repeated["tx_hash"] == pending["tx_hash"]
    assert len(chain.sent_raw) == 1

    chain.latest = 33
    retryable = service.reconcile_reservation(reservation["reservation_id"])
    assert retryable["state"] == "spending_reserved"
    assert retryable["failed_tx_hashes"] == [pending["tx_hash"]]


def test_external_failed_receipt_waits_for_required_confirmations_before_replacement(
    tmp_path,
):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, min_confirmations=2
    )
    failed_hash = "0x" + "e" * 64
    replacement_hash = "0x" + "f" * 64
    successful_external_transaction(chain, failed_hash, reservation=reservation)
    chain.receipts[failed_hash] = {
        "transactionHash": failed_hash,
        "status": "0x0",
        "blockNumber": "0x20",
    }

    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=failed_hash,
            payment_response=external_proof(reservation),
        ),
    )
    successful_external_transaction(
        chain, replacement_hash, reservation=reservation
    )

    assert pending["state"] == "payment_submitted"
    assert pending["reconciliation_status"] == "pending"
    with pytest.raises(ValueError, match="different transaction is pending"):
        service.finalize_external_payment(
            reservation["reservation_id"],
            FinalizeExternalPaymentRequest(
                transaction_hash=replacement_hash,
                payment_response=external_proof(reservation),
            ),
        )

    chain.latest = 33
    retryable = service.reconcile_reservation(reservation["reservation_id"])
    assert retryable["state"] == "spending_reserved"
    settled = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=replacement_hash,
            payment_response=external_proof(reservation),
        ),
    )
    assert settled["state"] == "settled"


def test_ambiguous_native_reconciliation_escalates_and_requires_operator_override(
    tmp_path,
):
    chain = Chain()
    chain.raise_after_send = True
    chain.hide_transactions = True
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        reconciliation_max_attempts=2,
        authorization_rail="native_allowance",
    )

    first = service.settle_reservation(
        reservation["reservation_id"], native_payment_authorization()
    )
    second = service.reconcile_reservation(reservation["reservation_id"])
    escalated = service.reconcile_reservation(reservation["reservation_id"])

    assert first["reconciliation_attempts"] == 1
    assert first["reconciliation_status"] == "pending"
    assert second["reconciliation_attempts"] == 2
    assert second["reconciliation_status"] == "pending"
    assert escalated["state"] == "payment_submitted"
    assert escalated["reconciliation_status"] == "manual_review_required"
    assert escalated["next_action"] == "operator_reconcile"
    assert escalated["manual_review_reason"]
    assert escalated["manual_review_required_at"]
    calls_after_escalation = len(chain.rpc_calls)
    assert len(chain.rpc_calls) == calls_after_escalation

    repeated = service.reconcile_reservation(reservation["reservation_id"])
    assert repeated["reconciliation_attempts"] == 2
    assert len(chain.rpc_calls) == calls_after_escalation

    chain.hide_transactions = False
    chain.receipts[first["tx_hash"]] = {"status": "0x1", "blockNumber": "0x20"}
    settled = service.reconcile_reservation(
        reservation["reservation_id"], operator_reconcile=True
    )
    assert settled["state"] == "settled"


def test_ambiguous_external_reconciliation_escalates_without_releasing_funds(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path, chain, reconciliation_max_attempts=1
    )
    tx_hash = "0x" + "9" * 64
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    chain.receipts.pop(tx_hash)

    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    calls_before_escalation = len(chain.rpc_calls)
    escalated = service.reconcile_reservation(reservation["reservation_id"])
    calls_after_escalation = len(chain.rpc_calls)
    repeated = service.reconcile_reservation(reservation["reservation_id"])

    assert pending["reconciliation_attempts"] == 1
    assert escalated["state"] == "payment_submitted"
    assert escalated["reconciliation_status"] == "manual_review_required"
    assert escalated["next_action"] == "operator_reconcile"
    assert calls_after_escalation == calls_before_escalation
    assert repeated == escalated
    assert len(chain.rpc_calls) == calls_after_escalation


def test_ambiguous_reconciliation_escalates_after_configured_age(tmp_path):
    chain = Chain()
    service, reservation = service_and_reservation(
        tmp_path,
        chain,
        reconciliation_max_attempts=12,
        reconciliation_max_age_seconds=60,
    )
    tx_hash = "0x" + "8" * 64
    successful_external_transaction(chain, tx_hash, reservation=reservation)
    chain.receipts.pop(tx_hash)
    pending = service.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=tx_hash,
            payment_response=external_proof(reservation),
        ),
    )
    with service.ledger.transaction() as tx:
        current = tx.get(reservation["reservation_id"])
        current = {**current, "reconciliation_started_at": "2000-01-01T00:00:00Z"}
        service._put_reservation(tx, current, tx_hash=tx_hash)
    calls_before_escalation = len(chain.rpc_calls)

    escalated = service.reconcile_reservation(reservation["reservation_id"])

    assert pending["state"] == escalated["state"] == "payment_submitted"
    assert escalated["reconciliation_status"] == "manual_review_required"
    assert escalated["manual_review_reason"] == "automatic reconciliation age limit reached"
    assert len(chain.rpc_calls) == calls_before_escalation


def test_reconciliation_limits_have_finite_secure_defaults():
    config = AppConfig()

    assert 1 <= config.payment_reconciliation_max_attempts <= 100
    assert 60 <= config.payment_reconciliation_max_age_seconds <= 86400


def test_funding_api_exposes_internal_reconciliation_endpoint(tmp_path,monkeypatch):
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL",f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}")
    from services.funding_service.app import create_app

    paths = {route.path for route in create_app().routes}
    assert "/funding/spending-reservations/{reservation_id}/reconcile" in paths
    assert "/funding/spending-reservations/{reservation_id}/proxy-prepare" in paths
    assert "/funding/spending-reservations/{reservation_id}/proxy-finalize" in paths
    assert "/funding/spending-reservations/{reservation_id}/hosted-authority" in paths


def test_proxy_prepare_api_marks_token_domain_mismatch_incompatible(monkeypatch):
    import services.funding_service.app as funding_app

    class IncompatibleService:
        def prepare_proxy_payment(self, _reservation_id, _request):
            raise ValueError(
                "merchant token domain does not match trusted Core configuration"
            )

    monkeypatch.setattr(funding_app, "SERVICE", IncompatibleService())
    monkeypatch.setattr(
        funding_app.APP_CONFIG,
        "clink_internal_api_token",
        "test-internal-token",
    )
    app = funding_app.create_app()

    async def call_api():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer test-internal-token"},
        ) as client:
            return await client.post(
                "/funding/spending-reservations/reserve_1/proxy-prepare",
                json={
                    "payment_requirement": {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "asset": "0x" + "4" * 40,
                        "amount_atomic": "1000",
                        "pay_to": DESTINATION,
                        "resource": "https://merchant.example/data",
                        "token_name": "USD Coin",
                        "token_version": "2",
                    }
                },
            )

    response = anyio.run(call_api)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "PROXY_INCOMPATIBLE",
        "message": "merchant token domain does not match trusted Core configuration",
    }


def test_proxy_prepare_schema_error_is_structured_incompatibility(monkeypatch):
    import services.funding_service.app as funding_app

    class ServiceMustNotRun:
        def prepare_proxy_payment(self, _reservation_id, _request):
            raise AssertionError("invalid merchant input must fail before service dispatch")

    monkeypatch.setattr(funding_app, "SERVICE", ServiceMustNotRun())
    monkeypatch.setattr(
        funding_app.APP_CONFIG,
        "clink_internal_api_token",
        "test-internal-token",
    )
    app = funding_app.create_app()

    async def call_api():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer test-internal-token"},
        ) as client:
            return await client.post(
                "/funding/spending-reservations/reserve_1/proxy-prepare",
                json={
                    "payment_requirement": {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "asset": "0x" + "4" * 40,
                        "amount_atomic": "1000",
                        "pay_to": DESTINATION,
                        "resource": "https://merchant.example/data",
                        "token_name": "USD\nCoin",
                        "token_version": "2",
                    }
                },
            )

    response = anyio.run(call_api)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "PROXY_INCOMPATIBLE",
        "message": "merchant proxy payment requirement is invalid",
    }
