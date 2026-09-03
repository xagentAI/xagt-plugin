from typing import Any
import yaml

VALID_METHODS = {"get", "head", "options", "post", "put", "patch", "delete"}


def parse_spec_content(content: str | dict) -> dict[str, Any]:
    if isinstance(content, dict):
        spec = content
    else:
        text = content.strip()
        if not text:
            raise ValueError("Empty spec")
        try:
            import json
            spec = json.loads(text)
        except Exception:
            try:
                spec = yaml.safe_load(text)
            except Exception as e:
                raise ValueError(f"Invalid JSON/YAML: {e}")
    if not isinstance(spec, dict):
        raise ValueError("Spec must be an object")
    if "openapi" not in spec and "swagger" not in spec:
        raise ValueError("Missing 'openapi' or 'swagger' version field")
    if "paths" not in spec or not isinstance(spec["paths"], dict):
        raise ValueError("Missing 'paths' object")
    return spec


def extract_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    servers = spec.get("servers", [])
    base = servers[0].get("url", "").rstrip("/") if servers else ""
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in VALID_METHODS or not isinstance(op, dict):
                continue
            params = op.get("parameters", []) or []
            req_body = op.get("requestBody", {}) or {}
            responses = op.get("responses", {}) or {}
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "operation_id": op.get("operationId") or f"{method.lower()}_{path.strip('/').replace('/', '_').replace('{','').replace('}','') or 'root'}",
                "summary": op.get("summary", "") or "",
                "description": op.get("description", "") or "",
                "parameters": params,
                "requestBody": req_body,
                "responses": responses,
                "tags": op.get("tags", []),
                "base_url": base,
            })
    return endpoints
