# -*- coding: utf-8 -*-
"""Unit tests for the CI gate (POST /v1/gate + check_gate policy)."""
import json

from fastapi.testclient import TestClient

from app.gate import evaluate_gate
from app.main import app

client = TestClient(app)


def _oa(paths):
    return json.dumps(
        {"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "paths": paths}
    )


def _resp(schema=None):
    r = {"description": "ok"}
    if schema is not None:
        r["content"] = {"application/json": {"schema": schema}}
    return {"200": r}


OPENAPI_BREAK_OLD = _oa(
    {
        "/users": {"get": {"responses": _resp()}},
        "/posts": {"get": {"responses": _resp()}},
    }
)
OPENAPI_BREAK_NEW = _oa({"/users": {"get": {"responses": _resp()}}})

# non-breaking: only a new field added
OPENAPI_SOFT_OLD = _oa(
    {
        "/users": {
            "get": {
                "responses": _resp(
                    {"type": "object", "properties": {"id": {"type": "integer"}}}
                )
            }
        }
    }
)
OPENAPI_SOFT_NEW = _oa(
    {
        "/users": {
            "get": {
                "responses": _resp(
                    {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string"},
                        },
                    }
                )
            }
        }
    }
)


# --------------------------------------------------------------------------- #
# evaluate_gate
# --------------------------------------------------------------------------- #
def test_gate_blocks_any_breaking_by_default():
    r = evaluate_gate(OPENAPI_BREAK_OLD, OPENAPI_BREAK_NEW, "openapi")
    assert r["passed"] is False
    assert len(r["blocked_by"]) == 1
    b = r["blocked_by"][0]
    assert b["change_type"] == "endpoint_removed"
    assert b["severity"] == "critical"
    assert b["location"] == "GET /posts"
    assert b["hint"]
    assert r["breaking_count"] == 1
    assert r["total_changes"] == 1


def test_gate_passes_for_non_breaking_change():
    r = evaluate_gate(OPENAPI_SOFT_OLD, OPENAPI_SOFT_NEW, "openapi")
    assert r["passed"] is True
    assert r["blocked_by"] == []
    assert r["breaking_count"] == 0


def test_gate_allow_breaking_true_always_passes():
    r = evaluate_gate(
        OPENAPI_BREAK_OLD, OPENAPI_BREAK_NEW, "openapi", allow_breaking=True
    )
    assert r["passed"] is True
    assert r["blocked_by"] == []


def test_gate_allow_breaking_false_blocks():
    r = evaluate_gate(
        OPENAPI_BREAK_OLD, OPENAPI_BREAK_NEW, "openapi", allow_breaking=False
    )
    assert r["passed"] is False
    assert len(r["blocked_by"]) == 1


def test_gate_max_severity_major_blocks_only_critical():
    r = evaluate_gate(
        OPENAPI_BREAK_OLD, OPENAPI_BREAK_NEW, "openapi", max_severity="major"
    )
    assert r["passed"] is False
    assert r["blocked_by"][0]["severity"] == "critical"


def test_gate_blocks_with_consumer_profile_hits_the_consumer():
    # /posts is removed, but a consumer that only uses /users is not affected
    r = evaluate_gate(
        OPENAPI_BREAK_OLD,
        OPENAPI_BREAK_NEW,
        "openapi",
        consumer_profile={"paths": ["/users"]},
    )
    assert r["passed"] is True
    assert r["consumer_aware"] is True
    assert r["blocked_by"] == []

    # a consumer that uses /posts IS affected
    r2 = evaluate_gate(
        OPENAPI_BREAK_OLD,
        OPENAPI_BREAK_NEW,
        "openapi",
        consumer_profile={"paths": ["/posts"]},
    )
    assert r2["passed"] is False
    assert r2["blocked_by"][0]["location"] == "GET /posts"


def test_gate_blocks_detects_required_field_added():
    old = _oa(
        {
            "/users": {
                "get": {
                    "responses": _resp(
                        {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "email": {"type": "string"},
                            },
                            "required": ["id"],
                        }
                    )
                }
            }
        }
    )
    new = _oa(
        {
            "/users": {
                "get": {
                    "responses": _resp(
                        {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "email": {"type": "string"},
                            },
                            "required": ["id", "email"],
                        }
                    )
                }
            }
        }
    )
    r = evaluate_gate(old, new, "openapi")
    assert r["passed"] is False
    assert any(b["change_type"] == "required_field_added" for b in r["blocked_by"])


# --------------------------------------------------------------------------- #
# HTTP endpoint
# --------------------------------------------------------------------------- #
def test_gate_endpoint_blocks():
    resp = client.post(
        "/v1/gate",
        json={
            "format": "openapi",
            "old_spec": OPENAPI_BREAK_OLD,
            "new_spec": OPENAPI_BREAK_NEW,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is False
    assert body["blocked_by"][0]["change_type"] == "endpoint_removed"


def test_gate_endpoint_passes_with_consumer_profile():
    resp = client.post(
        "/v1/gate",
        json={
            "format": "openapi",
            "old_spec": OPENAPI_BREAK_OLD,
            "new_spec": OPENAPI_BREAK_NEW,
            "consumer_profile": {"paths": ["/users"]},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["consumer_aware"] is True


def test_gate_endpoint_invalid_format_returns_400():
    resp = client.post(
        "/v1/gate",
        json={"format": "xml", "old_spec": "<a/>", "new_spec": "<b/>"},
    )
    assert resp.status_code == 400


def test_gate_endpoint_has_deterministic_output():
    body1 = client.post(
        "/v1/gate",
        json={"format": "openapi", "old_spec": OPENAPI_BREAK_OLD, "new_spec": OPENAPI_BREAK_NEW},
    ).json()
    body2 = client.post(
        "/v1/gate",
        json={"format": "openapi", "old_spec": OPENAPI_BREAK_OLD, "new_spec": OPENAPI_BREAK_NEW},
    ).json()
    assert body1 == body2