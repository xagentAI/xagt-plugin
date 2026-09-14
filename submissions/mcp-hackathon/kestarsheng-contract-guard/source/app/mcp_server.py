# -*- coding: utf-8 -*-
"""FastMCP server exposing Contract Guard as reusable MCP tools for AI agents.

Tools:
- check_breaking_changes:  compare two contracts, return structured breaking-change report
- list_supported_formats:  list accepted contract formats (instant, free)
- explain_change_type:     explain what a change_type means (instant, free)

Agent usage guidance:
1. Call check_breaking_changes before merging an API change, publishing a new
   version, or upgrading a dependency that ships an OpenAPI/GraphQL/JSON Schema.
2. The core diff is deterministic and reproducible — identical inputs always
   yield identical findings. Set use_llm=true only when you want an advisory
   impact assessment appended (requires a server-side key).
3. Treat findings with breaking=true as merge blockers; severity=critical means
   existing consumers will fail at runtime.
"""
from __future__ import annotations

import json

from fastmcp import FastMCP

from .config import PROJECT_SLUG, get_settings
from .diff_core import DiffError, detect_changes, normalize_format
from .migration import suggest_migration as _suggest_migration
from .models import SUPPORTED_FORMATS
from .semver import generate_changelog as _generate_changelog
from .semver import suggest_version_bump as _suggest_version_bump

mcp = FastMCP(
    PROJECT_SLUG,
    instructions=(
        "Contract Guard: deterministic API breaking-change detector for agents. "
        "Call check_breaking_changes(old_spec, new_spec, format) before merging "
        "an API change, publishing a new version, or upgrading a dependency. "
        "The diff is 100% deterministic and reproducible (no LLM needed for the "
        "core result). Findings with breaking=true are merge blockers; "
        "severity=critical means existing consumers will fail at runtime. "
        "Use list_supported_formats to discover accepted formats, and "
        "explain_change_type to interpret a change_type you don't recognize. "
        "Use suggest_version_bump to determine the SemVer increment level. "
        "Use generate_changelog to produce a markdown changelog for release notes. "
        "Use suggest_migration to get concrete advice on restoring compatibility."
    ),
)

_CHANGE_TYPE_DOCS = {
    "endpoint_removed": ("An entire endpoint (path + method) was removed.", "critical", True),
    "method_removed": ("An HTTP method on an existing path was removed.", "critical", True),
    "endpoint_added": ("A new endpoint was added.", "info", False),
    "parameter_removed": ("A request parameter was removed.", "major", True),
    "parameter_required_raised": ("A parameter changed from optional to required.", "major", True),
    "required_parameter_added": ("A new required parameter was added.", "critical", True),
    "request_body_removed": ("A request body was removed.", "major", True),
    "request_body_added_required": ("A required request body was added.", "major", True),
    "response_status_removed": ("A response status code was removed.", "critical", True),
    "schema_removed": ("A named schema/component was removed.", "critical", True),
    "schema_type_changed": ("A field's type changed.", "critical", True),
    "field_removed": ("An object field was removed.", "critical", True),
    "required_field_added": ("A field became required.", "critical", True),
    "enum_value_removed": ("An enum value was removed.", "critical", True),
    "constraint_tightened": ("A validation constraint was tightened (rejects previously-valid values).", "major", True),
    "type_removed": ("A GraphQL type was removed.", "critical", True),
    "type_kind_changed": ("A GraphQL type changed kind (object/enum/union/...).", "critical", True),
    "field_type_changed": ("A GraphQL field's type changed.", "critical", True),
    "field_type_became_non_null": ("A GraphQL field changed from nullable to non-null.", "critical", True),
    "input_field_removed": ("A GraphQL input field was removed.", "critical", True),
    "input_field_added_required": ("A required GraphQL input field was added.", "critical", True),
    "argument_removed": ("A GraphQL argument was removed.", "critical", True),
    "argument_added_required": ("A required GraphQL argument was added.", "critical", True),
    "argument_type_changed": ("A GraphQL argument's type changed in a breaking way.", "critical", True),
    "union_member_removed": ("A union member type was removed.", "critical", True),
    "property_removed": ("A JSON Schema property was removed.", "critical", True),
    "type_changed": ("A JSON Schema type changed.", "critical", True),
    "const_changed": ("A JSON Schema const value changed.", "critical", True),
    "required_property_added": ("A JSON Schema property became required.", "critical", True),
    "impact_assessment": ("LLM-generated consumer-impact assessment (advisory).", "info", False),
    "operation_deprecated": ("An OpenAPI operation was marked deprecated.", "minor", False),
    "operation_undeprecated": ("An OpenAPI operation's deprecation was removed.", "info", False),
    "content_type_removed": ("A content type was removed from a request body or response.", "major", True),
    "content_type_added": ("A content type was added to a request body or response.", "info", False),
    "directive_removed": ("A GraphQL directive was removed from the schema.", "major", True),
    "directive_added": ("A GraphQL directive was added to the schema.", "info", False),
    "field_deprecated": ("A GraphQL field was marked @deprecated.", "minor", False),
    "field_undeprecated": ("A GraphQL field's @deprecated was removed.", "info", False),
    "prefix_items_removed": ("JSON Schema prefixItems were shortened (tuple semantics changed).", "critical", True),
    "prefix_item_type_changed": ("A JSON Schema prefixItems entry type changed.", "critical", True),
    "contains_removed": ("A JSON Schema contains constraint was removed.", "major", True),
    "dependent_required_added": ("A JSON Schema dependentRequired dependency was added.", "major", True),
}


