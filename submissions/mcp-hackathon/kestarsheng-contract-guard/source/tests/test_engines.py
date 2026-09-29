# -*- coding: utf-8 -*-
"""Unit tests for the deterministic diff engines (OpenAPI / JSON Schema / GraphQL)."""
import json

from app.engines.graphql import diff_graphql, parse_graphql
from app.engines.json_schema import diff_json_schema
from app.engines.openapi import diff_openapi


def _has(findings, change_type, breaking=True):
    return any(f.change_type == change_type and f.breaking == breaking for f in findings)


# --------------------------------------------------------------------------- #
# OpenAPI helpers
# --------------------------------------------------------------------------- #
def _oa(paths=None, components=None):
    doc = {"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "paths": paths or {}}
    if components:
        doc["components"] = components
    return doc


def _resp200(schema=None):
    r200 = {"description": "ok"}
    if schema is not None:
        r200["content"] = {"application/json": {"schema": schema}}
    return {"200": r200}


def _op(schema=None, params=None):
    op = {"responses": _resp200(schema)}
    if params:
        op["parameters"] = params
    return op


def _obj(props=None, required=None):
    s = {"type": "object", "properties": props or {}}
    if required:
        s["required"] = required
    return s


# --------------------------------------------------------------------------- #
# OpenAPI
# --------------------------------------------------------------------------- #
def test_openapi_endpoint_removed():
    old = _oa({"/users": {"get": _op()}})
    new = _oa({})
    assert _has(diff_openapi(old, new), "endpoint_removed")
    assert diff_openapi(old, new)[0].severity == "critical"


def test_openapi_method_removed():
    old = _oa({"/users": {"get": _op(), "post": {"responses": {"201": {"description": "ok"}}}}})
    new = _oa({"/users": {"get": _op()}})
    assert _has(diff_openapi(old, new), "method_removed")


def test_openapi_required_parameter_added():
    old = _oa({"/users": {"get": _op()}})
    new = _oa({"/users": {"get": _op(params=[
        {"name": "limit", "in": "query", "required": True, "schema": {"type": "integer"}}
    ])}})
    assert _has(diff_openapi(old, new), "required_parameter_added")


def test_openapi_schema_type_changed():
    old = _oa({"/u": {"get": _op(_obj({"id": {"type": "integer"}}))}})
    new = _oa({"/u": {"get": _op(_obj({"id": {"type": "string"}}))}})
    assert _has(diff_openapi(old, new), "schema_type_changed")


def test_openapi_enum_removed():
    old = _oa({"/u": {"get": _op({"type": "string", "enum": ["a", "b", "c"]})}})
    new = _oa({"/u": {"get": _op({"type": "string", "enum": ["a", "b"]})}})
    assert _has(diff_openapi(old, new), "enum_value_removed")


def test_openapi_field_removed():
    old = _oa({"/u": {"get": _op(_obj({"id": {"type": "integer"}, "name": {"type": "string"}}))}})
    new = _oa({"/u": {"get": _op(_obj({"id": {"type": "integer"}}))}})
    assert _has(diff_openapi(old, new), "field_removed")


def test_openapi_required_field_added():
    old = _oa({"/u": {"get": _op(_obj({"id": {}, "name": {}}, ["id"]))}})
    new = _oa({"/u": {"get": _op(_obj({"id": {}, "name": {}}, ["id", "name"]))}})
    assert _has(diff_openapi(old, new), "required_field_added")


def test_openapi_constraint_tightened():
    old = _oa({"/u": {"get": _op({"type": "string", "maxLength": 100})}})
    new = _oa({"/u": {"get": _op({"type": "string", "maxLength": 50})}})
    assert _has(diff_openapi(old, new), "constraint_tightened")


def test_openapi_component_schema_removed():
    old = _oa({}, {"schemas": {"User": _obj({"id": {"type": "integer"}})}})
    new = _oa({}, {"schemas": {}})
    assert _has(diff_openapi(old, new), "schema_removed")


def test_openapi_nonbreaking_changes():
    old = _oa({"/u": {"get": _op(_obj({"id": {"type": "integer"}}))}})
    new = _oa({
        "/u": {"get": _op(_obj({"id": {"type": "integer"}, "name": {"type": "string"}}))},
        "/posts": {"get": _op()},
    })
    f = diff_openapi(old, new)
    assert _has(f, "endpoint_added", breaking=False)
    assert _has(f, "field_added", breaking=False)
    assert not any(x.breaking for x in f)


def test_openapi_type_widened_integer_to_number():
    old = _oa({"/u": {"get": _op({"type": "integer"})}})
    new = _oa({"/u": {"get": _op({"type": "number"})}})
    assert _has(diff_openapi(old, new), "schema_type_widened", breaking=False)


def test_openapi_ref_resolution():
    old = _oa(
        {"/u": {"get": _op({"$ref": "#/components/schemas/User"})}},
        {"schemas": {"User": _obj({"id": {"type": "integer"}, "email": {"type": "string"}})}},
    )
    new = _oa(
        {"/u": {"get": _op({"$ref": "#/components/schemas/User"})}},
        {"schemas": {"User": _obj({"id": {"type": "integer"}})}},
    )
    assert _has(diff_openapi(old, new), "field_removed")


# --------------------------------------------------------------------------- #
# JSON Schema
# --------------------------------------------------------------------------- #
def test_jsonschema_type_changed():
    assert _has(diff_json_schema({"type": "string"}, {"type": "integer"}), "type_changed")


def test_jsonschema_enum_removed():
    old = {"type": "string", "enum": ["red", "green", "blue"]}
    new = {"type": "string", "enum": ["red", "green"]}
    assert _has(diff_json_schema(old, new), "enum_value_removed")


def test_jsonschema_required_added():
    old = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    new = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}
    assert _has(diff_json_schema(old, new), "required_property_added")


