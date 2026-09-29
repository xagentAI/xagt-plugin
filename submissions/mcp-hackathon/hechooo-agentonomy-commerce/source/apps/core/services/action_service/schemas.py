from typing import Literal

from pydantic import BaseModel, Field


class CreateActionIntentRequest(BaseModel):
    user_id: str
    agent_id: str
    action_type: str = "service_purchase"
    amount_usdc: str | None = None
    target: str | None = None
    merchant_id: str | None = None
    authorization_id: str | None = None
    description: str | None = None
    metadata: dict = Field(default_factory=dict)


class UpdateActionIntentRequest(BaseModel):
    state: str | None = None
    policy_decision_id: str | None = None
    payment_id: str | None = None
    order_id: str | None = None
    receipt_id: str | None = None
    tx_hash: str | None = None
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


class RequestActionApprovalRequest(BaseModel):
    approval_type: str = "human_confirmation"
    requested_by: str | None = None
    message: str | None = None
    approval_url: str | None = None
    expires_in_minutes: int = 15
    metadata: dict = Field(default_factory=dict)


class SubmitActionApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    approved_by: str
    wallet_address: str | None = None
    signature: str | None = None
    note: str | None = None
    metadata: dict = Field(default_factory=dict)


class AgentActionIntent(BaseModel):
    action_id: str
    user_id: str
    agent_id: str
    action_type: str
    amount_usdc: str | None = None
    target: str | None = None
    merchant_id: str | None = None
    authorization_id: str | None = None
    policy_decision_id: str | None = None
    payment_id: str | None = None
    order_id: str | None = None
    receipt_id: str | None = None
    tx_hash: str | None = None
    approval_id: str | None = None
    approval_state: str | None = None
    description: str | None = None
    state: str = "created"
    error: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class ActionApproval(BaseModel):
    approval_id: str
    action_id: str
    user_id: str
    agent_id: str
    approval_type: str
    state: Literal["requested", "approved", "rejected", "expired"] = "requested"
    requested_by: str | None = None
    message: str | None = None
    approval_url: str | None = None
    approved_by: str | None = None
    wallet_address: str | None = None
    proof_hash: str | None = None
    note: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str
    expires_at: str
    responded_at: str | None = None
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()
