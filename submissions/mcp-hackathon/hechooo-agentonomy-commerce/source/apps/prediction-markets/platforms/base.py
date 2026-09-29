from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from shared.schemas import PredictionMarketOrderPreview


class PlatformExecutionResult(BaseModel):
    platform: str
    ready: bool = False
    submitted: bool = False
    order_id: str | None = None
    tx_hash: str | None = None
    status: str | None = None
    reason: str | None = None
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionAdapter(Protocol):
    platform: str

    def readiness(self) -> PlatformExecutionResult: ...

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult: ...