def test_jsonschema_property_removed():
    old = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
    new = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert _has(diff_json_schema(old, new), "property_removed")


def test_jsonschema_constraint_tightened():
    assert _has(diff_json_schema({"type": "string", "maxLength": 100}, {"type": "string", "maxLength": 50}), "constraint_tightened")


def test_jsonschema_const_changed():
    assert _has(diff_json_schema({"const": "v1"}, {"const": "v2"}), "const_changed")


def test_jsonschema_additional_properties_forbidden():
    assert _has(diff_json_schema({"type": "object"}, {"type": "object", "additionalProperties": False}), "constraint_tightened")


def test_jsonschema_ref_resolution():
    old = {"$ref": "#/$defs/User", "$defs": {"User": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}}}
    new = {"$ref": "#/$defs/User", "$defs": {"User": {"type": "object", "properties": {"id": {"type": "integer"}}}}}
    assert _has(diff_json_schema(old, new), "property_removed")


# --------------------------------------------------------------------------- #
# GraphQL
# --------------------------------------------------------------------------- #
def _gql(sdl):
    return parse_graphql(sdl)


def test_graphql_type_removed():
    old = _gql("type Query { a: String } type User { id: ID! }")
    new = _gql("type Query { a: String }")
    assert _has(diff_graphql(old, new), "type_removed")


def test_graphql_field_removed():
    old = _gql("type Query { a: String } type User { id: ID! name: String }")
    new = _gql("type Query { a: String } type User { id: ID! }")
    assert _has(diff_graphql(old, new), "field_removed")


def test_graphql_field_type_changed():
    old = _gql("type Query { a: String } type User { id: ID! }")
    new = _gql("type Query { a: String } type User { id: Int! }")
    assert _has(diff_graphql(old, new), "field_type_changed")


def test_graphql_field_becomes_non_null():
    old = _gql("type Query { a: String } type User { name: String }")
    new = _gql("type Query { a: String } type User { name: String! }")
    assert _has(diff_graphql(old, new), "field_type_became_non_null")


def test_graphql_enum_removed():
    old = _gql("type Query { a: String } enum Color { RED GREEN BLUE }")
    new = _gql("type Query { a: String } enum Color { RED GREEN }")
    assert _has(diff_graphql(old, new), "enum_value_removed")


def test_graphql_argument_removed():
    old = _gql("type Query { users(limit: Int): String }")
    new = _gql("type Query { users: String }")
    assert _has(diff_graphql(old, new), "argument_removed")


def test_graphql_argument_added_required():
    old = _gql("type Query { users: String }")
    new = _gql("type Query { users(limit: Int!): String }")
    assert _has(diff_graphql(old, new), "argument_added_required")


def test_graphql_input_field_required():
    old = _gql("type Query { a: String } input UserInput { name: String }")
    new = _gql("type Query { a: String } input UserInput { name: String email: String! }")
    assert _has(diff_graphql(old, new), "input_field_added_required")


def test_graphql_union_member_removed():
    old = _gql("type Query { a: String } type A { x: Int } type B { y: Int } union Result = A | B")
    new = _gql("type Query { a: String } type A { x: Int } type B { y: Int } union Result = A")
    assert _has(diff_graphql(old, new), "union_member_removed")


def test_graphql_nonbreaking_field_added():
    old = _gql("type Query { a: String } type User { id: ID! }")
    new = _gql("type Query { a: String } type User { id: ID! name: String }")
    f = diff_graphql(old, new)
    assert _has(f, "field_added", breaking=False)
    assert not any(x.breaking for x in f)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def test_detect_changes_openapi():
    from app.diff_core import detect_changes
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({}))
    report = detect_changes(old, new, "openapi")
    assert report.breaking is True
    assert report.breaking_count >= 1
    assert report.findings[0].source == "confirmed"


def test_detect_changes_format_alias():
    from app.diff_core import normalize_format
    assert normalize_format("swagger") == "openapi"
    assert normalize_format("gql") == "graphql"
    assert normalize_format("jsonschema") == "json-schema"


def test_detect_changes_equivalent():
    from app.diff_core import detect_changes
    spec = json.dumps(_oa({"/users": {"get": _op()}}))
    report = detect_changes(spec, spec, "openapi")
    assert report.breaking is False
    assert report.total_changes == 0


