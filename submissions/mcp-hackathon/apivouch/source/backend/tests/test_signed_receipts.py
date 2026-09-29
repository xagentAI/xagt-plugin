import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.core import signing
from app.main import app
from app.services import outcomes


def load_example():
    path = Path(__file__).resolve().parents[2] / "examples" / "verify_outcome_receipt.py"
    spec = importlib.util.spec_from_file_location("offline_receipt", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def configure(monkeypatch):
    for name in ("REQUIRE_SIGNED_RECEIPTS", "RECEIPT_SIGNING_PRIVATE_KEY_B64", "RECEIPT_SIGNING_KEY_ID"):
        monkeypatch.delenv(name, raising=False)

    def load(**env):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        config = signing.load_signing_config()
        monkeypatch.setattr(signing, "SIGNING_CONFIG", config)
        return config

    return load


def temporary_secret():
    return base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii")


def refused_request():
    return {"goal": "Refuse unaffordable providers", "providers": [
        {"name": name, "url": f"https://{name}.example/value", "price_usd": 1}
        for name in ("alpha", "beta")], "constraints": {
            "max_price_usd": 0, "max_latency_ms": 1000, "minimum_agreement": 2, "numeric_tolerance_percent": 0}}


def test_signed_rest_mcp_offline_and_independent_contract(configure):
    secret = temporary_secret()
    config = configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=secret, REQUIRE_SIGNED_RECEIPTS="true")
    assert config.ready and config.enabled and secret not in repr(config)
    client = TestClient(app)
    public = client.get("/.well-known/apivouch-signing-key.json").json()
    assert set(public) == {"schemaVersion", "slug", "algorithm", "keyId", "publicKey", "commit"}
    assert len(public["keyId"]) == 40
    assert secret not in json.dumps(public)
    receipt = client.post("/api/outcomes/demo").json()
    assert receipt["format"] == "apivouch-outcome-receipt-v2"
    assert load_example().verify(receipt)
    assert load_example().authenticity(receipt, public) == {"state": "signed", "valid": True}
    # Exercise A's actual independent v2 checker without changing its implementation.
    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_deployment.py"
    spec = importlib.util.spec_from_file_location("independent_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verifier = module.Verifier("https://example.com", public["commit"], "deterministic")
    verifier.http = lambda path: public
    try:
        verifier.integrity(receipt)
    finally:
        verifier.client.close()
    stored = client.get("/api/outcomes/receipts/" + receipt["receipt_id"]).json()
    assert stored["receipt"] == receipt
    assert stored["authenticity"] == {"state": "signed", "valid": True}
    rpc = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "apivouch_verify_receipt", "arguments": {"receipt_id": receipt["receipt_id"]}}}).json()["result"]
    assert rpc["structuredContent"] == stored == json.loads(rpc["content"][0]["text"])
    refused = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "apivouch_resolve_verified_outcome", "arguments": refused_request()}}).json()["result"]
    assert refused["isError"] and refused["structuredContent"]["verdict"] == "UNVERIFIED"
    assert load_example().authenticity(refused["structuredContent"], public)["valid"]


@pytest.mark.parametrize("fault", ["payload", "rehash", "signature", "missing_signature", "metadata", "wrong_key", "key_id", "commit", "algorithm"])
def test_tampering_separates_integrity_and_authenticity(configure, fault):
    configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=temporary_secret())
    client = TestClient(app)
    receipt = client.post("/api/outcomes/demo").json()
    public = client.get("/.well-known/apivouch-signing-key.json").json()
    if fault in {"payload", "rehash"}:
        receipt["result"] = 999
        if fault == "rehash":
            fp = outcomes.receipt_fingerprint(receipt)
            receipt["integrity"]["fingerprint"] = fp
            receipt["receipt_id"] = fp[7:31]
    elif fault == "signature":
        receipt["integrity"]["signature"] = base64.b64encode(b"x" * 64).decode()
    elif fault == "missing_signature":
        receipt["integrity"].pop("signature")
    elif fault == "metadata":
        receipt["authenticity"]["key_id"] = "other"
    elif fault == "wrong_key":
        public["publicKey"] = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()
    elif fault == "key_id":
        public["keyId"] = "other"
    elif fault == "commit":
        public["commit"] = "b" * 40
    else:
        receipt["integrity"]["algorithm"] = "other"
    assert load_example().authenticity(receipt, public) == {"state": "invalid", "valid": False}
    assert outcomes.verify_receipt(receipt) is (fault not in {"payload", "metadata"})


