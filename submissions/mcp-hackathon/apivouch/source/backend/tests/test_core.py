import pytest
from fastapi import HTTPException

from app.core.security import validate_url_for_fetch
from app.services.analyzer import analyze_endpoints
from app.services.contract import build_agent_contract
from app.services.importer import (
    extract_endpoints,
    parse_spec_content,
    resolve_local_ref,
)
from app.services.schemas import (
    infer_schema,
    infer_schema_from_samples,
    shape_signature,
    validate_instance,
)
from app.services.scoring import compute_score
from app.services.tester import prepare_request, probe_endpoint
from app.services.tools import generate_tools


def sample_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Sample", "version": "1"},
        "servers": [{"url": "https://example.com/api"}],
        "components": {"schemas": {"Weather": {"type": "object", "required": ["temp"], "properties": {"temp": {"type": "number"}}}}},
        "paths": {
            "/weather/{city}": {
                "parameters": [{"name": "city", "in": "path", "required": True, "schema": {"type": "string"}}],
                "get": {
                    "operationId": "getWeather",
                    "summary": "Get weather for a city",
                    "parameters": [{"name": "units", "in": "query", "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Weather"}}}}},
                },
            },
            "/orders": {"post": {"summary": "Create an order", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, "responses": {"201": {"description": "created"}}}},
        },
    }


def test_parse_json_yaml_and_reject_invalid():
    assert parse_spec_content(sample_spec())["openapi"] == "3.0.3"
    assert parse_spec_content("openapi: 3.0.3\ninfo: {title: x, version: '1'}\npaths: {}")['info']['title'] == "x"
    with pytest.raises(ValueError):
        parse_spec_content({"info": {}})


def test_extract_merges_path_parameters_and_resolves_response_ref():
    endpoints = extract_endpoints(sample_spec())
    weather = endpoints[0]
    assert {item["name"] for item in weather["parameters"]} == {"city", "units"}
    assert weather["response_schema"]["properties"]["temp"]["type"] == "number"
    assert weather["source_url"] == "https://example.com/api/weather/{city}"


def test_analyzer_marks_side_effects_and_missing_contract_evidence():
    analyses, issues = analyze_endpoints(extract_endpoints(sample_spec()))
    assert any(item["code"] == "SIDE_EFFECT_CONFIRMATION_REQUIRED" for item in issues)
    assert any(item["code"] == "SUCCESS_SCHEMA_MISSING" for item in issues)
    assert analyses[0]["safe_to_auto_test"] is True


def test_scoring_is_deterministic_and_live_evidence_matters():
    analyses, issues = analyze_endpoints(extract_endpoints(sample_spec()))
    before = compute_score(analyses, issues)
    after = compute_score(analyses, issues, [{"status": "passed"}, {"status": "skipped"}])
    assert before == compute_score(analyses, issues)
    assert after["breakdown"]["reliability"] != before["breakdown"]["reliability"]
    assert after["method"] == "deterministic-v1"


def test_inferred_schema_represents_observed_drift():
    schema = infer_schema_from_samples([{"price": "10"}, {"price": 10}])
    assert "oneOf" in schema["properties"]["price"]
    assert not validate_instance({"price": "10"}, schema)


def test_contract_generation_is_evidence_bound_not_simulated():
    spec = sample_spec()
    endpoints = extract_endpoints(spec)
    order = next(item for item in endpoints if item["method"] == "POST")
    tests = [{"operation_id": "getWeather", "observations": [{"success": True, "sample_data": {"temp": 31}}]}]
    contract, changes = build_agent_contract(spec, tests)
    contract_endpoints = extract_endpoints(contract)
    generated_order = next(item for item in contract_endpoints if item["method"] == "POST")
    assert generated_order["operation_id_declared"] is True
    assert any(item["kind"] == "operation_id" for item in changes)
    assert all("basis" in item for item in changes)
    assert order["operation_id"] != generated_order["operation_id"] or generated_order["operation_id"].startswith("post_")


