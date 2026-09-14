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