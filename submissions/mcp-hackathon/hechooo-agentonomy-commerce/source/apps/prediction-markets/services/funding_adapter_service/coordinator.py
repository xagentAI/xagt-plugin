from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from services.funding_adapter_service.core_gateway import (
    PredictionCoreGatewayError,
    PredictionFundingContext,
)
from services.funding_adapter_service.repository import (
    BridgeRepository,
    BridgeRepositoryError,
    CORE_PREBROADCAST_RELEASE_REASON,
)
from services.funding_adapter_service.schemas import (
    ConfirmPolymarketFundingOperationRequest,
    CreatePolymarketBridgeDepositRequest,
    CreatePolymarketFundingOperationRequest,
    POLYMARKET_BRIDGE_FAILURE_REASON,
    PolymarketFundingOperation,
    PolymarketFundingOperationView,
    PolymarketFundingRiskAssessment,
    RISK_ASSESSMENT_CLOCK_SKEW,
    RISK_ASSESSMENT_MAX_AGE,
    UINT256_MAX_ATOMIC,
    funding_operation_next_action,
)
from services.funding_adapter_service.service import (
    BridgeAdapterError,
    BridgeTransportError,
    PolymarketFundingAdapterService,
)
from shared.config import AppConfig


_AGENT_ID = "hermes"
_NETWORK = "eip155:137"
_PRODUCT = "prediction_markets"
_VENUE = "polymarket"
_MERCHANT_TRUST = "clink_verified"
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$")
_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_UINT256 = re.compile(r"^(?:0|[1-9][0-9]{0,77})$")

