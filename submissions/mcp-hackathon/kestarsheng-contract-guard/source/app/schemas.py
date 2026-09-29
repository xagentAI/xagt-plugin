# -*- coding: utf-8 -*-
"""Pydantic models for the REST API surface."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    commit: str
    service: str = "contract-guard"
    version: str = "1.0.0"


class VerificationResponse(BaseModel):
    schemaVersion: int = 1
    slug: str
    commit: str


class DiffRequest(BaseModel):
    old_spec: str = Field(..., description="Previous contract (OpenAPI/GraphQL SDL/JSON Schema text)")
    new_spec: str = Field(..., description="New contract text to compare against old_spec")
    format: str = Field("openapi", description="openapi | graphql | json-schema")
    use_llm: bool = Field(False, description="Append LLM impact assessment (advisory)")


class FindingResponse(BaseModel):
    change_type: str
    breaking: bool
    severity: str
    location: str
    summary: str
    previous: str | None = None
    current: str | None = None
    suggestion: str = ""
    source: str = "confirmed"
    format: str = ""
    id: str = ""


class DiffResponse(BaseModel):
    schema_version: int = 1
    format: str
    breaking: bool
    total_changes: int
    breaking_count: int
    counts: dict
    summary: str
    llm_enabled: bool
    findings: list[FindingResponse]


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


class ChainDiffRequest(BaseModel):
    specs: list[str] = Field(..., description="Ordered list of contract versions (v1, v2, ..., vN)")
    format: str = Field("openapi", description="openapi | graphql | json-schema")
    use_llm: bool = False


class ChainDiffStepResponse(BaseModel):
    step: int
    from_version: str
    to_version: str
    breaking: bool
    breaking_count: int
    total_changes: int
    summary: str
    findings: list[FindingResponse]


class ChainDiffResponse(BaseModel):
    format: str
    total_steps: int
    cumulative_breaking: bool
    cumulative_breaking_count: int
    steps: list[ChainDiffStepResponse]
    summary: str


class SemverResponse(BaseModel):
    bump: str
    reason: str
    current_version: str | None = None
    suggested_version: str | None = None
    breaking_count: int
    total_changes: int


class MigrationSuggestionResponse(BaseModel):
    change_type: str
    location: str
    severity: str
    summary: str
    migration: str
    current_suggestion: str


class MigrationResponse(BaseModel):
    total_breaking: int
    has_migration_path: bool
    suggestions: list[MigrationSuggestionResponse]


class ConsumerScanRequest(BaseModel):
    old_spec: str = Field(..., description="Previous contract (OpenAPI/GraphQL SDL/JSON Schema text)")
    new_spec: str = Field(..., description="New contract text to compare against old_spec")
    format: str = Field("openapi", description="openapi | graphql | json-schema")
    consumer_profile: dict | None = Field(
        None,
        description=(
            "Which parts of the API this consumer actually uses. Keys: "
            "paths (list of OpenAPI path templates), schemas (list of "
            "component/schema or GraphQL type names), fields (list of "
            "exact location prefixes). Omit for full (non-filtered) impact."
        ),
    )
    use_llm: bool = Field(False, description="Append LLM impact assessment (advisory)")

class GateRequest(BaseModel):
    old_spec: str = Field(..., description="Previous contract (OpenAPI/GraphQL SDL/JSON Schema text)")
    new_spec: str = Field(..., description="New contract text to compare against old_spec")
    format: str = Field("openapi", description="openapi | graphql | json-schema")
    max_severity: str | None = Field(
        None,
        description=(
            "Block only findings stricter than this threshold "
            "(critical > major > minor > info). Higher severity than the "
            "threshold blocks the gate. Omit with allow_breaking=false to "
            "block every breaking change."
        ),
    )
    allow_breaking: bool | None = Field(
        None,
        description=(
            "Explicit policy: true always passes (only informational), "
            "false blocks on any breaking change. Default (omit both) "
            "blocks on any breaking change."
        ),
    )
    consumer_profile: dict | None = Field(
        None,
        description=(
            "Optional consumer subset (paths/schemas/fields). When set, the "
            "gate evaluates only findings that hit this caller -- a change is "
            "blocked only if it breaks THIS consumer."
        ),
    )