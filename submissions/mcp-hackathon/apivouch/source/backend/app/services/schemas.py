from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def infer_schema(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        if not value:
            return {"type": "array", "items": {}}
        return {"type": "array", "items": merge_schemas([infer_schema(item) for item in value])}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {str(key): infer_schema(item) for key, item in value.items()},
            "required": sorted(str(key) for key in value),
            "additionalProperties": True,
        }
    return {}


def _signature(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if schema_type == "object":
        return "object"
    if schema_type == "array":
        return "array"
    return str(schema_type)


def merge_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    nonempty = [copy.deepcopy(schema) for schema in schemas if schema]
    if not nonempty:
        return {}
    signatures = {_signature(schema) for schema in nonempty}
    if len(signatures) > 1:
        unique: list[dict[str, Any]] = []
        for schema in nonempty:
            if schema not in unique:
                unique.append(schema)
        return {"oneOf": unique}
    kind = next(iter(signatures))
    if kind == "object":
        all_keys = sorted({key for schema in nonempty for key in (schema.get("properties") or {})})
        properties: dict[str, Any] = {}
        required_sets = [set(schema.get("required") or []) for schema in nonempty]
        for key in all_keys:
            child_schemas = [schema["properties"][key] for schema in nonempty if key in (schema.get("properties") or {})]
            properties[key] = merge_schemas(child_schemas)
        required = sorted(set.intersection(*required_sets)) if required_sets else []
        return {"type": "object", "properties": properties, "required": required, "additionalProperties": True}
    if kind == "array":
        return {"type": "array", "items": merge_schemas([schema.get("items") or {} for schema in nonempty])}
    return nonempty[0]


def infer_schema_from_samples(samples: list[Any]) -> dict[str, Any]:
    return merge_schemas([infer_schema(sample) for sample in samples])


def validate_instance(instance: Any, schema: dict[str, Any] | None) -> list[str]:
    if not schema:
        return []
    try:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    except (SchemaError, TypeError, ValueError) as exc:
        return [f"Invalid declared schema: {exc}"]
    messages: list[str] = []
    for error in errors[:10]:
        location = ".".join(str(part) for part in error.path) or "$"
        messages.append(f"{location}: {error.message}")
    return messages


def shape_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: shape_signature(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [shape_signature(value[0])] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"
