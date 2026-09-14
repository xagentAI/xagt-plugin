# -*- coding: utf-8 -*-
"""Internal data models for the deterministic diff engine.

The whole engine is LLM-free: every ``Finding`` produced by the engines is
``source == "confirmed"``. The optional LLM layer only appends additional
``source == "advisory"`` findings (impact assessment / migration guidance).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

# Ordered severity levels (critical most severe).
SEVERITY_ORDER = ("critical", "major", "minor", "info")

# Supported contract formats.
FORMAT_OPENAPI = "openapi"
FORMAT_GRAPHQL = "graphql"
FORMAT_JSON_SCHEMA = "json-schema"
SUPPORTED_FORMATS = (FORMAT_OPENAPI, FORMAT_GRAPHQL, FORMAT_JSON_SCHEMA)


@dataclass
class Finding:
    """A single detected contract change.

    Attributes:
        change_type: stable machine-readable change kind (e.g.
            ``endpoint_removed``, ``field_type_changed``).
        breaking: whether the change breaks existing consumers.
        severity: ``critical`` | ``major`` | ``minor`` | ``info``.
        location: human-readable location path (e.g. ``GET /users/{id}``).
        summary: one-line human description of what changed.
        previous: rendered representation of the old value (or None).
        current: rendered representation of the new value (or None).
        suggestion: migration / remediation guidance.
        source: ``confirmed`` (deterministic) or ``advisory`` (LLM).
        format: ``openapi`` | ``graphql`` | ``json-schema``.
    """

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
    id: str = ""  # stable id assigned at creation

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiffReport:
    """Complete result of a contract diff."""

    format: str
    breaking: bool
    total_changes: int = 0
    breaking_count: int = 0
    counts: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    schema_version: int = 1
    llm_enabled: bool = False

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "format": self.format,
            "breaking": self.breaking,
            "total_changes": self.total_changes,
            "breaking_count": self.breaking_count,
            "counts": self.counts,
            "summary": self.summary,
            "llm_enabled": self.llm_enabled,
            "findings": [f.as_dict() for f in self.findings],
        }