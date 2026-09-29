from pydantic import BaseModel, Field


class WriteAuditEventRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    event_type: str
    source_service: str
    action_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    policy_decision_id: str | None = None
    payment_id: str | None = None
    order_id: str | None = None
    receipt_id: str | None = None
    tx_hash: str | None = None
    payload: dict = Field(default_factory=dict)


class AuditEvent(BaseModel):
    event_id: str
    event_type: str
    source_service: str
    action_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    policy_decision_id: str | None = None
    payment_id: str | None = None
    order_id: str | None = None
    receipt_id: str | None = None
    tx_hash: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: str

    def to_dict(self) -> dict:
        return self.model_dump()


class AuditTrail(BaseModel):
    action_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    events: list[AuditEvent] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class AuditSummaryEvent(BaseModel):
    event: str
    summary: str
    at: str

    def to_dict(self) -> dict:
        return self.model_dump()
