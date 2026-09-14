# -*- coding: utf-8 -*-
"""Deterministic GraphQL SDL breaking-change diff engine.

Builds the schema from two SDL documents with ``graphql-core`` and compares
them against the breaking-change rules defined in the GraphQL spec appendix
(removed types/fields/arguments, changed types, nullable -> non-null, removed
enum values, added required arguments, interface fields, etc.).

Deterministic, no LLM calls.
"""
from __future__ import annotations

from typing import Any

from graphql import GraphQLSchema, Undefined, build_schema
from graphql.type import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLInputType,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLUnionType,
    get_named_type,
    get_nullable_type,
    is_non_null_type,
    is_object_type,
    is_interface_type,
    is_input_object_type,
    is_enum_type,
    is_scalar_type,
    is_union_type,
)

from ..models import FORMAT_GRAPHQL
from .base import make_finding, render

_BUILTIN_SCALARS = {"Int", "Float", "String", "Boolean", "ID"}


class SpecParseError(ValueError):
    """Raised when a GraphQL SDL document cannot be parsed."""


def parse_graphql(text: str) -> GraphQLSchema:
    """Build a GraphQL schema from SDL text."""
    try:
        return build_schema(text)
    except Exception as exc:  # noqa: BLE001 - graphql-core raises various
        raise SpecParseError(f"Cannot parse GraphQL SDL: {exc}") from exc


def _named_types(schema: GraphQLSchema) -> dict:
    out = {}
    for name, t in schema.type_map.items():
        if name.startswith("__"):
            continue
        if is_scalar_type(t) and name in _BUILTIN_SCALARS:
            continue
        out[name] = t
    return out


def diff_graphql(old_schema: GraphQLSchema, new_schema: GraphQLSchema) -> list:
    """Diff two GraphQL schemas, returning confirmed findings."""
    findings: list = []
    old_types = _named_types(old_schema)
    new_types = _named_types(new_schema)

    _diff_directives(old_schema, new_schema, findings)

    for name, old_t in old_types.items():
        new_t = new_types.get(name)
        if new_t is None:
            findings.append(make_finding(
                "type_removed", True, "critical", f"type {name}",
                f"Type {name} was removed",
                fmt=FORMAT_GRAPHQL,
            ))
            continue
        _diff_type(name, old_t, new_t, findings)

    for name in new_types:
        if name not in old_types:
            findings.append(make_finding(
                "type_added", False, "info", f"type {name}",
                f"Type {name} was added",
                fmt=FORMAT_GRAPHQL,
            ))
    return findings


def _diff_directives(old_schema: GraphQLSchema, new_schema: GraphQLSchema, out: list) -> None:
    old_dirs = {d.name: d for d in (old_schema.directives or [])
                if not d.name.startswith("__")}
    new_dirs = {d.name: d for d in (new_schema.directives or [])
                if not d.name.startswith("__")}
    for name in old_dirs:
        if name not in new_dirs:
            out.append(make_finding(
                "directive_removed", True, "major", f"directive @{name}",
                f"Directive @{name} was removed",
                suggestion="Removing a directive breaks schemas that apply it",
                fmt=FORMAT_GRAPHQL,
            ))
    for name in new_dirs:
        if name not in old_dirs:
            out.append(make_finding(
                "directive_added", False, "info", f"directive @{name}",
                f"Directive @{name} was added",
                fmt=FORMAT_GRAPHQL,
            ))


def _is_same_kind(a, b) -> bool:
    return type(a).__name__ == type(b).__name__


def _diff_type(name: str, old_t, new_t, out: list) -> None:
    if not _is_same_kind(old_t, new_t):
        out.append(make_finding(
            "type_kind_changed", True, "critical", f"type {name}",
            f"Type {name} changed kind from {_kind_name(old_t)} to {_kind_name(new_t)}",
            previous=_kind_name(old_t), current=_kind_name(new_t),
            fmt=FORMAT_GRAPHQL,
        ))
        return

    if is_object_type(old_t):
        _diff_fields(name, old_t.fields, new_t.fields, out)
    elif is_interface_type(old_t):
        _diff_fields(name, old_t.fields, new_t.fields, out)
    elif is_input_object_type(old_t):
        _diff_input_fields(name, old_t.fields, new_t.fields, out)
    elif is_enum_type(old_t):
        _diff_enum(name, old_t, new_t, out)
    elif is_union_type(old_t):
        _diff_union(name, old_t, new_t, out)


