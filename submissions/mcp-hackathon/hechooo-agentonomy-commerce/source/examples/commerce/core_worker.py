"""Process-isolated composition of the real Core services for the local demo.

The worker deliberately owns all wallet, grant and ledger state.  Its only
public transport is JSON lines on stdin/stdout; the chain and risk boundaries
are explicit in-memory simulation fixtures and never perform network I/O.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = ROOT / "apps" / "core"


def _clean_environment() -> None:
    """Prevent inherited deployment configuration from reaching Core services."""

    safe_keys = {
        "PATH",
        "SYSTEMROOT",
        "TMPDIR",
        "LANG",
        "LC_ALL",
    }
    safe = {key: value for key, value in os.environ.items() if key in safe_keys}
    safe["PYTHONPATH"] = str(CORE_ROOT)
    safe["PYTHONUNBUFFERED"] = "1"
    os.environ.clear()
    os.environ.update(safe)


_clean_environment()
sys.path.insert(0, str(CORE_ROOT))
sys.path.insert(0, str(ROOT))

from examples.commerce.core_persistence import (  # noqa: E402
    CorePersistenceError,
    PersistentCoreState,
    SettlementJournal,
    StateLock,
)

from eth_account import Account  # noqa: E402
from eth_account._utils.legacy_transactions import Transaction  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from eth_utils import keccak  # noqa: E402
import rlp  # noqa: E402

from services.account_service.repository import AccountRepository  # noqa: E402
from services.account_service.schemas import (  # noqa: E402
    AuthorizationResolutionRequest,
    PublicAccountSession,
    SpendingGrantRequest,
)
from services.account_service.service import AccountService  # noqa: E402
from services.action_service.schemas import (  # noqa: E402
    CreateActionIntentRequest,
    UpdateActionIntentRequest,
)
from services.action_service.service import ActionService  # noqa: E402
from services.audit_service.schemas import WriteAuditEventRequest  # noqa: E402
from services.audit_service.service import AuditService  # noqa: E402
from services.funding_service.schemas import (  # noqa: E402
    CreateSpendingReservationRequest,
    FinalizeSpendingReservationRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
)
from services.funding_service.service import FundingService  # noqa: E402
from services.policy_service.risk_provider import RiskProviderResult  # noqa: E402
from services.policy_service.schemas import EvaluateActionPolicyRequest  # noqa: E402
from services.policy_service.service import PolicyService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


POLYGON = "eip155:137"
POLYGON_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
RELAYER_KEY = "0x" + "33" * 32
SPENDER = Account.from_key(RELAYER_KEY).address
DESTINATION = "0x" + "44" * 20
APPROVAL_TX = "0x" + "55" * 32
RECEIPT_SIGNING_KEY = "agentonomy-commerce-simulation-receipt-key-" + "r" * 32

USER_ID = "commerce-demo-user"
AGENT_ID = "hermes"
MERCHANT_ID = "commerce_analytics"
VENUE = "clink_marketplace"
TRUST_TIER = "clink_verified"
RESOURCE = "https://commerce.local/analytics"
SIMULATION_LABEL = "local-in-memory-rpc-no-network"
TRANSFER_TOPIC = "0x" + keccak(
    text="Transfer(address,address,uint256)"
).hex()


def _money(value: Decimal | str | int) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.01")), ".2f")


def _address_word(value: str) -> str:
    return value.removeprefix("0x").lower().rjust(64, "0")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return _money(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _network_configs() -> dict[str, dict[str, Any]]:
    return {
        POLYGON: {
            "chain_id": 137,
            "required_confirmations": 1,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": POLYGON_TOKEN,
        }
    }


def _approve_calldata(spender: str, amount: int) -> str:
    return "0x095ea7b3" + _address_word(spender) + amount.to_bytes(32, "big").hex()


class AllowRiskProvider:
    """Deterministic low-risk result with a short, current validity window."""

    def assess(self, *, subject: str, network: str, asset: str = "USDC"):
        now = datetime.now(UTC)
        return RiskProviderResult(
            provider="misttrack",
            endpoint="v2/risk_score",
            subject=subject,
            network=network,
            asset=asset,
            coin="USDC-Polygon",
            score=10,
            risk_level="low",
            indicators=(),
            risk_details=(),
            hacking_event=None,
            assessed_at=now,
            expires_at=now + timedelta(minutes=5),
            response_sha256="a" * 64,
        )


class ApprovalRpc:
    """Closed-world allowance proof transport used only during local setup."""

    def __init__(self, owner: str) -> None:
        self.owner = owner

    def __call__(self, network: str, method: str, params: list[Any]) -> Any:
        if network != POLYGON:
            raise AssertionError("simulation only supports the configured Polygon rail")
        if method == "eth_chainId":
            return hex(137)
        if method == "eth_blockNumber":
            return "0x69"
        if method == "eth_call":
            return hex(20_000_000)

        tx_hash = params[0]
        if tx_hash != APPROVAL_TX:
            raise AssertionError("unknown simulated approval transaction")
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
                "to": POLYGON_TOKEN,
                "input": _approve_calldata(SPENDER, 20_000_000),
                "blockNumber": "0x64",
            }
        raise AssertionError(f"unexpected allowance RPC method: {method}")


class SettlementRpc:
    """Local RPC fixture which records and deterministically mines one transfer."""

    def __init__(self, payer: str, *, journal: SettlementJournal | None = None) -> None:
        self.payer = payer
        self._journal = journal
        self.sent_networks: list[str] = []
        self.receipts: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        if journal is not None:
            self.sent_networks = journal.sent_networks
            self.receipts = journal.receipts
            self.transactions = journal.transactions

    @property
    def submission_count(self) -> int:
        return len(self.sent_networks)

    def __call__(self, network: str, method: str, params: list[Any]) -> Any:
        if network != POLYGON:
            raise AssertionError("simulation only supports the configured Polygon rail")
        if method == "eth_chainId":
            return hex(137)
        if method == "eth_call":
            return hex(20_000_000)
        if method == "eth_getTransactionCount":
            return hex(len(self.sent_networks))
        if method == "eth_gasPrice":
            return hex(1_000_000_000)
        if method == "eth_estimateGas":
            return hex(100_000)
        if method == "eth_blockNumber":
            return "0x20"
        if method == "eth_sendRawTransaction":
            raw = params[0]
            raw_bytes = bytes.fromhex(str(raw).removeprefix("0x"))
            transaction_hash = "0x" + keccak(raw_bytes).hex()
            decoded = rlp.decode(raw_bytes, Transaction)
            input_data = "0x" + decoded.data.hex()
            if not input_data.startswith("0x23b872dd"):
                raise AssertionError("simulation received a non-transferFrom transaction")
            owner = "0x" + decoded.data[4 + 12 : 4 + 32].hex()
            destination = "0x" + decoded.data[4 + 32 + 12 : 4 + 64].hex()
            amount = int.from_bytes(decoded.data[4 + 64 : 4 + 96], "big")
            token = "0x" + decoded.to.hex()
            transaction = {
                "hash": transaction_hash,
                "from": Account.recover_transaction(raw),
                "nonce": hex(decoded.nonce),
                "to": token,
                "input": input_data,
            }
            receipt = {
                "transactionHash": transaction_hash,
                "status": "0x1",
                "blockNumber": "0x20",
                "logs": [
                    {
                        "address": token,
                        "topics": [
                            TRANSFER_TOPIC,
                            "0x" + _address_word(owner),
                            "0x" + _address_word(destination),
                        ],
                        "data": "0x" + amount.to_bytes(32, "big").hex(),
                    }
                ],
            }
            if transaction_hash in self.transactions:
                return transaction_hash
            if self._journal is not None:
                self._journal.record(
                    network,
                    transaction_hash,
                    transaction,
                    receipt,
                )
            self.sent_networks.append(network)
            self.transactions[transaction_hash] = transaction
            self.receipts[transaction_hash] = receipt
            return transaction_hash
        if not params:
            raise AssertionError(f"missing transaction hash for {method}")
        transaction_hash = params[0]
        if method == "eth_getTransactionByHash":
            return self.transactions.get(transaction_hash)
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(transaction_hash)
        raise AssertionError(f"unexpected settlement RPC method: {method}")


class CoreRuntime:
    """Real Core service composition owned by one worker process."""

    def __init__(
        self,
        state_dir: Path,
        *,
        persistent: bool = False,
    ) -> None:
        self.state_dir = state_dir.expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.persistent = persistent
        self._state_lock: StateLock | None = None
        self._persistent_state: PersistentCoreState | None = None
        database_path = self.state_dir / "core.sqlite3"
        if persistent:
            self._persistent_state = PersistentCoreState(
                self.state_dir,
                database_path,
            )
            self._state_lock = StateLock(self.state_dir)
            self._state_lock.acquire()
            self._persistent_state.prepare()
        database_url = f"sqlite+pysqlite:///{database_path}"

        receipt_signing_key = (
            self._persistent_state.receipt_secret
            if self._persistent_state is not None
            else RECEIPT_SIGNING_KEY
        )
        if not receipt_signing_key:
            raise CorePersistenceError("persistent Core receipt secret is unavailable")

        self.config = AppConfig(
            funding_database_url=database_url,
            account_allowed_products=("marketplace",),
            clink_live_funding=True,
            clink_native_facilitator_enabled=True,
            risk_mode="enforce",
            risk_provider="misttrack",
            misttrack_api_key="local-simulation-risk-fixture",
            polygon_rpc_url="http://127.0.0.1/simulation/polygon",
            base_rpc_url="http://127.0.0.1/simulation/base",
            clink_native_facilitator_relayer_private_key=RELAYER_KEY,
            clink_funding_spender_address=SPENDER,
            clink_polygon_usdc_address=POLYGON_TOKEN,
            clink_polygon_spender_address=SPENDER,
            clink_base_usdc_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            clink_base_spender_address=SPENDER,
            x402_payment_network=POLYGON,
            x402_payment_token="USDC",
            x402_payment_token_address=POLYGON_TOKEN,
            clink_receipt_signing_key=receipt_signing_key,
            native_min_confirmations=1,
        )

        persisted_metadata = (
            self._persistent_state.metadata
            if self._persistent_state is not None
            else None
        )
        self.wallet = None
        self.wallet_address = (
            persisted_metadata["wallet_address"] if persisted_metadata else ""
        )
        if persisted_metadata is None:
            self.wallet = Account.create()
            self.wallet_address = self.wallet.address
        self.repository = AccountRepository(database_url)
        self.approval_rpc = ApprovalRpc(self.wallet_address)
        self.account_service = AccountService(
            self.repository,
            domain="account.agentonomy-commerce.local",
            clock=lambda: datetime.now(UTC),
            rpc_transport=self.approval_rpc,
            network_configs=_network_configs(),
            allowed_products=set(self.config.account_allowed_products),
        )
        if persisted_metadata is None:
            self.wallet_identity, self.grant, self.allowance = (
                self._create_signed_authorization()
            )
            if self._persistent_state is not None:
                self._persistent_state.save_metadata(
                    {
                        "version": 1,
                        "wallet_address": self.wallet_address,
                        "wallet_identity_id": self.wallet_identity.wallet_identity_id,
                        "spending_grant_id": self.grant.spending_grant_id,
                        "asset_allowance_id": self.allowance.asset_allowance_id,
                        "user_id": USER_ID,
                        "agent_id": AGENT_ID,
                        "grant_expires_at": self.grant.expires_at.isoformat(),
                    }
                )
        else:
            self.wallet_identity, self.grant, self.allowance = (
                self._load_persisted_authorization(persisted_metadata)
            )

        self.action_service = ActionService(config=self.config)
        self.policy_service = PolicyService(
            config=self.config,
            risk_provider=AllowRiskProvider(),
        )
        self.audit_service = AuditService(
            database_url=database_url,
            storage_file=self.state_dir / "audit.jsonl",
            clock=lambda: datetime.now(UTC),
        )
        settlement_journal = (
            self._persistent_state.settlement_journal()
            if self._persistent_state is not None
            else None
        )
        self.settlement_rpc = SettlementRpc(
            self.wallet_address,
            journal=settlement_journal,
        )
        self.funding_service = FundingService(
            config=self.config,
            storage_file=self.state_dir / "funding.jsonl",
            rpc_transport=self.settlement_rpc,
            policy_service=self.policy_service,
        )

    def _load_persisted_authorization(
        self, metadata: dict[str, Any]
    ) -> tuple[Any, Any, Any]:
        identity = self.repository.wallet_identity(metadata["wallet_identity_id"])
        grant = self.repository.spending_grant(metadata["spending_grant_id"])
        allowance = self.repository.asset_allowance(metadata["asset_allowance_id"])
        if identity is None or grant is None or allowance is None:
            raise CorePersistenceError(
                "persistent Core metadata references missing authorization state"
            )
        if identity.wallet_address.lower() != metadata["wallet_address"].lower():
            raise CorePersistenceError(
                "persistent Core wallet identity does not match metadata"
            )
        if identity.user_id != metadata["user_id"]:
            raise CorePersistenceError(
                "persistent Core wallet identity user does not match metadata"
            )
        if grant.wallet_identity_id != identity.wallet_identity_id:
            raise CorePersistenceError(
                "persistent Core spending grant does not match wallet identity"
            )
        if grant.user_id != metadata["user_id"] or grant.agent_id != metadata["agent_id"]:
            raise CorePersistenceError(
                "persistent Core spending grant scope does not match metadata"
            )
        if allowance.wallet_identity_id != identity.wallet_identity_id:
            raise CorePersistenceError(
                "persistent Core asset allowance does not match wallet identity"
            )
        try:
            expected_expiry = datetime.fromisoformat(metadata["grant_expires_at"])
        except (TypeError, ValueError) as exc:
            raise CorePersistenceError("persistent Core grant expiry is invalid") from exc
        if grant.expires_at.astimezone(UTC) != expected_expiry.astimezone(UTC):
            raise CorePersistenceError(
                "persistent Core spending grant expiry does not match metadata"
            )
        return identity, grant, allowance

    def _create_signed_authorization(self):
        if self.wallet is None:
            raise CorePersistenceError(
                "persistent Core cannot create authorization without a wallet signer"
            )
        wallet = self.wallet
        now = datetime.now(UTC)
        public_session = self.repository.create_public_account_session(
            PublicAccountSession(
                public_account_session_id=f"public_{uuid4().hex}",
                token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
                browser_session_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
                csrf_token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
                user_id=USER_ID,
                expires_at=now + timedelta(minutes=30),
                exchanged_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        wallet_challenge = self.account_service.create_wallet_challenge(
            USER_ID,
            wallet.address,
            created_by_public_account_session_id=public_session.public_account_session_id,
        )
        wallet_signature = Account.sign_message(
            encode_defunct(text=wallet_challenge.message_to_sign),
            wallet.key,
        ).signature.hex()
        identity = self.account_service.verify_wallet_challenge(
            wallet_challenge.session_id,
            wallet_challenge.message_to_sign,
            wallet_signature,
        )

        unsigned_grant = SpendingGrantRequest(
            user_id=USER_ID,
            wallet_identity_id=identity.wallet_identity_id,
            agent_id=AGENT_ID,
            max_amount_usdc=Decimal("1.00"),
            per_transaction_limit_usdc=Decimal("1.00"),
            hourly_limit_usdc=Decimal("1.00"),
            daily_limit_usdc=Decimal("1.00"),
            product_scopes=["marketplace"],
            venue_scopes=[VENUE],
            merchant_scopes=[MERCHANT_ID],
            merchant_trust_scopes=[TRUST_TIER],
            notification_mode="silent_under_limits",
            network_scopes=[POLYGON],
            asset_scopes=[POLYGON_TOKEN],
            starts_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=30 if self.persistent else 1),
        )
        grant_challenge = self.account_service.create_spending_grant_challenge(
            unsigned_grant
        )
        grant_signature = Account.sign_message(
            encode_defunct(text=grant_challenge.message_to_sign),
            wallet.key,
        ).signature.hex()
        grant = self.account_service.create_spending_grant(
            unsigned_grant.model_copy(
                update={
                    "session_id": grant_challenge.session_id,
                    "signed_message": grant_challenge.message_to_sign,
                    "signature": grant_signature,
                }
            )
        )
        allowance = self.account_service.verify_asset_allowance(
            identity.wallet_identity_id,
            POLYGON,
            POLYGON_TOKEN,
            SPENDER,
            APPROVAL_TX,
        )
        return identity, grant, allowance

    def resolve_authorization(self, payload: dict[str, Any]) -> dict:
        request = AuthorizationResolutionRequest.model_validate(payload)
        return self.account_service.resolve_authorization(request).model_dump(mode="json")

    def create_account_session(self, user_id: str) -> dict:
        """Return the same account-console projection as Core's internal API."""

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.config.account_session_ttl_seconds)
        session_id = secrets.token_urlsafe(32)
        self.repository.create_public_account_session(
            PublicAccountSession(
                public_account_session_id=f"public_{uuid4().hex}",
                token_digest=hashlib.sha256(session_id.encode()).hexdigest(),
                user_id=user_id,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
        )
        return {
            "session_id": session_id,
            "account_url": f"/account/{session_id}",
            "expires_at": expires_at.isoformat(),
        }

    def create_action(self, payload: dict[str, Any]) -> dict:
        request = CreateActionIntentRequest.model_validate(payload)
        return self.action_service.create_intent(request).model_dump(mode="json")

    def evaluate_policy(self, payload: dict[str, Any]) -> dict:
        request = EvaluateActionPolicyRequest.model_validate(payload)
        return self.policy_service.evaluate(request).model_dump(mode="json")

    def update_action(self, action_id: str, payload: dict[str, Any]) -> dict:
        request = UpdateActionIntentRequest.model_validate(payload)
        action = self.action_service.update_intent(action_id, request)
        if action is None:
            raise ValueError("action intent not found")
        return action.model_dump(mode="json")

    def audit(self, payload: dict[str, Any]) -> dict:
        request = WriteAuditEventRequest.model_validate(payload)
        return self.audit_service.write_event(request).model_dump(mode="json")

    def funding_readiness(self) -> dict:
        return {
            **self.funding_service.get_funding_readiness(),
            "simulation": True,
            "simulation_label": SIMULATION_LABEL,
        }

    def reserve(self, payload: dict[str, Any]) -> dict:
        request = CreateSpendingReservationRequest.model_validate(payload)
        return self.funding_service.reserve_spending(request)

    def settle(self, reservation_id: str, payload: dict[str, Any]) -> dict:
        request = SettleSpendingReservationRequest.model_validate(payload)
        result = self.funding_service.settle_reservation(reservation_id, request)
        return self._verified_settlement(result)

    def reconcile(self, reservation_id: str) -> dict:
        result = self.funding_service.reconcile_reservation(reservation_id)
        return self._verified_settlement(result)

    def finalize(self, reservation_id: str, payload: dict[str, Any]) -> dict:
        request = FinalizeSpendingReservationRequest.model_validate(payload)
        return self.funding_service.finalize_reservation(reservation_id, request)

    def reservation(self, reservation_id: str) -> dict | None:
        return self.funding_service.get_reservation(reservation_id)

    def release(self, reservation_id: str, reason: str) -> dict:
        request = ReleaseSpendingReservationRequest(reason=reason)
        return self.funding_service.release_reservation(reservation_id, request)

    def health(self) -> dict:
        readiness = self.funding_readiness()
        return {
            "status": readiness["status"],
            "simulation": True,
            "real_funds": False,
            "simulation_label": SIMULATION_LABEL,
            "funding": {
                "status": readiness["status"],
                "network": POLYGON,
                "token": POLYGON_TOKEN,
                "spender_address": readiness.get("spender_address"),
            },
        }

    def snapshot(self) -> dict:
        grant = self.repository.spending_grant(self.grant.spending_grant_id)
        if grant is None:
            raise ValueError("demo spending grant not found")
        return {
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "wallet_address": self.wallet_address,
            "wallet_identity_id": self.wallet_identity.wallet_identity_id,
            "grant_id": grant.spending_grant_id,
            "grant_status": grant.status,
            "grant_expires_at": grant.expires_at.isoformat(),
            "budget_usdc": _money(grant.max_amount_usdc),
            "used_amount_usdc": _money(grant.used_amount_usdc),
            "reserved_amount_usdc": _money(grant.reserved_amount_usdc),
            "network": POLYGON,
            "token": POLYGON_TOKEN,
            "pay_to": DESTINATION,
            "merchant_id": MERCHANT_ID,
            "resource": RESOURCE,
            "spender_address": SPENDER,
            "settlement_submissions": self.settlement_rpc.submission_count,
            "receipt_signing_key": self.config.clink_receipt_signing_key,
            "simulation": True,
            "simulation_label": SIMULATION_LABEL,
        }

    def revoke(self) -> dict:
        grant = self.account_service.revoke_spending_grant(self.grant.spending_grant_id)
        return grant.model_dump(mode="json")

    def _verified_settlement(self, result: dict) -> dict:
        if result.get("state") not in {"settled", "finalized"}:
            return result
        tx_hash = result.get("tx_hash")
        receipt = self.settlement_rpc.receipts.get(tx_hash)
        if not isinstance(receipt, dict):
            raise RuntimeError("simulation settlement receipt is missing")
        if receipt.get("transactionHash", "").lower() != str(tx_hash).lower():
            raise RuntimeError("simulation settlement receipt hash mismatch")
        if receipt.get("status") != "0x1":
            raise RuntimeError("simulation settlement receipt is unsuccessful")
        expected_token = str(result["token_address"]).lower()
        expected_owner = self.wallet_address.lower()
        expected_destination = str(result["destination"]).lower()
        expected_amount = int(result["amount_atomic"])
        matching_logs = []
        for log in receipt.get("logs", []):
            topics = log.get("topics") or []
            try:
                amount = int(str(log.get("data"))[2:], 16)
                owner = "0x" + str(topics[1])[2:][-40:].lower()
                destination = "0x" + str(topics[2])[2:][-40:].lower()
            except (IndexError, TypeError, ValueError):
                continue
            if (
                str(log.get("address", "")).lower() == expected_token
                and topics[0].lower() == TRANSFER_TOPIC.lower()
                and owner == expected_owner
                and destination == expected_destination
                and amount == expected_amount
            ):
                matching_logs.append(log)
        if len(matching_logs) != 1:
            raise RuntimeError("simulation settlement Transfer receipt log could not be verified")
        return {
            **result,
            "settlement_receipt_verified": True,
            "simulation_receipt": {
                "transactionHash": receipt["transactionHash"],
                "status": receipt["status"],
                "blockNumber": receipt["blockNumber"],
                "transfer_log_verified": True,
            },
        }

    def close(self) -> None:
        if self._state_lock is not None:
            self._state_lock.release()
            self._state_lock = None


METHODS = {
    "resolve_authorization",
    "create_account_session",
    "create_action",
    "evaluate_policy",
    "update_action",
    "audit",
    "funding_readiness",
    "reserve",
    "settle",
    "reconcile",
    "finalize",
    "reservation",
    "release",
    "health",
    "snapshot",
    "revoke",
}


def _dispatch(runtime: CoreRuntime, method: str, params: dict[str, Any]) -> Any:
    if method not in METHODS:
        raise ValueError("unknown local Core operation")
    if method in {"resolve_authorization", "create_action", "evaluate_policy", "audit", "reserve"}:
        return getattr(runtime, method)(params)
    if method == "create_account_session":
        return runtime.create_account_session(params["user_id"])
    if method == "update_action":
        return runtime.update_action(params["action_id"], params.get("payload", {}))
    if method in {"settle", "finalize"}:
        return getattr(runtime, method)(params["reservation_id"], params.get("payload", {}))
    if method in {"reconcile", "reservation"}:
        return getattr(runtime, method)(params["reservation_id"])
    if method == "release":
        return runtime.release(params["reservation_id"], params.get("reason", ""))
    return getattr(runtime, method)()


def _response(request: dict[str, Any], *, result: Any = None, error: Exception | None = None) -> str:
    response: dict[str, Any] = {"id": request.get("id")}
    if error is None:
        response.update({"ok": True, "result": result})
    else:
        response.update(
            {
                "ok": False,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
    return json.dumps(response, default=_json_default, separators=(",", ":"))


def main() -> None:
    persistent = "--persistent" in sys.argv[1:]
    arguments = [argument for argument in sys.argv[1:] if argument != "--persistent"]
    if len(arguments) != 1:
        raise SystemExit("state directory argument is required")
    try:
        runtime = CoreRuntime(
            Path(arguments[0]),
            persistent=persistent,
        )
    except Exception as exc:
        print(_response({}, error=exc), flush=True)
        raise SystemExit(1) from exc
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            request: dict[str, Any] = {}
            try:
                request = json.loads(line)
                params = request.get("params")
                if params is None:
                    params = request.get("arguments", {})
                result = _dispatch(runtime, request["method"], params)
                print(_response(request, result=result), flush=True)
            except Exception as exc:
                print(_response(request, error=exc), flush=True)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
