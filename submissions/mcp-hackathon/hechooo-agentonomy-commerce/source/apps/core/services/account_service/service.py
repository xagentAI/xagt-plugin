from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from secrets import token_urlsafe
from typing import Any, Callable
from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak
from shared.canonical_assets import (
    AMOY_NETWORK,
    AMOY_USDC_ADDRESS,
    BASE_NETWORK,
    POLYGON_NETWORK,
    PRODUCTION_USDC_ADDRESSES,
    CanonicalAssetRegistry,
)

from .authorization import (
    REVIEWED_VENUE_BY_PRODUCT,
    grant_authorization_hash,
    reviewed_scope_amendment_is_valid,
)
from .repository import AccountRepository
from .schemas import (
    AccountSession,
    AssetAllowance,
    AuthorizationResolutionRequest,
    AuthorizationResolutionResult,
    MAX_UINT256,
    SpendingGrant,
    SpendingGrantRequest,
    WalletIdentity,
    canonicalize_evm_address,
    canonicalize_transaction_hash,
    reject_control_characters,
)


WALLET_IDENTITY_PURPOSE = "clink_wallet_identity"
SPENDING_GRANT_PURPOSE = "clink_spending_grant"
APPROVE_SELECTOR = "095ea7b3"
ALLOWANCE_SELECTOR = "dd62ed3e"
BALANCE_OF_SELECTOR = "70a08231"


class AllowanceVerificationPending(ValueError):
    """The same allowance proof may be checked again, but never resubmitted."""


class AllowanceAmountMismatch(ValueError):
    """A confirmed approve differs from the immutable prepared amount."""

    MESSAGE = "approve does not match the prepared amount"

    def __init__(self, evidence: dict[str, Any]):
        super().__init__(self.MESSAGE)
        # Keep the chain evidence independent from mutable ORM/recovery state.
        self.evidence = dict(evidence)
        self.recovery_record: dict[str, object] | None = None


DEFAULT_NETWORK_CONFIGS = {
    POLYGON_NETWORK: {
        "chain_id": 137,
        "required_confirmations": 3,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "token_address": PRODUCTION_USDC_ADDRESSES[POLYGON_NETWORK],
    },
    BASE_NETWORK: {
        "chain_id": 8453,
        "required_confirmations": 2,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "token_address": PRODUCTION_USDC_ADDRESSES[BASE_NETWORK],
    },
}
AMOY_NETWORK_CONFIG = {
    "chain_id": 80002,
    "required_confirmations": 3,
    "token_symbol": "USDC",
    "token_decimals": 6,
    "token_address": AMOY_USDC_ADDRESS,
}


def configured_network_configs(config: Any) -> dict[str, dict[str, Any]]:
    """Project account networks to the active Core economic scope."""

    if getattr(config, "hosted_rehearsal_enabled", False):
        return {AMOY_NETWORK: dict(AMOY_NETWORK_CONFIG)}
    return {
        network: dict(values) for network, values in DEFAULT_NETWORK_CONFIGS.items()
    }


@dataclass(frozen=True)
class WalletChallenge:
    session_id: str
    message_to_sign: str
    expires_at: datetime
    nonce: str


