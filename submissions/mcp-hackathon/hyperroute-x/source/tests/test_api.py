import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import SERVICE_SLUG, GIT_COMMIT

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["commit"] == GIT_COMMIT
    assert data["version"] == GIT_COMMIT
    assert data["slug"] == SERVICE_SLUG
    assert response.headers.get("x-source-commit") == GIT_COMMIT


def test_deployment_proof_endpoint():
    response = client.get("/.well-known/xagent-verification.json")
    assert response.status_code == 200
    data = response.json()
    assert data["schemaVersion"] == 1
    assert data["slug"] == SERVICE_SLUG
    assert data["commit"] == GIT_COMMIT


def test_quote_endpoint():
    payload = {
        "token_in": "OKB",
        "token_out": "USDT",
        "amount_in": "2.0",
        "max_slippage_bps": 50
    }
    response = client.post("/api/v1/quote", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["token_in"]["symbol"] == "OKB"
    assert data["token_out"]["symbol"] == "USDT"
    assert float(data["estimated_amount_out_formatted"]) > 80.0
    assert "route" in data
    assert len(data["route"]) >= 1


def test_build_tx_endpoint():
    # 1. Get quote
    quote_resp = client.post("/api/v1/quote", json={
        "token_in": "OKB",
        "token_out": "USDT",
        "amount_in": "1.0"
    })
    assert quote_resp.status_code == 200
    quote_data = quote_resp.json()

    # 2. Build transaction
    build_payload = {
        "recipient_wallet": "0x1111111111111111111111111111111111111111",
        "quote": quote_data,
        "deadline_seconds": 600
    }
    tx_resp = client.post("/api/v1/build-tx", json=build_payload)
    assert tx_resp.status_code == 200
    tx_data = tx_resp.json()
    assert tx_data["to"].startswith("0x")
    assert tx_data["data"].startswith("0x04e45aaf")
    assert tx_data["chain_id"] == 196
    assert tx_data["gas_limit"] > 100000


def test_simulate_endpoint():
    payload = {
        "to": "0x098d6B00041B1F3415c48b2E15a6b0c2A8F70570",
        "from_address": "0x1111111111111111111111111111111111111111",
        "data": "0x04e45aaf0000000000000000000000000000000000000000000000000000000000000020",
        "value": "0x0",
        "chain_id": 196
    }
    response = client.post("/api/v1/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "simulation_mode" in data


def test_simulate_endpoint_invalid_address():
    payload = {
        "to": "0xinvalid",
        "from_address": "0x1111111111111111111111111111111111111111",
        "data": "0x12345678"
    }
    response = client.post("/api/v1/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Invalid target 'to' address" in data["revert_reason"]


def test_mcp_tools_endpoint():
    response = client.get("/api/v1/mcp/tools")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["mcpVersion"] == "1.0.0"
    assert "tools" in manifest
    tool_names = [t["name"] for t in manifest["tools"]]
    assert "get_swap_quote" in tool_names
    assert "build_swap_transaction" in tool_names
    assert "simulate_swap_transaction" in tool_names


def test_root_endpoint_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    content = response.text
    assert "HyperRoute X" in content
    assert "X Layer" in content
    assert "tokenModalMask" in content
    assert "tokenSearchInput" in content
    assert "walletModalMask" in content
    assert "starsCanvas" in content
    assert "modalTokenList" in content
    assert "connectWalletBtn" in content
    assert "conduitPixels" in content
    assert "COMMIT" in content



def test_root_endpoint_json():
    # Test JSON content negotiation via Accept header
    response = client.get("/", headers={"accept": "application/json"})
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "hyperroute-x"
    assert data["slug"] == SERVICE_SLUG
    assert data["commit"] == GIT_COMMIT
    assert data["status"] == "active"

    # Test query param format=json
    response_query = client.get("/?format=json")
    assert response_query.status_code == 200
    assert response_query.json()["slug"] == SERVICE_SLUG

