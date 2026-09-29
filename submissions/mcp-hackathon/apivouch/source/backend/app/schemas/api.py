from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    openapi_url: str | None = None
    openapi_json: dict[str, Any] | None = None


class AnalyzeResponse(BaseModel):
    project_id: str
    endpoints: int
    score: dict[str, Any]
    issues: list[dict[str, Any]]


class ProxyRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class TestRequest(BaseModel):
    samples_per_endpoint: int = Field(default=2, ge=1, le=5)
    arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PaginationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "cursor", "page", "offset", "single"] = "auto"
    request_token_parameter: str | None = Field(default=None, min_length=1, max_length=128)
    items_path: str | None = Field(default=None, min_length=1, max_length=256)
    next_cursor_path: str | None = Field(default=None, min_length=1, max_length=256)
    has_more_path: str | None = Field(default=None, min_length=1, max_length=256)
    total_path: str | None = Field(default=None, min_length=1, max_length=256)
    snapshot_path: str | None = Field(default=None, min_length=1, max_length=256)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_records: int = Field(default=5000, ge=1, le=10000)


class ExhaustiveClaimRequest(BaseModel):
    """A claim to verify. Evidence is deliberately absent: APIVouch collects it."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1, max_length=256)
    claim_type: Literal["ALL", "NONE", "EXACT_COUNT", "MIN", "MAX"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_count: int | None = Field(default=None, ge=0)
    field: str | None = Field(default=None, min_length=1, max_length=256)
    candidate_id: str | int | float | None = None
    id_field: str = Field(default="id", min_length=1, max_length=128)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class OutcomeProvider(BaseModel):
    """A public, credential-free provider that can return the requested outcome."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=2048)
    result_path: str | None = Field(default=None, max_length=256)
    expected_schema: dict[str, Any] | None = None
    price_usd: float = Field(default=0, ge=0, le=1000)


class OutcomeConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_price_usd: float = Field(default=1, ge=0, le=1000)
    max_latency_ms: int = Field(default=5000, ge=50, le=30000)
    minimum_agreement: int = Field(default=2, ge=1, le=5)
    numeric_tolerance_percent: float = Field(default=1, ge=0, le=25)


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=3, max_length=500)
    providers: list[OutcomeProvider] = Field(min_length=2, max_length=5)
    constraints: OutcomeConstraints = Field(default_factory=OutcomeConstraints)


class ReceiptLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(pattern=r"^[0-9a-f]{24}$")
