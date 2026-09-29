from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer


class EvaluateActionPolicyRequest(BaseModel):
    action_id: str | None = None
    user_id: str
    agent_id: str
    action_type: str = "service_purchase"
    amount_usdc: str
    authorization_id: str | None = None
    merchant_id: str | None = None
    target_address: str | None = None
    chain: str | None = None
    risk_level: str | None = None
    risk_score: int | None = None
    risk_action: str | None = None
    user_confirmed: bool = False
    requires_confirmation: bool = True
    live_mode: bool = False
    metadata: dict = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    policy_decision_id: str
    action_id: str | None = None
    approved: bool
    decision: str
    reason_code: str
    reasons: list[str] = Field(default_factory=list)
    required_action: str | None = None
    user_id: str
    agent_id: str
    action_type: str
    amount_usdc: str
    authorization_id: str | None = None
    merchant_id: str | None = None
    target_address: str | None = None
    chain: str | None = None
    authorization_approved: bool | None = None
    remaining_amount_usdc: str | None = None
    risk_level: str | None = None
    risk_score: int | None = None
    risk_action: str | None = None
    risk_assessment: dict | None = None
    credit_model_assessment: dict | None = None
    evaluated_at: str
    event_log: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _serialize_model(self, handler: SerializerFunctionWrapHandler) -> dict:
        payload = handler(self)
        if self.credit_model_assessment is None:
            payload.pop("credit_model_assessment", None)
        return payload

    def to_dict(self) -> dict:
        return self.model_dump()
