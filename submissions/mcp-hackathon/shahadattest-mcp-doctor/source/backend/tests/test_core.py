from app.services.importer import parse_spec_content, extract_endpoints
from app.services.analyzer import analyze_endpoints
from app.services.scoring import compute_score
from app.services.repair import apply_repairs
from app.core.security import validate_url_for_fetch
import pytest
from fastapi import HTTPException


def sample_spec():
    return {"openapi": "3.0.0", "info": {"title": "t", "version": "1"},
            "servers": [{"url": "https://example.com"}],
            "paths": {"/weather": {"get": {"operationId": "getWeather", "summary": "Get weather",
                     "parameters": [{"name": "q", "in": "query"}],
                     "responses": {"200": {"description": "ok"}}}}}}


def test_parse_valid():
    spec = parse_spec_content(sample_spec())
    assert spec["openapi"] == "3.0.0"


def test_parse_invalid_rejected():
    with pytest.raises(ValueError):
        parse_spec_content({"info": {}})


def test_extract_endpoints():
    eps = extract_endpoints(sample_spec())
    assert len(eps) == 1 and eps[0]["method"] == "GET"


def test_scoring_deterministic():
    eps = extract_endpoints(sample_spec())
    a1, i1 = analyze_endpoints(eps)
    a2, i2 = analyze_endpoints(eps)
    assert compute_score(a1, i1) == compute_score(a2, i2)


def test_repair_extract_number():
    out = apply_repairs({"tmp": "31 C"}, [{"source_field": "tmp", "target_field": "temperature_celsius", "transform": "extract_number"}])
    assert out["temperature_celsius"] == 31


def test_repair_price_string():
    out = apply_repairs({"price": "149.99"}, [{"source_field": "price", "target_field": "price", "transform": "extract_number"}])
    assert abs(out["price"] - 149.99) < 0.001


def test_ssrf_blocked():
    for bad in ["http://localhost:8000/x", "http://127.0.0.1/", "http://0.0.0.0/", "http://169.254.169.254/"]:
        with pytest.raises(HTTPException):
            validate_url_for_fetch(bad)


def test_proxy_output_shape():
    # normalized proxy output must contain success/operation/data keys (contract)
    sample = {"success": True, "operation": "get_weather", "latency_ms": 10, "data": {"temperature_celsius": 31}}
    assert set(sample) >= {"success", "operation", "data"}