def _kind_name(t) -> str:
    if is_object_type(t):
        return "object"
    if is_interface_type(t):
        return "interface"
    if is_input_object_type(t):
        return "input"
    if is_enum_type(t):
        return "enum"
    if is_union_type(t):
        return "union"
    if is_scalar_type(t):
        return "scalar"
    return type(t).__name__


def _diff_fields(name: str, old_fields, new_fields, out: list) -> None:
    for fname, old_f in old_fields.items():
        new_f = new_fields.get(fname)
        if new_f is None:
            out.append(make_finding(
                "field_removed", True, "critical", f"{name}.{fname}",
                f"Field {name}.{fname} was removed",
                fmt=FORMAT_GRAPHQL,
            ))
            continue
        _diff_field_deprecated(name, fname, old_f, new_f, out)
        _diff_field_type(name, fname, old_f, new_f, out)
        _diff_args(name, fname, old_f.args, new_f.args, out)

    for fname, new_f in new_fields.items():
        if fname not in old_fields:
            out.append(make_finding(
                "field_added", False, "info", f"{name}.{fname}",
                f"Field {name}.{fname} was added",
                fmt=FORMAT_GRAPHQL,
            ))


def _diff_field_deprecated(name: str, fname: str, old_f: GraphQLField, new_f: GraphQLField, out: list) -> None:
    old_dep = getattr(old_f, "is_deprecated", False)
    new_dep = getattr(new_f, "is_deprecated", False)
    if not old_dep and new_dep:
        out.append(make_finding(
            "field_deprecated", False, "minor", f"{name}.{fname}",
            f"Field {name}.{fname} was marked @deprecated",
            suggestion="Communicate the deprecation timeline to consumers",
            fmt=FORMAT_GRAPHQL,
        ))
    elif old_dep and not new_dep:
        out.append(make_finding(
            "field_undeprecated", False, "info", f"{name}.{fname}",
            f"Field {name}.{fname} @deprecated was removed",
            fmt=FORMAT_GRAPHQL,
        ))


def _diff_field_type(name: str, fname: str, old_f: GraphQLField, new_f: GraphQLField, out: list) -> None:
    old_t, new_t = old_f.type, new_f.type
    old_nullable = get_nullable_type(old_t)
    new_nullable = get_nullable_type(new_t)
    old_named = get_named_type(old_t)
    new_named = get_named_type(new_t)

    if old_named.name != new_named.name:
        out.append(make_finding(
            "field_type_changed", True, "critical", f"{name}.{fname}",
            f"Field {name}.{fname} type changed from {str(old_t)} to {str(new_t)}",
            previous=str(old_t), current=str(new_t),
            fmt=FORMAT_GRAPHQL,
        ))
        return

    if is_non_null_type(old_t) != is_non_null_type(new_t):
        if is_non_null_type(new_t) and not is_non_null_type(old_t):
            out.append(make_finding(
                "field_type_became_non_null", True, "critical", f"{name}.{fname}",
                f"Field {name}.{fname} type changed from {str(old_t)} to {str(new_t)} (non-null)",
                previous=str(old_t), current=str(new_t),
                suggestion="Returning non-null breaks clients that handled null",
                fmt=FORMAT_GRAPHQL,
            ))
        else:
            out.append(make_finding(
                "field_type_became_nullable", False, "minor", f"{name}.{fname}",
                f"Field {name}.{fname} type changed from {str(old_t)} to {str(new_t)} (nullable)",
                previous=str(old_t), current=str(new_t),
                fmt=FORMAT_GRAPHQL,
            ))


def _diff_input_fields(name: str, old_fields, new_fields, out: list) -> None:
    for fname, old_f in old_fields.items():
        new_f = new_fields.get(fname)
        if new_f is None:
            out.append(make_finding(
                "input_field_removed", True, "critical", f"{name}.{fname}",
                f"Input field {name}.{fname} was removed",
                fmt=FORMAT_GRAPHQL,
            ))
            continue
        if is_non_null_type(old_f.type) != is_non_null_type(new_f.type) \
                or get_named_type(old_f.type).name != get_named_type(new_f.type).name:
            if str(old_f.type) != str(new_f.type):
                breaking = is_non_null_type(new_f.type) and not is_non_null_type(old_f.type)
                out.append(make_finding(
                    "input_field_type_changed", breaking, "critical" if breaking else "major",
                    f"{name}.{fname}",
                    f"Input field {name}.{fname} type changed from {str(old_f.type)} to {str(new_f.type)}",
                    previous=str(old_f.type), current=str(new_f.type),
                    fmt=FORMAT_GRAPHQL,
                ))

    for fname, new_f in new_fields.items():
        if fname in old_fields:
            continue
        if is_non_null_type(new_f.type):
            out.append(make_finding(
                "input_field_added_required", True, "critical", f"{name}.{fname}",
                f"Added required input field {name}.{fname}",
                previous=None, current=str(new_f.type),
                suggestion="A required input field breaks callers that omit it",
                fmt=FORMAT_GRAPHQL,
            ))
        else:
            out.append(make_finding(
                "input_field_added", False, "info", f"{name}.{fname}",
                f"Added optional input field {name}.{fname}",
                fmt=FORMAT_GRAPHQL,
            ))


