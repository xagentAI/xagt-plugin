from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse
import json
import os
import re
import socket
import threading

from opportunity_lens import InputError, analyze

MAX_BODY_BYTES = 65_536
MAX_JSON_DEPTH = 32
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_MAX_CONCURRENT_REQUESTS = 32
MAX_REQUEST_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_REQUESTS_LIMIT = 128
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _env_bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip()
    if not re.fullmatch(r"[0-9]+", normalized):
        raise RuntimeError(f"{name} must be an integer between {minimum} and {maximum}")
    try:
        return _bounded_int(int(normalized), name, minimum, maximum)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _json_depth_within_limit(value: Any, limit: int = MAX_JSON_DEPTH) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return True


def deployment_identity() -> tuple[str, str, bool]:
    commit = os.environ.get("APP_COMMIT", "").strip().lower()
    slug = os.environ.get("APP_SLUG", "runesleo-opportunity-lens").strip().lower()
    valid = bool(
        COMMIT_RE.fullmatch(commit)
        and len(slug) <= 80
        and SLUG_RE.fullmatch(slug)
    )
    return commit, slug, valid


def openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Opportunity Lens API",
            "version": "1.0.0",
            "description": "Deterministic advisory-only classification of opportunity descriptions into domains, signal state, evidence gaps, and a bounded validation action.",
        },
        "paths": {
            "/health": {"get": {"summary": "Deployment health and reviewed commit"}},
            "/.well-known/xagent-verification.json": {"get": {"summary": "Same-origin X-Agent verification"}},
            "/v1/profile": {
                "post": {
                    "summary": "Classify an opportunity and propose a non-executing validation action",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ProfileRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Advisory profile",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ProfileResponse"}
                                }
                            },
                        },
                        "400": {"description": "Invalid input"},
                        "408": {"description": "Request body timeout"},
                        "413": {"description": "Request body too large"},
                        "415": {"description": "Unsupported content type"},
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ProfileRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["headline"],
                    "properties": {
                        "headline": {"type": "string", "minLength": 1, "maxLength": 500},
                        "why_now": {"type": "string", "maxLength": 2000},
                        "candidate_class": {"type": "string", "maxLength": 120},
                        "evidence": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "source_id": {"type": "string", "maxLength": 200},
                                    "kind": {"type": "string", "maxLength": 120},
                                    "first_party": {"type": "boolean"},
                                    "url": {"type": "string", "maxLength": 1000},
                                    "note": {"type": "string", "maxLength": 1000},
                                },
                            },
                        },
                    },
                },
                "ProfileResponse": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schema", "profile", "validation", "safety"],
                    "properties": {
                        "schema": {"const": "opportunity_lens_response.v1"},
                        "profile": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "schema", "primary_domain", "domains", "innovation_types", "signal_state",
                                "evidence_classes", "unknowns", "execution_authorized", "capital_effect",
                                "human_notification_authorized"
                            ],
                            "properties": {
                                "schema": {"const": "opportunity_lens_profile.v1"},
                                "primary_domain": {"type": "string"},
                                "domains": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}},
                                "innovation_types": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}},
                                "signal_state": {"enum": ["WEAK_SIGNAL", "MECHANISM_SEED", "CROSS_DOMAIN_SEED", "READY_FOR_VALIDATION"]},
                                "evidence_classes": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}},
                                "unknowns": {"type": "array", "items": {"type": "string"}},
                                "execution_authorized": {"const": False},
                                "capital_effect": {"const": False},
                                "human_notification_authorized": {"const": False},
                            },
                        },
                        "validation": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "schema", "mode", "action_type", "reason_codes", "next_checks",
                                "actual_routing_enabled", "execution_authorized", "capital_effect",
                                "human_notification_authorized"
                            ],
                            "properties": {
                                "schema": {"const": "opportunity_lens_validation.v1"},
                                "mode": {"const": "ADVISORY_ONLY"},
                                "action_type": {"type": "string"},
                                "reason_codes": {"type": "array", "items": {"type": "string"}},
                                "next_checks": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                "actual_routing_enabled": {"const": False},
                                "execution_authorized": {"const": False},
                                "capital_effect": {"const": False},
                                "human_notification_authorized": {"const": False},
                            },
                        },
                        "safety": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "advisory_only", "execution_authorized", "capital_effect",
                                "account_effect", "public_publish_authorized"
                            ],
                            "properties": {
                                "advisory_only": {"const": True},
                                "execution_authorized": {"const": False},
                                "capital_effect": {"const": False},
                                "account_effect": {"const": False},
                                "public_publish_authorized": {"const": False},
                            },
                        },
                    },
                },
            }
        },
    }


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        request_timeout_seconds: int,
        max_concurrent_requests: int,
    ) -> None:
        self.request_timeout_seconds = request_timeout_seconds
        self.max_concurrent_requests = max_concurrent_requests
        self._worker_slots = threading.BoundedSemaphore(max_concurrent_requests)
        super().__init__(server_address, handler_class)

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(self.request_timeout_seconds)
        return request, client_address

    def process_request(self, request, client_address) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()

    def handle_error(self, request, client_address) -> None:
        if os.environ.get("QUIET_HTTP_LOGS", "1") != "1":
            super().handle_error(request, client_address)


