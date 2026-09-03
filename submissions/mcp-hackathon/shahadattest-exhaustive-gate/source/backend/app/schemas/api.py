from typing import Any, Optional
from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    resource_type: str = Field(min_length=1, max_length=128)
    source: str = Field(default="demo-crm", max_length=128)
    scope: dict[str, Any] = Field(default_factory=dict)
    pagination_type: str = Field(default="cursor")
    snapshot_strategy: str = Field(default="STRICT")


class ObservePage(BaseModel):
    page_number: Optional[int] = None
    offset: Optional[int] = None
    cursor_in: Optional[str] = None
    cursor_out: Optional[str] = None
    has_more: bool = False
    records_seen: int = Field(ge=0, default=0)
    items: list[dict[str, Any]] = Field(default_factory=list)
    scope: Optional[dict[str, Any]] = None
    snapshot_id: Optional[str] = None
    authoritative_total: Optional[int] = None


class FailureRecord(BaseModel):
    page_number: Optional[int] = None
    kind: str = Field(default="unknown")
    message: str = Field(default="", max_length=500)


class ClaimIn(BaseModel):
    type: str
    resource: Optional[str] = None
    scope: Optional[dict[str, Any]] = None
    value: Optional[Any] = None
    field: Optional[str] = None
    candidate_id: Optional[str] = None


class VerifyIn(BaseModel):
    claim: ClaimIn


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