@mcp.tool()
def check_breaking_changes(
    old_spec: str,
    new_spec: str,
    format: str = "openapi",
    use_llm: bool = False,
) -> str:
    """Detect breaking changes between two API contracts (deterministic, reproducible).

    Use this before merging an API change, publishing a new version, or upgrading
    a dependency that ships a contract. The core diff is 100% deterministic —
    identical inputs always yield identical findings, with no LLM in the loop.

    Args:
        old_spec: the previous contract text (OpenAPI JSON/YAML, GraphQL SDL,
            or JSON Schema JSON).
        new_spec: the new contract text to compare against old_spec.
        format: "openapi" | "graphql" | "json-schema" (aliases accepted:
            swagger/oas/gql/jsonschema/json).
        use_llm: if true, append an advisory impact assessment (requires a
            server-side LLM key; ignored if none configured).

    Returns:
        JSON string: {schema_version, format, breaking, total_changes,
        breaking_count, counts, summary, llm_enabled, findings[]}. Each finding
        has change_type, breaking, severity, location, summary, previous,
        current, suggestion, source ("confirmed"|"advisory"), id.
    """
    settings = get_settings()
    try:
        report = detect_changes(
            old_spec, new_spec, format,
            use_llm=use_llm and bool(settings.llm_api_key),
        )
    except DiffError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "report": report.as_dict()}, ensure_ascii=False)


@mcp.tool()
def list_supported_formats() -> str:
    """List the contract formats Contract Guard can diff (instant, free).

    Returns:
        JSON string with format ids, labels and accepted input encodings.
    """
    return json.dumps({
        "ok": True,
        "formats": [
            {"id": "openapi", "label": "OpenAPI 3.x", "accepts": "JSON or YAML"},
            {"id": "graphql", "label": "GraphQL SDL", "accepts": "schema definition language"},
            {"id": "json-schema", "label": "JSON Schema", "accepts": "JSON"},
        ],
    }, ensure_ascii=False)


@mcp.tool()
def explain_change_type(change_type: str) -> str:
    """Explain what a change_type means and whether it is breaking (instant, free).

    Use this to interpret a finding's change_type returned by check_breaking_changes.

    Args:
        change_type: the change_type string from a finding.

    Returns:
        JSON string with description, default severity and breaking flag.
    """
    entry = _CHANGE_TYPE_DOCS.get(change_type)
    if entry is None:
        return json.dumps({
            "ok": False,
            "error": f"Unknown change_type '{change_type}'",
            "known": sorted(_CHANGE_TYPE_DOCS.keys()),
        }, ensure_ascii=False)
    description, severity, breaking = entry
    return json.dumps({
        "ok": True,
        "change_type": change_type,
        "description": description,
        "default_severity": severity,
        "breaking": breaking,
    }, ensure_ascii=False)


@mcp.tool()
def suggest_version_bump(
    old_spec: str,
    new_spec: str,
    format: str = "openapi",
    current_version: str = "",
) -> str:
    """Suggest the SemVer bump level (major/minor/patch) for a contract change.

    Analyzes the diff and returns which version segment should be incremented
    based on breaking vs non-breaking changes.

    Args:
        old_spec: the previous contract text.
        new_spec: the new contract text.
        format: "openapi" | "graphql" | "json-schema".
        current_version: optional current version (e.g. "1.2.3") to compute the next version.

    Returns:
        JSON string with bump level, reason, and suggested next version.
    """
    settings = get_settings()
    try:
        report = detect_changes(old_spec, new_spec, format)
    except DiffError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    result = _suggest_version_bump(report, current_version)
    return json.dumps({"ok": True, **result}, ensure_ascii=False)


@mcp.tool()
def generate_changelog(
    old_spec: str,
    new_spec: str,
    format: str = "openapi",
    old_version: str = "",
    new_version: str = "",
) -> str:
    """Generate a markdown changelog from a contract diff.

    Groups findings by severity (critical/major/minor/info) and formats them
    as a markdown document suitable for release notes.

    Args:
        old_spec: the previous contract text.
        new_spec: the new contract text.
        format: "openapi" | "graphql" | "json-schema".
        old_version: optional previous version label.
        new_version: optional new version label.

    Returns:
        JSON string with the markdown changelog.
    """
    try:
        report = detect_changes(old_spec, new_spec, format)
    except DiffError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    changelog = _generate_changelog(report, old_version, new_version)
    return json.dumps({"ok": True, "changelog": changelog}, ensure_ascii=False)


@mcp.tool()
def suggest_migration(
    old_spec: str,
    new_spec: str,
    format: str = "openapi",
) -> str:
    """Generate compatibility migration suggestions for breaking changes.

    For each breaking change found, returns a concrete suggestion on how to
    modify the new spec to restore backward compatibility.

    Args:
        old_spec: the previous contract text.
        new_spec: the new contract text.
        format: "openapi" | "graphql" | "json-schema".

    Returns:
        JSON string with migration suggestions for each breaking change.
    """
    try:
        report = detect_changes(old_spec, new_spec, format)
    except DiffError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    result = _suggest_migration(report)
    return json.dumps({"ok": True, **result}, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()