class OpportunityLensHandler(BaseHTTPRequestHandler):
    server_version = "OpportunityLens"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def _send_common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Connection", "close")
        self.close_connection = True

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass

    def _path(self) -> str:
        return urlparse(self.path).path

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        commit, slug, valid = deployment_identity()
        if path == "/health":
            if not valid:
                self._send_json(503, {"status": "error", "code": "DEPLOYMENT_IDENTITY_INVALID"})
                return
            self._send_json(200, {"status": "ok", "commit": commit})
            return
        if path == "/.well-known/xagent-verification.json":
            if not valid:
                self._send_json(503, {"status": "error", "code": "DEPLOYMENT_IDENTITY_INVALID"})
                return
            self._send_json(200, {"schemaVersion": 1, "slug": slug, "commit": commit})
            return
        if path == "/openapi.json":
            self._send_json(200, openapi_document())
            return
        if path == "/":
            self._send_json(200, {
                "service": "Opportunity Lens API",
                "version": "1.0.0",
                "mode": "ADVISORY_ONLY",
                "endpoints": ["/health", "/.well-known/xagent-verification.json", "/openapi.json", "/v1/profile"],
            })
            return
        self._send_json(404, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:  # noqa: N802
        if self._path() != "/v1/profile":
            self._send_json(404, {"error": "NOT_FOUND"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json(415, {"error": "CONTENT_TYPE_MUST_BE_APPLICATION_JSON"})
            return
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._send_json(411, {"error": "CONTENT_LENGTH_REQUIRED"})
            return
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(400, {"error": "INVALID_CONTENT_LENGTH"})
            return
        if length < 0:
            self._send_json(400, {"error": "INVALID_CONTENT_LENGTH"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "REQUEST_BODY_TOO_LARGE", "max_bytes": MAX_BODY_BYTES})
            return
        try:
            body = self.rfile.read(length)
        except (TimeoutError, socket.timeout):
            self._send_json(408, {"error": "REQUEST_BODY_TIMEOUT"})
            return
        except OSError:
            self._send_json(400, {"error": "REQUEST_BODY_READ_FAILED"})
            return
        if len(body) != length:
            self._send_json(400, {"error": "INCOMPLETE_REQUEST_BODY"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except RecursionError:
            self._send_json(400, {"error": "JSON_NESTING_TOO_DEEP"})
            return
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "INVALID_JSON"})
            return
        if not _json_depth_within_limit(payload):
            self._send_json(400, {"error": "JSON_NESTING_TOO_DEEP", "max_depth": MAX_JSON_DEPTH})
            return
        try:
            result = analyze(payload)
        except InputError as exc:
            self._send_json(400, {"error": "INVALID_REQUEST", "detail": str(exc)})
            return
        except Exception:
            self._send_json(500, {"error": "INTERNAL_ERROR"})
            return
        self._send_json(200, result)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self._send_common_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("QUIET_HTTP_LOGS", "1") != "1":
            super().log_message(format, *args)


def create_server(
    host: str,
    port: int,
    *,
    request_timeout_seconds: int | None = None,
    max_concurrent_requests: int | None = None,
) -> BoundedThreadingHTTPServer:
    timeout = (
        _env_bounded_int(
            "REQUEST_TIMEOUT_SECONDS",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
            1,
            MAX_REQUEST_TIMEOUT_SECONDS,
        )
        if request_timeout_seconds is None
        else _bounded_int(request_timeout_seconds, "request_timeout_seconds", 1, MAX_REQUEST_TIMEOUT_SECONDS)
    )
    concurrency = (
        _env_bounded_int(
            "MAX_CONCURRENT_REQUESTS",
            DEFAULT_MAX_CONCURRENT_REQUESTS,
            1,
            MAX_CONCURRENT_REQUESTS_LIMIT,
        )
        if max_concurrent_requests is None
        else _bounded_int(max_concurrent_requests, "max_concurrent_requests", 1, MAX_CONCURRENT_REQUESTS_LIMIT)
    )
    return BoundedThreadingHTTPServer(
        (host, port),
        OpportunityLensHandler,
        request_timeout_seconds=timeout,
        max_concurrent_requests=concurrency,
    )


def main() -> int:
    host = os.environ.get("HOST", "0.0.0.0")
    port = _env_bounded_int("PORT", 8080, 1, 65_535)
    server = create_server(host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
