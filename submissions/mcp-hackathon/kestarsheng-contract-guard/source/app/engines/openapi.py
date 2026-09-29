# -*- coding: utf-8 -*-
"""Deterministic OpenAPI 3.x breaking-change diff engine.

Compares two OpenAPI documents and emits structured findings covering the
standard breaking-change rule set (removed endpoints/parameters/fields, type
changes, tightened constraints, removed enum values, added required members).

This engine is 100% deterministic and makes no LLM calls.
"""
from __future__ import annotations

from typing import Any

import yaml

from ..models import FORMAT_OPENAPI
from .base import make_finding, render

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class SpecParseError(ValueError):
    """Raised when a contract document cannot be parsed or is unsupported."""


def parse_openapi(text: str) -> dict:
    """Parse an OpenAPI 3.x document from either JSON or YAML."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecParseError(f"Cannot parse document (not JSON/YAML): {exc}") from exc

    if not isinstance(doc, dict):
        raise SpecParseError("OpenAPI document root must be an object")

    if "openapi" in doc and str(doc.get("openapi", "")).startswith("3."):
        return doc

    if "swagger" in doc:
        raise SpecParseError("Detected Swagger/OpenAPI 2.0; only OpenAPI 3.x is supported")
    raise SpecParseError("Not a valid OpenAPI 3.x document (missing 'openapi: 3.x')")


def _deref(ref: str, doc: dict) -> dict | None:
    if not isinstance(doc, dict) or not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node: Any = doc
    for part in ref.lstrip("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, dict) else None


def _resolve(schema, doc: dict):
    if isinstance(schema, dict) and "$ref" in schema:
        target = _deref(schema["$ref"], doc)
        if target is not None:
            merged = dict(target)
            merged.update({k: v for k, v in schema.items() if k != "$ref"})
            return merged
    return schema


def diff_openapi(old_doc: dict, new_doc: dict) -> list:
    """Diff two OpenAPI 3.x documents, returning confirmed findings."""
    findings: list = []
    old_paths = old_doc.get("paths") or {}
    new_paths = new_doc.get("paths") or {}
    _diff_paths(old_paths, new_paths, old_doc, new_doc, findings)
    _diff_components(old_doc, new_doc, findings)
    return findings


# --------------------------------------------------------------------------- #
# Paths / operations
# --------------------------------------------------------------------------- #
def _diff_paths(old_paths: dict, new_paths: dict, old_doc: dict, new_doc: dict, out: list) -> None:
    for path, old_item in (old_paths or {}).items():
        new_item = (new_paths or {}).get(path)
        if new_item is None:
            for method in _HTTP_METHODS:
                if method in old_item:
                    out.append(make_finding(
                        "endpoint_removed", True, "critical",
                        f"{method.upper()} {path}",
                        f"Endpoint {method.upper()} {path} was removed",
                        suggestion="Keep the endpoint or provide a deprecation window",
                        fmt=FORMAT_OPENAPI,
                    ))
            continue

        for method in _HTTP_METHODS:
            old_op = old_item.get(method)
            new_op = new_item.get(method)
            if old_op and not new_op:
                out.append(make_finding(
                    "method_removed", True, "critical",
                    f"{method.upper()} {path}",
                    f"Method {method.upper()} on path {path} was removed",
                    suggestion="Keep the method or provide a deprecation window",
                    fmt=FORMAT_OPENAPI,
                ))
            elif new_op and not old_op:
                out.append(make_finding(
                    "endpoint_added", False, "info",
                    f"{method.upper()} {path}",
                    f"Added endpoint {method.upper()} {path}",
                    fmt=FORMAT_OPENAPI,
                ))
            elif old_op and new_op:
                _diff_operation(path, method, old_item, new_item, old_op, new_op,
                                old_doc, new_doc, out)

    for path, new_item in (new_paths or {}).items():
        if path in (old_paths or {}):
            continue
        for method in _HTTP_METHODS:
            if method in new_item:
                out.append(make_finding(
                    "endpoint_added", False, "info",
                    f"{method.upper()} {path}",
                    f"Added endpoint {method.upper()} {path}",
                    fmt=FORMAT_OPENAPI,
                ))


def _diff_operation(path, method, old_item, new_item, old_op, new_op,
                    old_doc, new_doc, out) -> None:
    loc = f"{method.upper()} {path}"

    _diff_deprecated(old_op, new_op, loc, out)

    old_params = _collect_parameters(old_item, old_op, old_doc)
    new_params = _collect_parameters(new_item, new_op, new_doc)
    _diff_parameters(old_params, new_params, loc, old_doc, new_doc, out)

    _diff_request_body(old_op.get("requestBody"), new_op.get("requestBody"),
                       loc, old_doc, new_doc, out)

    _diff_responses(old_op.get("responses") or {}, new_op.get("responses") or {},
                    loc, old_doc, new_doc, out)


def _diff_deprecated(old_op: dict, new_op: dict, loc: str, out: list) -> None:
    old_dep = bool(old_op.get("deprecated", False))
    new_dep = bool(new_op.get("deprecated", False))
    if not old_dep and new_dep:
        out.append(make_finding(
            "operation_deprecated", False, "minor", loc,
            f"Operation {loc} was marked deprecated",
            suggestion="Communicate the deprecation timeline to consumers",
            fmt=FORMAT_OPENAPI,
        ))
    elif old_dep and not new_dep:
        out.append(make_finding(
            "operation_undeprecated", False, "info", loc,
            f"Operation {loc} deprecation was removed",
            fmt=FORMAT_OPENAPI,
        ))


def _collect_parameters(path_item: dict, op: dict, doc: dict) -> dict:
    merged: dict = {}
    for p in [*((path_item or {}).get("parameters") or []), *((op or {}).get("parameters") or [])]:
        resolved = _resolve(p, doc) if isinstance(p, dict) else p
        if not isinstance(resolved, dict):
            continue
        key = (resolved.get("in", "query"), resolved.get("name", ""))
        merged[key] = resolved
    return merged


def _diff_parameters(old_params: dict, new_params: dict, loc: str,
                     old_doc: dict, new_doc: dict, out: list) -> None:
    for key, old_p in old_params.items():
        pin, pname = key
        where = f"{loc} -> parameter {pin}:{pname}"
        new_p = new_params.get(key)
        if new_p is None:
            out.append(make_finding(
                "parameter_removed", True, "major", where,
                f"Parameter {pin}:{pname} was removed",
                suggestion="Clients may still send it; keep and mark deprecated",
                fmt=FORMAT_OPENAPI,
            ))
            continue

        if bool(new_p.get("required", False)) and not bool(old_p.get("required", False)):
            out.append(make_finding(
                "parameter_required_raised", True, "major", where,
                f"Parameter {pin}:{pname} became required",
                previous="required: false", current="required: true",
                suggestion="Keep it optional or default it",
                fmt=FORMAT_OPENAPI,
            ))

        _diff_schema(old_p.get("schema"), new_p.get("schema"), where,
                     old_doc, new_doc, out, set())

    for key, new_p in new_params.items():
        if key in old_params:
            continue
        pin, pname = key
        if new_p.get("required", False):
            out.append(make_finding(
                "required_parameter_added", True, "critical",
                f"{loc} -> parameter {pin}:{pname}",
                f"Added required parameter {pin}:{pname}",
                suggestion="Make it optional with a default to avoid breaking callers",
                fmt=FORMAT_OPENAPI,
            ))
        else:
            out.append(make_finding(
                "optional_parameter_added", False, "info",
                f"{loc} -> parameter {pin}:{pname}",
                f"Added optional parameter {pin}:{pname}",
                fmt=FORMAT_OPENAPI,
            ))


def _media_schema(obj: dict) -> dict | None:
    content = (obj or {}).get("content")
    if not isinstance(content, dict):
        return None
    for media in ("application/json", "application/x-www-form-urlencoded", "*/*"):
        if media in content:
            return content[media].get("schema")
    first = next(iter(content.values()), None)
    return first.get("schema") if first else None


def _media_types(obj: dict) -> set:
    content = (obj or {}).get("content")
    if not isinstance(content, dict):
        return set()
    return set(content.keys())


def _diff_content_types(old_obj, new_obj, loc: str, out: list) -> None:
    old_types = _media_types(old_obj)
    new_types = _media_types(new_obj)
    for mt in sorted(old_types - new_types):
        out.append(make_finding(
            "content_type_removed", True, "major", loc,
            f"Content type {render(mt)} was removed",
            previous=mt, current=None,
            suggestion="Clients sending this content type will be rejected",
            fmt=FORMAT_OPENAPI,
        ))
    for mt in sorted(new_types - old_types):
        out.append(make_finding(
            "content_type_added", False, "info", loc,
            f"Content type {render(mt)} was added",
            fmt=FORMAT_OPENAPI,
        ))


def _diff_request_body(old_rb, new_rb, loc, old_doc, new_doc, out) -> None:
    old_rb = _resolve(old_rb, old_doc) if isinstance(old_rb, dict) else None
    new_rb = _resolve(new_rb, new_doc) if isinstance(new_rb, dict) else None

    if old_rb and not new_rb:
        out.append(make_finding(
            "request_body_removed", True, "major", f"{loc} -> requestBody",
            "Request body was removed",
            suggestion="Keep the legacy body or provide a compatibility layer",
            fmt=FORMAT_OPENAPI,
        ))
        return

    if new_rb and not old_rb:
        if new_rb.get("required", False):
            out.append(make_finding(
                "request_body_added_required", True, "major", f"{loc} -> requestBody",
                "Added a required request body",
                suggestion="Make the body optional so legacy calls without it keep working",
                fmt=FORMAT_OPENAPI,
            ))
        return

    if not old_rb or not new_rb:
        return

    _diff_content_types(old_rb, new_rb, f"{loc} -> requestBody", out)
    _diff_schema(_media_schema(old_rb), _media_schema(new_rb),
                 f"{loc} -> requestBody", old_doc, new_doc, out, set())


def _diff_responses(old_resp: dict, new_resp: dict, loc: str,
                    old_doc: dict, new_doc: dict, out: list) -> None:
    for status, old_r in old_resp.items():
        new_r = new_resp.get(status)
        if new_r is None:
            out.append(make_finding(
                "response_status_removed", True, "critical",
                f"{loc} -> response {status}",
                f"Response status {status} was removed",
                suggestion="Removing a status code breaks clients that depend on it",
                fmt=FORMAT_OPENAPI,
            ))
            continue
        _diff_content_types(old_r, new_r, f"{loc} -> response {status}", out)
        _diff_schema(_media_schema(old_r), _media_schema(new_r),
                     f"{loc} -> response {status}", old_doc, new_doc, out, set())

    for status in new_resp:
        if status not in old_resp:
            out.append(make_finding(
                "response_status_added", False, "info",
                f"{loc} -> response {status}",
                f"Added response status {status}",
                fmt=FORMAT_OPENAPI,
            ))


def _diff_components(old_doc: dict, new_doc: dict, out: list) -> None:
    old_schemas = ((old_doc.get("components") or {}).get("schemas") or {})
    new_schemas = ((new_doc.get("components") or {}).get("schemas") or {})

    for name, old_schema in old_schemas.items():
        new_schema = new_schemas.get(name)
        if new_schema is None:
            out.append(make_finding(
                "schema_removed", True, "critical",
                f"#/components/schemas/{name}",
                f"Component schema {name} was removed",
                suggestion="Removing a referenced schema breaks every endpoint using it",
                fmt=FORMAT_OPENAPI,
            ))
            continue
        _diff_schema(old_schema, new_schema, f"#/components/schemas/{name}",
                     old_doc, new_doc, out, set())

    for name in new_schemas:
        if name not in old_schemas:
            out.append(make_finding(
                "schema_added", False, "info",
                f"#/components/schemas/{name}",
                f"Added component schema {name}",
                fmt=FORMAT_OPENAPI,
            ))


# --------------------------------------------------------------------------- #
# Schema recursion
# --------------------------------------------------------------------------- #
def _diff_schema(old_schema, new_schema, loc, old_doc, new_doc, out, seen) -> None:
    old_schema = _resolve(old_schema, old_doc) if isinstance(old_schema, dict) else None
    new_schema = _resolve(new_schema, new_doc) if isinstance(new_schema, dict) else None

    if not isinstance(old_schema, dict) and not isinstance(new_schema, dict):
        return
    if not isinstance(old_schema, dict):
        out.append(make_finding(
            "schema_added", False, "info", loc, "Added schema structure",
            fmt=FORMAT_OPENAPI,
        ))
        return
    if not isinstance(new_schema, dict):
        out.append(make_finding(
            "schema_removed", True, "critical", loc, "Schema structure was removed",
            suggestion="Removing a schema breaks clients that depend on it",
            fmt=FORMAT_OPENAPI,
        ))
        return

    key = (old_schema.get("$ref") or f"old:{id(old_schema)}",
           new_schema.get("$ref") or f"new:{id(new_schema)}")
    if key in seen:
        return
    seen.add(key)

    _diff_schema_type(old_schema, new_schema, loc, out)
    _diff_schema_enum(old_schema, new_schema, loc, out)
    _diff_schema_constraints(old_schema, new_schema, loc, out)
    _diff_schema_properties(old_schema, new_schema, loc, old_doc, new_doc, out, seen)
    _diff_schema_required(old_schema, new_schema, loc, out)
    _diff_schema_items(old_schema, new_schema, loc, old_doc, new_doc, out, seen)


def _diff_schema_type(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_type = old_s.get("type")
    new_type = new_s.get("type")
    if old_type == new_type:
        return
    if old_type and not new_type:
        out.append(make_finding(
            "schema_type_removed", True, "major", loc,
            f"Type constraint removed (was {render(old_type)})",
            previous=old_type, current="(none)",
            fmt=FORMAT_OPENAPI,
        ))
        return
    if old_type == "integer" and new_type == "number":
        out.append(make_finding(
            "schema_type_widened", False, "minor", loc,
            "Field type widened from integer to number",
            previous="integer", current="number",
            fmt=FORMAT_OPENAPI,
        ))
        return
    out.append(make_finding(
        "schema_type_changed", True, "critical", loc,
        f"Field type changed from {render(old_type)} to {render(new_type)}",
        previous=old_type, current=new_type,
        suggestion="Type changes are the most common breaking change; keep type stable",
        fmt=FORMAT_OPENAPI,
    ))


def _diff_schema_enum(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_enum = old_s.get("enum") if isinstance(old_s.get("enum"), list) else None
    new_enum = new_s.get("enum") if isinstance(new_s.get("enum"), list) else None
    if old_enum is None and new_enum is None:
        return
    old_vals = set(old_enum or [])
    new_vals = set(new_enum or [])
    for v in sorted(old_vals - new_vals, key=str):
        out.append(make_finding(
            "enum_value_removed", True, "critical", loc,
            f"Enum value {render(v)} was removed",
            previous=v, current=None,
            suggestion="Clients sending a removed enum value will be rejected",
            fmt=FORMAT_OPENAPI,
        ))
    for v in sorted(new_vals - old_vals, key=str):
        out.append(make_finding(
            "enum_value_added", False, "info", loc,
            f"Added enum value {render(v)}",
            previous=None, current=v,
            fmt=FORMAT_OPENAPI,
        ))


def _diff_schema_constraints(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    for field, desc in [
        ("minimum", "minimum lower bound raised"),
        ("exclusiveMinimum", "exclusiveMinimum tightened"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if n is not None and o is not None and n > o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                suggestion="Tightening the minimum rejects previously-valid smaller values",
                fmt=FORMAT_OPENAPI,
            ))
    for field, desc in [
        ("maximum", "maximum upper bound lowered"),
        ("exclusiveMaximum", "exclusiveMaximum tightened"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if n is not None and o is not None and n < o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                suggestion="Tightening the maximum rejects previously-valid larger values",
                fmt=FORMAT_OPENAPI,
            ))
    for field, desc in [
        ("maxLength", "maxLength reduced"),
        ("maxItems", "maxItems reduced"),
        ("maxProperties", "maxProperties reduced"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if n is not None and o is not None and n < o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                fmt=FORMAT_OPENAPI,
            ))
    for field, desc in [
        ("minLength", "minLength raised"),
        ("minItems", "minItems raised"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if n is not None and o is not None and n > o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                fmt=FORMAT_OPENAPI,
            ))
    o_fmt, n_fmt = old_s.get("format"), new_s.get("format")
    if n_fmt is not None and o_fmt != n_fmt:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            f"format changed from {render(o_fmt)} to {render(n_fmt)}",
            previous=o_fmt, current=n_fmt,
            suggestion="A format change can alter parsing semantics (e.g. date-time -> date)",
            fmt=FORMAT_OPENAPI,
        ))
    if old_s.get("additionalProperties") is not False and new_s.get("additionalProperties") is False:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            "additionalProperties changed to forbidden",
            previous="true/default", current="false",
            suggestion="Forbidding extra properties rejects previously-accepted payloads",
            fmt=FORMAT_OPENAPI,
        ))


def _diff_schema_properties(old_s: dict, new_s: dict, loc, old_doc, new_doc, out, seen) -> None:
    old_props = old_s.get("properties") or {}
    new_props = new_s.get("properties") or {}
    for name, old_prop in old_props.items():
        new_prop = new_props.get(name)
        if new_prop is None:
            out.append(make_finding(
                "field_removed", True, "critical", f"{loc}.{name}",
                f"Field {name} was removed",
                suggestion="Removing an object field breaks clients reading it",
                fmt=FORMAT_OPENAPI,
            ))
            continue
        _diff_schema(old_prop, new_prop, f"{loc}.{name}", old_doc, new_doc, out, seen)
    for name in new_props:
        if name not in old_props:
            out.append(make_finding(
                "field_added", False, "info", f"{loc}.{name}",
                f"Added field {name}",
                fmt=FORMAT_OPENAPI,
            ))


def _diff_schema_required(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_req = set(old_s.get("required") or [])
    new_req = set(new_s.get("required") or [])
    for name in new_req - old_req:
        out.append(make_finding(
            "required_field_added", True, "critical", loc,
            f"Field {name} became required",
            previous=None, current=f"required: {name}",
            suggestion="A newly required field breaks payloads that omit it",
            fmt=FORMAT_OPENAPI,
        ))
    for name in old_req - new_req:
        out.append(make_finding(
            "required_field_removed", False, "minor", loc,
            f"Field {name} is no longer required",
            previous=f"required: {name}", current=None,
            fmt=FORMAT_OPENAPI,
        ))


def _diff_schema_items(old_s: dict, new_s: dict, loc, old_doc, new_doc, out, seen) -> None:
    old_items = old_s.get("items")
    new_items = new_s.get("items")
    if isinstance(old_items, dict) or isinstance(new_items, dict):
        _diff_schema(old_items, new_items, f"{loc}[]", old_doc, new_doc, out, seen)