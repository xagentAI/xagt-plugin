from typing import Any, Optional
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    openapi_url: Optional[str] = None
    openapi_json: Optional[dict[str, Any]] = None


class AnalyzeResponse(BaseModel):
    project_id: str
    endpoints: int
    score: dict[str, Any]
    issues: list[dict[str, Any]]


class ProxyRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
