from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib

from eth_account import Account
from eth_account._utils.legacy_transactions import Transaction
from eth_account.messages import encode_defunct
from eth_utils import keccak
import rlp

from services.account_service.repository import AccountRepository
from services.account_service.schemas import (
    AuthorizationResolutionRequest,
    PublicAccountSession,
    SpendingGrant,
    SpendingGrantRequest,
    WalletIdentity,
)
from services.account_service.service import AccountService
from services.action_service.schemas import (
    CreateActionIntentRequest,
    UpdateActionIntentRequest,
)
from services.action_service.service import ActionService
from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    SettleSpendingReservationRequest,
)
from services.funding_service.service import FundingService
from services.policy_service.schemas import EvaluateActionPolicyRequest
from services.policy_service.risk_provider import RiskProviderResult
from services.policy_service.service import PolicyService
from shared.config import AppConfig


NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
POLYGON = "eip155:137"
BASE = "eip155:8453"
POLYGON_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BASE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
RELAYER_KEY = "0x" + "33" * 32
SPENDER = Account.from_key(RELAYER_KEY).address
DESTINATION = "0x" + "44" * 20
POLYGON_APPROVAL_TX = "0x" + "55" * 32
BASE_APPROVAL_TX = "0x" + "66" * 32
RECEIPT_SIGNING_KEY = "unified-account-e2e-receipt-key-" + "1" * 32


class AllowRiskProvider:
    def assess(self, *, subject: str, network: str, asset: str = "USDC"):
        return RiskProviderResult(
            provider="misttrack",
            endpoint="v2/risk_score",
            subject=subject,
            network=network,
            asset=asset,
            coin="USDC-Polygon" if network == POLYGON else "USDC-Base",
            score=10,
            risk_level="low",
            indicators=(),
            risk_details=(),
            hacking_event=None,
            assessed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            response_sha256="a" * 64,
        )


def account_network_configs():
    return {
        POLYGON: {
            "chain_id": 137,
            "required_confirmations": 1,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": POLYGON_TOKEN,
        },
        BASE: {
            "chain_id": 8453,
            "required_confirmations": 1,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": BASE_TOKEN,
        },
    }


def approve_calldata(spender: str, amount: int) -> str:
    return "0x095ea7b3" + ("0" * 24) + spender[2:] + amount.to_bytes(32, "big").hex()


def transfer_with_authorization_calldata(
    payer: str,
    pay_to: str,
    amount: int,
    *,
    valid_after: int = 0,
    valid_before: int = 2**256 - 1,
    nonce: str = "0x" + "77" * 32,
) -> str:
    address_word = lambda value: value.removeprefix("0x").rjust(64, "0")
    uint_word = lambda value: hex(value)[2:].rjust(64, "0")
    words = (
        address_word(payer),
        address_word(pay_to),
        uint_word(amount),
        uint_word(valid_after),
        uint_word(valid_before),
        nonce.removeprefix("0x"),
        uint_word(27),
        "88" * 32,
        "99" * 32,
    )
    return "0xe3ee160e" + "".join(words)


class ApprovalRpc:
    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.proofs = {
            (POLYGON, POLYGON_APPROVAL_TX): (137, POLYGON_TOKEN),
            (BASE, BASE_APPROVAL_TX): (8453, BASE_TOKEN),
        }

    def __call__(self, network: str, method: str, params: list) -> object:
        if method == "eth_chainId":
            return hex(137 if network == POLYGON else 8453)
        if method == "eth_blockNumber":
            return "0x69"
        if method == "eth_call":
            return hex(20_000_000)

        tx_hash = params[0]
        chain_id, token = self.proofs[(network, tx_hash)]
        assert chain_id == (137 if network == POLYGON else 8453)
        if method == "eth_getTransactionReceipt":
            return {
                "transactionHash": tx_hash,
                "status": "0x1",
                "blockNumber": "0x64",
            }
        if method == "eth_getTransactionByHash":
            return {
                "hash": tx_hash,
                "from": self.owner,
                "to": token,
                "input": approve_calldata(SPENDER, 20_000_000),
                "blockNumber": "0x64",
            }
        raise AssertionError(f"unexpected account RPC method: {method}")


