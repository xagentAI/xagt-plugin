from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
import json
import os
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    DEFAULT_MAX_CONCURRENT_REQUESTS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    MAX_BODY_BYTES,
    create_server,
)
from opportunity_lens import InputError, analyze  # noqa: E402

COMMIT = "a" * 40
SLUG = "runesleo-opportunity-lens"


@contextmanager
def running_server(*, valid_identity: bool = True):
    env = {
        "APP_COMMIT": COMMIT if valid_identity else "not-a-commit",
        "APP_SLUG": SLUG,
        "QUIET_HTTP_LOGS": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, response_headers, json.loads(payload or b"{}")


class ClassifierTests(unittest.TestCase):
    def test_hackathon_routes_to_bounded_commercial_review(self) -> None:
        result = analyze({
            "headline": "X-Agent MCP Hackathon for a deployed AI agent API",
            "why_now": "Submission deadline is near; prizes include X-Points and paid-call potential.",
            "evidence": [{"source_id": "official:event", "kind": "OFFICIAL_GRANT_TERMS", "first_party": True}],
        })
        profile = result["profile"]
        validation = result["validation"]
        self.assertIn("AI_AGENT_SOFTWARE", profile["domains"])
        self.assertIn("DATA_INFRA", profile["domains"])
        self.assertIn("GRANT_BOUNTY_PARTNERSHIP", profile["domains"])
        self.assertIn("API", profile["innovation_types"])
        self.assertIn("INCENTIVE", profile["innovation_types"])
        self.assertEqual(profile["signal_state"], "READY_FOR_VALIDATION")
        self.assertEqual(validation["action_type"], "COMMERCIAL_REVIEW")
        self.assertFalse(result["safety"]["execution_authorized"])
        self.assertFalse(result["safety"]["capital_effect"])
        self.assertFalse(result["safety"]["public_publish_authorized"])

    def test_prediction_data_api_routes_to_strategy_test(self) -> None:
        result = analyze({
            "headline": "Prediction market orderbook API with timestamped market data",
            "why_now": "The public endpoint is live.",
        })
        self.assertIn("PREDICTION_INFOFI", result["profile"]["domains"])
        self.assertEqual(result["validation"]["action_type"], "STRATEGY_TEST")

    def test_unknown_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(InputError, "unknown fields"):
            analyze({"headline": "test", "private_state_path": "/tmp/private"})

    def test_evidence_is_bounded(self) -> None:
        with self.assertRaisesRegex(InputError, "evidence exceeds"):
            analyze({"headline": "test", "evidence": [{}] * 13})


class HttpContractTests(unittest.TestCase):
    def test_health_returns_exact_review_commit_and_security_headers(self) -> None:
        with running_server() as port:
            status, headers, payload = request(port, "GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok", "commit": COMMIT})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Connection"], "close")
        self.assertEqual(headers["Server"], "OpportunityLens")
        self.assertNotIn("Python", headers["Server"])

    def test_same_origin_verification_contract(self) -> None:
        with running_server() as port:
            status, _, payload = request(port, "GET", "/.well-known/xagent-verification.json")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"schemaVersion": 1, "slug": SLUG, "commit": COMMIT})

    def test_invalid_deployment_identity_fails_health_closed_without_echo(self) -> None:
        with running_server(valid_identity=False) as port:
            status, _, payload = request(port, "GET", "/health")
        self.assertEqual(status, 503)
        self.assertEqual(payload, {"status": "error", "code": "DEPLOYMENT_IDENTITY_INVALID"})
        self.assertNotIn("commit", payload)

    def test_profile_endpoint(self) -> None:
        body = json.dumps({
            "headline": "AI agent workflow API for a builder bounty",
            "why_now": "Official deadline is within seven days.",
            "evidence": [{"source_id": "official", "kind": "OFFICIAL_DOC", "first_party": True}],
        }).encode()
        with running_server() as port:
            status, _, payload = request(
                port,
                "POST",
                "/v1/profile",
                body,
                {"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema"], "opportunity_lens_response.v1")
        self.assertEqual(payload["validation"]["action_type"], "COMMERCIAL_REVIEW")
        self.assertFalse(payload["validation"]["actual_routing_enabled"])

    def test_invalid_json_and_content_type_are_rejected(self) -> None:
        with running_server() as port:
            bad_json = request(port, "POST", "/v1/profile", b"{", {"Content-Type": "application/json", "Content-Length": "1"})
            bad_type = request(port, "POST", "/v1/profile", b"{}", {"Content-Type": "text/plain", "Content-Length": "2"})
        self.assertEqual(bad_json[0], 400)
        self.assertEqual(bad_type[0], 415)

    def test_excessive_json_nesting_is_rejected(self) -> None:
        body = (("[" * 2_000) + "0" + ("]" * 2_000)).encode()
        with running_server() as port:
            status, _, payload = request(
                port,
                "POST",
                "/v1/profile",
                body,
                {"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "JSON_NESTING_TOO_DEEP")

    def test_oversized_body_is_rejected_before_read(self) -> None:
        with running_server() as port:
            status, _, payload = request(
                port,
                "POST",
                "/v1/profile",
                b"{}",
                {"Content-Type": "application/json", "Content-Length": str(MAX_BODY_BYTES + 1)},
            )
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "REQUEST_BODY_TOO_LARGE")

    def test_openapi_is_machine_readable_and_closed(self) -> None:
        with running_server() as port:
            status, _, payload = request(port, "GET", "/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(payload["openapi"], "3.1.0")
        self.assertIn("/v1/profile", payload["paths"])
        response_ref = payload["paths"]["/v1/profile"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        self.assertEqual(response_ref, "#/components/schemas/ProfileResponse")
        request_schema = payload["components"]["schemas"]["ProfileRequest"]
        evidence_schema = request_schema["properties"]["evidence"]["items"]
        self.assertFalse(request_schema["additionalProperties"])
        self.assertFalse(evidence_schema["additionalProperties"])
        response_schema = payload["components"]["schemas"]["ProfileResponse"]
        self.assertFalse(response_schema["additionalProperties"])
        self.assertFalse(response_schema["properties"]["safety"]["properties"]["execution_authorized"]["const"])
        self.assertFalse(response_schema["properties"]["safety"]["properties"]["public_publish_authorized"]["const"])

    def test_server_resource_limits_and_env_validation(self) -> None:
        server = create_server(
            "127.0.0.1",
            0,
            request_timeout_seconds=3,
            max_concurrent_requests=7,
        )
        try:
            self.assertEqual(server.request_timeout_seconds, 3)
            self.assertEqual(server.max_concurrent_requests, 7)
            self.assertEqual(server.request_queue_size, 64)
            self.assertTrue(server.daemon_threads)
        finally:
            server.server_close()
        with patch.dict(os.environ, {"REQUEST_TIMEOUT_SECONDS": "0"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "between 1 and 30"):
                create_server("127.0.0.1", 0)
        with patch.dict(os.environ, {"MAX_CONCURRENT_REQUESTS": "129"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "between 1 and 128"):
                create_server("127.0.0.1", 0)
        with patch.dict(os.environ, {}, clear=True):
            default_server = create_server("127.0.0.1", 0)
            try:
                self.assertEqual(default_server.request_timeout_seconds, DEFAULT_REQUEST_TIMEOUT_SECONDS)
                self.assertEqual(default_server.max_concurrent_requests, DEFAULT_MAX_CONCURRENT_REQUESTS)
            finally:
                default_server.server_close()


class PublicReleaseSafetyTests(unittest.TestCase):
    def test_candidate_is_standalone_and_does_not_import_private_radar(self) -> None:
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        lens_source = (ROOT / "opportunity_lens.py").read_text(encoding="utf-8")
        combined = app_source + lens_source
        self.assertNotIn("production.", combined)
        self.assertNotIn(".local/state", combined)
        self.assertNotIn("cmd3-", combined)
        self.assertNotIn("subprocess", combined)
        self.assertNotIn("eval(", combined)
        self.assertNotIn("exec(", combined)

    def test_docker_is_digest_pinned_non_root_and_minimal(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile.splitlines()[0], r"^FROM python:3\.12\.14-slim-bookworm@sha256:[0-9a-f]{64}$")
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn("COPY --chown=65532:65532 app.py opportunity_lens.py ./", dockerfile)
        self.assertNotIn("COPY .", dockerfile)
        self.assertIn("QUIET_HTTP_LOGS=1", dockerfile)
        self.assertIn("REQUEST_TIMEOUT_SECONDS=10", dockerfile)
        self.assertIn("MAX_CONCURRENT_REQUESTS=32", dockerfile)

    def test_public_allowlist_excludes_internal_metadata_and_secrets(self) -> None:
        allowlist_path = ROOT / "PUBLIC_RELEASE_ALLOWLIST.txt"
        entries = [
            line.strip()
            for line in allowlist_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        for required in ("LICENSE", "README.md", "README.zh.md", "REVIEW-codex-pass.md", "CHANGELOG.md", "SECURITY.md"):
            self.assertIn(required, entries)
        corpus = []
        for relative in entries:
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            corpus.append(path.read_text(encoding="utf-8"))
        public_text = "\n".join(corpus)
        private_home_prefix = "/" + "Users" + "/"
        private_state_marker = ".local/" + "state/leo-opportunity-radar"
        private_share_marker = ".local/" + "share/leo-opportunity-radar"
        self.assertNotIn(private_home_prefix, public_text)
        self.assertNotIn(private_state_marker, public_text)
        self.assertNotIn(private_share_marker, public_text)
        self.assertNotRegex(public_text, r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b")
        self.assertNotRegex(public_text, r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
        self.assertNotRegex(public_text, r"\bAKIA[0-9A-Z]{16}\b")
        self.assertNotRegex(public_text, r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
        self.assertNotRegex(public_text, r"\bsk-[A-Za-z0-9_-]{20,}\b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
