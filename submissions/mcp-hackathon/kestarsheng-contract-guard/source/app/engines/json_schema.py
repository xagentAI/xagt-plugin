# -*- coding: utf-8 -*-
"""Deterministic JSON Schema breaking-change diff engine.

Recursively compares two JSON Schema documents (draft-07 / 2020-12 keywords:
type, enum, const, required, properties, items, numeric/string/array
constraints, additionalProperties) and emits confirmed findings.

Deterministic, no LLM calls.
"""
from __future__ import annotations

import json
from typing import Any

from ..models import FORMAT_JSON_SCHEMA
from .base import make_finding, render

_WARP = {"~1": "/", "~0": "~"}


class SpecParseError(ValueError):
    """Raised when a JSON Schema document cannot be parsed."""


def parse_json_schema(text: str) -> dict:
    """Parse a JSON Schema document (JSON only)."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecParseError(f"Cannot parse JSON Schema (invalid JSON): {exc}") from exc
    if not isinstance(doc, dict):
        raise SpecParseError("JSON Schema root must be an object")
    if "type" not in doc and "properties" not in doc and "$ref" not in doc \
            and "enum" not in doc and "const" not in doc and "oneOf" not in doc \
            and "anyOf" not in doc and "allOf" not in doc:
        raise SpecParseError("Document does not look like a JSON Schema")
    return doc


def _deref(ref: str, root: dict) -> dict | None:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        out = ""
        i = 0
        while i < len(part):
            if part[i] == "~" and i + 1 < len(part) and part[i:i + 2] in _WARP:
                out += _WARP[part[i:i + 2]]
                i += 2
            else:
                out += part[i]
                i += 1
        part = out
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, dict) else None


def _resolve(schema: dict, root: dict) -> dict:
    if isinstance(schema, dict) and "$ref" in schema:
        target = _deref(schema["$ref"], root)
        if target is not None:
            merged = dict(target)
            merged.update({k: v for k, v in schema.items() if k != "$ref"})
            return merged
    return schema


def diff_json_schema(old_root: dict, new_root: dict) -> list:
    """Diff two JSON Schema documents, returning confirmed findings."""
    findings: list = []
    _walk(old_root, new_root, "$", old_root, new_root, findings, set())
    return findings


def _walk(old_s, new_s, loc, old_root, new_root, out, seen) -> None:
    old_s = _resolve(old_s, old_root) if isinstance(old_s, dict) else None
    new_s = _resolve(new_s, new_root) if isinstance(new_s, dict) else None

    if not isinstance(old_s, dict) and not isinstance(new_s, dict):
        return
    if not isinstance(new_s, dict):
        out.append(make_finding(
            "schema_removed", True, "critical", loc, "Schema node was removed",
            fmt=FORMAT_JSON_SCHEMA,
        ))
        return
    if not isinstance(old_s, dict):
        out.append(make_finding(
            "schema_added", False, "info", loc, "Schema node was added",
            fmt=FORMAT_JSON_SCHEMA,
        ))
        return

    key = (old_s.get("$ref") or id(old_s), new_s.get("$ref") or id(new_s))
    if key in seen:
        return
    seen.add(key)

    _diff_type(old_s, new_s, loc, out)
    _diff_enum_const(old_s, new_s, loc, out)
    _diff_required(old_s, new_s, loc, out)
    _diff_properties(old_s, new_s, loc, old_root, new_root, out, seen)
    _diff_items(old_s, new_s, loc, old_root, new_root, out, seen)
    _diff_prefix_items(old_s, new_s, loc, out)
    _diff_contains(old_s, new_s, loc, out)
    _diff_dependent_required(old_s, new_s, loc, out)
    _diff_constraints(old_s, new_s, loc, out)
    _diff_unevaluated(old_s, new_s, loc, out)


def _diff_type(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_type = old_s.get("type")
    new_type = new_s.get("type")
    if old_type == new_type:
        return
    if old_type and not new_type:
        out.append(make_finding(
            "type_constraint_removed", True, "major", loc,
            f"Type constraint removed (was {render(old_type)})",
            previous=old_type, current="(none)",
            fmt=FORMAT_JSON_SCHEMA,
        ))
        return
    if old_type == "integer" and new_type == "number":
        out.append(make_finding(
            "type_widened", False, "minor", loc,
            "Type widened from integer to number",
            previous="integer", current="number",
            fmt=FORMAT_JSON_SCHEMA,
        ))
        return
    if old_type and new_type:
        out.append(make_finding(
            "type_changed", True, "critical", loc,
            f"Type changed from {render(old_type)} to {render(new_type)}",
            previous=old_type, current=new_type,
            suggestion="Keep the type stable or add a new field/version",
            fmt=FORMAT_JSON_SCHEMA,
        ))


def _diff_enum_const(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_const = old_s.get("const", _MISSING)
    new_const = new_s.get("const", _MISSING)
    if old_const is not _MISSING or new_const is not _MISSING:
        if old_const != new_const:
            out.append(make_finding(
                "const_changed", True, "critical", loc,
                f"const value changed from {render(old_const)} to {render(new_const)}",
                previous=old_const, current=new_const,
                fmt=FORMAT_JSON_SCHEMA,
            ))
        return

    old_enum = old_s.get("enum") if isinstance(old_s.get("enum"), list) else None
    new_enum = new_s.get("enum") if isinstance(new_s.get("enum"), list) else None
    if old_enum is None and new_enum is None:
        return
    old_vals = set(map(json.dumps, old_enum or []))
    new_vals = set(map(json.dumps, new_enum or []))
    for v in sorted(old_vals - new_vals):
        out.append(make_finding(
            "enum_value_removed", True, "critical", loc,
            f"Enum value removed: {v}",
            previous=v, current=None,
            fmt=FORMAT_JSON_SCHEMA,
        ))
    for v in sorted(new_vals - old_vals):
        out.append(make_finding(
            "enum_value_added", False, "info", loc,
            f"Enum value added: {v}",
            previous=None, current=v,
            fmt=FORMAT_JSON_SCHEMA,
        ))


_MISSING = object()


def _diff_required(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_req = set(old_s.get("required") or [])
    new_req = set(new_s.get("required") or [])
    for name in new_req - old_req:
        out.append(make_finding(
            "required_property_added", True, "critical", loc,
            f"Property {name} became required",
            previous=None, current=f"required: {name}",
            fmt=FORMAT_JSON_SCHEMA,
        ))
    for name in old_req - new_req:
        out.append(make_finding(
            "required_property_removed", False, "minor", loc,
            f"Property {name} is no longer required",
            previous=f"required: {name}", current=None,
            fmt=FORMAT_JSON_SCHEMA,
        ))


def _diff_properties(old_s, new_s, loc, old_root, new_root, out, seen) -> None:
    old_props = old_s.get("properties") or {}
    new_props = new_s.get("properties") or {}
    for name, old_prop in old_props.items():
        new_prop = new_props.get(name)
        if new_prop is None:
            out.append(make_finding(
                "property_removed", True, "critical", f"{loc}.properties.{name}",
                f"Property {name} was removed",
                fmt=FORMAT_JSON_SCHEMA,
            ))
            continue
        _walk(old_prop, new_prop, f"{loc}.properties.{name}",
              old_root, new_root, out, seen)
    for name in new_props:
        if name not in old_props:
            out.append(make_finding(
                "property_added", False, "info", f"{loc}.properties.{name}",
                f"Property {name} was added",
                fmt=FORMAT_JSON_SCHEMA,
            ))


def _diff_items(old_s, new_s, loc, old_root, new_root, out, seen) -> None:
    old_items = old_s.get("items")
    new_items = new_s.get("items")
    if isinstance(old_items, dict) or isinstance(new_items, dict):
        _walk(old_items, new_items, f"{loc}.items",
              old_root, new_root, out, seen)


def _diff_constraints(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    for field, desc, tighten_when in [
        ("minLength", "minLength raised", "gt"),
        ("minItems", "minItems raised", "gt"),
        ("minimum", "minimum raised", "gt"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if isinstance(o, (int, float)) and isinstance(n, (int, float)) and n > o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                fmt=FORMAT_JSON_SCHEMA,
            ))
    for field, desc in [
        ("maxLength", "maxLength reduced"),
        ("maxItems", "maxItems reduced"),
        ("maximum", "maximum reduced"),
    ]:
        o, n = old_s.get(field), new_s.get(field)
        if isinstance(o, (int, float)) and isinstance(n, (int, float)) and n < o:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc, desc,
                previous=o, current=n,
                fmt=FORMAT_JSON_SCHEMA,
            ))

    for field in ("pattern", "format"):
        o, n = old_s.get(field), new_s.get(field)
        if n is not None and o != n:
            out.append(make_finding(
                "constraint_tightened", True, "major", loc,
                f"{field} changed from {render(o)} to {render(n)}",
                previous=o, current=n,
                fmt=FORMAT_JSON_SCHEMA,
            ))

    if old_s.get("uniqueItems") is not True and new_s.get("uniqueItems") is True:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            "uniqueItems changed to true",
            previous=False, current=True,
            fmt=FORMAT_JSON_SCHEMA,
        ))

    if old_s.get("additionalProperties") is not False \
            and new_s.get("additionalProperties") is False:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            "additionalProperties changed to forbidden",
            previous="true/default", current="false",
            fmt=FORMAT_JSON_SCHEMA,
        ))


def _diff_prefix_items(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_pi = old_s.get("prefixItems")
    new_pi = new_s.get("prefixItems")
    if not isinstance(old_pi, list) and not isinstance(new_pi, list):
        return
    old_len = len(old_pi) if isinstance(old_pi, list) else 0
    new_len = len(new_pi) if isinstance(new_pi, list) else 0
    if old_len > new_len and new_len >= 0:
        out.append(make_finding(
            "prefix_items_removed", True, "critical", loc,
            f"prefixItems shortened from {old_len} to {new_len} entries",
            previous=old_len, current=new_len,
            suggestion="Removing prefix items changes tuple semantics",
            fmt=FORMAT_JSON_SCHEMA,
        ))
    for i in range(min(old_len, new_len)):
        old_item = old_pi[i] if isinstance(old_pi, list) and i < len(old_pi) else None
        new_item = new_pi[i] if isinstance(new_pi, list) and i < len(new_pi) else None
        if isinstance(old_item, dict) and isinstance(new_item, dict):
            old_t = old_item.get("type")
            new_t = new_item.get("type")
            if old_t and new_t and old_t != new_t:
                out.append(make_finding(
                    "prefix_item_type_changed", True, "critical", f"{loc}.prefixItems[{i}]",
                    f"prefixItems[{i}] type changed from {render(old_t)} to {render(new_t)}",
                    previous=old_t, current=new_t,
                    fmt=FORMAT_JSON_SCHEMA,
                ))


def _diff_contains(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_has = "contains" in old_s
    new_has = "contains" in new_s
    if not old_has and not new_has:
        return
    if old_has and not new_has:
        out.append(make_finding(
            "contains_removed", True, "major", loc,
            "contains constraint was removed",
            suggestion="Removing contains allows arrays that previously failed validation",
            fmt=FORMAT_JSON_SCHEMA,
        ))
    old_mc = old_s.get("minContains")
    new_mc = new_s.get("minContains")
    if isinstance(old_mc, (int, float)) and isinstance(new_mc, (int, float)) and new_mc > old_mc:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            f"minContains raised from {old_mc} to {new_mc}",
            previous=old_mc, current=new_mc,
            fmt=FORMAT_JSON_SCHEMA,
        ))
    old_xc = old_s.get("maxContains")
    new_xc = new_s.get("maxContains")
    if isinstance(old_xc, (int, float)) and isinstance(new_xc, (int, float)) and new_xc < old_xc:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            f"maxContains lowered from {old_xc} to {new_xc}",
            previous=old_xc, current=new_xc,
            fmt=FORMAT_JSON_SCHEMA,
        ))


def _diff_dependent_required(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    old_dr = old_s.get("dependentRequired") or {}
    new_dr = new_s.get("dependentRequired") or {}
    if not isinstance(old_dr, dict) or not isinstance(new_dr, dict):
        return
    for prop, old_deps in old_dr.items():
        new_deps = new_dr.get(prop)
        if new_deps is None:
            continue
        old_set = set(old_deps) if isinstance(old_deps, list) else set()
        new_set = set(new_deps) if isinstance(new_deps, list) else set()
        added = new_set - old_set
        for dep in sorted(added):
            out.append(make_finding(
                "dependent_required_added", True, "major", loc,
                f"dependentRequired: {prop} now requires {dep}",
                previous=None, current=f"{prop} -> {dep}",
                suggestion="Adding a dependent requirement breaks payloads that omit the dependency",
                fmt=FORMAT_JSON_SCHEMA,
            ))


def _diff_unevaluated(old_s: dict, new_s: dict, loc: str, out: list) -> None:
    if old_s.get("unevaluatedProperties") is not False \
            and new_s.get("unevaluatedProperties") is False:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            "unevaluatedProperties changed to forbidden",
            previous="true/default", current="false",
            fmt=FORMAT_JSON_SCHEMA,
        ))
    if old_s.get("unevaluatedItems") is not False \
            and new_s.get("unevaluatedItems") is False:
        out.append(make_finding(
            "constraint_tightened", True, "major", loc,
            "unevaluatedItems changed to forbidden",
            previous="true/default", current="false",
            fmt=FORMAT_JSON_SCHEMA,
        ))