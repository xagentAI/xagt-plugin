from __future__ import annotations

from collections import Counter
from typing import Any

AMBIGUOUS_PARAMS = {"q", "data", "info", "param", "arg", "x", "foo", "value"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def analyze_endpoints(endpoints: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    analyses: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    operation_counts = Counter(ep.get("operation_id") for ep in endpoints)

    def add(severity: str, code: str, message: str, endpoint: dict[str, Any], repair: str) -> None:
        issues.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "endpoint": f"{endpoint['method']} {endpoint['path']}",
                "operation_id": endpoint["operation_id"],
                "suggested_repair": repair,
            }
        )

    for endpoint in endpoints:
        description = (endpoint.get("description") or endpoint.get("summary") or "").strip()
        parameters = endpoint.get("parameters") or []
        responses = endpoint.get("responses") or {}
        operation_id = endpoint.get("operation_id") or ""

        documentation = 100
        if not description:
            documentation -= 45
            add("medium", "MISSING_DESCRIPTION", "Operation has no agent-readable purpose.", endpoint, "Add a concrete operation description.")
        elif len(description) < 20:
            documentation -= 15
            add("low", "THIN_DESCRIPTION", "Operation description is too short to guide an agent.", endpoint, "Describe outcome, limits, and side effects.")
        missing_parameter_docs = sum(1 for parameter in parameters if not parameter.get("description"))
        if missing_parameter_docs:
            documentation -= min(35, missing_parameter_docs * 10)
            add("medium", "PARAMETER_DESCRIPTION_MISSING", f"{missing_parameter_docs} parameter(s) lack descriptions.", endpoint, "Document the meaning and accepted values of every parameter.")

        schema_quality = 100
        if not endpoint.get("response_schema"):
            schema_quality -= 50
            add("high", "SUCCESS_SCHEMA_MISSING", "No JSON schema is declared for a successful response.", endpoint, "Add a 2xx response schema or infer one from bounded observations.")
        missing_parameter_schemas = sum(1 for parameter in parameters if not parameter.get("schema") and not parameter.get("type"))
        if missing_parameter_schemas:
            schema_quality -= min(30, missing_parameter_schemas * 10)
            add("medium", "PARAMETER_SCHEMA_MISSING", f"{missing_parameter_schemas} parameter(s) lack schemas.", endpoint, "Declare parameter types and constraints.")
        if endpoint.get("requestBody") and not (endpoint["requestBody"].get("content") or endpoint["requestBody"].get("schema")):
            schema_quality -= 20
            add("medium", "REQUEST_SCHEMA_MISSING", "Request body has no machine-readable schema.", endpoint, "Declare the request body schema.")

        error_quality = 100
        status_codes = {str(code) for code in responses}
        if not any(code.startswith("4") for code in status_codes):
            error_quality -= 35
            add("medium", "CLIENT_ERROR_UNDOCUMENTED", "No 4xx response is documented.", endpoint, "Document invalid input and authentication failures.")
        if not any(code.startswith("5") or code == "default" for code in status_codes):
            error_quality -= 15
            add("low", "SERVER_ERROR_UNDOCUMENTED", "No 5xx/default response is documented.", endpoint, "Document retryable upstream failures.")

        usability = 100
        if not endpoint.get("operation_id_declared"):
            usability -= 15
            add("medium", "OPERATION_ID_GENERATED", "The source contract does not declare operationId.", endpoint, "Declare a stable, unique operationId.")
        if operation_counts[operation_id] > 1:
            usability -= 30
            add("high", "DUPLICATE_OPERATION_ID", f"operationId '{operation_id}' is not unique.", endpoint, "Assign a unique tool-facing operationId.")
        ambiguous = next((parameter.get("name") for parameter in parameters if str(parameter.get("name", "")).lower() in AMBIGUOUS_PARAMS), None)
        if ambiguous:
            usability -= 10
            add("low", "AMBIGUOUS_PARAMETER", f"Parameter '{ambiguous}' is ambiguous for autonomous use.", endpoint, "Use a domain-specific parameter name.")
        if endpoint.get("deprecated"):
            usability -= 20
            add("medium", "DEPRECATED_OPERATION", "The operation is marked deprecated.", endpoint, "Prefer a supported replacement before generating a tool.")
        if endpoint["method"] not in SAFE_METHODS:
            usability -= 10
            add("medium", "SIDE_EFFECT_CONFIRMATION_REQUIRED", f"{endpoint['method']} may change external state.", endpoint, "Require explicit confirmation and keep automatic execution disabled.")
        if endpoint.get("security") and not description:
            usability -= 5

        analyses.append(
            {
                "method": endpoint["method"],
                "path": endpoint["path"],
                "operation_id": operation_id,
                "description_quality": max(0, documentation),
                "schema_quality": max(0, schema_quality),
                "error_documentation": max(0, error_quality),
                "agent_usability": max(0, usability),
                "safe_to_auto_test": endpoint["method"] in SAFE_METHODS,
                "requires_authentication": bool(endpoint.get("security")),
                "deprecated": bool(endpoint.get("deprecated")),
            }
        )
    return analyses, issues
