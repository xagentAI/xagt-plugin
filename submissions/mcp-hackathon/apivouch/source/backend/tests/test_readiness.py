import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core import config, signing
from app.models import db


@pytest.mark.parametrize("url", [
    "http://example.com", "https://user:secret@example.com", "https://@example.com",
    "https://example.com/path", "https://example.com//", "https://example.com?",
    "https://example.com#", "https://example.com:0", "https://example.com:65536",
    "https://example.com:", " https://example.com", "https://example.com\n",
    "https://example.com\\evil", "https://example%2ecom", "https://-bad.example",
    "https://example..com", "ftp://localhost", "http://127.0.0.1.evil", "https://[bad]",
])
def test_invalid_public_origins(url):
    with pytest.raises(ValueError, match="^Invalid public origin$"):
        config.validate_public_base_url(url)


@pytest.mark.parametrize("url", ["", "https://example.com", "https://example.com:8443/",
                                     "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_public_origins(url):
    assert config.validate_public_base_url(url) == url.removesuffix("/")


def test_deployment_config(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL_VALID", True)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL_CONFIGURED", False)
    monkeypatch.setattr(config, "GIT_COMMIT", "dev-local")
    assert config.deployment_config_ready()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL_CONFIGURED", True)
    for commit in ["dev-local", "a" * 39, "A" * 40, "a" * 40 + "\n"]:
        monkeypatch.setattr(config, "GIT_COMMIT", commit)
        assert not config.deployment_config_ready()
    monkeypatch.setattr(config, "GIT_COMMIT", "a" * 40)
    assert config.deployment_config_ready()
    monkeypatch.setattr(config, "PROJECT_SLUG", "other")
    assert not config.deployment_config_ready()


def test_readiness_and_proof_ignore_headers(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://review.example")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL_CONFIGURED", True)
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.SigningConfig())
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"configuration": True, "database": True, "signing": True}
    proof = client.get("/.well-known/xagent-verification.json", headers={
        "host": "evil.example", "x-forwarded-host": "secret.example", "x-forwarded-proto": "http"}).json()
    assert proof["apiBaseUrl"] == "https://review.example"
    assert proof["readinessUrl"] == "https://review.example/ready"
    assert "signingKeyUrl" not in proof
    monkeypatch.setenv("RECEIPT_SIGNING_PRIVATE_KEY_B64", "YQ==")
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.load_signing_config())
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


@pytest.mark.parametrize("required", ["true", "invalid"])
def test_signing_required_stays_live(monkeypatch, required):
    monkeypatch.delenv("RECEIPT_SIGNING_PRIVATE_KEY_B64", raising=False)
    monkeypatch.setenv("REQUIRE_SIGNED_RECEIPTS", required)
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.load_signing_config())
    client = TestClient(main.app)
    assert client.get("/health").json()["status"] == "ok"
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["signing"] is False


def test_invalid_config_safe(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL_VALID", False)
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503
    response = client.get("/.well-known/xagent-verification.json")
    assert response.status_code == 503
    assert response.json() == {"detail": "Deployment configuration unavailable"}


def test_database_errors_and_timeout_are_bounded(monkeypatch):
    class Unavailable:
        def connect(self):
            raise RuntimeError("postgres://user:secret@private traceback")

    monkeypatch.setattr(db, "engine", Unavailable())
    monkeypatch.setattr(db, "_probe", None)
    client = TestClient(main.app)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False
    assert "secret" not in response.text and "traceback" not in response.text
    released = threading.Event()
    calls = []

    class Stalled:
        def connect(self):
            calls.append(1)
            released.wait(5)
            raise RuntimeError("secret")

    monkeypatch.setattr(db, "engine", Stalled())
    monkeypatch.setattr(db, "READINESS_TIMEOUT", 0.05)
    try:
        started = time.monotonic()
        for _ in range(3):
            assert client.get("/ready").status_code == 503
            assert client.get("/health").status_code == 200
        assert time.monotonic() - started < 1.5
        assert len(calls) == 1
    finally:
        released.set()
        db._probe.result(timeout=2)
