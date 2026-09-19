from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import urljoin

import yaml

VALID_METHODS = {"get", "head", "options", "post", "put", "patch", "delete"}


def parse_spec_content(content: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(content, dict):
        spec = copy.deepcopy(content)
    else:
        text = content.strip()
        if not text:
            raise ValueError("Empty specification")
        try:
            spec = json.loads(text)
        except json.JSONDecodeError:
            try:
                spec = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise ValueError(f"Invalid JSON/YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise TypeError("Specification must be an object")
    if "openapi" not in spec and "swagger" not in spec:
        raise ValueError("Missing 'openapi' or 'swagger' version field")
    if "paths" not in spec or not isinstance(spec["paths"], dict):
        raise ValueError("Missing 'paths' object")
    return spec


def resolve_local_ref(root: dict[str, Any], value: Any, seen: set[str] | None = None) -> Any:
    """Resolve local JSON pointers without fetching external documents."""
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    ref = value.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    visited = set(seen or ())
    if ref in visited:
        return value
    visited.add(ref)
    current: Any = root
    try:
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            current = current[token]
    except (KeyError, TypeError):
        return value
    resolved = copy.deepcopy(current)
    if isinstance(resolved, dict) and "$ref" in resolved:
        return resolve_local_ref(root, resolved, visited)
    siblings = {k: copy.deepcopy(v) for k, v in value.items() if k != "$ref"}
    if isinstance(resolved, dict):
        resolved.update(siblings)
    return resolved


def dereference_local(root: dict[str, Any], value: Any, seen: set[str] | None = None) -> Any:
    if isinstance(value, dict):
        if "$ref" in value:
            resolved = resolve_local_ref(root, value, seen)
            if resolved is value or resolved == value:
                return copy.deepcopy(value)
            ref = value.get("$ref")
            visited = set(seen or ())
            if isinstance(ref, str):
                visited.add(ref)
            return dereference_local(root, resolved, visited)
        return {key: dereference_local(root, item, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [dereference_local(root, item, seen) for item in value]
    return copy.deepcopy(value)


def _server_url(spec: dict[str, Any]) -> str:
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        url = str(servers[0].get("url") or "")
        for name, definition in (servers[0].get("variables") or {}).items():
            default = definition.get("default") if isinstance(definition, dict) else None
            if default is not None:
                url = url.replace("{" + name + "}", str(default))
        return url.rstrip("/")
    if spec.get("swagger"):
        scheme = (spec.get("schemes") or ["https"])[0]
        host = spec.get("host") or ""
        base_path = spec.get("basePath") or ""
        return f"{scheme}://{host}{base_path}".rstrip("/") if host else ""
    return ""


def response_schema(spec: dict[str, Any], responses: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[tuple[str, Any]] = []
    for status, response in responses.items():
        if str(status).startswith("2"):
            candidates.append((str(status), resolve_local_ref(spec, response)))
    candidates.sort(key=lambda item: item[0])
    for _, response in candidates:
        if not isinstance(response, dict):
            continue
        if isinstance(response.get("schema"), dict):
            return dereference_local(spec, response["schema"])
        content = response.get("content") or {}
        if isinstance(content, dict):
            preferred = content.get("application/json")
            media = preferred or next((v for v in content.values() if isinstance(v, dict)), None)
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return dereference_local(spec, media["schema"])
    return None


def extract_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    base = _server_url(spec)
    global_security = spec.get("security")
    for path, raw_path_item in (spec.get("paths") or {}).items():
        path_item = resolve_local_ref(spec, raw_path_item)
        if not isinstance(path_item, dict):
            continue
        path_parameters = [dereference_local(spec, p) for p in (path_item.get("parameters") or [])]
        for method, raw_operation in path_item.items():
            if method.lower() not in VALID_METHODS:
                continue
            operation = resolve_local_ref(spec, raw_operation)
            if not isinstance(operation, dict):
                continue
            operation_parameters = [dereference_local(spec, p) for p in (operation.get("parameters") or [])]
            merged: dict[tuple[str, str], dict[str, Any]] = {}
            for parameter in path_parameters + operation_parameters:
                if isinstance(parameter, dict):
                    merged[(str(parameter.get("name")), str(parameter.get("in")))] = parameter
            request_body = dereference_local(spec, operation.get("requestBody") or {})
            responses = {
                str(code): resolve_local_ref(spec, response)
                for code, response in (operation.get("responses") or {}).items()
            }
            generated_id = f"{method.lower()}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '') or 'root'}"
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId") or generated_id,
                    "operation_id_declared": bool(operation.get("operationId")),
                    "summary": operation.get("summary") or "",
                    "description": operation.get("description") or "",
                    "parameters": list(merged.values()),
                    "requestBody": request_body if isinstance(request_body, dict) else {},
                    "responses": responses,
                    "response_schema": response_schema(spec, responses),
                    "tags": operation.get("tags") or [],
                    "security": operation.get("security", global_security),
                    "deprecated": bool(operation.get("deprecated")),
                    "base_url": base,
                    "source_url": urljoin(base + "/", path.lstrip("/")) if base else "",
                }
            )
    return endpoints