# --------------------------------------------------------------------------- #
# Enhanced detection rules
# --------------------------------------------------------------------------- #
def test_openapi_content_type_removed():
    old = {"openapi": "3.0.0", "paths": {"/upload": {"post": {
        "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}},
                          "required": True}}}}}
    new = {"openapi": "3.0.0", "paths": {"/upload": {"post": {
        "requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object"}}},
                          "required": True}}}}}
    f = diff_openapi(old, new)
    assert _has(f, "content_type_removed", breaking=True)


def test_openapi_operation_deprecated():
    old = _oa({"/old": {"get": _op()}})
    new = {"openapi": "3.0.0", "paths": {"/old": {"get": {**_op(), "deprecated": True}}}}
    f = diff_openapi(old, new)
    assert _has(f, "operation_deprecated", breaking=False)


def test_graphql_directive_removed():
    old = _gql("directive @cache on FIELD_DEFINITION\ntype Query { a: String @cache }")
    new = _gql("type Query { a: String }")
    f = diff_graphql(old, new)
    assert _has(f, "directive_removed", breaking=True)


def test_jsonschema_prefix_items_removed():
    old = {"type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}]}
    new = {"type": "array", "prefixItems": [{"type": "string"}]}
    f = diff_json_schema(old, new)
    assert _has(f, "prefix_items_removed", breaking=True)


def test_jsonschema_contains_constraint():
    old = {"type": "array", "contains": {"type": "string"}, "minContains": 1}
    new = {"type": "array", "contains": {"type": "string"}, "minContains": 3}
    f = diff_json_schema(old, new)
    assert _has(f, "constraint_tightened", breaking=True)


def test_jsonschema_dependent_required():
    old = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
           "dependentRequired": {"a": []}}
    new = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
           "dependentRequired": {"a": ["b"]}}
    f = diff_json_schema(old, new)
    assert _has(f, "dependent_required_added", breaking=True)


def test_jsonschema_unevaluated_properties():
    old = {"type": "object", "properties": {"a": {"type": "string"}}}
    new = {"type": "object", "properties": {"a": {"type": "string"}},
           "unevaluatedProperties": False}
    f = diff_json_schema(old, new)
    assert _has(f, "constraint_tightened", breaking=True)


# --------------------------------------------------------------------------- #
# SemVer + Changelog
# --------------------------------------------------------------------------- #
def test_semver_major_bump():
    from app.diff_core import detect_changes
    from app.semver import suggest_version_bump
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({}))
    report = detect_changes(old, new, "openapi")
    result = suggest_version_bump(report, "1.2.3")
    assert result["bump"] == "major"
    assert result["suggested_version"] == "2.0.0"


def test_semver_patch_bump():
    from app.diff_core import detect_changes
    from app.semver import suggest_version_bump
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({"/users": {"get": _op()}, "/posts": {"get": _op()}}))
    report = detect_changes(old, new, "openapi")
    result = suggest_version_bump(report, "1.2.3")
    assert result["bump"] == "patch"
    assert result["suggested_version"] == "1.2.4"


def test_changelog_generation():
    from app.diff_core import detect_changes
    from app.semver import generate_changelog
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({}))
    report = detect_changes(old, new, "openapi")
    changelog = generate_changelog(report, "1.0.0", "2.0.0")
    assert "## API Contract Changes" in changelog
    assert "Breaking Changes" in changelog


# --------------------------------------------------------------------------- #
# Migration suggestions
# --------------------------------------------------------------------------- #
def test_migration_suggestions():
    from app.diff_core import detect_changes
    from app.migration import suggest_migration
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({}))
    report = detect_changes(old, new, "openapi")
    result = suggest_migration(report)
    assert result["total_breaking"] > 0
    assert result["has_migration_path"] is True
    assert len(result["suggestions"]) > 0
    assert "migration" in result["suggestions"][0]


# --------------------------------------------------------------------------- #
# SARIF export
# --------------------------------------------------------------------------- #
def test_sarif_export():
    from app.diff_core import detect_changes
    from app.sarif import export_sarif
    old = json.dumps(_oa({"/users": {"get": _op()}}))
    new = json.dumps(_oa({}))
    report = detect_changes(old, new, "openapi")
    sarif = export_sarif(report)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "Contract Guard"
    assert len(sarif["runs"][0]["results"]) > 0


# --------------------------------------------------------------------------- #
# Chain diff
# --------------------------------------------------------------------------- #
def test_chain_diff():
    from app.diff_core import detect_changes
    v1 = json.dumps(_oa({"/users": {"get": _op()}}))
    v2 = json.dumps(_oa({"/users": {"get": _op()}, "/posts": {"get": _op()}}))
    v3 = json.dumps(_oa({"/users": {"get": _op()}}))

    r1 = detect_changes(v1, v2, "openapi")
    r2 = detect_changes(v2, v3, "openapi")

    assert r1.breaking is False
    assert r2.breaking is True
    assert r2.breaking_count >= 1