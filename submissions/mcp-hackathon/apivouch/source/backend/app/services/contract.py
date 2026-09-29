from __future__ import annotations

import copy
import re
from typing import Any

from app.services.importer import VALID_METHODS, extract_endpoints
from app.services.schemas import infer_schema_from_samples


def _operation_id(method: str, path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/{}")).strip("_") or "root"
    return f"{method.lower()}_{cleaned}"[:64]


def _successful_samples(test: dict[str, Any] | None) -> list[Any]:
    if not test:
        return []
    return [
        observation.get("sample_data")
        for observation in test.get("observations") or []
        if observation.get("success") and isinstance(observation.get("sample_data"), (dict, list))
    ]


def build_agent_contract(
    source_spec: dict[str, Any], test_results: list[dict[str, Any]] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create an evidence-bound contract; never modify or claim to repair the upstream API."""
    contract = copy.deepcopy(source_spec)
    swagger_2 = bool(contract.get("swagger") and not contract.get("openapi"))
    contract.setdefault("info", {})
    contract["info"]["title"] = f"{contract['info'].get('title') or 'Imported API'} — Agent Contract"
    contract["info"]["version"] = str(contract["info"].get("version") or "1.0.0")
    contract["info"]["description"] = "Generated deterministically by APIVouch. Generated fields are marked with x-apivouch-generated."
    contract["x-apivouch"] = {"generator": "apivouch", "version": "1.0.0", "evidence": "declared contract plus bounded live observations"}
    if swagger_2:
        schemas = contract.setdefault("definitions", {})
        error_ref = "#/definitions/APIVouchError"
    else:
        components = contract.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        error_ref = "#/components/schemas/APIVouchError"
    schemas["APIVouchError"] = {
        "type": "object",
        "required": ["code", "message", "retryable"],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "retryable": {"type": "boolean"},
        },
        "additionalProperties": False,
    }

    tests_by_operation = {test.get("operation_id"): test for test in (test_results or [])}
    changes: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in VALID_METHODS or not isinstance(operation, dict):
                continue
            old_id = operation.get("operationId")
            candidate = old_id or _operation_id(method, path)
            base_candidate = candidate
            suffix = 2
            while candidate in used_ids:
                candidate = f"{base_candidate}_{suffix}"
                suffix += 1
            used_ids.add(candidate)
            if candidate != old_id:
                operation["operationId"] = candidate
                changes.append({"kind": "operation_id", "target": f"{method.upper()} {path}", "before": old_id, "after": candidate, "basis": "deterministic"})
            if not (operation.get("description") or operation.get("summary")):
                operation["description"] = f"Call {method.upper()} {path}. Review parameter descriptions and upstream limits before autonomous use."
                operation["x-apivouch-generated"] = True
                changes.append({"kind": "description", "target": candidate, "basis": "deterministic-placeholder"})
            parameters = operation.get("parameters") or []
            for parameter in parameters:
                if not isinstance(parameter, dict) or "$ref" in parameter:
                    continue
                if not parameter.get("description"):
                    parameter["description"] = f"Value for {parameter.get('name') or 'this parameter'}. Confirm semantics with the API owner."
                    parameter["x-apivouch-generated"] = True
                    changes.append({"kind": "parameter_description", "target": f"{candidate}.{parameter.get('name')}", "basis": "deterministic-placeholder"})
                if not parameter.get("schema") and not parameter.get("type"):
                    parameter["schema"] = {"type": "string"}
                    parameter["x-apivouch-generated"] = True
                    changes.append({"kind": "parameter_schema", "target": f"{candidate}.{parameter.get('name')}", "basis": "conservative-default"})

            responses = operation.setdefault("responses", {})
            has_success_schema = False
            for code, response in responses.items():
                if str(code).startswith("2") and isinstance(response, dict):
                    content = response.get("content") or {}
                    has_success_schema = bool(response.get("schema")) or any(isinstance(media, dict) and media.get("schema") for media in content.values())
                    if has_success_schema:
                        break
            source_endpoints = extract_endpoints(source_spec)
            source_endpoint = next((item for item in source_endpoints if item["method"] == method.upper() and item["path"] == path), None)
            test = tests_by_operation.get(source_endpoint.get("operation_id") if source_endpoint else candidate)
            samples = _successful_samples(test)
            if not has_success_schema and samples:
                inferred = infer_schema_from_samples(samples)
                success_code = next((str(code) for code in responses if str(code).startswith("2")), "200")
                response = responses.setdefault(success_code, {"description": "Successful response"})
                response["content"] = {"application/json": {"schema": inferred}}
                response["x-apivouch-generated"] = True
                changes.append({"kind": "response_schema", "target": candidate, "basis": f"{len(samples)} bounded live observation(s)"})
            for code, description in (("400", "Invalid tool arguments"), ("429", "Rate limit reached"), ("502", "Upstream call failed")):
                if code not in responses:
                    responses[code] = {"description": description, "x-apivouch-generated": True}
                    if swagger_2:
                        responses[code]["schema"] = {"$ref": error_ref}
                    else:
                        responses[code]["content"] = {"application/json": {"schema": {"$ref": error_ref}}}
                    changes.append({"kind": "error_contract", "target": f"{candidate}.{code}", "basis": "adapter-envelope"})
            operation["x-apivouch-safety"] = {
                "readOnly": method.upper() in {"GET", "HEAD", "OPTIONS"},
                "automaticExecution": method.upper() in {"GET", "HEAD", "OPTIONS"},
                "confirmationRequired": method.upper() not in {"GET", "HEAD", "OPTIONS"},
            }
    return contract, changes