def test_tools_include_body_output_and_safety_annotations():
    tools = generate_tools(extract_endpoints(sample_spec()))
    weather = next(item for item in tools if item["name"] == "get_weather")
    order = next(item for item in tools if item["annotations"]["destructiveHint"])
    assert weather["inputSchema"]["properties"]["city"]["x-location"] == "path"
    assert "body" in order["inputSchema"]["properties"]
    assert order["annotations"]["readOnlyHint"] is False


def test_prepare_request_places_path_and_query_arguments():
    endpoint = extract_endpoints(sample_spec())[0]
    prepared = prepare_request(endpoint, {"city": "New York", "units": "metric"})
    assert prepared["url"].endswith("/weather/New%20York")
    assert prepared["params"] == {"units": "metric"}
    with pytest.raises(ValueError, match="city"):
        prepare_request(endpoint, {})


def test_ssrf_rejects_private_and_credentialed_urls():
    for url in ["http://localhost/x", "http://127.0.0.1/", "http://169.254.169.254/", "https://user:pass@example.com"]:
        with pytest.raises(HTTPException):
            validate_url_for_fetch(url)


def test_server_variables_are_expanded_from_defaults():
    spec = sample_spec()
    spec["servers"] = [{"url": "https://{region}.example.com/{version}", "variables": {"region": {"default": "eu"}, "version": {"default": "v1"}}}]
    assert extract_endpoints(spec)[0]["base_url"] == "https://eu.example.com/v1"


def test_external_refs_are_preserved_without_network_fetching():
    external = {"$ref": "https://example.com/schemas.json#/Weather"}
    assert resolve_local_ref(sample_spec(), external) == external


def test_duplicate_operation_ids_are_reported_and_tool_names_stay_unique():
    spec = sample_spec()
    spec["paths"]["/orders"]["post"]["operationId"] = "getWeather"
    endpoints = extract_endpoints(spec)
    _, issues = analyze_endpoints(endpoints)
    tools = generate_tools(endpoints)
    assert sum(item["code"] == "DUPLICATE_OPERATION_ID" for item in issues) == 2
    assert len({item["name"] for item in tools}) == len(tools)


def test_swagger_contract_keeps_valid_swagger_error_references():
    swagger = {
        "swagger": "2.0",
        "info": {"title": "Legacy", "version": "1"},
        "schemes": ["https"],
        "host": "legacy.example.com",
        "basePath": "/v1",
        "paths": {"/status": {"get": {"responses": {"200": {"description": "ok", "schema": {"type": "object"}}}}}},
    }
    contract, _ = build_agent_contract(swagger)
    assert contract["swagger"] == "2.0"
    assert "openapi" not in contract
    assert contract["paths"]["/status"]["get"]["responses"]["400"]["schema"]["$ref"] == "#/definitions/APIVouchError"
    assert extract_endpoints(contract)[0]["base_url"] == "https://legacy.example.com/v1"


def test_schema_inference_and_signatures_cover_nested_values():
    value = {"active": True, "count": 2, "ratio": 1.5, "items": [{"id": 1}], "missing": None}
    schema = infer_schema(value)
    assert schema["properties"]["active"]["type"] == "boolean"
    assert schema["properties"]["items"]["items"]["type"] == "object"
    assert shape_signature(value)["items"] == [{"id": "integer"}]


def test_schema_validation_reports_precise_location():
    errors = validate_instance({"price": "ten"}, {"type": "object", "properties": {"price": {"type": "number"}}})
    assert errors and errors[0].startswith("price:")


@pytest.mark.asyncio
async def test_probe_never_calls_state_changing_operation():
    endpoint = next(item for item in extract_endpoints(sample_spec()) if item["method"] == "POST")
    result = await probe_endpoint(endpoint)
    assert result["status"] == "skipped"
    assert "never auto-tested" in result["reason"]