class SettlementRpc:
    def __init__(self, payer: str) -> None:
        self.payer = payer
        self.sent_networks: list[str] = []
        self.receipts: dict[str, dict] = {}
        self.external_challenges: dict[str, dict] = {}
        self.transactions = {
            "0x" + keccak(text="unified-account-e2e-prediction").hex(): POLYGON_TOKEN,
            "0x" + keccak(text="unified-account-e2e-marketplace").hex(): BASE_TOKEN,
        }

    def transaction_hash(self, product: str) -> str:
        suffix = "prediction" if product == "prediction_markets" else "marketplace"
        return "0x" + keccak(text=f"unified-account-e2e-{suffix}").hex()

    def bind_external_challenge(self, transaction_hash: str, reservation: dict) -> None:
        self.external_challenges[transaction_hash] = reservation
        self.receipts[transaction_hash] = {
            "transactionHash": transaction_hash,
            "status": "0x1",
            "blockNumber": "0x20",
        }

    def __call__(self, network: str, method: str, params: list) -> object:
        if method == "eth_chainId":
            return hex(137 if network == POLYGON else 8453)
        if method == "eth_call":
            return hex(20_000_000)
        if method == "eth_getTransactionCount":
            return hex(len(self.sent_networks))
        if method == "eth_gasPrice":
            return hex(1_000_000_000)
        if method == "eth_estimateGas":
            return hex(100_000)
        if method == "eth_sendRawTransaction":
            raw = params[0]
            transaction_hash = "0x" + keccak(
                bytes.fromhex(raw.removeprefix("0x"))
            ).hex()
            decoded = rlp.decode(bytes.fromhex(raw.removeprefix("0x")), Transaction)
            self.sent_networks.append(network)
            self.transactions[transaction_hash] = {
                "hash": transaction_hash,
                "from": Account.recover_transaction(raw),
                "nonce": hex(decoded.nonce),
                "to": "0x" + decoded.to.hex(),
                "input": "0x" + decoded.data.hex(),
            }
            self.receipts[transaction_hash] = {
                "transactionHash": transaction_hash,
                "status": "0x1",
                "blockNumber": "0x20",
            }
            return transaction_hash
        if method == "eth_blockNumber":
            return "0x20"
        transaction_hash = params[0]
        transaction = self.transactions.get(transaction_hash)
        if method == "eth_getTransactionByHash":
            if transaction is None:
                return None
            if isinstance(transaction, dict):
                return transaction
            token = transaction
            challenge = self.external_challenges.get(transaction_hash)
            calldata_kwargs = (
                {
                    "valid_after": int(challenge["valid_after"]),
                    "valid_before": int(challenge["valid_before"]),
                    "nonce": challenge["nonce"],
                }
                if challenge is not None
                else {}
            )
            return {
                "hash": transaction_hash,
                "to": token,
                "input": transfer_with_authorization_calldata(
                    self.payer, DESTINATION, 2_000_000, **calldata_kwargs
                ),
            }
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(
                transaction_hash, {"status": "0x1", "blockNumber": "0x20"}
            )
        raise AssertionError(f"unexpected settlement RPC method: {method}")


def resolution_request(
    *,
    product: str,
    venue: str,
    network: str,
    token: str,
    merchant: str,
    authorization_rail: str = "native_allowance",
) -> AuthorizationResolutionRequest:
    return AuthorizationResolutionRequest(
        user_id="user_1",
        agent_id="hermes",
        product=product,
        venue=venue,
        merchant=merchant,
        authorization_rail=authorization_rail,
        network=network,
        token_address=token,
        merchant_trust_tier=(
            "clink_verified" if product == "marketplace" else None
        ),
        spender_address=SPENDER if authorization_rail == "native_allowance" else None,
        amount_usdc=Decimal("2"),
        destination=DESTINATION,
        resource=(
            "polymarket:funding"
            if product == "prediction_markets"
            else "https://merchant.example/api"
        ),
    )


