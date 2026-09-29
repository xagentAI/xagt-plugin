from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountSessionRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=96)


class InteractionRequest(StrictModel):
    kind: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=96)
    payload: dict[str, Any]


class InteractionConsumeRequest(StrictModel):
    token: str = Field(min_length=16, max_length=256)
