# -*- coding: utf-8 -*-
"""Unit tests for consumer-aware impact scan and transitive propagation."""
import json

from app.impact import (
    build_reference_graph,
    compute_affected_operations,
    matches_profile,
    scan_consumer_impact,
)

OA_V1 = """openapi: 3.0.3
info: {title: Pets, version: 1.0.0}
paths:
  /pets:
    get:
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
    post:
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/NewPet'
      responses:
        '201': {description: created}
  /pets/{id}:
    get:
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
components:
  schemas:
    Pet:
      type: object
      required: [id]
      properties:
        id: {type: integer}
        age: {type: integer}
    NewPet:
      type: object
      required: [name]
      properties:
        name: {type: string}
"""


def _change_type_critical():
    new = OA_V1.replace("id: {type: integer}", "id: {type: string}")
    return OA_V1, new


def _only_newpet_changed():
    new = OA_V1.replace(
        "name: {type: string}",
        "name: {type: string}\n        tag: {type: string}",
    )
    return OA_V1, new


def test_consumer_path_hits_only_used_endpoint():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi", consumer_profile={"paths": ["/pets"]})
    assert r["consumer_aware"] is True
    assert r["consumer_affected"] is True
    assert r["hit_count"] >= 1
    assert r["hit_count"] < r["total_changes"]
    assert all("GET /pets" in str(h["location"]) for h in r["hits"])


def test_consumer_miss_when_unrelated_path():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi", consumer_profile={"paths": ["/unrelated"]})
    assert r["consumer_affected"] is False
    assert r["hit_count"] == 0
    assert r["miss_count"] == r["total_changes"]


def test_consumer_schema_profile_matches_component_change():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi", consumer_profile={"schemas": ["Pet"]})
    assert r["consumer_affected"] is True
    assert any(h["location"].startswith("#/components/schemas/Pet") for h in r["hits"])


def test_consumer_field_profile_prefix_match():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi", consumer_profile={"fields": ["#/components/schemas/Pet.id"]})
    assert r["consumer_affected"] is True


def test_no_profile_means_full_impact():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi")
    assert r["consumer_aware"] is False
    assert r["consumer_affected"] == r["breaking"]
    assert r["hit_count"] == r["total_changes"]
    assert r["miss_count"] == 0


def test_transitive_propagation_to_all_referencing_operations():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi")
    ops = r["impact"]["affected_operations"]
    assert "GET /pets" in ops
    assert "GET /pets/{id}" in ops
    assert "POST /pets" not in ops


def test_transitive_propagation_newpet_change_hits_post():
    old = OA_V1
    new = OA_V1.replace("name: {type: string}", "name: {type: integer}")
    r = scan_consumer_impact(old, new, "openapi")
    ops = r["impact"]["affected_operations"]
    assert "POST /pets" in ops
    assert "GET /pets" not in ops


def test_component_finding_gets_affected_operations():
    old, new = _change_type_critical()
    r = scan_consumer_impact(old, new, "openapi")
    schema_finding = next(h for h in r["hits"] if h["location"].startswith("#/components/schemas/Pet"))
    assert "GET /pets" in schema_finding["affected_operations"]
    assert "GET /pets/{id}" in schema_finding["affected_operations"]


def test_reference_graph_built_from_doc():
    import yaml
    doc = yaml.safe_load(OA_V1)
    graph = build_reference_graph(doc)
    assert "Pet" in graph
    assert set(graph["Pet"]) == {"GET /pets", "GET /pets/{id}"}
    assert "NewPet" in graph
    assert graph["NewPet"] == ["POST /pets"]


def test_graphql_scan_no_operations():
    gql_old = "type Query { pet: Pet }\ntype Pet { id: ID! }"
    gql_new = "type Query { pet: Pet }\ntype Pet { id: String! }"
    r = scan_consumer_impact(gql_old, gql_new, "graphql", consumer_profile={"schemas": ["Pet"]})
    assert r["consumer_aware"] is True
    assert r["consumer_affected"] is True
    assert r["impact"]["affected_operations"] == []


def test_json_schema_field_profile():
    js_old = json.dumps({"type": "object", "properties": {"id": {"type": "integer"}, "age": {"type": "integer"}}})
    js_new = json.dumps({"type": "object", "properties": {"id": {"type": "string"}, "age": {"type": "integer"}}})
    r = scan_consumer_impact(js_old, js_new, "json-schema", consumer_profile={"fields": ["$.properties.id"]})
    assert r["consumer_affected"] is True
    assert any("$.properties.id" in h["location"] for h in r["hits"])


def test_matches_profile_helpers():
    from app.engines.base import make_finding
    from app.models import FORMAT_OPENAPI
    f = make_finding("field_removed", True, "critical", "GET /pets -> response 200.age",
                     "x", fmt=FORMAT_OPENAPI)
    hit, reason = matches_profile(f, {"paths": ["/pets"]})
    assert hit and reason
    hit2, _ = matches_profile(f, {"paths": ["/zoo"]})
    assert not hit2