def test_one_signed_grant_authorizes_two_products_and_revokes_together(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    monkeypatch.setenv("ACTION_INTENT_FILE", str(tmp_path / "actions.jsonl"))
    monkeypatch.setenv("POLICY_DECISION_FILE", str(tmp_path / "policies.jsonl"))
    monkeypatch.setenv("AUDIT_EVENT_FILE", str(tmp_path / "audit.jsonl"))

    config = AppConfig(
        funding_database_url=database_url,
        account_allowed_products=("prediction_markets", "marketplace"),
        clink_live_funding=True,
        risk_mode="enforce",
        misttrack_api_key="test-key",
        clink_native_facilitator_enabled=True,
        x402_payment_network=BASE,
        x402_payment_token_address=BASE_TOKEN,
        clink_native_facilitator_relayer_private_key=RELAYER_KEY,
        clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        native_min_confirmations=1,
    )
    wallet = Account.create()
    repository = AccountRepository(database_url)
    account_service = AccountService(
        repository,
        domain="account.clink.example",
        clock=lambda: NOW,
        rpc_transport=ApprovalRpc(wallet.address),
        network_configs=account_network_configs(),
        allowed_products=set(config.account_allowed_products),
    )

    public_session = repository.create_public_account_session(
        PublicAccountSession(
            public_account_session_id="public_e2e_user_1",
            token_digest=hashlib.sha256(b"e2e-public-token").hexdigest(),
            browser_session_digest=hashlib.sha256(b"e2e-browser").hexdigest(),
            csrf_token_digest=hashlib.sha256(b"e2e-csrf").hexdigest(),
            user_id="user_1",
            expires_at=NOW + timedelta(minutes=30),
            exchanged_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    wallet_challenge = account_service.create_wallet_challenge(
        "user_1",
        wallet.address,
        created_by_public_account_session_id=public_session.public_account_session_id,
    )
    wallet_signature = Account.sign_message(
        encode_defunct(text=wallet_challenge.message_to_sign), wallet.key
    ).signature.hex()
    identity = account_service.verify_wallet_challenge(
        wallet_challenge.session_id,
        wallet_challenge.message_to_sign,
        wallet_signature,
    )

    unsigned_grant = SpendingGrantRequest(
        user_id="user_1",
        wallet_identity_id=identity.wallet_identity_id,
        agent_id="hermes",
        max_amount_usdc=Decimal("10"),
        per_transaction_limit_usdc=Decimal("5"),
        daily_limit_usdc=Decimal("10"),
        product_scopes=["prediction_markets", "marketplace"],
        venue_scopes=["polymarket", "clink_marketplace"],
        merchant_scopes=["polymarket", "merchant_1"],
        network_scopes=[POLYGON, BASE],
        asset_scopes=[POLYGON_TOKEN, BASE_TOKEN],
        starts_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
    )
    grant_challenge = account_service.create_spending_grant_challenge(unsigned_grant)
    grant_signature = Account.sign_message(
        encode_defunct(text=grant_challenge.message_to_sign), wallet.key
    ).signature.hex()
    grant = account_service.create_spending_grant(
        unsigned_grant.model_copy(
            update={
                "session_id": grant_challenge.session_id,
                "signed_message": grant_challenge.message_to_sign,
                "signature": grant_signature,
            }
        )
    )

    polygon_allowance = account_service.verify_asset_allowance(
        identity.wallet_identity_id,
        POLYGON,
        POLYGON_TOKEN,
        SPENDER,
        POLYGON_APPROVAL_TX,
    )
    base_allowance = account_service.verify_asset_allowance(
        identity.wallet_identity_id,
        BASE,
        BASE_TOKEN,
        SPENDER,
        BASE_APPROVAL_TX,
    )
    assert polygon_allowance.network == POLYGON
    assert base_allowance.network == BASE
    assert polygon_allowance.asset_allowance_id != base_allowance.asset_allowance_id

    prediction = resolution_request(
        product="prediction_markets",
        venue="polymarket",
        network=BASE,
        token=BASE_TOKEN,
        merchant="polymarket",
    )
    marketplace = resolution_request(
        product="marketplace",
        venue="clink_marketplace",
        network=BASE,
        token=BASE_TOKEN,
        merchant="merchant_1",
    )
    prediction_resolution = account_service.resolve_authorization(prediction)
    marketplace_resolution = account_service.resolve_authorization(marketplace)
    assert prediction_resolution.ready is True
    assert marketplace_resolution.ready is True
    assert prediction_resolution.spending_grant_id == grant.spending_grant_id
    assert marketplace_resolution.spending_grant_id == grant.spending_grant_id
    assert prediction_resolution.asset_allowance_id == base_allowance.asset_allowance_id
    assert marketplace_resolution.asset_allowance_id == base_allowance.asset_allowance_id

    action_service = ActionService(config=config)
    policy_service = PolicyService(
        config=config,
        risk_provider=AllowRiskProvider(),
    )
    audit_service = AuditService(database_url=database_url)
    settlement_rpc = SettlementRpc(wallet.address)
    funding_service = FundingService(
        config=config,
        storage_file=tmp_path / "funding.jsonl",
        rpc_transport=settlement_rpc,
    )
    funding_service._utc_now = lambda: NOW.replace(tzinfo=None)
    product_scopes = (
        {
                "product": "prediction_markets",
                "resolution": prediction,
                "allowance": base_allowance,
            "purchase_id": "prediction_funding_1",
            "quote_hash": "0x" + "aa" * 32,
            "merchant_id": "polymarket",
            "venue": "polymarket",
            "action_type": "funding_transfer",
            "audit_source": "clink_prediction_markets",
            "audit_event": "prediction_market_funding_policy_evaluated",
        },
        {
            "product": "marketplace",
            "resolution": marketplace,
            "allowance": base_allowance,
            "purchase_id": "marketplace_purchase_1",
            "quote_hash": "0x" + "bb" * 32,
            "merchant_id": "merchant_1",
            "venue": "clink_marketplace",
            "action_type": "marketplace_purchase",
            "audit_source": "clink_marketplace",
            "audit_event": "marketplace_purchase_policy_evaluated",
        },
    )
    outcomes = []
    for scope in product_scopes:
        resolution = scope["resolution"]
        provenance = {
            "purchase_id": scope["purchase_id"],
            "quote_hash": scope["quote_hash"],
            "network": resolution.network,
            "asset": resolution.token_address,
            "amount_atomic": "2000000",
            "destination": DESTINATION,
            "resource": resolution.resource,
            "authorization_rail": "native_allowance",
            "product": scope["product"],
            "wallet_identity_id": identity.wallet_identity_id,
            "spending_grant_id": grant.spending_grant_id,
            "asset_allowance_id": scope["allowance"].asset_allowance_id,
            **(
                {"merchant_trust_tier": "clink_verified"}
                if scope["product"] == "marketplace"
                else {}
            ),
        }
        action = action_service.create_intent(
            CreateActionIntentRequest(
                user_id="user_1",
                agent_id="hermes",
                action_type=scope["action_type"],
                amount_usdc="2",
                merchant_id=scope["merchant_id"],
                metadata=provenance,
            )
        )
        policy = policy_service.evaluate(
            EvaluateActionPolicyRequest(
                action_id=action.action_id,
                user_id="user_1",
                agent_id="hermes",
                action_type=scope["action_type"],
                amount_usdc="2",
                merchant_id=scope["merchant_id"],
                target_address=DESTINATION,
                chain=resolution.network,
                user_confirmed=True,
                metadata=provenance,
            )
        )
        assert policy.approved is True
        action_service.update_intent(
            action.action_id,
            UpdateActionIntentRequest(
                state="policy_approved", policy_decision_id=policy.policy_decision_id
            ),
        )
        audit = audit_service.write_event(
            WriteAuditEventRequest(
                event_type=scope["audit_event"],
                source_service=scope["audit_source"],
                action_id=action.action_id,
                user_id="user_1",
                agent_id="hermes",
                policy_decision_id=policy.policy_decision_id,
                payload={
                    **provenance,
                    "merchant_id": scope["merchant_id"],
                    "venue": scope["venue"],
                },
            )
        )
        reservation = funding_service.reserve_spending(
            CreateSpendingReservationRequest(
                idempotency_key=scope["purchase_id"],
                action_id=action.action_id,
                policy_decision_id=policy.policy_decision_id,
                merchant_id=scope["merchant_id"],
                amount_usdc="2",
                venue=scope["venue"],
                **provenance,
            )
        )
        settled = funding_service.settle_reservation(
            reservation["reservation_id"],
            SettleSpendingReservationRequest(
                payment_authorization={
                    "scheme": "exact",
                    "network": resolution.network,
                    "asset": "USDC",
                    "amount_atomic": "2000000",
                    "pay_to": DESTINATION,
                },
            ),
        )

        assert action_service.get_intent(action.action_id).metadata == provenance
        assert policy.metadata == provenance
        assert audit.payload == {
            **provenance,
            "merchant_id": scope["merchant_id"],
            "venue": scope["venue"],
        }
        assert reservation["authorization_path"] == "unified_grant"
        assert reservation["authorization_rail"] == "native_allowance"
        assert reservation["product"] == scope["product"]
        assert reservation["single_submission"] is (
            scope["product"] == "prediction_markets"
        )
        assert reservation["spending_grant_id"] == grant.spending_grant_id
        assert reservation["asset_allowance_id"] == scope["allowance"].asset_allowance_id
        assert settled["state"] == "settled"
        assert settled["budget_accounting_state"] == "settled"
        assert settled["settlement_rail"] == "clink_allowance"
        outcomes.append((action, policy, audit, reservation, settled))

    assert outcomes[0][0].action_id != outcomes[1][0].action_id
    assert outcomes[0][1].policy_decision_id != outcomes[1][1].policy_decision_id
    assert outcomes[0][2].event_id != outcomes[1][2].event_id
    assert repository.spending_grant(grant.spending_grant_id).used_amount_usdc == Decimal(
        "4"
    )
    assert repository.spending_grant_daily_usage(
        grant.spending_grant_id, NOW.date()
    ) == (Decimal("4"), Decimal("0"))
    assert settlement_rpc.sent_networks == [BASE, BASE]

    account_service.revoke_spending_grant(grant.spending_grant_id)
    for request in (prediction, marketplace):
        unavailable = account_service.resolve_authorization(request)
        assert unavailable.ready is False
        assert unavailable.reason_code == "SPENDING_GRANT_REQUIRED"


def test_external_x402_end_to_end_requires_grant_but_no_allowance(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'external.sqlite3'}"
    monkeypatch.setenv("ACTION_INTENT_FILE", str(tmp_path / "external-actions.jsonl"))
    monkeypatch.setenv("POLICY_DECISION_FILE", str(tmp_path / "external-policies.jsonl"))
    monkeypatch.setenv("AUDIT_EVENT_FILE", str(tmp_path / "external-audit.jsonl"))
    config = AppConfig(
        funding_database_url=database_url,
        account_allowed_products=("marketplace",),
        x402_payment_network=BASE,
        x402_payment_token_address=BASE_TOKEN,
        clink_receipt_signing_key=RECEIPT_SIGNING_KEY,
        native_min_confirmations=1,
    )
    wallet = Account.create()
    repository = AccountRepository(database_url)
    identity = repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_external",
            user_id="user_1",
            wallet_address=wallet.address,
            status="active",
            proof_hash="0xproof",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    grant = repository.save_spending_grant(
        SpendingGrant(
            spending_grant_id="grant_external",
            wallet_identity_id=identity.wallet_identity_id,
            user_id="user_1",
            agent_id="hermes",
            status="active",
            max_amount_usdc=Decimal("5"),
            per_transaction_limit_usdc=Decimal("2"),
            daily_limit_usdc=Decimal("5"),
            product_scopes=["marketplace"],
            venue_scopes=["clink_marketplace"],
            merchant_scopes=["merchant_1"],
            network_scopes=[BASE],
            asset_scopes=[BASE_TOKEN],
            starts_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    account_service = AccountService(
        repository,
        domain="account.clink.example",
        clock=lambda: NOW,
        network_configs=account_network_configs(),
        allowed_products={"marketplace"},
    )
    request = resolution_request(
        product="marketplace",
        venue="clink_marketplace",
        network=BASE,
        token=BASE_TOKEN,
        merchant="merchant_1",
        authorization_rail="external_x402",
    )
    resolution = account_service.resolve_authorization(request)

    assert resolution.ready is True
    assert resolution.authorization_rail == "external_x402"
    assert resolution.asset_allowance_id is None
    assert repository.asset_allowances(identity.wallet_identity_id) == []

    scope = {
        "purchase_id": "external_purchase_1",
        "quote_hash": "0x" + "cc" * 32,
        "network": BASE,
        "asset": "USDC",
        "amount_atomic": "2000000",
        "destination": DESTINATION,
        "resource": request.resource,
        "authorization_rail": "external_x402",
        "product": "marketplace",
        "wallet_identity_id": identity.wallet_identity_id,
        "spending_grant_id": grant.spending_grant_id,
        "token_address": BASE_TOKEN,
        "merchant_trust_tier": "clink_verified",
    }
    actions = ActionService(config=config)
    action = actions.create_intent(
        CreateActionIntentRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="2",
            merchant_id="merchant_1",
            metadata=scope,
        )
    )
    policy = PolicyService(config=config).evaluate(
        EvaluateActionPolicyRequest(
            action_id=action.action_id,
            user_id="user_1",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="2",
            merchant_id="merchant_1",
            target_address=DESTINATION,
            chain=BASE,
            user_confirmed=True,
            metadata=scope,
        )
    )
    actions.update_intent(
        action.action_id,
        UpdateActionIntentRequest(
            state="policy_approved", policy_decision_id=policy.policy_decision_id
        ),
    )
    AuditService(database_url=database_url).write_event(
        WriteAuditEventRequest(
            event_type="marketplace_purchase_policy_evaluated",
            source_service="clink_marketplace",
            action_id=action.action_id,
            user_id="user_1",
            agent_id="hermes",
            policy_decision_id=policy.policy_decision_id,
            payload={
                **scope,
                "merchant_id": "merchant_1",
                "venue": "clink_marketplace",
            },
        )
    )
    chain = SettlementRpc(wallet.address)
    funding = FundingService(
        config=config,
        storage_file=tmp_path / "external-funding.jsonl",
        rpc_transport=chain,
    )
    funding._utc_now = lambda: NOW.replace(tzinfo=None)
    reservation = funding.reserve_spending(
        CreateSpendingReservationRequest(
            idempotency_key="external_purchase_1",
            action_id=action.action_id,
            policy_decision_id=policy.policy_decision_id,
            merchant_id="merchant_1",
            amount_usdc="2",
            venue="clink_marketplace",
            **scope,
        )
    )
    transaction_hash = chain.transaction_hash("marketplace")
    chain.bind_external_challenge(transaction_hash, reservation)
    settled = funding.finalize_external_payment(
        reservation["reservation_id"],
        FinalizeExternalPaymentRequest(
            transaction_hash=transaction_hash,
            payment_response={
                "network": BASE,
                "asset": "USDC",
                "amount_atomic": "2000000",
                "pay_to": DESTINATION,
                "nonce": reservation["nonce"],
                "valid_after": reservation["valid_after"],
                "valid_before": reservation["valid_before"],
            },
        ),
    )

    assert reservation["authorization_rail"] == "external_x402"
    assert reservation["asset_allowance_id"] is None
    assert settled["state"] == "settled"
    assert settled["settlement_rail"] == "external_x402_signature"
    assert settled["receipt_id"]
    assert funding._load_latest("receipt")[settled["receipt_id"]]["tx_hash"] == (
        transaction_hash
    )