@pytest.mark.parametrize("env", [
    {"REQUIRE_SIGNED_RECEIPTS": "true"},
    {"REQUIRE_SIGNED_RECEIPTS": "TRUE"},
    {"REQUIRE_SIGNED_RECEIPTS": "1"},
    {"REQUIRE_SIGNED_RECEIPTS": " false"},
    {"RECEIPT_SIGNING_PRIVATE_KEY_B64": ""},
    {"RECEIPT_SIGNING_PRIVATE_KEY_B64": "secret-not-base64"},
    {"RECEIPT_SIGNING_KEY_ID": "orphan"},
    {"RECEIPT_SIGNING_KEY_ID": "unsafe\nvalue"},
    {"RECEIPT_SIGNING_KEY_ID": "x" * 65},
])
def test_invalid_configuration_safe_503_and_health(configure, env, monkeypatch):
    config = configure(**env)
    assert not config.ready
    assert config.error in {"invalid_requirement", "missing_key", "invalid_private_key", "invalid_key_id"}
    async def no_network(*args):
        pytest.fail("Invalid signing configuration must fail before provider calls")
    monkeypatch.setattr(outcomes, "safe_request", no_network)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    for path in ("/api/outcomes/demo", "/api/outcomes/live-demo", "/api/outcomes/execute", "/mcp"):
        body = refused_request() if path != "/mcp" else {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "apivouch_resolve_verified_outcome", "arguments": refused_request()}}
        response = client.post(path, json=body)
        assert response.status_code == 503
        assert response.json() == {"detail": "Receipt signing unavailable"}
    assert client.get("/.well-known/apivouch-signing-key.json").status_code == 503


def test_strict_private_encoding_and_override(configure):
    secret = temporary_secret()
    for bad in (secret + "\n", secret.rstrip("="), secret + "=", "!" + secret[1:],
                base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw() + b"x").decode()):
        config = configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=bad)
        assert config.error == "invalid_private_key"
        assert bad not in repr(config)
    config = configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=secret, RECEIPT_SIGNING_KEY_ID="release-2026.09_1")
    assert config.key_id == "release-2026.09_1"
    assert config.ready


def test_unsigned_legacy_and_no_key_discovery(configure):
    config = configure()
    assert config.ready and not config.required and not config.enabled
    client = TestClient(app)
    assert client.get("/.well-known/apivouch-signing-key.json").status_code == 404
    receipt = client.post("/api/outcomes/demo").json()
    assert receipt["format"] == "apivouch-outcome-receipt-v1"
    assert "authenticity" not in receipt and "signature" not in receipt["integrity"]
    original = copy.deepcopy(receipt)
    configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=temporary_secret(), REQUIRE_SIGNED_RECEIPTS="true")
    assert outcomes.verify_receipt(receipt)
    assert outcomes.receipt_authenticity(receipt) == {"state": "unsigned", "valid": False}
    assert load_example().authenticity(receipt) == {"state": "unsigned", "valid": False}
    assert receipt == original


def test_runtime_signing_error_is_safe(configure, monkeypatch):
    config = configure(RECEIPT_SIGNING_PRIVATE_KEY_B64=temporary_secret())

    class BrokenKey:
        def sign(self, message):
            raise RuntimeError("private diagnostic must not escape")

    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.SigningConfig(key_id=config.key_id, _key=BrokenKey()))
    response = TestClient(app).post("/api/outcomes/demo")
    assert response.status_code == 503
    assert response.json() == {"detail": "Receipt signing unavailable"}