def _diff_args(name: str, fname: str, old_args, new_args, out: list) -> None:
    for aname, old_a in old_args.items():
        new_a = new_args.get(aname)
        if new_a is None:
            out.append(make_finding(
                "argument_removed", True, "critical", f"{name}.{fname}({aname}:)",
                f"Argument {aname}: on {name}.{fname} was removed",
                fmt=FORMAT_GRAPHQL,
            ))
            continue
        if str(old_a.type) != str(new_a.type):
            if _arg_breaking_change(old_a, new_a):
                out.append(make_finding(
                    "argument_type_changed", True, "critical", f"{name}.{fname}({aname}:)",
                    f"Argument {aname}: type changed from {str(old_a.type)} to {str(new_a.type)}",
                    previous=str(old_a.type), current=str(new_a.type),
                    fmt=FORMAT_GRAPHQL,
                ))
            else:
                out.append(make_finding(
                    "argument_type_widened", False, "minor", f"{name}.{fname}({aname}:)",
                    f"Argument {aname}: type widened from {str(old_a.type)} to {str(new_a.type)}",
                    previous=str(old_a.type), current=str(new_a.type),
                    fmt=FORMAT_GRAPHQL,
                ))

    for aname, new_a in new_args.items():
        if aname in old_args:
            continue
        if is_non_null_type(new_a.type) and new_a.default_value in (None, Undefined):
            out.append(make_finding(
                "argument_added_required", True, "critical", f"{name}.{fname}({aname}:)",
                f"Added required argument {aname}: to {name}.{fname}",
                previous=None, current=str(new_a.type),
                suggestion="A required argument breaks callers that omit it",
                fmt=FORMAT_GRAPHQL,
            ))
        else:
            out.append(make_finding(
                "argument_added", False, "info", f"{name}.{fname}({aname}:)",
                f"Added optional argument {aname}: to {name}.{fname}",
                fmt=FORMAT_GRAPHQL,
            ))


def _arg_breaking_change(old_a: GraphQLArgument, new_a: GraphQLArgument) -> bool:
    if get_named_type(old_a.type).name != get_named_type(new_a.type).name:
        return True
    if is_non_null_type(new_a.type) and not is_non_null_type(old_a.type):
        if new_a.default_value in (None, Undefined):
            return True
    return False


def _diff_enum(name: str, old_e: GraphQLEnumType, new_e: GraphQLEnumType, out: list) -> None:
    old_vals = set(old_e.values.keys())
    new_vals = set(new_e.values.keys())
    for v in sorted(old_vals - new_vals):
        out.append(make_finding(
            "enum_value_removed", True, "critical", f"enum {name}.{v}",
            f"Enum value {name}.{v} was removed",
            fmt=FORMAT_GRAPHQL,
        ))
    for v in sorted(new_vals - old_vals):
        out.append(make_finding(
            "enum_value_added", False, "info", f"enum {name}.{v}",
            f"Enum value {name}.{v} was added",
            fmt=FORMAT_GRAPHQL,
        ))


def _diff_union(name: str, old_u: GraphQLUnionType, new_u: GraphQLUnionType, out: list) -> None:
    old_members = {t.name for t in old_u.types}
    new_members = {t.name for t in new_u.types}
    for m in sorted(old_members - new_members):
        out.append(make_finding(
            "union_member_removed", True, "critical", f"union {name} = {m}",
            f"Union member {m} was removed from {name}",
            fmt=FORMAT_GRAPHQL,
        ))
    for m in sorted(new_members - old_members):
        out.append(make_finding(
            "union_member_added", False, "info", f"union {name} = {m}",
            f"Union member {m} was added to {name}",
            fmt=FORMAT_GRAPHQL,
        ))