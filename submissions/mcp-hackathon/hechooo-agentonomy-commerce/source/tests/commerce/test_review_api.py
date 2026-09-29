from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TOKEN = "review-token-" + "a" * 40
COMMIT = "a" * 40


class Bridge:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def request(self, method, arguments=None):
        self.calls.append((method, arguments))
        if method == "snapshot":
            return {"remaining_amount_usdc": "1.00", "real_funds": False}
        if method == "search":
            return {"count": 1, "items": [{"offering_id": "csv-reconciliation-v1"}]}
        if method == "purchase":
            return {"_error": "not_found"}
        return {"preview_id": "preview_test", "state": "preview_created"}

    def close(self):
        pass


def app_for(tmp_path, **changes):
    from agentonomy_commerce.api import create_app
    from agentonomy_commerce.settings import Settings

    values = dict(state_dir=tmp_path, api_token=TOKEN, source_commit=COMMIT,
                  project_slug="hechooo-agentonomy-commerce", merchant_port=18081)
    values.update(changes)
    return create_app(Settings(**values), bridge_factory=Bridge)


def test_health_and_proof_are_public_and_exact(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["commit"] == COMMIT
        assert health.json()["real_funds"] is False
        assert client.get("/.well-known/xagent-verification.json").json() == {
            "schemaVersion": 1, "slug": "hechooo-agentonomy-commerce", "commit": COMMIT}


def test_missing_or_wrong_auth_never_calls_capability(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        assert client.get("/v1/services").status_code == 401
        assert client.get("/v1/services", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/v1/services", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.json()["settlement_mode"] == "simulated"


def test_preview_requires_idempotency_and_rejects_identity_override(tmp_path):
    with TestClient(app_for(tmp_path), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        body = {"offering_id": "csv-reconciliation-v1", "csv_text": "sensitive-value"}
        assert client.post("/v1/previews", json=body).status_code == 422
        response = client.post("/v1/previews", json={**body, "user_id": "attacker"},
                               headers={"Idempotency-Key": "test-1"})
        assert response.status_code == 422
        assert "sensitive-value" not in response.text
        ok = client.post("/v1/previews", json=body, headers={"Idempotency-Key": "test-1"})
        assert ok.status_code == 200
        assert ok.json()["real_funds"] is False


def test_body_limit_and_structured_not_found(tmp_path):
    with TestClient(app_for(tmp_path), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = client.post("/v1/previews", content=b"x" * 262145)
        assert response.status_code == 413
        assert client.get("/v1/purchases/purchase_missing").status_code == 404


def test_rate_limit_is_enforced(tmp_path):
    with TestClient(app_for(tmp_path, requests_per_minute=2),
                    headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        assert client.get("/v1/budget").status_code == 200
        assert client.get("/v1/budget").status_code == 200
        assert client.get("/v1/budget").status_code == 429


@pytest.mark.parametrize("changes", [{"api_token": ""}, {"api_token": "short"},
                                    {"source_commit": "main"}, {"project_slug": "../evil"}])
def test_invalid_deployment_configuration_fails_closed(tmp_path, changes):
    with pytest.raises(ValueError):
        app_for(tmp_path, **changes)


def test_unresponsive_worker_is_closed_and_health_becomes_unavailable(tmp_path, monkeypatch):
    import threading
    from agentonomy_commerce import api
    from agentonomy_commerce.settings import Settings

    closed = threading.Event()

    class BlockedBridge(Bridge):
        def request(self, method, arguments=None):
            if method == "search":
                closed.wait(timeout=2)
            return super().request(method, arguments)

        def close(self):
            closed.set()

    monkeypatch.setattr(api, "CALL_TIMEOUT_SECONDS", 0.01, raising=False)
    settings = Settings(tmp_path, TOKEN, COMMIT, "hechooo-agentonomy-commerce")
    with TestClient(api.create_app(settings, bridge_factory=BlockedBridge), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        assert client.get("/v1/services").status_code == 503
        assert closed.is_set()
        assert client.get("/health").status_code == 503


def test_review_page_assets_are_public_and_do_not_cache_credentials(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert page.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/style.css").status_code == 200
        assert client.get("/assets/../../settings.py").status_code == 404
        assert client.get("/v1/budget").status_code == 401


def test_health_detects_exited_worker_before_next_purchase(tmp_path):
    from types import SimpleNamespace
    with TestClient(app_for(tmp_path)) as client:
        client.app.state.bridge.process = SimpleNamespace(poll=lambda: 1)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
