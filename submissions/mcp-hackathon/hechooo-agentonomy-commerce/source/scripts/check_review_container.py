"""Check the public verification surface of a review container.

This module intentionally uses only the Python standard library so it can be
run from a checkout or from a minimal CI harness before any optional clients
are installed. It never prints response bodies or bearer tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


DEFAULT_PROJECT_SLUG = "hechooo-agentonomy-commerce"
MAX_RESPONSE_BYTES = 64 * 1024
RequestFn = Callable[..., tuple[int, dict[str, Any]]]


class VerificationError(RuntimeError):
    """A public verification check failed with a safe diagnostic."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat redirects as an unsafe response instead of forwarding auth."""

    def redirect_request(self, *args, **kwargs):
        return None


_HTTP_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


def normalize_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise VerificationError("base URL is invalid")
    value = base_url.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VerificationError("base URL must be an HTTP(S) origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VerificationError("base URL must not contain credentials or query data")
    if parsed.path not in {"", "/"}:
        raise VerificationError("base URL must be an origin without a path")
    try:
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise VerificationError("base URL has an invalid host or port") from exc
    if parsed.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise VerificationError("cleartext verification is limited to loopback")
    return value


def _decode_response(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise VerificationError("response exceeds the verification size limit")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("container returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError("container returned a non-object JSON response")
    return value


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    """Make one bounded JSON request and return status plus object body."""

    body = None
    request_headers = {"Accept": "application/json"}
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if headers is not None:
        request_headers.update(headers)
    if payload is not None:
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise VerificationError("request payload is not JSON serializable") from exc
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with _HTTP_OPENER.open(request, timeout=timeout) as response:
            return response.status, _decode_response(response.read(MAX_RESPONSE_BYTES + 1))
    except HTTPError as exc:
        try:
            response_body = exc.read(MAX_RESPONSE_BYTES + 1)
            decoded = _decode_response(response_body)
        except VerificationError:
            decoded = {}
        return exc.code, decoded
    except (OSError, URLError, TimeoutError) as exc:
        raise VerificationError("container request failed") from exc


def _safe_public(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "status",
        "commit",
        "schemaVersion",
        "slug",
        "real_funds",
        "settlement_mode",
        "service_transport",
    }
    return {key: value[key] for key in sorted(allowed) if key in value}


def check_public_surface(
    base_url: str,
    expected_commit: str,
    *,
    project_slug: str = DEFAULT_PROJECT_SLUG,
    requester: RequestFn = request_json,
) -> dict[str, Any]:
    """Validate health and proof responses without sending credentials."""

    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise VerificationError("expected commit must be exactly 40 lowercase hex characters")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project_slug):
        raise VerificationError("project slug is invalid")
    origin = normalize_base_url(base_url)
    health_status, health = requester("GET", urljoin(origin + "/", "health"))
    if health_status != 200 or health.get("status") != "ok":
        raise VerificationError("health check did not return ready")
    if health.get("commit") != expected_commit:
        raise VerificationError("health commit does not match expected commit")
    if health.get("real_funds") is not False or health.get("settlement_mode") != "simulated":
        raise VerificationError("health response does not disclose simulated settlement")

    proof_status, proof = requester(
        "GET", urljoin(origin + "/", ".well-known/xagent-verification.json")
    )
    if proof_status != 200:
        raise VerificationError("verification proof is unavailable")
    if proof.get("schemaVersion") != 1:
        raise VerificationError("verification proof schema is unsupported")
    if proof.get("slug") != project_slug or proof.get("commit") != expected_commit:
        raise VerificationError("verification proof does not match expected source")
    return {"health": _safe_public(health), "proof": _safe_public(proof)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--project-slug", default=DEFAULT_PROJECT_SLUG)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = check_public_surface(
            args.base_url,
            args.expected_commit,
            project_slug=args.project_slug,
        )
    except VerificationError as exc:
        print(f"container verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
