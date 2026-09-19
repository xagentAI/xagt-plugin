from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Tiny", "version": "1"},
    "servers": [{"url": "https://example.com"}],
    "paths": {"/status": {"get": {"summary": "Status", "responses": {"200": {"description": "ok"}}}}},
}


def create_project() -> str:
    response = client.post("/api/projects", json={"name": "Tiny API", "openapi_json": SPEC})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_health_and_verification_are_commit_bound():
    health = client.get("/health").json()
    proof = client.get("/.well-known/xagent-verification.json").json()
    assert health["status"] == "ok"
    assert len(health["commit"]) == 40
    assert {key: proof[key] for key in ("schemaVersion", "slug", "commit")} == {
        "schemaVersion": 1, "slug": "apivouch", "commit": health["commit"]}
    assert proof["healthCheckUrl"] == "/health"
    assert proof["readinessUrl"] == "/ready"
    assert proof["mcpEndpoint"] == "/mcp"


def test_project_contract_export_and_dynamic_mcp_flow():
    pid = create_project()
    project = client.get(f"/api/projects/{pid}").json()
    assert project["score"]["method"] == "deterministic-v1"
    assert client.get(f"/api/projects/{pid}/tools").json() == []

    generated = client.post(f"/api/projects/{pid}/contract").json()
    comparison = generated["comparison"]
    assert comparison["basis"].endswith("no simulated score")
    assert comparison["after_score"] >= comparison["before_score"]
    assert client.get(f"/api/projects/{pid}/comparison").json() == comparison
    assert client.get(f"/api/projects/{pid}/contract").status_code == 200

    initialize = client.post(f"/mcp/{pid}", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}).json()
    assert initialize["result"]["serverInfo"]["name"] == "APIVouch Agent Adapter"
    listed = client.post(f"/mcp/{pid}", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    assert listed["result"]["tools"][0]["name"] == "get_status"
    assert listed["result"]["tools"][-1]["name"] == "apivouch_prove_exhaustive_claim"

    exported = client.get(f"/api/projects/{pid}/export").json()
    assert exported["format"] == "apivouch-agent-pack-v1"
    assert exported["agent_contract"]
    assert exported["mcp_endpoint"] == f"/mcp/{pid}"


def test_unknown_mcp_tool_returns_protocol_error():
    pid = create_project()
    response = client.post(f"/mcp/{pid}", json={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "missing", "arguments": {}}}).json()
    assert response["error"]["code"] == -32602


def test_product_mcp_exposes_verified_outcome_router():
    initialized = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).json()
    assert initialized["result"]["serverInfo"]["name"] == "APIVouch Outcome Router"
    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    tool = listed["result"]["tools"][0]
    assert tool["name"] == "apivouch_resolve_verified_outcome"
    assert tool["annotations"]["readOnlyHint"] is True


def test_outcome_api_rejects_same_origin_aliases_before_network():
    response = client.post(
        "/api/outcomes/execute",
        json={
            "goal": "Resolve the same fact",
            "providers": [
                {"name": "first", "url": "https://example.com/a"},
                {"name": "second", "url": "https://example.com/b"},
            ],
            "constraints": {"minimum_agreement": 2},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Every provider must use a distinct network origin"


def test_delete_project_is_recoverably_scoped():
    pid = create_project()
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_proof_request_rejects_client_supplied_evidence():
    pid = create_project()
    response = client.post(
        f"/api/projects/{pid}/prove",
        json={"operation_id": "get_status", "claim_type": "ALL", "records_seen": 1_000_000, "has_more": False},
    )
    assert response.status_code == 422
