"""Black-box HTTP fixtures, deliberately independent of the application."""

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_deployment.py"
SHA = "a" * 40
RESOLVE = "apivouch_resolve_verified_outcome"
VERIFY = "apivouch_verify_receipt"
MODERN_VERSION = "2026-07-28"
META_PREFIX = "io.modelcontextprotocol/"


def hashed(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class Deployment:
    def __init__(self, version=2, fault=None):
        self.key = Ed25519PrivateKey.generate()
        self.version = version
        self.fault = fault
        self.store = {}
        self.requests = []
        self.modern_methods = []

    def seal(self, receipt):
        if receipt["format"].endswith("v2"):
            receipt["authenticity"] = {"state": "signed", "algorithm": "Ed25519", "key_id": "temporary"}
        fingerprint = hashed({k: v for k, v in receipt.items() if k not in {"receipt_id", "integrity"}})
        receipt["receipt_id"] = fingerprint[7:31]
        receipt["integrity"] = {"algorithm": "SHA-256", "fingerprint": fingerprint, "verifiable": True}
        if receipt["format"].endswith("v2"):
            message = (receipt["format"] + "\n" + fingerprint[7:]).encode()
            receipt["integrity"]["signature"] = base64.b64encode(self.key.sign(message)).decode()
        return receipt

    def receipt(self, kind):
        fixture = kind == "fixture"
        refused = kind == "refused" or (kind == "live" and self.fault in {"live_unavailable", "unverified_result"})
        names = ["Atlas Courier", "Beacon Logistics", "Legacy Ship", "Offline Express"] if fixture else ["alpha", "beta"]
        urls = [self.base] * 4 if fixture else ["https://alpha.example", "https://beta.example"]
        if kind == "live":
            names = ["Frankfurter", "Floatrates", "ExchangeRate-API"]
            urls = ["https://api.frankfurter.app", "https://www.floatrates.com", "https://open.er-api.com"]
        attempts = []
        for i, (name, url) in enumerate(zip(names, urls, strict=True)):
            value = [18.4, 18.44, "call us", None][i] if fixture else 0.9
            accepted = not refused and i < 2
            attempts.append({"name": name, "url": url + "/value", "resolved_origin": url,
                             "status": ("SELECTED" if i == 0 else "ELIGIBLE") if accepted else "REJECTED",
                             "agrees_with_consensus": accepted, "contract_validated": accepted,
                             "price_usd": 0, "latency_ms": 1, "upstream_status": 503 if i == 3 else 200,
                             "value_preview": value, "value_digest": hashed(value),
                             "request_url_digest": hashed(url), "expected_schema_digest": hashed({"type": "number"}),
                             "response_digest": hashed({"value": value}),
                             "reason": None if accepted else ("Schema mismatch: number required" if i == 2 else "HTTP 503")})
        receipt = {"format": f"apivouch-outcome-receipt-v{self.version}", "deployment_commit": SHA,
                   "goal": "fixture" if fixture else "USD to EUR", "created_at": "2026-09-19T00:00:00Z",
                   "verdict": "UNVERIFIED" if refused else "VERIFIED", "result": None if refused else attempts[0]["value_preview"],
                   "selected_provider": None if refused else names[0], "selected_price_usd": 0,
                   "constraints": {"minimum_agreement": 2, "max_price_usd": 0.01, "max_latency_ms": 3000,
                                   "numeric_tolerance_percent": 1 if fixture else 2},
                   "agreement": {"providers": 0 if refused else 2, "required": 2},
                   "provider_independence": {"required": not fixture, "distinct_configured_origins": len(set(urls))},
                   "attempts": attempts}
        if fixture:
            if self.fault == "insufficient_agreement":
                attempts[1].update(status="REJECTED", agrees_with_consensus=False, reason="Insufficient agreement")
                receipt["agreement"]["providers"] = 1
            elif self.fault == "missing_origin":
                attempts[1].pop("resolved_origin")
            elif self.fault == "duplicate_provider":
                attempts[1]["name"] = attempts[0]["name"]
            elif self.fault == "configured_origin_count":
                receipt["provider_independence"]["distinct_configured_origins"] = 4
            elif self.fault == "receipt_commit":
                receipt["deployment_commit"] = "b" * 40
            elif self.fault == "numeric_disagreement":
                attempts[1]["value_preview"] = 99
                attempts[1]["value_digest"] = hashed(99)
            elif self.fault == "failure_attempts":
                attempts[3]["upstream_status"] = 200
        if kind == "live" and self.fault == "duplicated_final_origin":
            attempts[1]["resolved_origin"] = attempts[0]["resolved_origin"]
        if kind == "live" and self.fault == "unverified_result":
            receipt["result"] = 0.9
        if self.fault == "unsigned_" + kind:
            receipt["format"] = "apivouch-outcome-receipt-v1"
        self.seal(receipt)
        if fixture and self.fault == "altered_receipt":
            receipt["goal"] = "tampered secret"
        if fixture and self.fault == "invalid_signature":
            receipt["integrity"]["signature"] = base64.b64encode(b"x" * 64).decode()
        if fixture and self.fault == "missing_signature":
            receipt["integrity"].pop("signature")
        if fixture and self.fault == "altered_authenticity":
            receipt["authenticity"]["key_id"] = "tampered"
        self.store[receipt["receipt_id"]] = copy.deepcopy(receipt)
        return receipt

    @staticmethod
    def content(value, error=False):
        return {"isError": error, "structuredContent": value, "content": [{"type": "text", "text": json.dumps(value)}]}

    def respond(self, path, body, headers):
        self.requests.append(path)
        if path == "/health":
            return {"status": "ok", "service": "apivouch", "commit": "b" * 40 if self.fault == "wrong_commit" else SHA}
        if path == "/.well-known/xagent-verification.json":
            proof = {"schemaVersion": 1, "slug": "wrong" if self.fault == "slug" else "apivouch",
                     "commit": "b" * 40 if self.fault == "proof_mismatch" else SHA,
                     "apiBaseUrl": self.base, "healthCheckUrl": self.base + "/health",
                     "readinessUrl": self.base + "/ready",
                     "productTools": [RESOLVE, VERIFY],
                     "mcpProtocolVersions": ["2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28"],
                     "receiptFormats": ["apivouch-outcome-receipt-v1"],
                     "mcpEndpoint": "https://attacker.example/mcp" if self.fault == "cross_origin" else self.base + "/mcp"}
            if self.version == 2:
                proof["signingKeyUrl"] = self.base + "/.well-known/apivouch-signing-key.json"
                proof["receiptFormats"].append("apivouch-outcome-receipt-v2")
            if self.fault == "missing_url":
                proof.pop("readinessUrl")
            if self.fault == "wrong_path":
                proof["readinessUrl"] = self.base + "/health"
            if self.fault == "proof_tools":
                proof["productTools"] = []
            if self.fault == "proof_versions":
                proof["mcpProtocolVersions"] = []
            return proof
        if path == "/ready":
            return {"status": "starting" if self.fault == "not_ready" else "ready", "commit": SHA}
        if path == "/.well-known/apivouch-signing-key.json":
            return {"schemaVersion": 1, "slug": "apivouch", "commit": SHA, "algorithm": "Ed25519",
                    "keyId": "wrong" if self.fault == "wrong_key_id" else "temporary",
                    "publicKey": base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()}
        if path == "/api/outcomes/demo":
            return self.receipt("fixture")
        if path == "/api/outcomes/live-demo":
            return self.receipt("live")
        if path.startswith("/api/outcomes/receipts/"):
            receipt = copy.deepcopy(self.store[path.rsplit("/", 1)[1]])
            if self.fault == "altered_store":
                receipt["goal"] = "changed in storage"
            return {"receipt": receipt, "integrity_valid": True}
        assert path == "/mcp"
        method = body["method"]
        if method == "notifications/initialized":
            return None
        envelope = {"jsonrpc": "2.0", "id": body["id"]}
        params = body["params"]
        error = None
        modern = "_meta" in params or method == "server/discover" or "Mcp-Method" in headers
        if modern:
            self.modern_methods.append(method)
            meta = params.get("_meta", {})
            if not isinstance(meta.get(META_PREFIX + "clientCapabilities"), dict):
                return {**envelope, "error": {"code": -32602, "message": "Missing metadata"}}
            if self.fault != "modern_accepts_mismatch" and (
                    headers.get("MCP-Protocol-Version") != meta.get(META_PREFIX + "protocolVersion")
                    or headers.get("Mcp-Method") != method
                    or (method == "tools/call" and headers.get("Mcp-Name") != params.get("name"))):
                return {**envelope, "error": {"code": -32020, "message": "Header mismatch"}}
            if meta.get(META_PREFIX + "protocolVersion") != MODERN_VERSION:
                return {**envelope, "error": {"code": -32022, "message": "Unsupported version"}}
            if self.fault == "modern_broken":
                return {**envelope, "error": {"code": -32601, "message": "Modern unavailable"}}
        if method == "server/discover" and modern:
            result = {"supportedVersions": [MODERN_VERSION, "2024-11-05", "2025-03-26", "2025-06-18"],
                      "capabilities": {"tools": {}}}
            if self.fault == "modern_discovery":
                result["supportedVersions"] = []
        elif method == "initialize":
            version = params["protocolVersion"]
            result = {"protocolVersion": version if version in {"2024-11-05", "2025-03-26", "2025-06-18"}
                      else "2025-06-18", "capabilities": {"tools": {}}}
        elif method == "tools/list":
            result = {"tools": [{"name": RESOLVE}, {"name": VERIFY}]}
            if self.fault == "extra_tool" and not modern:
                result["tools"].append({"name": "extra"})
            if self.fault == "modern_tools" and modern:
                result["tools"] = []
        elif method == "tools/call":
            name, arguments = params["name"], params["arguments"]
            if name not in {RESOLVE, VERIFY} or not arguments:
                error = -32602
            elif name == RESOLVE:
                result = self.content(self.receipt("refused"), True)
            else:
                result = self.content({"receipt": self.store[arguments["receipt_id"]], "integrity_valid": True})
                if self.fault == "wrong_tool_channel":
                    result["isError"] = True
                if self.fault == "modern_call" and modern:
                    result = self.content({"receipt": {}, "integrity_valid": True})
        else:
            error = -32601
        if error:
            if self.fault == "wrong_rpc_channel":
                envelope["result"] = {"isError": True, "code": error}
            else:
                envelope["error"] = {"code": error, "message": "fixture error"}
        else:
            if modern:
                result.update(resultType="complete", _meta={META_PREFIX + "serverInfo": {"name": "APIVouch", "version": "1"}})
                if method in {"server/discover", "tools/list"}:
                    result.update(ttlMs=0, cacheScope="private")
                if self.fault == "modern_result_type":
                    result.pop("resultType")
                if self.fault == "modern_server_info":
                    result["_meta"] = {}
                if self.fault == "modern_cache":
                    result.pop("ttlMs", None)
            envelope["result"] = result
        return envelope


@contextmanager
def serving(version=2, fault=None):
    deployment = Deployment(version, fault)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.reply(None)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.reply(json.loads(data) if data else None)

        def reply(self, body):
            if fault == "slow_read":
                time.sleep(0.2)
            if fault == "redirect":
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                return
            value = deployment.respond(self.path, body, self.headers)
            raw = b"" if value is None else json.dumps(value).encode()
            if fault == "oversized":
                raw = b"x" * (1024 * 1024 + 1)
            status = 202 if value is None else 200
            if value and value.get("error", {}).get("code") in {-32020, -32022}:
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    deployment.base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield deployment
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def invoke(base, mode="deterministic", commit=SHA, require_signed=False):
    completed = subprocess.run([sys.executable, str(SCRIPT), "--base-url", base,
                                "--expected-commit", commit, "--mode", mode] + (["--require-signed"] if require_signed else []),
                               capture_output=True, text=True, timeout=30, check=False)
    assert completed.stderr == ""
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize("version", [1, 2])
def test_deterministic_http_gate(version):
    with serving(version) as deployment:
        code, report = invoke(deployment.base)
        assert code == 0, report
        assert report["mode"] == "deterministic-fixture"
        assert report["live_verified"] is False
        assert "receipt.corruption_rejected" in report["checks"]
        assert "receipt.unverified_no_result" in report["checks"]
        assert ("receipt.signature" in report["checks"]) is (version == 2)
        assert "/api/outcomes/live-demo" not in deployment.requests
        assert deployment.modern_methods == ["server/discover", "tools/list", "tools/list", "tools/call"]
        assert "mcp.modern.header_mismatch" in report["checks"]
        assert "mcp.modern.receipt_retrieval" in report["checks"]


@pytest.mark.parametrize("version", [1, 2])
def test_require_signed_prevents_full_downgrade(version):
    with serving(version) as deployment:
        code, report = invoke(deployment.base, require_signed=True)
    assert code == (0 if version == 2 else 1), report
    assert report["invariant"] == (None if version == 2 else "proof.signed_required")


@pytest.mark.parametrize(("fault", "invariant"), [
    ("wrong_commit", "health.commit"),
    ("proof_mismatch", "proof.commit"),
    ("slug", "proof.identity"),
    ("cross_origin", "proof.same_origin_urls"),
    ("missing_url", "proof.required_urls"),
    ("wrong_path", "proof.exact_urls"),
    ("proof_tools", "proof.product_tools"),
    ("proof_versions", "proof.protocol_versions"),
    ("not_ready", "ready.deployment"),
    ("extra_tool", "mcp.exact_tools"),
    ("wrong_rpc_channel", "mcp.error_channel"),
    ("wrong_tool_channel", "mcp.tool_error_channel"),
    ("insufficient_agreement", "evidence.agreement"),
    ("altered_receipt", "receipt.fingerprint"),
    ("invalid_signature", "receipt.signature"),
    ("missing_signature", "receipt.signature"),
    ("unsigned_fixture", "receipt.signed_required"),
    ("unsigned_refused", "receipt.signed_required"),
    ("modern_broken", "mcp.modern.result"),
    ("modern_accepts_mismatch", "mcp.modern.header_mismatch"),
    ("modern_discovery", "mcp.modern.discovery"),
    ("modern_tools", "mcp.modern.exact_tools"),
    ("modern_call", "mcp.modern.receipt_retrieval"),
    ("modern_result_type", "mcp.modern.result_type"),
    ("modern_server_info", "mcp.modern.server_info"),
    ("modern_cache", "mcp.modern.cache"),
    ("altered_authenticity", "receipt.fingerprint"),
    ("altered_store", "receipt.store_retrieval"),
    ("wrong_key_id", "receipt.key_document"),
    ("missing_origin", "evidence.final_origin"),
    ("duplicate_provider", "evidence.unique_providers"),
    ("configured_origin_count", "evidence.configured_origins"),
    ("receipt_commit", "receipt.commit"),
    ("numeric_disagreement", "evidence.numeric_agreement"),
    ("failure_attempts", "fixture.failure_attempts"),
    ("oversized", "http.response_size"),
    ("redirect", "http.no_redirects"),
])
def test_negative_named_invariant(fault, invariant):
    with serving(fault=fault) as deployment:
        code, report = invoke(deployment.base)
    assert code == 1, report
    assert report["invariant"] == invariant
    assert "tampered secret" not in json.dumps(report)


@pytest.mark.parametrize(("fault", "code", "invariant"), [
    (None, 0, None),
    ("live_unavailable", 2, None),
    ("duplicated_final_origin", 1, "evidence.distinct_final_origins"),
    ("unverified_result", 1, "receipt.unverified_no_result"),
    ("invalid_signature", 1, "receipt.signature"),
    ("unsigned_live", 1, "receipt.signed_required"),
])
def test_live_premise_and_unavailability(fault, code, invariant):
    with serving(fault=fault) as deployment:
        actual, report = invoke(deployment.base, "live")
    assert actual == code, report
    assert report["invariant"] == invariant
    assert report["live_verified"] is (code == 0)


@pytest.mark.parametrize(("base", "commit", "invariant"), [
    ("http://public.example", SHA, "url.https_or_loopback"),
    ("https://user:secret@example.com", SHA, "url.safe"),
    ("https://example.com/path", SHA, "url.base_origin"),
    ("https://example.com", "short", "input.exact_commit"),
])
def test_cli_rejects_unsafe_inputs(base, commit, invariant):
    code, report = invoke(base, commit=commit)
    assert code == 1
    assert report["invariant"] == invariant
    assert "secret" not in json.dumps(report)


def test_cli_argument_errors_are_machine_json():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["invariant"] == "input.arguments"


def test_verifier_has_no_application_imports():
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(name and name.split(".")[0] in {"app", "backend", "examples"} for name in imports)


def test_strict_json_and_origin_normalization():
    spec = importlib.util.spec_from_file_location("deployment_verifier", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.origin("https://EXAMPLE.com:443/path") == module.origin("https://example.com")
    for raw, invariant in [(b'{"x":1,"x":2}', "http.unique_json_keys"), (b'{"x":NaN}', "http.finite_json")]:
        with pytest.raises(module.Failure, match=invariant):
            module.strict_json(raw)


def test_read_timeout_is_safe_machine_failure(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("deployment_timeout_verifier", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "READ_SECONDS", 0.05)
    with serving(fault="slow_read") as deployment:
        code = module.main(["--base-url", deployment.base, "--expected-commit", SHA, "--mode", "live"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["invariant"] == "http.timeout"
