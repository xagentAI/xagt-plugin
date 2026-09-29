"""Independent HTTP deployment gate. See docs/deployment-verifier.md."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import ipaddress
import json
import math
import re
import sys
import time
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 1024 * 1024
CONNECT_SECONDS = 5
READ_SECONDS = 15
TOTAL_SECONDS = 45
RESOLVE = "apivouch_resolve_verified_outcome"
VERIFY = "apivouch_verify_receipt"
KEY_PATH = "/.well-known/apivouch-signing-key.json"
MODERN_VERSION = "2026-07-28"
META_PREFIX = "io.modelcontextprotocol/"


class Failure(Exception):
    pass


def require(condition, invariant):
    if not condition:
        raise Failure(invariant)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def origin(url):
    parts = urlsplit(url)
    require(parts.scheme in {"http", "https"} and parts.hostname and not parts.username
            and not parts.password and not parts.fragment, "url.safe")
    return parts.scheme, parts.hostname.lower(), parts.port or (443 if parts.scheme == "https" else 80)


def base_url(value):
    scheme, host, _ = origin(value)
    parts = urlsplit(value)
    require(parts.path in {"", "/"} and not parts.query, "url.base_origin")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    require(scheme == "https" or loopback, "url.https_or_loopback")
    return value.rstrip("/")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "http.unique_json_keys")
            result[key] = value
        return result

    def invalid(_):
        raise Failure("http.finite_json")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class Verifier:
    def __init__(self, base, commit, mode, require_signed=False):
        self.base = base_url(base)
        require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "input.exact_commit")
        self.commit = commit
        self.mode = mode
        self.require_signed = require_signed
        self.checks = []
        self.request_id = 0
        self.client = httpx.Client(follow_redirects=False, trust_env=False,
                                   timeout=httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS))

    def check(self, condition, name):
        require(condition, name)
        if name not in self.checks:
            self.checks.append(name)

    def http(self, path, payload=None, *, post=False, empty=False, headers=None, status=200, invariant="http.status"):
        url = self.base + path if path.startswith("/") else path
        self.check(origin(url) == origin(self.base), "http.same_origin")
        started = time.monotonic()
        try:
            with self.client.stream("POST" if post else "GET", url, json=payload,
                                    headers={"Accept": "application/json", "Accept-Encoding": "identity", **(headers or {})}) as response:
                self.check(not 300 <= response.status_code < 400, "http.no_redirects")
                self.check(response.status_code in ({200, 202, 204} if empty else {status}), invariant)
                self.check(response.headers.get("content-encoding", "identity") == "identity", "http.encoding")
                length = response.headers.get("content-length")
                self.check(length is None or 0 <= int(length) <= MAX_BYTES, "http.response_size")
                body = bytearray()
                for chunk in response.iter_raw():
                    body.extend(chunk)
                    self.check(len(body) <= MAX_BYTES, "http.response_size")
                    self.check(time.monotonic() - started <= TOTAL_SECONDS, "http.total_timeout")
                if empty:
                    self.check(not body, "mcp.initialized_empty")
                    return None
                self.check(response.headers.get("content-type", "").split(";")[0] == "application/json", "http.json_content_type")
                try:
                    value = strict_json(body)
                except (ValueError, UnicodeError, RecursionError):
                    raise Failure("http.valid_json") from None
                self.check(isinstance(value, dict), "http.object")
                return value
        except httpx.TimeoutException:
            raise Failure("http.timeout") from None
        except httpx.HTTPError:
            raise Failure("http.transport") from None

    def rpc(self, method, params=None, error=None, *, modern=False, mismatch=False):
        self.request_id += 1
        params = dict(params or {})
        headers = {}
        invariant = "mcp.modern.header_mismatch" if mismatch else "mcp.modern.result"
        if modern:
            params["_meta"] = {META_PREFIX + "protocolVersion": MODERN_VERSION,
                               META_PREFIX + "clientCapabilities": {},
                               META_PREFIX + "clientInfo": {"name": "apivouch-independent-verifier", "version": "1"}}
            headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": MODERN_VERSION,
                       "Mcp-Method": "server/discover" if mismatch else method}
            if method == "tools/call":
                headers["Mcp-Name"] = params["name"]
        value = self.http("/mcp", {"jsonrpc": "2.0", "id": self.request_id,
                                  "method": method, "params": params}, post=True, headers=headers,
                          status=400 if mismatch else 200, invariant=invariant if modern else "http.status")
        self.check(value.get("jsonrpc") == "2.0" and type(value.get("id")) is int
                   and value["id"] == self.request_id, "mcp.envelope")
        if error is not None:
            self.check("result" not in value and isinstance(value.get("error"), dict)
                       and value["error"].get("code") == error, invariant if modern else "mcp.error_channel")
            return None
        self.check("error" not in value and isinstance(value.get("result"), dict), invariant if modern else "mcp.result_channel")
        if modern:
            result = value["result"]
            self.check(result.get("resultType") == "complete", "mcp.modern.result_type")
            info = result.get("_meta", {}).get(META_PREFIX + "serverInfo", {})
            self.check(isinstance(info.get("name"), str) and bool(info["name"])
                       and isinstance(info.get("version"), str) and bool(info["version"]), "mcp.modern.server_info")
            if method in {"server/discover", "tools/list"}:
                self.check(type(result.get("ttlMs")) is int and result["ttlMs"] == 0
                           and result.get("cacheScope") == "private", "mcp.modern.cache")
        return value["result"]

    def tool_content(self, value, is_error):
        self.check(value.get("isError") is is_error, "mcp.tool_error_channel")
        content = value.get("content")
        self.check(isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text",
                   "mcp.text_content")
        self.check(strict_json(content[0]["text"]) == value.get("structuredContent"), "mcp.content_agreement")
        return value["structuredContent"]

    def integrity(self, receipt):
        fmt = receipt.get("format")
        self.check(fmt in {"apivouch-outcome-receipt-v1", "apivouch-outcome-receipt-v2"}, "receipt.format")
        self.check(not self.require_signed or fmt == "apivouch-outcome-receipt-v2", "receipt.signed_required")
        fingerprint = digest({k: v for k, v in receipt.items() if k not in {"receipt_id", "integrity"}})
        integrity = receipt.get("integrity", {})
        self.check(integrity.get("algorithm") == "SHA-256" and integrity.get("fingerprint") == fingerprint
                   and receipt.get("receipt_id") == fingerprint[7:31], "receipt.fingerprint")
        if fmt.endswith("v1"):
            self.check("authenticity" not in receipt, "receipt.v1_unsigned")
            return
        auth = receipt.get("authenticity", {})
        self.check(set(auth) == {"state", "algorithm", "key_id"} and auth.get("state") == "signed"
                   and auth.get("algorithm") == "Ed25519" and isinstance(auth.get("key_id"), str)
                   and bool(auth["key_id"]), "receipt.authenticity")
        key = self.http(KEY_PATH)
        self.check(type(key.get("schemaVersion")) is int and key["schemaVersion"] == 1
                   and key.get("slug") == "apivouch" and key.get("commit") == self.commit
                   and key.get("algorithm") == "Ed25519" and key.get("keyId") == auth["key_id"], "receipt.key_document")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
        except ImportError:
            raise Failure("receipt.crypto_dependency") from None
        try:
            from cryptography.exceptions import InvalidSignature

            public = base64.b64decode(key["publicKey"], validate=True)
            signature = base64.b64decode(integrity["signature"], validate=True)
            require(len(public) == 32 and len(signature) == 64, "receipt.signature")
            Ed25519PublicKey.from_public_bytes(public).verify(signature, (fmt + "\n" + fingerprint[7:]).encode("utf-8"))
        except (ValueError, KeyError, TypeError, InvalidSignature):
            raise Failure("receipt.signature") from None
        self.check(True, "receipt.signature")

    def receipt(self, receipt, *, fixture):
        self.integrity(receipt)
        self.check(receipt.get("deployment_commit") == self.commit, "receipt.commit")
        attempts = receipt.get("attempts", [])
        self.check(isinstance(attempts, list) and 2 <= len(attempts) <= 5, "evidence.attempts")
        names = [a["name"].casefold() for a in attempts]
        self.check(len(names) == len(set(names)), "evidence.unique_providers")
        configured = {origin(a["url"]) for a in attempts}
        independence = receipt["provider_independence"]
        self.check(independence.get("required") is (not fixture), "evidence.independence_mode")
        self.check(independence.get("distinct_configured_origins") == len(configured), "evidence.configured_origins")
        if fixture:
            self.check(configured == {origin(self.base)}, "fixture.configured_origin")
        if not fixture:
            self.check(len(configured) == len(attempts) and all(o[0] == "https" for o in configured), "evidence.independent_origins")
        constraints = receipt["constraints"]
        required = constraints["minimum_agreement"]
        self.check(type(required) is int and 2 <= required <= len(attempts)
                   and receipt["agreement"]["required"] == required, "evidence.required_agreement")
        agreeing = [a for a in attempts if a.get("agrees_with_consensus") is True]
        for attempt in attempts:
            self.check(attempt.get("status") in {"SELECTED", "ELIGIBLE", "REJECTED"}, "evidence.status")
            if attempt["status"] == "REJECTED":
                self.check(bool(attempt.get("reason")) and attempt.get("agrees_with_consensus") is False, "evidence.rejected")
        verdict = receipt.get("verdict")
        self.check(verdict in {"VERIFIED", "UNVERIFIED"}, "receipt.verdict")
        if verdict == "UNVERIFIED":
            self.check(receipt.get("result") is None and receipt.get("selected_provider") is None
                       and receipt.get("selected_price_usd") == 0 and not agreeing
                       and all(a["status"] == "REJECTED" for a in attempts)
                       and 0 <= receipt["agreement"]["providers"] < required, "receipt.unverified_no_result")
            return
        self.check(len(agreeing) >= required and receipt["agreement"]["providers"] == len(agreeing), "evidence.agreement")
        finals = []
        for attempt in agreeing:
            self.check(bool(attempt.get("resolved_origin")), "evidence.final_origin")
            finals.append(origin(attempt["resolved_origin"]))
            self.check(attempt["status"] in {"SELECTED", "ELIGIBLE"}
                       and attempt.get("contract_validated") is True
                       and 200 <= attempt["upstream_status"] < 300
                       and 0 <= attempt["latency_ms"] <= constraints["max_latency_ms"]
                       and 0 <= attempt["price_usd"] <= constraints["max_price_usd"], "evidence.eligible")
            for field in ("request_url_digest", "expected_schema_digest", "response_digest", "value_digest"):
                self.check(isinstance(attempt.get(field), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", attempt[field]) is not None,
                           "evidence.digests")
            self.check(digest(attempt["value_preview"]) == attempt["value_digest"], "evidence.value_digest")
        self.check(len(set(finals)) == (1 if fixture else len(agreeing)), "evidence.distinct_final_origins")
        if fixture:
            self.check(set(finals) == {origin(self.base)}, "fixture.final_origin")
        selected = [a for a in agreeing if a["status"] == "SELECTED"]
        self.check(len(selected) == 1 and selected[0]["name"] == receipt["selected_provider"]
                   and selected[0]["value_digest"] == digest(receipt["result"])
                   and selected[0]["price_usd"] == receipt["selected_price_usd"], "evidence.selection")
        result = receipt["result"]
        tolerance = constraints["numeric_tolerance_percent"]
        self.check(type(result) in {int, float} and math.isfinite(result)
                   and type(tolerance) in {int, float} and 0 <= tolerance <= (1 if fixture else 2), "evidence.numeric_policy")
        for attempt in agreeing:
            value = attempt["value_preview"]
            self.check(type(value) in {int, float} and math.isfinite(value)
                       and abs(value - result) / max(abs(value), abs(result), 1e-12) * 100 <= tolerance, "evidence.numeric_agreement")
        if fixture:
            by_name = {a["name"]: a for a in attempts}
            self.check(set(by_name) == {"Atlas Courier", "Beacon Logistics", "Legacy Ship", "Offline Express"}, "fixture.providers")
            self.check(by_name["Legacy Ship"]["status"] == "REJECTED"
                       and by_name["Legacy Ship"]["contract_validated"] is False
                       and by_name["Legacy Ship"]["reason"].startswith("Schema mismatch:")
                       and by_name["Offline Express"]["status"] == "REJECTED"
                       and by_name["Offline Express"]["upstream_status"] == 503, "fixture.failure_attempts")
            self.check({a["value_preview"] for a in agreeing} == {18.4, 18.44}, "fixture.values")

    def stored(self, receipt):
        rest = self.http("/api/outcomes/receipts/" + receipt["receipt_id"])
        mcp = self.tool_content(self.rpc("tools/call", {"name": VERIFY, "arguments": {"receipt_id": receipt["receipt_id"]}}), False)
        self.check(rest == mcp and rest.get("receipt") == receipt and rest.get("integrity_valid") is True, "receipt.store_retrieval")
        self.integrity(rest["receipt"])

    def run(self):
        health = self.http("/health")
        self.check(health.get("status") == "ok" and health.get("service") == "apivouch", "health.identity")
        self.check(health.get("commit") == self.commit, "health.commit")
        proof = self.http("/.well-known/xagent-verification.json")
        self.check(proof.get("slug") == "apivouch" and type(proof.get("schemaVersion")) is int
                   and proof["schemaVersion"] == 1, "proof.identity")
        self.check(proof.get("commit") == self.commit, "proof.commit")
        urls = {"apiBaseUrl": "", "healthCheckUrl": "/health", "readinessUrl": "/ready", "mcpEndpoint": "/mcp"}
        formats = proof.get("receiptFormats")
        self.check(formats in (["apivouch-outcome-receipt-v1"],
                              ["apivouch-outcome-receipt-v1", "apivouch-outcome-receipt-v2"]), "proof.receipt_formats")
        if "apivouch-outcome-receipt-v2" in formats:
            urls["signingKeyUrl"] = KEY_PATH
        else:
            self.check("signingKeyUrl" not in proof, "proof.signing_disabled")
        advertised_signing = "apivouch-outcome-receipt-v2" in formats
        self.check(not self.require_signed or advertised_signing, "proof.signed_required")
        self.require_signed = self.require_signed or advertised_signing
        for field, path in urls.items():
            self.check(isinstance(proof.get(field), str), "proof.required_urls")
            self.check(origin(proof[field]) == origin(self.base), "proof.same_origin_urls")
            self.check(proof[field] == self.base + path, "proof.exact_urls")
        self.check(proof.get("productTools") == [RESOLVE, VERIFY], "proof.product_tools")
        self.check(proof.get("mcpProtocolVersions") == ["2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28"],
                   "proof.protocol_versions")
        ready = self.http("/ready")
        self.check(ready.get("status") == "ready" and ready.get("commit") == self.commit, "ready.deployment")
        modern = MODERN_VERSION in proof["mcpProtocolVersions"]
        if modern:
            # These requests precede legacy initialization and carry their own metadata.
            discovered = self.rpc("server/discover", modern=True)
            self.check(discovered.get("supportedVersions") == [MODERN_VERSION, "2024-11-05", "2025-03-26", "2025-06-18"]
                       and isinstance(discovered.get("capabilities", {}).get("tools"), dict), "mcp.modern.discovery")
            listed = self.rpc("tools/list", modern=True).get("tools")
            self.check(isinstance(listed, list) and len(listed) == 2
                       and {t.get("name") for t in listed} == {RESOLVE, VERIFY}, "mcp.modern.exact_tools")
            self.rpc("tools/list", error=-32020, modern=True, mismatch=True)
        for version in ("2025-06-18", "2024-11-05"):
            initialized = self.rpc("initialize", {"protocolVersion": version, "capabilities": {},
                                                  "clientInfo": {"name": "apivouch-independent-verifier", "version": "1"}})
            self.check(initialized.get("protocolVersion") == version and "tools" in initialized.get("capabilities", {}), "mcp.initialize")
        self.http("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, post=True, empty=True)
        tools = self.rpc("tools/list")["tools"]
        self.check(len(tools) == 2 and {t["name"] for t in tools} == {RESOLVE, VERIFY}, "mcp.exact_tools")
        self.rpc("verifier/unknown", error=-32601)
        self.rpc("tools/call", {"name": "verifier_unknown", "arguments": {}}, error=-32602)
        for name in (RESOLVE, VERIFY):
            self.rpc("tools/call", {"name": name, "arguments": {}}, error=-32602)
        receipt = self.http("/api/outcomes/demo", post=True)
        self.receipt(receipt, fixture=True)
        self.check(receipt["verdict"] == "VERIFIED", "fixture.verified")
        self.stored(receipt)
        if modern:
            verified = self.tool_content(self.rpc("tools/call", {"name": VERIFY,
                                         "arguments": {"receipt_id": receipt["receipt_id"]}}, modern=True), False)
            self.check(verified.get("receipt") == receipt and verified.get("integrity_valid") is True,
                       "mcp.modern.receipt_retrieval")
        corrupted = copy.deepcopy(receipt)
        corrupted["goal"] = str(corrupted.get("goal", "")) + " corrupted"
        try:
            self.integrity(corrupted)
        except Failure as exc:
            self.check(str(exc) == "receipt.fingerprint", "receipt.corruption_rejected")
        else:
            raise Failure("receipt.corruption_rejected")
        # Zero budget excludes both providers before any network request is made.
        arguments = {"goal": "Refuse an outcome with no affordable providers", "providers": [
            {"name": name, "url": "https://" + name + ".example/value", "price_usd": 1,
             "expected_schema": {"type": "number"}} for name in ("alpha", "beta")],
            "constraints": {"max_price_usd": 0, "max_latency_ms": 1000, "minimum_agreement": 2, "numeric_tolerance_percent": 0}}
        refused = self.tool_content(self.rpc("tools/call", {"name": RESOLVE, "arguments": arguments}), True)
        self.receipt(refused, fixture=False)
        self.check(refused["verdict"] == "UNVERIFIED", "receipt.refusal")
        self.stored(refused)
        if self.mode == "live":
            live = self.http("/api/outcomes/live-demo", post=True)
            self.receipt(live, fixture=False)
            self.check({origin(a["url"]) for a in live["attempts"]} == {
                origin("https://api.frankfurter.app"), origin("https://www.floatrates.com"),
                origin("https://open.er-api.com")}, "live.provider_premise")
            self.stored(live)
            if live["verdict"] == "UNVERIFIED":
                return 2
            self.check(live["result"] > 0, "live.positive_rate")
        return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure("input.arguments")


def main(argv=None):
    verifier = None
    mode = None
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--base-url", required=True)
        parser.add_argument("--expected-commit", required=True)
        parser.add_argument("--mode", required=True, choices=("deterministic", "live"))
        parser.add_argument("--require-signed", action="store_true", help="Reject unsigned deployment proof and receipts.")
        args = parser.parse_args(argv)
        mode = args.mode
        verifier = Verifier(args.base_url, args.expected_commit, mode, args.require_signed)
        code = verifier.run()
        failure = None
    except Failure as exc:
        code, failure = 1, str(exc)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        code, failure = 1, "response.contract"
    finally:
        if verifier is not None:
            verifier.client.close()
    report = {"status": {0: "passed", 1: "failed", 2: "live-unavailable"}[code],
              "mode": "deterministic-fixture" if mode == "deterministic" else mode,
              "invariant": failure, "checks": verifier.checks if verifier else [],
              "live_verified": code == 0 and mode == "live"}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