@dataclass(frozen=True)
class SpendingGrantChallenge:
    session_id: str
    message_to_sign: str
    expires_at: datetime
    nonce: str


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        *,
        domain: str,
        clock: Callable[[], datetime] | None = None,
        challenge_ttl: timedelta = timedelta(minutes=10),
        rpc_transport: Callable[[str, str, list[Any]], Any] | None = None,
        network_configs: dict[str, dict[str, Any]] | None = None,
        allowed_products: set[str] | None = None,
    ):
        if not domain:
            raise ValueError("wallet challenge domain is required")
        reject_control_characters(domain)
        if challenge_ttl <= timedelta(0):
            raise ValueError("wallet challenge TTL must be positive")
        self.repository = repository
        self.domain = domain
        self.clock = clock or (lambda: datetime.now(UTC))
        self.challenge_ttl = challenge_ttl
        self.rpc_transport = rpc_transport
        self.network_configs = self._validate_network_configs(
            DEFAULT_NETWORK_CONFIGS if network_configs is None else network_configs
        )
        self.asset_registry = CanonicalAssetRegistry(
            {
                network: config
                for network, config in self.network_configs.items()
                if config["token_address"] is not None
            }
        )
        self.allowed_products = (
            {"prediction_markets", "marketplace", "transfers"}
            if allowed_products is None
            else allowed_products
        )

    def create_wallet_challenge(
        self,
        user_id: str,
        wallet_address: str,
        return_url: str | None = None,
        *,
        authorizing_wallet_identity_id: str | None = None,
        created_by_public_account_session_id: str | None = None,
    ) -> WalletChallenge:
        """Persist a short-lived, single-use EIP-191 ownership challenge."""
        del return_url  # Transport routing is intentionally not part of the ownership proof.
        now = self._now()
        account_session = AccountSession(
            account_session_id=f"wallet_challenge_{uuid4().hex}",
            user_id=user_id,
            wallet_address=wallet_address,
            nonce=token_urlsafe(32),
            domain=self.domain,
            purpose=WALLET_IDENTITY_PURPOSE,
            wallet_identity_id=authorizing_wallet_identity_id,
            created_by_public_account_session_id=created_by_public_account_session_id,
            expires_at=now + self.challenge_ttl,
            created_at=now,
        )
        self.repository.save_account_session(account_session)
        return WalletChallenge(
            session_id=account_session.account_session_id,
            message_to_sign=self._canonical_message(account_session),
            expires_at=account_session.expires_at,
            nonce=account_session.nonce,
        )

    def verify_wallet_challenge(
        self, session_id: str, signed_message: str, signature: str
    ) -> WalletIdentity:
        account_session = self.repository.account_session(session_id)
        if account_session is None:
            raise ValueError("wallet challenge was not found")
        if account_session.domain != self.domain:
            raise ValueError("wallet challenge domain mismatch")

        expected_message = self._canonical_message(account_session)
        if not isinstance(signed_message, str) or signed_message.encode("utf-8") != expected_message.encode(
            "utf-8"
        ):
            raise ValueError("wallet challenge message does not match")

        signature_bytes = self._signature_bytes(signature)
        try:
            recovered_address = Account.recover_message(
                encode_defunct(text=expected_message), signature=signature
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid wallet signature") from exc
        if canonicalize_evm_address(recovered_address) != account_session.wallet_address:
            raise ValueError("wallet signature does not match challenge wallet")

        now = self._now()
        identity = WalletIdentity(
            wallet_identity_id=f"wallet_identity_{uuid4().hex}",
            user_id=account_session.user_id,
            wallet_address=account_session.wallet_address,
            status="active",
            proof_hash="0x" + keccak(signature_bytes).hex(),
            verified_at=now,
            created_at=now,
            updated_at=now,
        )
        return self.repository.consume_wallet_challenge_and_activate_identity(
            account_session.account_session_id, identity, now
        )

    def cancel_wallet_challenge(
        self,
        session_id: str,
        *,
        user_id: str,
        public_account_session_id: str,
    ) -> bool:
        return self.repository.cancel_wallet_challenge(
            session_id,
            user_id=user_id,
            public_account_session_id=public_account_session_id,
            now=self._now(),
        )

    def revoke_wallet_identity(self, wallet_identity_id: str) -> WalletIdentity:
        return self.repository.revoke_wallet_identity_and_pause_active_grants(
            wallet_identity_id, self._now()
        )

    def disconnect_wallet_identity(
        self,
        wallet_identity_id: str,
        public_account_session_id: str,
    ) -> WalletIdentity:
        return self.repository.disconnect_wallet_identity(
            wallet_identity_id,
            self._now(),
            require_prepared_allowances=True,
            public_account_session_id=public_account_session_id,
        )

    def prepare_wallet_identity_disconnect(
        self,
        wallet_identity_id: str,
        public_account_session_id: str,
    ) -> WalletIdentity:
        return self.repository.prepare_wallet_identity_disconnect(
            wallet_identity_id,
            public_account_session_id,
            self._now(),
        )

    def create_spending_grant_challenge(
        self, request: SpendingGrantRequest
    ) -> SpendingGrantChallenge:
        self._validate_grant_request(request)
        amended_grant = self._validated_amendment_target(request)
        identity = self.repository.wallet_identity(request.wallet_identity_id)
        if identity is None:
            raise ValueError("wallet identity was not found")
        if identity.user_id != request.user_id:
            raise ValueError("spending grant user does not match wallet identity")
        if identity.status != "active":
            raise ValueError("wallet identity is not active")

        now = self._now()
        payload = {
            "spending_grant_id": (
                amended_grant.spending_grant_id
                if amended_grant is not None
                else f"spending_grant_{uuid4().hex}"
            ),
            "terms": request.terms_payload(),
        }
        if amended_grant is not None:
            # Exclude mutable accounting counters so ordinary usage does not
            # invalidate an otherwise fresh signed amendment.
            payload["base_authority_hash"] = grant_authorization_hash(amended_grant)
            payload["base_authority_revision"] = (
                self.repository.spending_grant_authority_revision(
                    amended_grant.spending_grant_id
                )
            )
        account_session = AccountSession(
            account_session_id=f"spending_grant_challenge_{uuid4().hex}",
            user_id=request.user_id,
            wallet_address=identity.wallet_address,
            wallet_identity_id=identity.wallet_identity_id,
            nonce=token_urlsafe(32),
            domain=self.domain,
            purpose=SPENDING_GRANT_PURPOSE,
            created_by_public_account_session_id=(
                request.created_by_public_account_session_id
            ),
            payload=payload,
            payload_hash=self._payload_hash(payload),
            expires_at=now + self.challenge_ttl,
            created_at=now,
        )
        self.repository.save_account_session(account_session)
        return SpendingGrantChallenge(
            session_id=account_session.account_session_id,
            message_to_sign=self._canonical_grant_message(account_session),
            expires_at=account_session.expires_at,
            nonce=account_session.nonce,
        )

    def create_spending_grant(self, request: SpendingGrantRequest) -> SpendingGrant:
        if not request.session_id or not request.signed_message or not request.signature:
            raise ValueError("signed spending grant challenge is required")
        self._validate_grant_request(request)
        account_session = self.repository.account_session(request.session_id)
        if account_session is None:
            raise ValueError("spending grant challenge was not found")
        if account_session.domain != self.domain:
            raise ValueError("spending grant challenge domain mismatch")
        if account_session.purpose != SPENDING_GRANT_PURPOSE:
            raise ValueError("account session purpose mismatch")
        if not account_session.payload or "terms" not in account_session.payload:
            raise ValueError("spending grant challenge payload is invalid")
        if account_session.payload["terms"] != request.terms_payload():
            raise ValueError("grant terms do not match challenge")
        expected_payload_hash = self._payload_hash(account_session.payload)
        if account_session.payload_hash != expected_payload_hash:
            raise ValueError("spending grant challenge payload mismatch")

        expected_message = self._canonical_grant_message(account_session)
        if request.signed_message.encode("utf-8") != expected_message.encode("utf-8"):
            raise ValueError("spending grant message does not match challenge")
        try:
            recovered_address = Account.recover_message(
                encode_defunct(text=expected_message), signature=request.signature
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid spending grant signature") from exc
        if canonicalize_evm_address(recovered_address) != account_session.wallet_address:
            raise ValueError("spending grant signature does not match wallet")

        now = self._now()
        if request.amends_spending_grant_id is not None:
            self._validated_amendment_target(request)
            return self.repository.consume_grant_challenge_and_amend_grant(
                account_session.account_session_id,
                request,
                now,
                expected_payload_hash,
            )
        grant = SpendingGrant(
            spending_grant_id=account_session.payload["spending_grant_id"],
            wallet_identity_id=request.wallet_identity_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            status="pending" if request.starts_at > now else "active",
            max_amount_usdc=request.max_amount_usdc,
            per_transaction_limit_usdc=request.per_transaction_limit_usdc,
            hourly_limit_usdc=request.hourly_limit_usdc,
            daily_limit_usdc=request.daily_limit_usdc,
            product_scopes=request.product_scopes,
            venue_scopes=request.venue_scopes,
            merchant_scopes=request.merchant_scopes,
            merchant_trust_scopes=request.merchant_trust_scopes,
            notification_mode=request.notification_mode,
            network_scopes=request.network_scopes,
            asset_scopes=request.asset_scopes,
            starts_at=request.starts_at,
            expires_at=request.expires_at,
            created_at=now,
            updated_at=now,
        )
        return self.repository.consume_grant_challenge_and_create_grant(
            account_session.account_session_id,
            grant,
            now,
            expected_payload_hash,
        )

    def pause_spending_grant(self, spending_grant_id: str) -> SpendingGrant:
        return self.repository.pause_spending_grant(spending_grant_id, self._now())

    def resume_spending_grant(self, spending_grant_id: str) -> SpendingGrant:
        return self.repository.resume_spending_grant(spending_grant_id, self._now())

    def reduce_spending_grant(
        self,
        spending_grant_id: str,
        *,
        max_amount_usdc: Decimal | None = None,
        per_transaction_limit_usdc: Decimal | None = None,
        hourly_limit_usdc: Decimal | None = None,
        daily_limit_usdc: Decimal | None = None,
    ) -> SpendingGrant:
        return self.repository.reduce_spending_grant(
            spending_grant_id,
            self._now(),
            max_amount_usdc=max_amount_usdc,
            per_transaction_limit_usdc=per_transaction_limit_usdc,
            hourly_limit_usdc=hourly_limit_usdc,
            daily_limit_usdc=daily_limit_usdc,
        )

    def revoke_spending_grant(self, spending_grant_id: str) -> SpendingGrant:
        return self.repository.revoke_spending_grant(spending_grant_id, self._now())

    def resolve_authorization(
        self,
        request: AuthorizationResolutionRequest,
        *,
        opc_authorization: tuple[str, str] | None = None,
    ) -> AuthorizationResolutionResult:
        """Resolve immutable spending references without making a policy decision."""
        now = self._now()
        if request.opc_installation_id is None and opc_authorization is not None:
            raise ValueError("OPC authorization scope requires an installation")
        if request.opc_installation_id is not None and opc_authorization is None:
            return self._resolution_failure(
                "OPC_INSTALLATION_NOT_READY",
                opc_installation_id=request.opc_installation_id,
            )
        opc_wallet_identity_id, opc_spending_grant_id = (
            opc_authorization if opc_authorization is not None else (None, None)
        )

        def resolution_failure(reason_code: str) -> AuthorizationResolutionResult:
            return self._resolution_failure(
                reason_code,
                opc_installation_id=request.opc_installation_id,
            )

        identities = {
            item.wallet_identity_id: item
            for item in self.repository.active_wallet_identities(request.user_id)
            if opc_wallet_identity_id is None
            or item.wallet_identity_id == opc_wallet_identity_id
        }
        if not identities:
            return resolution_failure(
                "OPC_INSTALLATION_NOT_READY"
                if request.opc_installation_id is not None
                else "WALLET_IDENTITY_REQUIRED"
            )

        grants = [
            item
            for item in self.repository.active_spending_grants(request.user_id, at=now)
            if item.wallet_identity_id in identities and item.agent_id == request.agent_id
            and (
                opc_spending_grant_id is None
                or item.spending_grant_id == opc_spending_grant_id
            )
        ]
        if not grants:
            return resolution_failure(
                "OPC_INSTALLATION_NOT_READY"
                if request.opc_installation_id is not None
                else "SPENDING_GRANT_REQUIRED"
            )

        scope_stages = (
            (
                "PRODUCT_SCOPE_MISMATCH",
                lambda item: request.product in item.product_scopes,
            ),
            (
                "VENUE_SCOPE_MISMATCH",
                lambda item: (
                    request.product not in REVIEWED_VENUE_BY_PRODUCT
                    or (
                        request.product == "marketplace"
                        and request.venue is None
                    )
                    or request.venue == REVIEWED_VENUE_BY_PRODUCT[request.product]
                )
                and (not item.venue_scopes or request.venue in item.venue_scopes),
            ),
            (
                "MERCHANT_SCOPE_MISMATCH",
                lambda item: not item.merchant_scopes or request.merchant in item.merchant_scopes,
            ),
            (
                "MERCHANT_TRUST_SCOPE_MISMATCH",
                lambda item: (
                    request.product == "transfers"
                    and request.merchant_trust_tier is None
                )
                or (
                    request.product != "transfers"
                    and (
                        (
                            request.product != "marketplace"
                            and request.merchant_trust_tier is None
                        )
                        or request.merchant_trust_tier in item.merchant_trust_scopes
                    )
                ),
            ),
            (
                "NETWORK_SCOPE_MISMATCH",
                lambda item: request.network in item.network_scopes,
            ),
        )
        for reason_code, predicate in scope_stages:
            grants = [item for item in grants if predicate(item)]
            if not grants:
                return resolution_failure(reason_code)

        try:
            canonical_token = self.asset_registry.token_address(request.network)
        except ValueError:
            return resolution_failure("ASSET_SCOPE_MISMATCH")
        if request.token_address is not None and request.token_address != canonical_token:
            return resolution_failure("ASSET_SCOPE_MISMATCH")
        if request.asset is not None:
            try:
                requested_asset = canonicalize_evm_address(request.asset)
            except ValueError:
                requested_asset = None
            if requested_asset is not None and requested_asset != canonical_token:
                return resolution_failure("ASSET_SCOPE_MISMATCH")
        requested_tokens = {canonical_token}
        if requested_tokens:
            grants = [
                item
                for item in grants
                if any(token in item.asset_scopes for token in requested_tokens)
            ]
            if not grants:
                return resolution_failure("ASSET_SCOPE_MISMATCH")

        grants = [
            item
            for item in grants
            if request.amount_usdc <= item.per_transaction_limit_usdc
        ]
        if not grants:
            return resolution_failure("PER_TRANSACTION_LIMIT_EXCEEDED")

        grants_with_total = [
            (
                item,
                item.max_amount_usdc
                - item.used_amount_usdc
                - item.reserved_amount_usdc,
            )
            for item in grants
        ]
        grants_with_total = [
            value for value in grants_with_total if request.amount_usdc <= value[1]
        ]
        if not grants_with_total:
            return resolution_failure("BUDGET_EXCEEDED")

        grants_with_budget = []
        for item, remaining in grants_with_total:
            hourly_used, hourly_reserved = (
                self.repository.spending_grant_rolling_hour_usage(
                    item.spending_grant_id, now
                )
            )
            hourly_remaining = (
                item.hourly_limit_usdc - hourly_used - hourly_reserved
            )
            if request.amount_usdc > hourly_remaining:
                continue
            daily_used, daily_reserved = self.repository.spending_grant_daily_usage(
                item.spending_grant_id, now.date()
            )
            daily_remaining = item.daily_limit_usdc - daily_used - daily_reserved
            if request.amount_usdc <= daily_remaining:
                grants_with_budget.append(
                    (item, remaining, hourly_remaining, daily_remaining)
                )
        if not grants_with_budget:
            hourly_available = any(
                request.amount_usdc
                <= item.hourly_limit_usdc
                - sum(
                    self.repository.spending_grant_rolling_hour_usage(
                        item.spending_grant_id, now
                    )
                )
                for item, _remaining in grants_with_total
            )
            return resolution_failure(
                "DAILY_LIMIT_EXCEEDED" if hourly_available else "HOURLY_LIMIT_EXCEEDED"
            )

        if request.authorization_rail == "external_x402":
            selected_grant, remaining, hourly_remaining, daily_remaining = min(
                grants_with_budget,
                key=lambda value: (value[0].spending_grant_id, value[0].wallet_identity_id),
            )
            return AuthorizationResolutionResult(
                ready=True,
                opc_installation_id=request.opc_installation_id,
                authorization_rail="external_x402",
                wallet_identity_id=selected_grant.wallet_identity_id,
                spending_grant_id=selected_grant.spending_grant_id,
                remaining_amount_usdc=remaining,
                remaining_daily_amount_usdc=daily_remaining,
                remaining_hourly_amount_usdc=hourly_remaining,
                notification_mode=selected_grant.notification_mode,
                user_interaction_required=True,
                interaction_reason_code="EXTERNAL_X402_SIGNATURE_REQUIRED",
                next_action="create_action_and_evaluate_policy",
            )

        candidates = []
        for item, remaining, hourly_remaining, daily_remaining in grants_with_budget:
            for current in self.repository.asset_allowances(item.wallet_identity_id):
                if current.status != "active":
                    continue
                if current.network != request.network:
                    continue
                if current.spender_address != request.spender_address:
                    continue
                if not self._allowance_matches_asset(current, request):
                    continue
                if current.token_address not in item.asset_scopes:
                    continue
                required_atomic = request.amount_usdc * (Decimal(10) ** current.token_decimals)
                if required_atomic != required_atomic.to_integral_value():
                    continue
                required_atomic_int = int(required_atomic)
                if current.observed_allowance_atomic < required_atomic_int:
                    continue
                candidates.append(
                    (
                        item.spending_grant_id,
                        current.asset_allowance_id,
                        item.wallet_identity_id,
                        item,
                        current,
                        remaining,
                        hourly_remaining,
                        daily_remaining,
                        required_atomic_int,
                    )
                )
        if not candidates:
            return resolution_failure("ASSET_ALLOWANCE_REQUIRED")

        (
            _,
            _,
            wallet_identity_id,
            selected_grant,
            selected_allowance,
            remaining,
            hourly_remaining,
            daily_remaining,
            required_atomic,
        ) = min(candidates)
        return AuthorizationResolutionResult(
            ready=True,
            opc_installation_id=request.opc_installation_id,
            authorization_rail=request.authorization_rail,
            wallet_identity_id=wallet_identity_id,
            spending_grant_id=selected_grant.spending_grant_id,
            asset_allowance_id=selected_allowance.asset_allowance_id,
            remaining_amount_usdc=remaining,
            remaining_daily_amount_usdc=daily_remaining,
            remaining_hourly_amount_usdc=hourly_remaining,
            notification_mode=selected_grant.notification_mode,
            user_interaction_required=(
                selected_grant.notification_mode != "silent_under_limits"
            ),
            interaction_reason_code=(
                "NOTIFICATION_POLICY_REQUIRES_CONFIRMATION"
                if selected_grant.notification_mode != "silent_under_limits"
                else None
            ),
            required_amount_atomic=required_atomic,
            observed_allowance_atomic=selected_allowance.observed_allowance_atomic,
            next_action="create_action_and_evaluate_policy",
        )

    @staticmethod
    def _resolution_failure(
        reason_code: str,
        *,
        opc_installation_id: str | None = None,
    ) -> AuthorizationResolutionResult:
        return AuthorizationResolutionResult(
            ready=False,
            opc_installation_id=opc_installation_id,
            reason_code=reason_code,
            next_action="configure_wallet_authorization",
        )

    def _resolution_token_addresses(
        self,
        request: AuthorizationResolutionRequest,
        identities: dict[str, WalletIdentity],
    ) -> set[str]:
        if request.token_address is not None:
            return {request.token_address}
        try:
            return {canonicalize_evm_address(request.asset or "")}
        except ValueError:
            return {
                allowance.token_address
                for wallet_identity_id in identities
                for allowance in self.repository.asset_allowances(wallet_identity_id)
                if allowance.network == request.network
                and allowance.spender_address == request.spender_address
                and self._allowance_matches_asset(allowance, request)
            }

    @staticmethod
    def _allowance_matches_asset(
        allowance: AssetAllowance, request: AuthorizationResolutionRequest
    ) -> bool:
        if request.token_address is not None and allowance.token_address != request.token_address:
            return False
        if request.asset is None:
            return True
        try:
            return allowance.token_address == canonicalize_evm_address(request.asset)
        except ValueError:
            return allowance.token_symbol.lower() == request.asset

    def verify_asset_allowance(
        self,
        wallet_identity_id: str,
        network: str,
        token_address: str,
        spender_address: str,
        allowance_tx_hash: str,
        expected_amount_atomic: int | None = None,
    ) -> AssetAllowance:
        if expected_amount_atomic is not None and (
            type(expected_amount_atomic) is not int
            or not 1 <= expected_amount_atomic <= MAX_UINT256
        ):
            raise ValueError("prepared amount must be a positive uint256 integer")
        config = self._network_config(network)
        token_address = canonicalize_evm_address(token_address)
        self.asset_registry.require_pair(network, token_address)
        spender_address = canonicalize_evm_address(spender_address)
        allowance_tx_hash = canonicalize_transaction_hash(allowance_tx_hash)
        identity = self.repository.wallet_identity(wallet_identity_id)
        if identity is None:
            raise ValueError("wallet identity was not found")
        if identity.status != "active":
            raise ValueError("wallet identity is not active")
        self._verify_rpc_chain(network, config)

        receipt = self._rpc(network, "eth_getTransactionReceipt", [allowance_tx_hash])
        if receipt is None:
            raise AllowanceVerificationPending("allowance receipt was not found")
        if self._hex_int(receipt.get("status"), "receipt status") != 1:
            raise ValueError("allowance receipt was not successful")
        if canonicalize_transaction_hash(receipt.get("transactionHash")) != allowance_tx_hash:
            raise ValueError("receipt transaction hash does not match")

        transaction = self._rpc(network, "eth_getTransactionByHash", [allowance_tx_hash])
        if transaction is None:
            raise AllowanceVerificationPending("allowance transaction was not found")
        if canonicalize_transaction_hash(transaction.get("hash")) != allowance_tx_hash:
            raise ValueError("transaction hash does not match proof")
        if canonicalize_evm_address(transaction.get("from")) != identity.wallet_address:
            raise ValueError("transaction sender does not match wallet identity")
        if canonicalize_evm_address(transaction.get("to")) != token_address:
            raise ValueError("transaction token does not match requested token")

        decoded_spender, approved_amount = self._decode_approve_calldata(
            transaction.get("input")
        )
        if decoded_spender != spender_address:
            raise ValueError("approve spender does not match requested spender")
        if approved_amount == 0:
            raise ValueError("approved amount must be positive")

        confirmed_block = self._hex_int(receipt.get("blockNumber"), "receipt block")
        transaction_block = self._hex_int(
            transaction.get("blockNumber"), "transaction block"
        )
        if transaction_block != confirmed_block:
            raise ValueError("transaction block does not match receipt")
        current_block = self._hex_int(
            self._rpc(network, "eth_blockNumber", []), "current block"
        )
        confirmations = current_block - confirmed_block + 1
        if confirmations < config["required_confirmations"]:
            raise AllowanceVerificationPending("allowance transaction has insufficient confirmations")

        observed = self._observe_allowance(
            network, token_address, identity.wallet_address, spender_address
        )
        now = self._now()
        block_hash = None
        if expected_amount_atomic is not None and approved_amount != expected_amount_atomic:
            try:
                receipt_block_hash = canonicalize_transaction_hash(
                    receipt.get("blockHash")
                )
                transaction_block_hash = canonicalize_transaction_hash(
                    transaction.get("blockHash")
                )
            except ValueError as exc:
                raise ValueError(
                    "allowance receipt and transaction block hashes are required"
                ) from exc
            if receipt_block_hash != transaction_block_hash:
                raise ValueError(
                    "transaction block hash does not match receipt"
                )
            block_hash = receipt_block_hash

        allowance = AssetAllowance(
            asset_allowance_id=f"asset_allowance_{uuid4().hex}",
            wallet_identity_id=wallet_identity_id,
            network=network,
            token_address=token_address,
            token_symbol=config["token_symbol"],
            token_decimals=config["token_decimals"],
            spender_address=spender_address,
            approved_amount_atomic=approved_amount,
            observed_allowance_atomic=observed,
            allowance_tx_hash=allowance_tx_hash,
            status=self._allowance_status(approved_amount, observed),
            confirmed_block=confirmed_block,
            last_chain_check_at=now,
            created_at=now,
            updated_at=now,
        )
        if expected_amount_atomic is not None and approved_amount != expected_amount_atomic:
            raise AllowanceAmountMismatch(
                {
                    "user_id": identity.user_id,
                    "wallet_identity_id": wallet_identity_id,
                    "network": network,
                    "token_address": token_address,
                    "spender_address": spender_address,
                    "allowance_tx_hash": allowance_tx_hash,
                    "expected_amount_atomic": str(expected_amount_atomic),
                    "actual_approved_amount_atomic": str(approved_amount),
                    "observed_allowance_atomic": str(observed),
                    "confirmed_block": confirmed_block,
                    "confirmed_block_hash": block_hash,
                    "verified_at": now,
                }
            )
        return self.repository.save_verified_asset_allowance(allowance)

    def inspect_asset_allowance(
        self, wallet_identity_id: str, network: str,
        token_address: str, spender_address: str,
    ) -> AssetAllowance:
        """Observe an allowance, including approvals made outside this console.

        This is a chain read, not a synthetic approval transaction. Existing
        transaction proof is retained; a newly discovered scope has no tx hash.
        The caller must restrict the target to its server-owned approval config.
        """
        config = self._network_config(network)
        token_address = canonicalize_evm_address(token_address)
        self.asset_registry.require_pair(network, token_address)
        spender_address = canonicalize_evm_address(spender_address)
        identity = self.repository.wallet_identity(wallet_identity_id)
        if identity is None or identity.status != "active":
            raise ValueError("active wallet identity is required")
        existing = next((item for item in self.repository.asset_allowances(wallet_identity_id)
            if item.network == network and item.token_address == token_address
            and item.spender_address == spender_address), None)
        if existing is not None:
            return self.refresh_asset_allowance(existing.asset_allowance_id)
        self._verify_rpc_chain(network, config)
        observed = self._observe_allowance(
            network, token_address, identity.wallet_address, spender_address
        )
        at = self._now()
        return self.repository.save_verified_asset_allowance(AssetAllowance(
            asset_allowance_id=f"asset_allowance_{uuid4().hex}",
            wallet_identity_id=wallet_identity_id, network=network,
            token_address=token_address, spender_address=spender_address,
            token_symbol=config["token_symbol"], token_decimals=config["token_decimals"],
            approved_amount_atomic=observed, observed_allowance_atomic=observed,
            status=self._allowance_status(observed, observed),
            last_chain_check_at=at, created_at=at, updated_at=at,
        ))

    def refresh_asset_allowance(self, asset_allowance_id: str) -> AssetAllowance:
        allowance = self.repository.asset_allowance(asset_allowance_id)
        if allowance is None:
            raise ValueError("asset allowance was not found")
        config = self._network_config(allowance.network)
        identity = self.repository.wallet_identity(allowance.wallet_identity_id)
        if identity is None:
            raise ValueError("wallet identity was not found")
        try:
            self._verify_rpc_chain(allowance.network, config)
            observed = self._observe_allowance(
                allowance.network,
                allowance.token_address,
                identity.wallet_address,
                allowance.spender_address,
            )
        except Exception:
            return self.repository.mark_asset_allowance_stale(
                asset_allowance_id, self._now()
            )
        return self.repository.refresh_asset_allowance(
            asset_allowance_id,
            observed_allowance_atomic=observed,
            status=self._allowance_status(allowance.approved_amount_atomic, observed),
            now=self._now(),
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def _canonical_message(self, account_session: AccountSession) -> str:
        if account_session.domain != self.domain:
            raise ValueError("wallet challenge domain mismatch")
        return "\n".join(
            (
                "Clink Wallet Identity",
                f"Domain: {account_session.domain}",
                f"User ID: {account_session.user_id}",
                f"Wallet Address: {account_session.wallet_address}",
                f"Session ID: {account_session.account_session_id}",
                f"Nonce: {account_session.nonce}",
                f"Issued At: {self._timestamp(account_session.created_at)}",
                f"Expiration Time: {self._timestamp(account_session.expires_at)}",
                f"Purpose: {WALLET_IDENTITY_PURPOSE}",
            )
        )

    def _canonical_grant_message(self, account_session: AccountSession) -> str:
        if account_session.domain != self.domain:
            raise ValueError("spending grant challenge domain mismatch")
        if account_session.purpose != SPENDING_GRANT_PURPOSE or not account_session.payload:
            raise ValueError("account session purpose mismatch")
        terms = account_session.payload["terms"]
        lines = [
            "Clink Spending Grant",
            f"Domain: {account_session.domain}",
            f"User ID: {terms['user_id']}",
            f"Wallet Identity ID: {terms['wallet_identity_id']}",
            f"Wallet Address: {account_session.wallet_address}",
            f"Agent ID: {terms['agent_id']}",
            f"Maximum Amount USDC: {terms['max_amount_usdc']}",
            f"Per Transaction Limit USDC: {terms['per_transaction_limit_usdc']}",
            f"Rolling Hour Limit USDC: {terms['hourly_limit_usdc']}",
            f"Daily Limit USDC: {terms['daily_limit_usdc']}",
            f"Products: {self._compact_json(terms['product_scopes'])}",
            f"Venues: {self._compact_json(terms['venue_scopes'])}",
            f"Merchants: {self._compact_json(terms['merchant_scopes'])}",
            f"Merchant Trust: {self._compact_json(terms['merchant_trust_scopes'])}",
            f"Notification Mode: {terms['notification_mode']}",
            f"Networks: {self._compact_json(terms['network_scopes'])}",
            f"Assets: {self._compact_json(terms['asset_scopes'])}",
            f"Starts At: {terms['starts_at']}",
            f"Expires At: {terms['expires_at']}",
        ]
        if terms.get("amends_spending_grant_id"):
            lines.append(
                f"Amends Spending Grant ID: {terms['amends_spending_grant_id']}"
            )
        base_authority_hash = (account_session.payload or {}).get(
            "base_authority_hash"
        )
        if base_authority_hash is not None:
            lines.append(f"Base Authority Hash: {base_authority_hash}")
        base_authority_revision = (account_session.payload or {}).get(
            "base_authority_revision"
        )
        if base_authority_revision is not None:
            lines.append(f"Base Authority Revision: {base_authority_revision}")
        opc_installation = terms.get("opc_installation")
        if opc_installation is not None:
            lines.extend(
                [
                    f"OPC Pairing ID: {opc_installation['pairing_id']}",
                    f"OPC Installation ID: {opc_installation['installation_id']}",
                    "OPC Public Key: "
                    f"{self._compact_json(opc_installation['public_jwk'])}",
                    "OPC Public Key Thumbprint: "
                    f"{opc_installation['public_jwk_thumbprint']}",
                    f"OPC Label: {opc_installation['label']}",
                    f"OPC Scope: {opc_installation['scope']}",
                    "OPC Consent Expires At: "
                    f"{opc_installation['consent_expires_at']}",
                ]
            )
        lines.extend(
            [
                f"Session ID: {account_session.account_session_id}",
                f"Nonce: {account_session.nonce}",
                f"Issued At: {self._timestamp(account_session.created_at)}",
                f"Expiration Time: {self._timestamp(account_session.expires_at)}",
                f"Purpose: {SPENDING_GRANT_PURPOSE}",
            ]
        )
        return "\n".join(lines)

    def _validate_grant_request(self, request: SpendingGrantRequest) -> None:
        unsupported_products = set(request.product_scopes) - self.allowed_products
        if unsupported_products:
            raise ValueError(
                f"unsupported product scope: {sorted(unsupported_products)[0]}"
            )
        transfer_product = "transfers" in request.product_scopes
        transfer_venue = "clink_transfers" in request.venue_scopes
        if transfer_product != transfer_venue:
            raise ValueError(
                "transfers product scope requires the clink_transfers venue"
            )
        unsupported_networks = set(request.network_scopes) - self.network_configs.keys()
        if unsupported_networks:
            raise ValueError(
                f"unsupported network scope: {sorted(unsupported_networks)[0]}"
            )
        if request.expires_at <= self._now():
            raise ValueError("grant expiry must be in the future")

    def _validated_amendment_target(
        self, request: SpendingGrantRequest
    ) -> SpendingGrant | None:
        grant_id = request.amends_spending_grant_id
        if grant_id is None:
            return None
        grant = self.repository.spending_grant(grant_id)
        if grant is None:
            raise ValueError("spending grant amendment target was not found")
        if (
            grant.user_id != request.user_id
            or grant.wallet_identity_id != request.wallet_identity_id
            or grant.agent_id != request.agent_id
        ):
            raise ValueError("spending grant amendment identity mismatch")
        if grant.status != "active":
            raise ValueError("only an active spending grant can be amended")
        immutable_fields = (
            "merchant_scopes",
            "merchant_trust_scopes",
            "notification_mode",
            "network_scopes",
            "asset_scopes",
            "starts_at",
            "expires_at",
        )
        if any(
            getattr(grant, field) != getattr(request, field)
            for field in immutable_fields
        ):
            raise ValueError("signed amendment cannot change grant scope outside reviewed fields")
        if not reviewed_scope_amendment_is_valid(
            grant.product_scopes,
            grant.venue_scopes,
            request.product_scopes,
            request.venue_scopes,
        ):
            raise ValueError("signed amendment cannot change grant scope outside reviewed fields")
        return grant

    def _observe_allowance(
        self, network: str, token: str, owner: str, spender: str
    ) -> int:
        calldata = (
            "0x"
            + ALLOWANCE_SELECTOR
            + ("0" * 24)
            + owner[2:]
            + ("0" * 24)
            + spender[2:]
        )
        result = self._rpc(
            network,
            "eth_call",
            [{"to": token, "data": calldata}, "latest"],
        )
        observed = self._hex_int(result, "allowance result")
        if observed >= 2**256:
            raise ValueError("allowance result exceeds uint256")
        return observed

    def observe_wallet_balance(self, *, network: str, wallet_address: str) -> int:
        config = self._network_config(network)
        token_address = config["token_address"]
        if token_address is None:
            raise ValueError("network token address is not configured")
        owner = canonicalize_evm_address(wallet_address)
        calldata = (
            "0x" + BALANCE_OF_SELECTOR + ("0" * 24) + owner[2:].lower()
        )
        result = self._rpc(
            network,
            "eth_call",
            [{"to": token_address, "data": calldata}, "latest"],
        )
        observed = self._hex_int(result, "balance result")
        if observed >= 2**256:
            raise ValueError("balance result exceeds uint256")
        return observed

    def _rpc(self, network: str, method: str, params: list[Any]) -> Any:
        self._network_config(network)
        if self.rpc_transport is None:
            raise ValueError("asset allowance RPC transport is not configured")
        result = self.rpc_transport(network, method, params)
        if isinstance(result, dict) and set(result) == {"result"}:
            return result["result"]
        return result

    def _network_config(self, network: str) -> dict[str, Any]:
        if network not in self.network_configs:
            raise ValueError(f"unsupported asset allowance network: {network}")
        return self.network_configs[network]

    @staticmethod
    def _validate_network_configs(
        configs: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        validated = {}
        for network, config in configs.items():
            chain_id = config.get("chain_id")
            confirmations = config.get("required_confirmations")
            decimals = config.get("token_decimals", 6)
            symbol = config.get("token_symbol", "USDC")
            token_address = config.get("token_address")
            if not network or not isinstance(chain_id, int) or chain_id <= 0:
                raise ValueError("network chain_id must be positive")
            if not isinstance(confirmations, int) or confirmations <= 0:
                raise ValueError("network required_confirmations must be positive")
            if not isinstance(decimals, int) or not 0 <= decimals <= 255:
                raise ValueError("network token_decimals must be between 0 and 255")
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("network token_symbol is required")
            if token_address is not None:
                token_address = canonicalize_evm_address(token_address)
            validated[network] = {
                "chain_id": chain_id,
                "required_confirmations": confirmations,
                "token_symbol": symbol,
                "token_decimals": decimals,
                "token_address": token_address,
            }
        return validated

    def _verify_rpc_chain(self, network: str, config: dict[str, Any]) -> None:
        observed_chain_id = self._hex_int(
            self._rpc(network, "eth_chainId", []), "RPC chain id"
        )
        if observed_chain_id != config["chain_id"]:
            raise ValueError("RPC chain id does not match requested network")

    @staticmethod
    def _decode_approve_calldata(calldata: str) -> tuple[str, int]:
        if not isinstance(calldata, str) or not calldata.startswith("0x"):
            raise ValueError("approve calldata must be hex encoded")
        encoded = calldata[2:]
        if len(encoded) != 8 + 64 + 64:
            raise ValueError("approve calldata length is invalid")
        try:
            bytes.fromhex(encoded)
        except ValueError as exc:
            raise ValueError("approve calldata must contain only hex characters") from exc
        if encoded[:8].lower() != APPROVE_SELECTOR:
            raise ValueError("transaction does not use approve selector")
        spender_word = encoded[8:72]
        if int(spender_word[:24], 16) != 0:
            raise ValueError("approve spender encoding is invalid")
        spender = canonicalize_evm_address("0x" + spender_word[24:])
        amount = int(encoded[72:], 16)
        return spender, amount

    @staticmethod
    def _hex_int(value: Any, field_name: str) -> int:
        if not isinstance(value, str) or not value.startswith("0x"):
            raise ValueError(f"{field_name} must be a hexadecimal quantity")
        try:
            result = int(value, 16)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a hexadecimal quantity") from exc
        if result < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return result

    @staticmethod
    def _allowance_status(_approved: int, observed: int) -> str:
        if observed == 0:
            return "revoked"
        return "active"

    @staticmethod
    def _compact_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def _payload_hash(cls, payload: dict[str, Any]) -> str:
        encoded = cls._compact_json(payload).encode("utf-8")
        return "0x" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z").replace(
            ".000000Z", "Z"
        )

    @staticmethod
    def _signature_bytes(signature: str) -> bytes:
        if not isinstance(signature, str):
            raise ValueError("invalid wallet signature")
        try:
            return bytes.fromhex(signature.removeprefix("0x"))
        except ValueError as exc:
            raise ValueError("invalid wallet signature") from exc
