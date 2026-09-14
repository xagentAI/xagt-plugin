# -*- coding: utf-8 -*-
"""Unified diff orchestration: parse + deterministic diff + optional LLM advisory.

This is the single entry point used by both the REST API and the MCP tools.
"""
from __future__ import annotations

from .engines.json_schema import SpecParseError as JsonSchemaParseError
from .engines.json_schema import diff_json_schema, parse_json_schema
from .engines.graphql import SpecParseError as GraphqlParseError
from .engines.graphql import diff_graphql, parse_graphql
from .engines.openapi import SpecParseError as OpenApiParseError
from .engines.openapi import diff_openapi, parse_openapi
from .llm_advisor import assess
from .models import (
    DiffReport,
    Finding,
    FORMAT_GRAPHQL,
    FORMAT_JSON_SCHEMA,
    FORMAT_OPENAPI,
    SEVERITY_ORDER,
    SUPPORTED_FORMATS,
)

_FORMAT_ALIASES = {
    "openapi": FORMAT_OPENAPI,
    "swagger": FORMAT_OPENAPI,
    "oas": FORMAT_OPENAPI,
    "openapi3": FORMAT_OPENAPI,
    "graphql": FORMAT_GRAPHQL,
    "gql": FORMAT_GRAPHQL,
    "graphql-sdl": FORMAT_GRAPHQL,
    "json-schema": FORMAT_JSON_SCHEMA,
    "json_schema": FORMAT_JSON_SCHEMA,
    "jsonschema": FORMAT_JSON_SCHEMA,
    "json": FORMAT_JSON_SCHEMA,
}


class DiffError(ValueError):
    """Raised when a contract cannot be parsed or the format is unsupported."""


def normalize_format(fmt: str) -> str:
    key = (fmt or "").strip().lower()
    if key in _FORMAT_ALIASES:
        return _FORMAT_ALIASES[key]
    raise DiffError(
        f"Unsupported format '{fmt}'. Supported: {', '.join(SUPPORTED_FORMATS)}"
    )


def detect_changes(old_raw: str, new_raw: str, fmt: str, *, use_llm: bool = False) -> DiffReport:
    """Parse two contracts, run the deterministic diff, optionally add LLM advisory."""
    fmt = normalize_format(fmt)

    try:
        if fmt == FORMAT_OPENAPI:
            old_doc = parse_openapi(old_raw)
            new_doc = parse_openapi(new_raw)
            findings = diff_openapi(old_doc, new_doc)
        elif fmt == FORMAT_GRAPHQL:
            old_schema = parse_graphql(old_raw)
            new_schema = parse_graphql(new_raw)
            findings = diff_graphql(old_schema, new_schema)
        elif fmt == FORMAT_JSON_SCHEMA:
            old_root = parse_json_schema(old_raw)
            new_root = parse_json_schema(new_raw)
            findings = diff_json_schema(old_root, new_root)
        else:  # pragma: no cover - guarded by normalize_format
            raise DiffError(f"Unsupported format: {fmt}")
    except (OpenApiParseError, GraphqlParseError, JsonSchemaParseError) as exc:
        raise DiffError(str(exc)) from exc

    llm_enabled = False
    if use_llm:
        advisory = assess(findings, fmt)
        if advisory:
            findings = [*findings, *advisory]
            llm_enabled = True

    return _build_report(fmt, findings, llm_enabled)


def _build_report(fmt: str, findings: list[Finding], llm_enabled: bool) -> DiffReport:
    counts = {sev: 0 for sev in SEVERITY_ORDER}
    breaking_count = 0
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        if f.breaking:
            breaking_count += 1

    breaking = breaking_count > 0
    total = len(findings)

    if total == 0:
        summary = "No changes detected — the contracts are equivalent."
    else:
        sev_parts = [f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts.get(s, 0)]
        summary = (
            f"Detected {total} change(s); {breaking_count} breaking "
            f"({', '.join(sev_parts)})."
        )

    return DiffReport(
        format=fmt,
        breaking=breaking,
        total_changes=total,
        breaking_count=breaking_count,
        counts=counts,
        findings=findings,
        summary=summary,
        llm_enabled=llm_enabled,
    )