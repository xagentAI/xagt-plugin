"""Owner-bound direct transfers using the existing Core money state machine."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable
from uuid import uuid4

import httpx

from services.action_service.schemas import CreateActionIntentRequest, UpdateActionIntentRequest
from services.action_service.service import ActionService
from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService
from services.funding_service.hosted_client import (
    HostedExecutionNotFound,
    HostedFacilitatorError,
)
from services.funding_service.schemas import (
    CreateDirectTransferRequest, CreateSpendingReservationRequest, SettleSpendingReservationRequest,
)
from services.policy_service.schemas import EvaluateActionPolicyRequest


class DirectTransferService:
    """One durable operation per actor/request; money remains in FundingLedger.

    A short processing lease serializes duplicate orchestration. Its expiry only
    permits recovery of the SAME reservation, never a replacement payment.
    """

    _HOSTED_LOOKUP_MISS_RETRY_DELAY_SECONDS = 60

    def __init__(self, funding, *, resolve_authorization: Callable[[dict], dict] | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.funding = funding
        self.config = funding.config
        self.ledger = funding.ledger
        self.resolve_authorization = resolve_authorization or self._resolve_over_http
        self.clock = clock or (lambda: datetime.now(UTC))

    def create(self, request: CreateDirectTransferRequest) -> dict:
        request = CreateDirectTransferRequest.model_validate(request.model_dump())
        if not self.config.clink_direct_transfers_enabled:
            raise ValueError("DIRECT_TRANSFERS_DISABLED")
        if self.config.clink_facilitator_mode != "hosted":
            raise ValueError("DIRECT_TRANSFERS_REQUIRE_HOSTED")
        asset = self.funding.asset_registry.asset(request.network)
        transfer_id = "transfer_" + self._hash([request.user_id, request.agent_id, request.request_id])[:48]
        fingerprint = self._hash(request.model_dump())
        amount_atomic = str(int(Decimal(request.amount_usdc) * 10**asset.token_decimals))
        lease = uuid4().hex
        now = self.clock().timestamp()
        busy = False
        with self.ledger.transaction() as tx:
            row = tx.get(transfer_id)
            if row is not None and row["request_hash"] != fingerprint:
                raise ValueError("TRANSFER_REQUEST_CONFLICT")
            if row is not None and (row["token_address"], row["amount_atomic"]) != (asset.token_address, amount_atomic):
                raise ValueError("TRANSFER_ASSET_CONFIGURATION_CHANGED")
            if row is not None and row.get("lease_until", 0) > now:
                busy = True
            else:
                row = {
                    **(row or {}), **request.model_dump(), "transfer_id": transfer_id,
                    "request_hash": fingerprint, "token_address": asset.token_address,
                    "amount_atomic": amount_atomic,
                    "lease_id": lease, "lease_until": now + 300,
                    "reason_code": None,
                }
                tx.put("direct_transfer", transfer_id, row)
        if busy:
            return self._response(row, self._reservation(transfer_id), reason="TRANSFER_IN_PROGRESS")
        try:
            reservation = self._reservation(transfer_id)
            if reservation is None:
                reservation = self._prepare(row, lease)
            self._require_claim(transfer_id, lease)
            if reservation.get("state") not in {"settled", "finalized", "released", "reorg_review"}:
                # Recovery is read-only at Hosted: never resubmit an unknown operation.
                if self._has_submission(reservation):
                    reservation = self._recover(reservation)
                else:
                    reservation = self.funding.settle_reservation(
                        reservation["reservation_id"], SettleSpendingReservationRequest(payment_authorization={
                            "kind": "direct_transfer", "operation_id": transfer_id,
                            "reservation_id": reservation["reservation_id"], "network": row["network"],
                            "destination": row["to_address"], "token": row["token_address"],
                            "amount_atomic": row["amount_atomic"],
                        }))
            return self._response(row, reservation)
        except ValueError as exc:
            code = self._safe_reason(str(exc))
            with self.ledger.transaction() as tx:
                current = tx.get(transfer_id)
                if current.get("lease_id") == lease:
                    tx.put("direct_transfer", transfer_id, {**current, "reason_code": code})
            return self._response(row, self._reservation(transfer_id), reason=code)
        finally:
            with self.ledger.transaction() as tx:
                current = tx.get(transfer_id)
                if current.get("lease_id") == lease:
                    tx.put("direct_transfer", transfer_id, {**current, "lease_until": 0})

    def get(self, transfer_id: str, *, user_id: str, agent_id: str,
            opc_installation_id: str | None = None) -> dict:
        if re.fullmatch(r"transfer_[0-9a-f]{48}", transfer_id) is None:
            raise ValueError("TRANSFER_NOT_FOUND")
        with self.ledger.transaction() as tx:
            row = tx.get(transfer_id)
        if row is None or (row["user_id"], row["agent_id"], row.get("opc_installation_id")) != (
            user_id, agent_id, opc_installation_id
        ):
            raise ValueError("TRANSFER_NOT_FOUND")
        reservation = self._reservation(transfer_id)
        if reservation is not None and self._has_submission(reservation) and reservation.get("state") not in {"settled", "finalized", "released", "reorg_review"}:
            # Only recover an already accepted/submission-unknown Hosted operation.
            # This path cannot call settle_reservation or client.submit.
            try:
                reservation = self._recover(reservation)
            except ValueError:
                return self._response(row, reservation, reason="TRANSFER_RECONCILIATION_REQUIRED")
        return self._response(row, reservation, reason=row.get("reason_code"))

    def _prepare(self, row: dict, lease: str) -> dict:
        executor = self.funding._hosted_executor_address(
            self.config.clink_hosted_facilitator_chain_targets.get(row["network"]))
        if executor is None:
            raise ValueError("HOSTED_TARGET_NOT_CONFIGURED")
        resource = "clink:transfer:" + row["transfer_id"]
        resolution = self.resolve_authorization({
            "user_id": row["user_id"], "agent_id": row["agent_id"],
            "opc_installation_id": row.get("opc_installation_id"),
            "authorization_rail": "native_allowance", "product": "transfers",
            "venue": "clink_transfers", "merchant": row["to_address"],
            "network": row["network"], "token_address": row["token_address"],
            "spender_address": executor, "amount_usdc": row["amount_usdc"],
            "destination": row["to_address"], "resource": resource,
        })
        if resolution.get("ready") is not True:
            raise ValueError(self._safe_reason(resolution.get("reason_code") or "TRANSFER_NOT_READY"))
        if resolution.get("user_interaction_required") is True:
            raise ValueError("TRANSFER_USER_INTERACTION_REQUIRED")
        self._require_claim(row["transfer_id"], lease)
        scope = {
            "purchase_id": row["transfer_id"],  # Generic existing operation reference, not a purchase record.
            "quote_hash": "0x" + row["request_hash"], "network": row["network"],
            "asset": row["token_address"], "amount_atomic": row["amount_atomic"],
            "destination": row["to_address"], "resource": resource,
            "authorization_rail": "native_allowance", "product": "transfers",
            **{key: resolution[key] for key in ("wallet_identity_id", "spending_grant_id", "asset_allowance_id")},
        }
        if row.get("opc_installation_id"):
            scope["opc_installation_id"] = row["opc_installation_id"]
        actions = ActionService(config=self.config)
        action = actions.create_intent(CreateActionIntentRequest(
            user_id=row["user_id"], agent_id=row["agent_id"], action_type="funding_transfer",
            amount_usdc=row["amount_usdc"], target=row["to_address"], merchant_id=row["to_address"],
            description="Direct USDC transfer", metadata=scope))
        policy = self.funding.policy_service.evaluate(EvaluateActionPolicyRequest(
            action_id=action.action_id, user_id=row["user_id"], agent_id=row["agent_id"],
            action_type="funding_transfer", amount_usdc=row["amount_usdc"], merchant_id=row["to_address"],
            target_address=row["to_address"], chain=row["network"], metadata=scope,
            requires_confirmation=False, user_confirmed=False, live_mode=self.config.clink_live_funding))
        actions.update_intent(action.action_id, UpdateActionIntentRequest(
            state="policy_approved" if policy.approved else "blocked", policy_decision_id=policy.policy_decision_id))
        AuditService(database_url=self.config.funding_database_url).write_event(WriteAuditEventRequest(
            event_type="direct_transfer_policy_evaluated", source_service="clink_core_transfer",
            action_id=action.action_id, user_id=row["user_id"], agent_id=row["agent_id"],
            policy_decision_id=policy.policy_decision_id,
            payload={**scope, "merchant_id": row["to_address"], "venue": "clink_transfers"}))
        if policy.approved is not True:
            raise ValueError(policy.reason_code)
        self._require_claim(row["transfer_id"], lease)
        # A recovered lease may have already completed reserve before losing its reply.
        existing = self._reservation(row["transfer_id"])
        if existing is not None:
            return existing
        return self.funding.reserve_spending(CreateSpendingReservationRequest(
            **scope, idempotency_key=row["transfer_id"], action_id=action.action_id,
            policy_decision_id=policy.policy_decision_id, merchant_id=row["to_address"],
            amount_usdc=row["amount_usdc"], venue="clink_transfers"))

    def _require_claim(self, transfer_id: str, lease: str) -> None:
        with self.ledger.transaction() as tx:
            row = tx.get(transfer_id)
            if row is None or row.get("lease_id") != lease or row.get("lease_until", 0) <= self.clock().timestamp():
                raise ValueError("TRANSFER_IN_PROGRESS")

    def _reservation(self, transfer_id: str) -> dict | None:
        with self.ledger.transaction() as tx:
            row = tx.by_purchase(transfer_id)
            operation = tx.get(transfer_id)
        if row is not None and (row.get("product") != "transfers" or row.get("venue") != "clink_transfers"):
            raise ValueError("TRANSFER_REQUEST_CONFLICT")
        if row is not None and (operation is None or any(
            row.get(target) != operation.get(source) for target, source in (
                ("user_id", "user_id"), ("agent_id", "agent_id"),
                ("opc_installation_id", "opc_installation_id"), ("destination", "to_address"),
                ("network", "network"), ("token_address", "token_address"),
                ("amount_atomic", "amount_atomic"),
            )
        )):
            raise ValueError("TRANSFER_REQUEST_CONFLICT")
        return row

    @staticmethod
    def _has_submission(row: dict) -> bool:
        return row.get("settlement_rail") == "hosted" and bool(
            row.get("hosted_request_id") or row.get("hosted_execution_id") or row.get("hosted_submission_unknown"))

    def _recover(self, reservation: dict) -> dict:
        # A process may have died after persisting intent or posting it, before
        # storing a response. There is no evidence that a second POST is safe.
        with self.ledger.transaction() as tx:
            current = tx.get(reservation["reservation_id"])
            if (
                current.get("state") not in {"settled", "finalized", "released", "reorg_review"}
                and not current.get("hosted_execution_id")
                and current.get("hosted_submission_unknown") is not True
            ):
                # Do not erase private legacy transaction evidence by writing
                # back get()'s redacted view while establishing recovery state.
                tx.require_no_durable_transaction_evidence(current["reservation_id"])
                self.funding._put_reservation(tx, {
                    **current, "hosted_submission_unknown": True,
                    "reconciliation_status": "pending", "next_action": "reconcile_hosted_execution",
                })
        current = self._reservation(reservation["purchase_id"])
        if current.get("hosted_execution_id"):
            return self.funding._reconcile_hosted_reservation(
                reservation["reservation_id"]
            )
        with self.ledger.transaction() as tx:
            capability = tx.payment_capability_for_reservation(
                reservation["reservation_id"]
            )
        if capability is None:
            raise ValueError("HOSTED_PAYMENT_CAPABILITY_UNAVAILABLE")
        client = self.funding._require_hosted_client(
            capability.network, capability=capability
        )
        prepared = self.funding._prepare_hosted_request(
            current, capability, client
        )
        try:
            response = client.recover_by_idempotency(prepared)
        except HostedExecutionNotFound:
            return self._rearm_after_definitive_lookup_miss(
                reservation["reservation_id"]
            )
        except HostedFacilitatorError:
            return current
        return self.funding._apply_hosted_response(
            reservation["reservation_id"], response
        )

    def _rearm_after_definitive_lookup_miss(self, reservation_id: str) -> dict:
        """Permit one same-operation POST only after a delayed, explicit 404.

        The transfer ID, reservation, budget hold, policy decision and Hosted
        idempotency key remain unchanged.  Any execution or durable transaction
        evidence keeps the operation recovery-only.
        """
        with self.ledger.transaction() as tx:
            current = tx.get(reservation_id)
            if current is None:
                raise ValueError("TRANSFER_NOT_FOUND")
            if current.get("hosted_execution_id"):
                return current
            issued_at = current.get("hosted_request_issued_at")
            if (
                not isinstance(issued_at, int)
                or self.clock().timestamp() - issued_at
                < self._HOSTED_LOOKUP_MISS_RETRY_DELAY_SECONDS
            ):
                return current
            tx.require_no_durable_transaction_evidence(reservation_id)
            retryable = {
                **current,
                "hosted_request_id": None,
                "hosted_request_nonce": None,
                "hosted_request_hash": None,
                "hosted_request_issued_at": None,
                "hosted_execution_id": None,
                "hosted_status": "not_found_retryable",
                "hosted_submission_unknown": False,
                "reconciliation_status": "retryable",
                "next_action": "retry_settlement",
                "last_reconciliation_error": None,
            }
            self.funding._put_reservation(tx, retryable)
            return retryable

    def _resolve_over_http(self, payload: dict) -> dict:
        try:
            response = httpx.post(
                self.config.account_service_url + "/internal/authorization-resolution", json=payload,
                headers={"Authorization": "Bearer " + self.config.clink_internal_api_token},
                timeout=15, follow_redirects=False)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("invalid resolution")
            return body
        except (httpx.HTTPError, ValueError):
            raise ValueError("ACCOUNT_SERVICE_UNAVAILABLE") from None

    @staticmethod
    def _hash(payload) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _safe_reason(message: str) -> str:
        prefix = message.split(":", 1)[0]
        return prefix if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", prefix) else "TRANSFER_NOT_READY"

    @staticmethod
    def _response(row: dict, reservation: dict | None, *, reason: str | None = None) -> dict:
        status = "attention_required" if reason else "preparing"
        next_action = "retry_same_request" if reason else "query_transfer"
        if reservation:
            state = reservation["state"]
            if state in {"settled", "finalized"} and reservation.get("budget_accounting_state") == "settled" and reservation.get("receipt_id"):
                status, next_action, reason = "succeeded", "none", None
            elif reservation.get("reconciliation_status") == "manual_review_required":
                status, next_action = "review_required", "contact_operator"
                if not reason:
                    reason = DirectTransferService._safe_reason(
                        str(
                            reservation.get("release_reason")
                            or "HOSTED_EXECUTION_REVIEW_REQUIRED"
                        )
                    )
            elif state == "released":
                status, next_action = "failed", "none"
                if not reason and reservation.get("release_reason"):
                    reason = DirectTransferService._safe_reason(
                        str(reservation["release_reason"])
                    )
            elif state == "reorg_review":
                status, next_action = "review_required", "contact_operator"
            elif reservation.get("hosted_submission_unknown"):
                status, next_action = "pending", "query_transfer"
            elif state == "payment_submitted" or reservation.get("hosted_execution_id"):
                status, next_action = "pending", "query_transfer"
            elif not reason:
                status, next_action = "reserved", "retry_same_request"
        return {
            "transfer_id": row["transfer_id"], "request_id": row["request_id"],
            "status": status, "network": row["network"], "asset": "USDC",
            "token_address": row["token_address"], "to_address": row["to_address"],
            "amount_usdc": row["amount_usdc"], "amount_atomic": row["amount_atomic"],
            "reservation_id": (reservation or {}).get("reservation_id"),
            "tx_hash": (reservation or {}).get("tx_hash"), "receipt_id": (reservation or {}).get("receipt_id"),
            "reason_code": reason, "next_action": next_action,
        }