class FundingCoordinatorError(RuntimeError):
    """Fixed, redacted funding orchestration failure."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VenueAccount:
    user_id: str
    binding_id: str
    venue_wallet_address: str

    def __post_init__(self) -> None:
        _canonical_id(self.user_id, field_name="user_id")
        _canonical_id(self.binding_id, field_name="binding_id")
        object.__setattr__(
            self,
            "venue_wallet_address",
            _canonical_address(
                self.venue_wallet_address, field_name="venue_wallet_address"
            ),
        )


class VenueAccountGateway(Protocol):
    def resolve_active_account(self, *, user_id: str) -> VenueAccount: ...

    def get_buying_power_atomic(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
    ) -> str: ...


class RiskAssessmentGateway(Protocol):
    """Provide non-authoritative context that Core independently evaluates."""

    available: bool

    def assess(
        self,
        *,
        operation_id: str,
        user_id: str,
        bridge_address: str,
        amount_atomic: str,
        resource: str,
    ) -> PolymarketFundingRiskAssessment: ...


class UnavailableRiskAssessmentGateway:
    """Fail-closed fallback when no Core-delegated context input is assembled."""

    available = False

    def assess(
        self,
        *,
        operation_id: str,
        user_id: str,
        bridge_address: str,
        amount_atomic: str,
        resource: str,
    ) -> PolymarketFundingRiskAssessment:
        del operation_id, user_id, bridge_address, amount_atomic, resource
        raise FundingCoordinatorError(
            "funding risk assessment is unavailable", status_code=503
        )


class UnavailableVenueAccountGateway:
    """Fail-closed until a user-scoped production venue reader is wired."""

    def resolve_active_account(self, *, user_id: str) -> VenueAccount:
        del user_id
        raise FundingCoordinatorError(
            "venue account service is unavailable", status_code=503
        )

    def get_buying_power_atomic(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
    ) -> str:
        del user_id, binding_id, venue_wallet_address
        raise FundingCoordinatorError(
            "venue account service is unavailable", status_code=503
        )


class PredictionCoreFundingGateway(Protocol):
    def funding_readiness(self) -> dict[str, Any]: ...

    def account_readiness(self, user_id: str) -> dict[str, Any]: ...

    def resolve_authorization(self, **kwargs: Any) -> dict[str, Any]: ...

    def create_action(self, context: PredictionFundingContext) -> dict[str, Any]: ...

    def evaluate_policy(
        self, context: PredictionFundingContext, **kwargs: Any
    ) -> dict[str, Any]: ...

    def update_action_policy_approved(
        self, context: PredictionFundingContext, **kwargs: Any
    ) -> dict[str, Any]: ...

    def audit_policy_evaluated(
        self, context: PredictionFundingContext, **kwargs: Any
    ) -> dict[str, Any]: ...

    def reserve(
        self, context: PredictionFundingContext, **kwargs: Any
    ) -> dict[str, Any]: ...

    def settle(
        self, reservation_id: str, *, payment_authorization: dict[str, Any]
    ) -> dict[str, Any]: ...

    def reservation(self, reservation_id: str) -> dict[str, Any]: ...

    def reconcile(self, reservation_id: str) -> dict[str, Any]: ...

    def finalize(self, reservation_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def release(self, reservation_id: str, **kwargs: Any) -> dict[str, Any]: ...


class PolymarketFundingCoordinator:
    """Durable Core-controlled Polymarket funding operation coordinator."""

    def __init__(
        self,
        *,
        config: AppConfig,
        funding_adapter: PolymarketFundingAdapterService,
        core_gateway: PredictionCoreFundingGateway,
        venue_accounts: VenueAccountGateway,
        risk_assessments: RiskAssessmentGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.funding_adapter = funding_adapter
        self.repository: BridgeRepository = funding_adapter.repository
        self.core_gateway = core_gateway
        self.venue_accounts = venue_accounts
        self.risk_assessments = (
            risk_assessments or UnavailableRiskAssessmentGateway()
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.source_token = _canonical_address(
            config.polymarket_bridge_source_token_address,
            field_name="source_token_address",
        )
        self.destination_token = _canonical_address(
            config.polymarket_pusd_token_address,
            field_name="destination_token_address",
        )

    def prepare(
        self, request: CreatePolymarketFundingOperationRequest
    ) -> PolymarketFundingOperation:
        account = self._venue_account(request.user_id)
        operation_id = _stable_id(
            "pm_funding", request.user_id, request.idempotency_key
        )
        replay = self._idempotency_replay(request, account)
        if replay is not None:
            return replay

        deposit = self._deposit_target(account)
        amount_atomic = _amount_atomic(request.amount_usdc)
        assessment, risk_observed_at = self._risk_assessment(
            operation_id=operation_id,
            user_id=request.user_id,
            bridge_address=deposit.bridge_address,
            amount_atomic=amount_atomic,
            resource=request.resource,
        )

        funding = self._funding_readiness()
        account_readiness = self._account_readiness(request.user_id)
        mandate = self._validated_mandate(account_readiness)
        spender = self._validated_funding_readiness(funding)

        authorization = self._authorization(
            user_id=request.user_id,
            opc_installation_id=request.opc_installation_id,
            amount_usdc=request.amount_usdc,
            amount_atomic=amount_atomic,
            spender_address=spender,
            destination=deposit.bridge_address,
            resource=request.resource,
        )
        (
            wallet_identity_id,
            spending_grant_id,
            asset_allowance_id,
        ) = self._validated_authorization(
            authorization,
            amount_atomic=amount_atomic,
            account_readiness=account_readiness,
            mandate=mandate,
            opc_installation_id=request.opc_installation_id,
        )

        buying_power_before = self._buying_power(account)
        immutable = {
            "operation_id": operation_id,
            "user_id": request.user_id,
            "agent_id": _AGENT_ID,
            "idempotency_key": request.idempotency_key,
            "binding_id": account.binding_id,
            "venue_wallet_address": account.venue_wallet_address,
            "bridge_address": deposit.bridge_address,
            "source_network": deposit.source_network,
            "source_token_address": deposit.source_token_address,
            "destination_network": deposit.destination_network,
            "destination_token_address": deposit.destination_token_address,
            "amount_usdc": request.amount_usdc,
            "amount_atomic": amount_atomic,
            "resource": request.resource,
            "wallet_identity_id": wallet_identity_id,
            "spending_grant_id": spending_grant_id,
            "asset_allowance_id": asset_allowance_id,
            "spender_address": spender,
            "venue_buying_power_before_atomic": buying_power_before,
            "risk_assessment_id": assessment.assessment_id,
            "risk_level": assessment.risk_level,
            "risk_score": assessment.risk_score,
            "risk_action": assessment.risk_action,
            "risk_assessed_at": assessment.assessed_at,
        }
        if request.opc_installation_id is not None:
            immutable["opc_installation_id"] = request.opc_installation_id
        request_hash = _canonical_hash("request", immutable)
        quote_fields = (
            "operation_id",
            "binding_id",
            "bridge_address",
            "source_network",
            "source_token_address",
            "destination_network",
            "destination_token_address",
            "amount_usdc",
            "amount_atomic",
            "resource",
            "wallet_identity_id",
            "spending_grant_id",
            "asset_allowance_id",
            "spender_address",
        )
        if request.opc_installation_id is not None:
            quote_fields = ("operation_id", "opc_installation_id", *quote_fields[1:])
        quote_hash = _canonical_hash(
            "quote",
            {key: immutable[key] for key in quote_fields},
        )
        now = risk_observed_at
        operation = PolymarketFundingOperation(
            **immutable,
            request_hash=request_hash,
            quote_hash=quote_hash,
            status="created",
            created_at=now,
            updated_at=now,
            revision=0,
        )
        failed = False
        conflict = False
        try:
            stored, _created = self.repository.create_funding_operation(operation)
            return stored
        except BridgeRepositoryError as exc:
            conflict = str(exc) == "funding operation context conflict"
            failed = True
        if conflict:
            raise FundingCoordinatorError("funding operation conflict")
        if failed:
            raise FundingCoordinatorError("funding operation persistence failed")
        raise AssertionError("unreachable")

    def _idempotency_replay(
        self,
        request: CreatePolymarketFundingOperationRequest,
        account: VenueAccount,
    ) -> PolymarketFundingOperation | None:
        failed = False
        try:
            replay = self.repository.get_funding_operation_by_idempotency(
                user_id=request.user_id,
                binding_id=account.binding_id,
                idempotency_key=request.idempotency_key,
            )
        except BridgeRepositoryError:
            failed = True
            replay = None
        if failed:
            raise FundingCoordinatorError("funding operation lookup failed")
        if replay is None:
            return None
        if (
            replay.operation_id
            != _stable_id("pm_funding", request.user_id, request.idempotency_key)
            or replay.venue_wallet_address != account.venue_wallet_address
            or replay.amount_usdc != request.amount_usdc
            or replay.resource != request.resource
            or replay.opc_installation_id != request.opc_installation_id
        ):
            raise FundingCoordinatorError("funding operation conflict")
        return replay

    def get(
        self, *, user_id: str, operation_id: str
    ) -> PolymarketFundingOperation:
        invalid_scope = False
        try:
            user_id = _canonical_id(user_id, field_name="user_id")
            operation_id = _canonical_id(operation_id, field_name="operation_id")
        except (TypeError, ValueError):
            invalid_scope = True
        if invalid_scope:
            raise FundingCoordinatorError(
                "funding operation is unavailable", status_code=404
            )
        account = self._venue_account(user_id)
        failed = False
        try:
            operation = self.repository.get_funding_operation(
                user_id=user_id,
                binding_id=account.binding_id,
                operation_id=operation_id,
            )
        except BridgeRepositoryError:
            failed = True
            operation = None
        if failed:
            raise FundingCoordinatorError("funding operation lookup failed")
        if operation is None:
            raise FundingCoordinatorError("funding operation is unavailable", status_code=404)
        return operation

    def get_history(
        self, *, user_id: str, operation_id: str
    ) -> PolymarketFundingOperation:
        """Read an operation by its original owner, independent of live binding.

        History recovery is deliberately read-only.  Unlike ``get`` (which is
        used by continue/confirm and therefore requires the current active
        venue binding), this path must remain available after a wallet binding
        changes or is removed.
        """
        try:
            user_id = _canonical_id(user_id, field_name="user_id")
            operation_id = _canonical_id(operation_id, field_name="operation_id")
        except (TypeError, ValueError):
            raise FundingCoordinatorError(
                "funding operation is unavailable", status_code=404
            ) from None

        try:
            operation = self.repository.get_funding_operation_for_recovery(
                user_id=user_id,
                operation_id=operation_id,
            )
        except BridgeRepositoryError:
            raise FundingCoordinatorError(
                "funding operation history lookup failed", status_code=503
            ) from None
        if operation is None:
            raise FundingCoordinatorError(
                "funding operation is unavailable", status_code=404
            )
        return operation

    def confirm(
        self,
        operation_id: str,
        request: ConfirmPolymarketFundingOperationRequest,
    ) -> PolymarketFundingOperation:
        self._require_live_confirmation()
        operation = self.get(
            user_id=request.user_id,
            operation_id=operation_id,
        )
        self._require_installation_match(
            operation,
            request.opc_installation_id,
        )
        if operation.status == "created":
            operation, _won = self._cas(
                operation,
                status="confirmed",
                confirmed_at=self._utc_now(),
            )
        return self._advance_loaded(operation)

    def advance(
        self,
        *,
        user_id: str,
        operation_id: str,
        opc_installation_id: str | None = None,
    ) -> PolymarketFundingOperation:
        self._require_live_confirmation()
        operation = self.get(user_id=user_id, operation_id=operation_id)
        self._require_installation_match(
            operation,
            opc_installation_id,
        )
        return self._advance_loaded(operation)

    @staticmethod
    def _require_installation_match(
        operation: PolymarketFundingOperation,
        opc_installation_id: str | None,
    ) -> None:
        if operation.opc_installation_id != opc_installation_id:
            raise FundingCoordinatorError("funding operation conflict")

    def recover_ambiguous(
        self, *, user_id: str, operation_id: str
    ) -> PolymarketFundingOperation:
        invalid_scope = False
        try:
            user_id = _canonical_id(user_id, field_name="user_id")
            operation_id = _canonical_id(operation_id, field_name="operation_id")
        except (TypeError, ValueError):
            invalid_scope = True
        if invalid_scope:
            raise FundingCoordinatorError(
                "funding operation is unavailable", status_code=404
            )
        lookup_failed = False
        try:
            operation = self.repository.get_funding_operation_for_recovery(
                user_id=user_id,
                operation_id=operation_id,
            )
        except BridgeRepositoryError:
            lookup_failed = True
            operation = None
        if lookup_failed:
            raise FundingCoordinatorError("funding operation recovery lookup failed")
        if operation is None:
            raise FundingCoordinatorError(
                "funding operation is unavailable", status_code=404
            )
        if operation.status not in {
            "action_creating",
            "policy_evaluating",
            "reservation_creating",
            "finalizing",
        }:
            raise FundingCoordinatorError(
                "funding operation is not an ambiguous external attempt"
            )
        operation, _ = self._cas(operation, status="manual_review")
        return operation

    def _require_live_confirmation(self) -> None:
        if not self.config.live_mode or not self.config.require_user_confirmation:
            raise FundingCoordinatorError(
                "live funding confirmation is unavailable", status_code=503
            )

    @property
    def risk_assessment_available(self) -> bool:
        return getattr(self.risk_assessments, "available", False) is True

    @staticmethod
    def view(
        operation: PolymarketFundingOperation,
    ) -> PolymarketFundingOperationView:
        return PolymarketFundingOperationView(
            operation_id=operation.operation_id,
            user_id=operation.user_id,
            opc_installation_id=operation.opc_installation_id,
            binding_id=operation.binding_id,
            venue_wallet_address=operation.venue_wallet_address,
            bridge_address=operation.bridge_address,
            status=operation.status,
            amount_usdc=operation.amount_usdc,
            resource=operation.resource,
            action_id=operation.action_id,
            policy_decision_id=operation.policy_decision_id,
            audit_event_id=operation.audit_event_id,
            reservation_id=operation.reservation_id,
            core_tx_hash=operation.core_tx_hash,
            core_state=operation.core_state,
            bridge_status=operation.bridge_status,
            venue_buying_power_before_atomic=(
                operation.venue_buying_power_before_atomic
            ),
            venue_buying_power_after_atomic=(
                operation.venue_buying_power_after_atomic
            ),
            failure_reason_code=operation.failure_reason_code,
            confirmed_at=operation.confirmed_at,
            finalized_at=operation.finalized_at,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            revision=operation.revision,
            next_action=funding_operation_next_action(operation.status),
        )

    def _advance_loaded(
        self, operation: PolymarketFundingOperation
    ) -> PolymarketFundingOperation:
        for _step in range(20):
            status = operation.status
            if status in {
                "created",
                "action_unknown",
                "policy_unknown",
                "manual_review",
                "finalized",
                "failed",
                "released",
            }:
                return operation

            if status == "confirmed":
                operation, won = self._cas(operation, status="action_creating")
                if not won:
                    continue
                result = self._core_mutation(
                    lambda: self.core_gateway.create_action(self._context(operation))
                )
                if result is None:
                    operation, _ = self._cas(operation, status="action_unknown")
                    return operation
                action_id = _result_id(result, "action_id")
                if action_id is None:
                    operation, _ = self._cas(operation, status="action_unknown")
                    return operation
                operation, _ = self._cas(
                    operation,
                    status="action_created",
                    action_id=action_id,
                )
                continue

            if status == "action_creating":
                return operation

            if status == "action_created":
                operation, won = self._cas(operation, status="policy_evaluating")
                if not won:
                    continue
                result = self._core_mutation(
                    lambda: self.core_gateway.evaluate_policy(
                        self._context(operation),
                        action_id=operation.action_id,
                        risk_level=operation.risk_level,
                        risk_score=operation.risk_score,
                        risk_action=operation.risk_action,
                        user_confirmed=True,
                        live_mode=True,
                    )
                )
                if result is None:
                    operation, _ = self._cas(operation, status="policy_unknown")
                    return operation
                policy_id = _result_id(result, "policy_decision_id")
                if policy_id is None or not isinstance(result.get("approved"), bool):
                    operation, _ = self._cas(operation, status="policy_unknown")
                    return operation
                if result["approved"] is not True:
                    reason = _reason_code(result.get("reason_code"), "POLICY_BLOCKED")
                    operation, _ = self._cas(
                        operation,
                        status="failed",
                        policy_decision_id=policy_id,
                        failure_reason_code=reason,
                    )
                    return operation
                operation, _ = self._cas(
                    operation,
                    status="policy_approved",
                    policy_decision_id=policy_id,
                )
                continue

            if status == "policy_evaluating":
                return operation

            if status == "policy_approved":
                operation, won = self._cas(
                    operation, status="reservation_creating"
                )
                if not won:
                    continue
                context = self._context(operation)
                updated = self._core_mutation(
                    lambda: self.core_gateway.update_action_policy_approved(
                        context,
                        action_id=operation.action_id,
                        policy_decision_id=operation.policy_decision_id,
                    )
                )
                if updated is None:
                    return operation
                audited = self._core_mutation(
                    lambda: self.core_gateway.audit_policy_evaluated(
                        context,
                        action_id=operation.action_id,
                        policy_decision_id=operation.policy_decision_id,
                    )
                )
                if audited is None:
                    return operation
                reserved = self._core_mutation(
                    lambda: self.core_gateway.reserve(
                        context,
                        action_id=operation.action_id,
                        policy_decision_id=operation.policy_decision_id,
                    )
                )
                audit_id = _result_id(audited, "event_id")
                reservation_id = (
                    _result_id(reserved, "reservation_id")
                    if reserved is not None
                    else None
                )
                if (
                    reservation_id is None
                    or audit_id is None
                    or reserved.get("state") != "spending_reserved"
                ):
                    return operation
                operation, _ = self._cas(
                    operation,
                    status="reserved",
                    audit_event_id=audit_id,
                    reservation_id=reservation_id,
                    core_state="spending_reserved",
                )
                continue

            if status == "reservation_creating":
                return operation

            if status == "reserved":
                operation, _ = self._cas(
                    operation, status="transaction_prepared"
                )
                continue

            if status == "transaction_prepared":
                operation, won = self._cas(
                    operation, status="settlement_submitting"
                )
                if not won:
                    continue
                payment_authorization = {
                    "kind": "prediction_market_bridge_transfer",
                    "operation_id": operation.operation_id,
                    "reservation_id": operation.reservation_id,
                    "binding_id": operation.binding_id,
                    "bridge_address": operation.bridge_address,
                    "source_token": operation.source_token_address,
                    "amount_atomic": operation.amount_atomic,
                }
                result = self._core_mutation(
                    lambda: self.core_gateway.settle(
                        operation.reservation_id,
                        payment_authorization=payment_authorization,
                    )
                )
                if result is None:
                    operation, _ = self._cas(
                        operation,
                        status="settlement_unknown",
                    )
                    return operation
                operation = self._consume_core_state(
                    operation, result, recovery_read=False
                )
                if operation.status in {
                    "settlement_unknown",
                    "submitted",
                    "released",
                    "failed",
                    "manual_review",
                }:
                    return operation
                continue

            if status in {
                "settlement_submitting",
                "settlement_unknown",
                "submitted",
            }:
                operation = self._recover_core(operation)
                if operation.status in {
                    "settlement_submitting",
                    "settlement_unknown",
                    "submitted",
                    "released",
                    "failed",
                    "manual_review",
                }:
                    return operation
                continue

            if status == "chain_confirmed":
                operation, _ = self._cas(operation, status="bridge_pending")
                continue

            if status == "bridge_pending":
                return self._poll_bridge(operation)

            if status == "venue_credited":
                operation, won = self._cas(operation, status="finalizing")
                if not won:
                    continue
                return self._finalize(operation)

            if status == "finalizing":
                return operation

            return operation
        raise FundingCoordinatorError("funding operation did not converge")

    def _recover_core(
        self, operation: PolymarketFundingOperation
    ) -> PolymarketFundingOperation:
        result = self._core_mutation(
            lambda: self.core_gateway.reservation(operation.reservation_id)
        )
        if result is None:
            return operation
        if self._core_tx_hash_drifted(operation, result):
            return self._mark_core_tx_hash_drift(operation)
        if _core_prebroadcast_state(result) in {"pending", "blocked"}:
            return self._consume_core_state(
                operation,
                result,
                recovery_read=True,
            )
        state = result.get("state")
        if state in {"spending_reserved", "payment_submitted"} and not _core_failure(
            result
        ):
            reconciled = self._core_mutation(
                lambda: self.core_gateway.reconcile(operation.reservation_id)
            )
            if reconciled is not None:
                result = reconciled
        if (
            operation.status == "settlement_unknown"
            and _operation_allows_prebroadcast_release(operation)
            and _core_retryable_without_transaction(result)
        ):
            released = self._core_mutation(
                lambda: self.core_gateway.release(
                    operation.reservation_id,
                    reason="prediction_market_prebroadcast_retry",
                )
            )
            if _core_released_without_transaction(released):
                operation, _ = self._cas(
                    operation,
                    status="released",
                    core_state="released",
                    failure_reason_code=CORE_PREBROADCAST_RELEASE_REASON,
                )
                return operation
        return self._consume_core_state(operation, result, recovery_read=True)

    def _consume_core_state(
        self,
        operation: PolymarketFundingOperation,
        result: dict[str, Any],
        *,
        recovery_read: bool,
    ) -> PolymarketFundingOperation:
        if self._core_tx_hash_drifted(operation, result):
            return self._mark_core_tx_hash_drift(operation)
        prebroadcast_state = _core_prebroadcast_state(result)
        if prebroadcast_state == "blocked":
            tx_hash = _canonical_tx_hash(result.get("tx_hash"))
            operation, _ = self._cas(
                operation,
                status="manual_review",
                core_tx_hash=tx_hash,
                core_state="payment_submitted",
                failure_reason_code="CORE_RISK_PREBROADCAST_BLOCKED",
            )
            return operation
        if prebroadcast_state == "pending":
            if operation.status == "settlement_submitting":
                tx_hash = _canonical_tx_hash(result.get("tx_hash"))
                operation, _ = self._cas(
                    operation,
                    status="settlement_unknown",
                    core_tx_hash=tx_hash,
                    core_state="payment_submitted",
                )
            return operation
        state = result.get("state")
        if _core_failure(result):
            return self._release_core_failure(
                operation, result, already_read=recovery_read
            )
        if state == "payment_submitted":
            tx_hash = _canonical_tx_hash(result.get("tx_hash"))
            if operation.status == "submitted":
                return operation
            operation, _ = self._cas(
                operation,
                status="submitted",
                core_tx_hash=tx_hash,
                core_state="payment_submitted",
            )
            return operation
        if state == "settled":
            tx_hash = _canonical_tx_hash(result.get("tx_hash"))
            if operation.status == "settlement_submitting":
                operation, _ = self._cas(
                    operation,
                    status="submitted",
                    core_tx_hash=tx_hash,
                    core_state="payment_submitted",
                )
                if operation.status not in {"submitted", "settlement_unknown"}:
                    return operation
            operation, _ = self._cas(
                operation,
                status="chain_confirmed",
                core_tx_hash=tx_hash,
                core_state="settled",
            )
            return operation
        if state == "spending_reserved" and operation.status in {
            "settlement_submitting",
            "settlement_unknown",
        }:
            if operation.status == "settlement_unknown":
                return operation
            operation, _ = self._cas(
                operation,
                status="settlement_unknown",
                core_state="spending_reserved",
            )
            return operation
        return operation

    @staticmethod
    def _core_tx_hash_drifted(
        operation: PolymarketFundingOperation,
        result: dict[str, Any],
    ) -> bool:
        if operation.core_tx_hash is None or result.get("tx_hash") is None:
            return False
        try:
            observed = _canonical_tx_hash(result.get("tx_hash"))
        except FundingCoordinatorError:
            return True
        return observed != operation.core_tx_hash

    def _mark_core_tx_hash_drift(
        self, operation: PolymarketFundingOperation
    ) -> PolymarketFundingOperation:
        if operation.status == "manual_review":
            return operation
        operation, _ = self._cas(
            operation,
            status="manual_review",
            failure_reason_code="CORE_TX_HASH_DRIFT",
        )
        return operation

    def _release_core_failure(
        self,
        operation: PolymarketFundingOperation,
        result: dict[str, Any],
        *,
        already_read: bool,
    ) -> PolymarketFundingOperation:
        if not already_read:
            fresh = self._core_mutation(
                lambda: self.core_gateway.reservation(operation.reservation_id)
            )
            if fresh is None or not _core_failure(fresh):
                return operation
            result = fresh
        proof = _core_failure(result)
        if proof is None:
            return operation
        if result.get("state") == "released":
            released = result
        else:
            released = self._core_mutation(
                lambda: self.core_gateway.release(
                    operation.reservation_id,
                    reason="prediction_market_funding_failed",
                )
            )
            if released is None or released.get("state") != "released":
                if operation.status == "settlement_submitting":
                    operation, _ = self._cas(
                        operation, status="settlement_unknown"
                    )
                return operation
            released_proof = _core_failure(released)
            if released_proof is None:
                return operation
            proof = released_proof
        operation, _ = self._cas(
            operation,
            status="released",
            core_tx_hash=proof["tx_hash"],
            core_state="released",
            core_replacement_forbidden=True,
            core_failure_evidence_kind=proof["kind"],
            failure_reason_code=proof["reason_code"],
        )
        return operation

    def _poll_bridge(
        self, operation: PolymarketFundingOperation
    ) -> PolymarketFundingOperation:
        failed = False
        try:
            observation = self.funding_adapter.get_bridge_status(
                user_id=operation.user_id,
                binding_id=operation.binding_id,
                venue_wallet_address=operation.venue_wallet_address,
                bridge_address=operation.bridge_address,
                expected_amount_atomic=operation.amount_atomic,
                not_before_time_ms=int(operation.confirmed_at.timestamp() * 1_000),
                expected_bridge_tx_hash=operation.core_tx_hash,
            )
        except (BridgeAdapterError, TypeError, ValueError, RuntimeError):
            failed = True
            observation = None
        if failed or observation is None:
            return operation
        if observation.status == "FAILED":
            operation, _ = self._cas(
                operation,
                status="failed",
                bridge_observation_id=observation.observation_id,
                bridge_status="FAILED",
                failure_reason_code=POLYMARKET_BRIDGE_FAILURE_REASON,
            )
            return operation
        if observation.status != "COMPLETED":
            operation, _ = self._cas(
                operation,
                status="bridge_pending",
                bridge_observation_id=observation.observation_id,
                bridge_status=observation.status,
                venue_buying_power_after_atomic=None,
            )
            return operation
        account = VenueAccount(
            user_id=operation.user_id,
            binding_id=operation.binding_id,
            venue_wallet_address=operation.venue_wallet_address,
        )
        buying_power_after = self._buying_power(account)
        required_buying_power = (
            int(operation.venue_buying_power_before_atomic)
            + int(operation.amount_atomic)
        )
        next_status = (
            "venue_credited"
            if required_buying_power <= int(UINT256_MAX_ATOMIC)
            and int(buying_power_after) >= required_buying_power
            else "bridge_pending"
        )
        operation, _ = self._cas(
            operation,
            status=next_status,
            bridge_observation_id=observation.observation_id,
            bridge_status="COMPLETED",
            venue_buying_power_after_atomic=buying_power_after,
        )
        return operation

    def _finalize(
        self, operation: PolymarketFundingOperation
    ) -> PolymarketFundingOperation:
        result = self._core_mutation(
            lambda: self.core_gateway.reservation(operation.reservation_id)
        )
        if result is None:
            return operation
        if self._core_tx_hash_drifted(operation, result):
            return self._mark_core_tx_hash_drift(operation)
        if not _same_core_transaction(result, operation.core_tx_hash):
            return operation
        if result.get("state") != "finalized":
            if result.get("state") != "settled":
                return operation
            result = self._core_mutation(
                lambda: self.core_gateway.finalize(
                    operation.reservation_id,
                    delivery_status="delivered",
                    output_hash=operation.request_hash,
                )
            )
        if result is None:
            return operation
        if self._core_tx_hash_drifted(operation, result):
            return self._mark_core_tx_hash_drift(operation)
        if result.get("state") != "finalized" or not _same_core_transaction(
            result, operation.core_tx_hash
        ):
            return operation
        operation, _ = self._cas(
            operation,
            status="finalized",
            core_state="finalized",
            finalized_at=self._utc_now(),
        )
        return operation

    def _context(
        self, operation: PolymarketFundingOperation
    ) -> PredictionFundingContext:
        return PredictionFundingContext(
            user_id=operation.user_id,
            agent_id=operation.agent_id,
            opc_installation_id=operation.opc_installation_id,
            operation_id=operation.operation_id,
            idempotency_key=operation.idempotency_key,
            resource=operation.resource,
            wallet_identity_id=operation.wallet_identity_id,
            spending_grant_id=operation.spending_grant_id,
            asset_allowance_id=operation.asset_allowance_id,
            amount_usdc=operation.amount_usdc,
            amount_atomic=operation.amount_atomic,
            token_address=operation.source_token_address,
            destination=operation.bridge_address,
            quote_hash=operation.quote_hash,
        )

    def _cas(
        self,
        current: PolymarketFundingOperation,
        *,
        status: str,
        **updates: Any,
    ) -> tuple[PolymarketFundingOperation, bool]:
        values = current.model_dump()
        values.update(updates)
        values.update(
            status=status,
            revision=current.revision + 1,
            updated_at=max(self._utc_now(), current.updated_at),
        )
        invalid = False
        try:
            replacement = PolymarketFundingOperation.model_validate(values)
        except (TypeError, ValueError):
            invalid = True
            replacement = None
        if invalid or replacement is None:
            raise FundingCoordinatorError("funding operation transition failed")
        failed = False
        try:
            stored = self.repository.compare_and_set_funding_operation(
                expected_revision=current.revision,
                expected_status=current.status,
                replacement=replacement,
            )
        except BridgeRepositoryError:
            failed = True
            stored = None
        if failed:
            raise FundingCoordinatorError("funding operation transition failed")
        if stored is not None:
            return stored, True
        return (
            self.get(
                user_id=current.user_id,
                operation_id=current.operation_id,
            ),
            False,
        )

    @staticmethod
    def _core_mutation(operation: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
        failed = False
        try:
            result = operation()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (PredictionCoreGatewayError, TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            return None
        raise AssertionError("unreachable")

    def _venue_account(self, user_id: str) -> VenueAccount:
        failed = False
        try:
            account = self.venue_accounts.resolve_active_account(user_id=user_id)
            if not isinstance(account, VenueAccount) or account.user_id != user_id:
                raise ValueError
            return account
        except FundingCoordinatorError:
            raise
        except (TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            raise FundingCoordinatorError("venue account is unavailable")
        raise AssertionError("unreachable")

    def _buying_power(self, account: VenueAccount) -> str:
        failed = False
        try:
            value = self.venue_accounts.get_buying_power_atomic(
                user_id=account.user_id,
                binding_id=account.binding_id,
                venue_wallet_address=account.venue_wallet_address,
            )
            return _canonical_uint256(value, field_name="venue_buying_power")
        except FundingCoordinatorError:
            raise
        except (TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            raise FundingCoordinatorError("venue buying power is unavailable")
        raise AssertionError("unreachable")

    def _funding_readiness(self) -> dict[str, Any]:
        failed = False
        try:
            value = self.core_gateway.funding_readiness()
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (PredictionCoreGatewayError, TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            raise FundingCoordinatorError("Core funding is not ready")
        raise AssertionError("unreachable")

    def _account_readiness(self, user_id: str) -> dict[str, Any]:
        failed = False
        try:
            value = self.core_gateway.account_readiness(user_id)
            if not isinstance(value, dict) or value.get("user_id") != user_id:
                raise ValueError
            return value
        except (PredictionCoreGatewayError, TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            raise FundingCoordinatorError("Core account is not ready")
        raise AssertionError("unreachable")

    def _validated_mandate(self, readiness: dict[str, Any]) -> dict[str, Any]:
        failed = False
        try:
            mandate = readiness.get("active_spending_mandate")
            valid = (
                readiness.get("wallet_bound") is True
                and readiness.get("spending_grant_active") is True
                and isinstance(mandate, dict)
                and mandate.get("agent_id") == _AGENT_ID
                and _PRODUCT in mandate.get("product_scopes", [])
                and _VENUE in mandate.get("venue_scopes", [])
                and _MERCHANT_TRUST in mandate.get("merchant_trust_scopes", [])
                and _NETWORK in mandate.get("network_scopes", [])
                and self.source_token
                in {
                    str(asset).lower()
                    for asset in mandate.get("asset_scopes", [])
                    if isinstance(asset, str)
                }
                and readiness.get("chain_allowances", {}).get(_NETWORK) is True
            )
        except (AttributeError, TypeError, ValueError):
            failed = True
            valid = False
            mandate = None
        if not valid:
            raise FundingCoordinatorError("Core account is not ready")
        if failed or not isinstance(mandate, dict):
            raise FundingCoordinatorError("Core account is not ready")
        return mandate

    def _validated_funding_readiness(
        self, funding: dict[str, Any]
    ) -> str:
        failed = False
        try:
            rail = funding.get("settlement_rail")
            if rail == "clink_hosted_executor":
                spender_addresses = funding.get("spender_addresses")
                if not isinstance(spender_addresses, dict):
                    raise ValueError("spender_addresses is invalid")
                spender = _canonical_address(
                    spender_addresses.get(_NETWORK),
                    field_name="spender_address",
                )
                execution_ready = (
                    funding.get("hosted_facilitator_enabled") is True
                    and funding.get("hosted_facilitator_ready") is True
                    and funding.get("automatic_payment_rail")
                    == "clink_hosted_executor"
                )
            else:
                spender = _canonical_address(
                    funding.get("spender_address"), field_name="spender_address"
                )
                execution_ready = (
                    rail == "clink_native_facilitator"
                    and funding.get("native_facilitator_ready") is True
                )
            supported_assets = funding.get("supported_assets")
            valid = (
                funding.get("status") == "ready"
                and funding.get("live_funding_enabled") is True
                and execution_ready
                and isinstance(supported_assets, dict)
                and _canonical_address(
                    supported_assets.get(_NETWORK),
                    field_name="source_token_address",
                )
                == self.source_token
            )
        except (AttributeError, TypeError, ValueError):
            failed = True
            valid = False
            spender = ""
        if failed or not valid:
            raise FundingCoordinatorError("Core funding is not ready")
        return spender

    @staticmethod
    def _validated_authorization(
        authorization: dict[str, Any],
        *,
        amount_atomic: str,
        account_readiness: dict[str, Any],
        mandate: dict[str, Any],
        opc_installation_id: str | None,
    ) -> tuple[str, str, str]:
        failed = False
        try:
            wallet_identity_id = _canonical_id(
                authorization.get("wallet_identity_id"),
                field_name="wallet_identity_id",
            )
            spending_grant_id = _canonical_id(
                authorization.get("spending_grant_id"),
                field_name="spending_grant_id",
            )
            asset_allowance_id = _canonical_id(
                authorization.get("asset_allowance_id"),
                field_name="asset_allowance_id",
            )
            valid = (
                authorization.get("ready") is True
                and authorization.get("authorization_rail") == "native_allowance"
                and authorization.get("required_amount_atomic")
                == int(amount_atomic)
                and wallet_identity_id
                == account_readiness.get("wallet_identity_id")
                and spending_grant_id == mandate.get("spending_grant_id")
                and authorization.get("opc_installation_id")
                == opc_installation_id
            )
        except (AttributeError, TypeError, ValueError):
            failed = True
            valid = False
            wallet_identity_id = spending_grant_id = asset_allowance_id = ""
        if failed or not valid:
            raise FundingCoordinatorError("Core authorization is not ready")
        return wallet_identity_id, spending_grant_id, asset_allowance_id

    def _deposit_target(self, account: VenueAccount):
        failure: tuple[str, int] | None = None
        try:
            deposit = self.funding_adapter.create_deposit_address(
                CreatePolymarketBridgeDepositRequest(
                    user_id=account.user_id,
                    binding_id=account.binding_id,
                    venue_wallet_address=account.venue_wallet_address,
                )
            )
            if (
                deposit.user_id != account.user_id
                or deposit.binding_id != account.binding_id
                or deposit.venue_wallet_address != account.venue_wallet_address
                or deposit.source_network != _NETWORK
                or deposit.destination_network != _NETWORK
                or deposit.source_token_address != self.source_token
                or deposit.destination_token_address != self.destination_token
            ):
                raise ValueError
            return deposit
        except BridgeTransportError:
            failure = ("Bridge service is temporarily unavailable", 503)
        except BridgeAdapterError as exc:
            if str(exc) == "bridge binding context conflict":
                failure = ("Bridge target context conflict", 409)
            else:
                failure = ("Bridge target could not be created", 502)
        except (TypeError, ValueError, RuntimeError):
            failure = ("Bridge target could not be created", 502)
        if failure is not None:
            message, status_code = failure
            raise FundingCoordinatorError(message, status_code=status_code)
        raise AssertionError("unreachable")

    def _authorization(self, **kwargs: Any) -> dict[str, Any]:
        failed = False
        try:
            value = self.core_gateway.resolve_authorization(
                user_id=kwargs["user_id"],
                agent_id=_AGENT_ID,
                amount_usdc=kwargs["amount_usdc"],
                amount_atomic=kwargs["amount_atomic"],
                token_address=self.source_token,
                spender_address=kwargs["spender_address"],
                destination=kwargs["destination"],
                resource=kwargs["resource"],
                opc_installation_id=kwargs["opc_installation_id"],
            )
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (PredictionCoreGatewayError, TypeError, ValueError, RuntimeError):
            failed = True
        if failed:
            raise FundingCoordinatorError("Core authorization is not ready")
        raise AssertionError("unreachable")

    def _risk_assessment(
        self,
        *,
        operation_id: str,
        user_id: str,
        bridge_address: str,
        amount_atomic: str,
        resource: str,
    ) -> tuple[PolymarketFundingRiskAssessment, datetime]:
        if not self.risk_assessment_available:
            raise FundingCoordinatorError(
                "funding risk assessment is unavailable", status_code=503
            )
        failed = False
        try:
            assessment = self.risk_assessments.assess(
                operation_id=operation_id,
                user_id=user_id,
                bridge_address=bridge_address,
                amount_atomic=amount_atomic,
                resource=resource,
            )
            observed_at = self._utc_now()
            valid = (
                isinstance(assessment, PolymarketFundingRiskAssessment)
                and assessment.subject_id == user_id
                and assessment.bridge_address == bridge_address
                and assessment.amount_atomic == amount_atomic
                and assessment.resource == resource
                and observed_at - RISK_ASSESSMENT_MAX_AGE
                <= assessment.assessed_at
                <= observed_at + RISK_ASSESSMENT_CLOCK_SKEW
            )
        except (FundingCoordinatorError, TypeError, ValueError, RuntimeError):
            failed = True
            assessment = None
            observed_at = None
            valid = False
        if failed or not valid or assessment is None or observed_at is None:
            raise FundingCoordinatorError(
                "funding risk assessment is unavailable", status_code=503
            )
        if assessment.risk_action != "approve":
            raise FundingCoordinatorError("funding risk assessment did not approve")
        return assessment, observed_at

    def _utc_now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise FundingCoordinatorError("funding clock is invalid")
        return value.astimezone(UTC)


def _canonical_id(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _canonical_address(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    normalized = value.strip().lower()
    if not _ADDRESS.fullmatch(normalized) or normalized == "0x" + "0" * 40:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _canonical_uint256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _UINT256.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")
    if (
        len(value) > len(UINT256_MAX_ATOMIC)
        or len(value) == len(UINT256_MAX_ATOMIC)
        and value > UINT256_MAX_ATOMIC
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def _canonical_tx_hash(value: Any) -> str:
    if not isinstance(value, str):
        raise FundingCoordinatorError("Core reservation state is invalid")
    normalized = value.strip().lower()
    if not _TX_HASH.fullmatch(normalized):
        raise FundingCoordinatorError("Core reservation state is invalid")
    return normalized


def _result_id(result: dict[str, Any] | None, field_name: str) -> str | None:
    if result is None:
        return None
    try:
        return _canonical_id(result.get(field_name), field_name=field_name)
    except (TypeError, ValueError):
        return None


def _reason_code(value: Any, default: str) -> str:
    if isinstance(value, str) and _REASON.fullmatch(value):
        return value
    return default


def _core_failure(result: dict[str, Any]) -> dict[str, str] | None:
    if result.get("replacement_forbidden") is not True:
        return None
    evidence = result.get("failed_submission_evidence")
    if not isinstance(evidence, list) or len(evidence) != 1:
        return None
    item = evidence[0]
    if not isinstance(item, dict):
        return None
    kind = item.get("kind")
    raw_reason = item.get("reason_code")
    if kind not in {"definite_rpc_rejection", "failed_receipt"}:
        return None
    if not isinstance(raw_reason, str):
        return None
    reason = raw_reason.upper()
    if not _REASON.fullmatch(reason):
        return None
    try:
        tx_hash = _canonical_tx_hash(result.get("tx_hash"))
        evidence_hash = _canonical_tx_hash(item.get("tx_hash"))
    except FundingCoordinatorError:
        return None
    if evidence_hash != tx_hash:
        return None
    return {"kind": kind, "reason_code": reason, "tx_hash": tx_hash}


def _core_prebroadcast_state(result: dict[str, Any]) -> str | None:
    state = result.get("risk_prebroadcast_state")
    blocked = result.get("risk_prebroadcast_blocked")
    blocked_at = result.get("risk_prebroadcast_blocked_at")
    if state in {"pending", "ready"} and blocked is False and blocked_at is None:
        return state
    if state == "blocked" and blocked is True and isinstance(blocked_at, str):
        return state
    return None


def _core_retryable_without_transaction(result: dict[str, Any]) -> bool:
    return bool(
        result.get("state") == "spending_reserved"
        and result.get("reconciliation_status") == "retryable"
        and result.get("next_action") == "retry_settlement"
        and _core_has_no_transaction_evidence(result)
        and result.get("single_submission") is True
        and result.get("replacement_forbidden") is False
        and not result.get("failed_submission_evidence")
    )


def _operation_allows_prebroadcast_release(
    operation: PolymarketFundingOperation,
) -> bool:
    return bool(
        operation.core_state in {None, "spending_reserved"}
        and operation.core_tx_hash is None
        and operation.core_replacement_forbidden is False
        and operation.core_failure_evidence_kind is None
    )


def _core_has_no_transaction_evidence(result: dict[str, Any]) -> bool:
    return bool(
        result.get("tx_hash") is None
        and result.get("receipt_id") is None
        and result.get("receipt") is None
        and result.get("settlement_sender") is None
        and result.get("settlement_nonce") is None
        and result.get("settlement_transaction") is None
        and not result.get("failed_tx_hashes")
        and not result.get("failed_merchant_tx_hashes")
        and not result.get("failed_submission_evidence")
        and not result.get("definitive_failure")
    )


def _core_released_without_transaction(result: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(result, dict)
        and result.get("state") == "released"
        and result.get("release_reason") == "prediction_market_prebroadcast_retry"
        and _core_has_no_transaction_evidence(result)
        and result.get("single_submission") is True
        and result.get("replacement_forbidden") is False
    )


def _same_core_transaction(result: dict[str, Any], expected_hash: str | None) -> bool:
    if expected_hash is None:
        return False
    try:
        return _canonical_tx_hash(result.get("tx_hash")) == expected_hash
    except FundingCoordinatorError:
        return False


def _amount_atomic(amount_usdc: str) -> str:
    whole, fraction = amount_usdc.split(".", 1)
    return str(int(whole) * 1_000_000 + int(fraction))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _canonical_hash(namespace: str, value: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_canonical_json_value,
    ).encode("utf-8")
    return "0x" + hashlib.sha256(encoded).hexdigest()


def _canonical_json_value(value: Any) -> str:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError("value is not canonically serializable")
