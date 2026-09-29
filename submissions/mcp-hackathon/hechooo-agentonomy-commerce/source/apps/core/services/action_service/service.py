from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from eth_utils import keccak

from services.action_policy_repository import ActionPolicyRepository
from services.action_service.schemas import (
    ActionApproval,
    AgentActionIntent,
    CreateActionIntentRequest,
    RequestActionApprovalRequest,
    SubmitActionApprovalRequest,
    UpdateActionIntentRequest,
)
from shared.config import AppConfig


class ActionService:
    """Owns durable AgentActionIntent and ActionApproval provenance."""

    SENSITIVE_APPROVAL_KEYS = {
        "signature",
        "raw_signature",
        "raw_transaction",
        "signed_message",
        "signed_payload",
        "signed_transaction",
    }
    EVM_SIGNATURE_PATTERN = re.compile(r"^0x[0-9a-fA-F]{130}$")
    PAYMENT_ACTION_TYPES = {
        "funding_transfer",
        "marketplace_purchase",
        "prediction_market_order_execute",
    }
    VALID_STATES = {
        "created",
        "policy_checked",
        "policy_evaluated",
        "policy_approved",
        "needs_confirmation",
        "approval_requested",
        "user_approved",
        "user_rejected",
        "blocked",
        "executing",
        "preview_created",
        "payment_created",
        "spending_reserved",
        "signing_required",
        "payment_submitted",
        "paid_but_undelivered",
        "submitted",
        "settled",
        "completed",
        "failed",
        "cancelled",
    }

    def __init__(
        self,
        config: AppConfig | None = None,
        storage_file: Path | str | None = None,
        approval_file: Path | str | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        # Retained for callers during JSONL retirement; it is never authoritative.
        self.legacy_storage_file = Path(storage_file) if storage_file is not None else None
        self.legacy_approval_file = (
            Path(approval_file) if approval_file is not None else None
        )
        self.repository = ActionPolicyRepository(self.config.funding_database_url)

    def create_intent(self, request: CreateActionIntentRequest) -> AgentActionIntent:
        now = self._utc_now()
        intent = AgentActionIntent(
            action_id=f"act_{uuid4().hex[:12]}",
            user_id=request.user_id,
            agent_id=request.agent_id,
            action_type=request.action_type,
            amount_usdc=request.amount_usdc,
            target=request.target,
            merchant_id=request.merchant_id,
            authorization_id=request.authorization_id,
            description=request.description,
            metadata=request.metadata,
            created_at=self._format_time(now),
            updated_at=self._format_time(now),
            event_log=[
                {
                    "event": "created",
                    "state": "created",
                    "created_at": self._format_time(now),
                }
            ],
        )
        return AgentActionIntent.model_validate(
            self.repository.create_action_intent(intent.to_dict())
        )

    def get_intent(self, action_id: str) -> AgentActionIntent | None:
        payload = self.repository.action_intent(action_id)
        return AgentActionIntent.model_validate(payload) if payload is not None else None

    def update_intent(
        self, action_id: str, request: UpdateActionIntentRequest
    ) -> AgentActionIntent | None:
        now = self._utc_now()

        def update(payload: dict) -> dict:
            intent = AgentActionIntent.model_validate(payload)
            state = request.state or intent.state
            if state not in self.VALID_STATES:
                raise ValueError(f"unsupported action intent state: {state}")
            if intent.action_type in self.PAYMENT_ACTION_TYPES and request.metadata:
                raise ValueError("payment action metadata is immutable")
            updated = intent.model_copy(
                update={
                    "state": state,
                    "policy_decision_id": request.policy_decision_id
                    or intent.policy_decision_id,
                    "payment_id": request.payment_id or intent.payment_id,
                    "order_id": request.order_id or intent.order_id,
                    "receipt_id": request.receipt_id or intent.receipt_id,
                    "tx_hash": request.tx_hash or intent.tx_hash,
                    "error": request.error if request.error is not None else intent.error,
                    "metadata": {**intent.metadata, **request.metadata},
                    "updated_at": self._format_time(now),
                    "event_log": [
                        *intent.event_log,
                        {
                            "event": "updated",
                            "state": state,
                            "policy_decision_id": request.policy_decision_id,
                            "payment_id": request.payment_id,
                            "order_id": request.order_id,
                            "receipt_id": request.receipt_id,
                            "tx_hash": request.tx_hash,
                            "error": request.error,
                            "created_at": self._format_time(now),
                        },
                    ],
                }
            )
            return updated.to_dict()

        payload = self.repository.update_action_intent(action_id, update)
        return AgentActionIntent.model_validate(payload) if payload is not None else None

    def request_approval(
        self, action_id: str, request: RequestActionApprovalRequest
    ) -> ActionApproval | None:
        intent = self.get_intent(action_id)
        if intent is None:
            return None
        self._require_safe_approval_content(request.metadata)
        now = self._utc_now()
        approval = ActionApproval(
            approval_id=f"appr_{uuid4().hex[:12]}",
            action_id=intent.action_id,
            user_id=intent.user_id,
            agent_id=intent.agent_id,
            approval_type=request.approval_type,
            requested_by=request.requested_by,
            message=request.message,
            approval_url=request.approval_url,
            metadata=request.metadata,
            created_at=self._format_time(now),
            expires_at=self._format_time(
                now + timedelta(minutes=max(request.expires_in_minutes, 1))
            ),
            event_log=[
                {
                    "event": "approval_requested",
                    "state": "requested",
                    "created_at": self._format_time(now),
                }
            ],
        )
        approval = ActionApproval.model_validate(
            self.repository.create_action_approval(approval.to_dict())
        )
        self._set_approval_state(
            intent,
            approval,
            action_state="approval_requested",
            event_name="approval_requested",
            now=now,
        )
        return approval

    def submit_approval(
        self, approval_id: str, request: SubmitActionApprovalRequest
    ) -> ActionApproval | None:
        self._require_safe_approval_content(request.metadata)
        self._require_safe_approval_content(request.note)
        now = self._utc_now()

        def update(payload: dict) -> dict:
            approval = ActionApproval.model_validate(payload)
            if approval.state != "requested":
                raise ValueError("action approval was already submitted")
            expires_at = datetime.fromisoformat(
                approval.expires_at.replace("Z", "+00:00")
            )
            if expires_at <= now:
                raise ValueError("action approval has expired")
            proof_hash = self._proof_hash(request.signature)
            updated = approval.model_copy(
                update={
                    "state": request.decision,
                    "approved_by": request.approved_by,
                    "wallet_address": request.wallet_address,
                    "proof_hash": proof_hash,
                    "note": request.note,
                    "metadata": {**approval.metadata, **request.metadata},
                    "responded_at": self._format_time(now),
                    "event_log": [
                        *approval.event_log,
                        {
                            "event": "approval_submitted",
                            "state": request.decision,
                            "approved_by": request.approved_by,
                            "wallet_address": request.wallet_address,
                            "proof_hash": proof_hash,
                            "created_at": self._format_time(now),
                        },
                    ],
                }
            )
            return updated.to_dict()

        payload = self.repository.update_action_approval(approval_id, update)
        if payload is None:
            return None
        approval = ActionApproval.model_validate(payload)
        intent = self.get_intent(approval.action_id)
        if intent is not None:
            self._set_approval_state(
                intent,
                approval,
                action_state=(
                    "user_approved" if request.decision == "approved" else "user_rejected"
                ),
                event_name="approval_submitted",
                now=now,
                extra_metadata={"last_approval_decision": request.decision},
            )
        return approval

    def get_approval(self, approval_id: str) -> ActionApproval | None:
        payload = self.repository.action_approval(approval_id)
        return ActionApproval.model_validate(payload) if payload is not None else None

    def _set_approval_state(
        self,
        intent: AgentActionIntent,
        approval: ActionApproval,
        action_state: str,
        event_name: str,
        now: datetime,
        extra_metadata: dict | None = None,
    ) -> AgentActionIntent:
        def update(payload: dict) -> dict:
            current = AgentActionIntent.model_validate(payload)
            metadata = (
                current.metadata
                if current.action_type in self.PAYMENT_ACTION_TYPES
                else {**current.metadata, **(extra_metadata or {})}
            )
            updated = current.model_copy(
                update={
                    "state": action_state,
                    "approval_id": approval.approval_id,
                    "approval_state": approval.state,
                    "metadata": metadata,
                    "updated_at": self._format_time(now),
                    "event_log": [
                        *current.event_log,
                        {
                            "event": event_name,
                            "state": action_state,
                            "approval_id": approval.approval_id,
                            "approval_state": approval.state,
                            "created_at": self._format_time(now),
                        },
                    ],
                }
            )
            return updated.to_dict()

        payload = self.repository.update_action_intent(intent.action_id, update)
        assert payload is not None
        return AgentActionIntent.model_validate(payload)

    @staticmethod
    def _proof_hash(signature: str | None) -> str | None:
        if signature is None:
            return None
        if not isinstance(signature, str) or not signature:
            raise ValueError("approval signature must be a non-empty string")
        try:
            material = bytes.fromhex(signature.removeprefix("0x"))
        except ValueError:
            material = signature.encode("utf-8")
        return "0x" + keccak(material).hex()

    @classmethod
    def _require_safe_approval_content(cls, value) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key).strip().lower() in cls.SENSITIVE_APPROVAL_KEYS:
                    raise ValueError(
                        "approval content contains sensitive signature material"
                    )
                cls._require_safe_approval_content(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                cls._require_safe_approval_content(nested)
            return
        if isinstance(value, str) and cls.EVM_SIGNATURE_PATTERN.fullmatch(value):
            raise ValueError("approval content contains sensitive signature material")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
