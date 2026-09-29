from pydantic import BaseModel, Field


class CreateAuthorizationRequest(BaseModel):
    user_id: str
    agent_id: str
    max_amount_usdc: str
    expires_in_minutes: int = 30


class CheckAuthorizationRequest(BaseModel):
    amount_usdc: str


class SpendAuthorizationRequest(BaseModel):
    amount_usdc: str
    payment_id: str | None = None


class BudgetAuthorization(BaseModel):
    authorization_id: str
    user_id: str
    agent_id: str
    max_amount_usdc: str
    spent_amount_usdc: str
    remaining_amount_usdc: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str | None = None
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class AuthorizationCheckResult(BaseModel):
    authorization_id: str
    approved: bool
    status: str
    reason: str
    amount_usdc: str
    remaining_amount_usdc: str

    def to_dict(self) -> dict:
        return self.model_dump()
