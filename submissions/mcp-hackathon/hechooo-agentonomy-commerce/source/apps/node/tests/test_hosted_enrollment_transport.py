from __future__ import annotations

import base64
from pathlib import Path
import sys

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/core"))
sys.path.insert(0, str(ROOT / "apps/node"))

from clink_node.hosted_enrollment import (  # noqa: E402
    EnrollmentAuthentication,
    EnrollmentRequestNotDispatched,
)
from clink_node.hosted_enrollment_transport import (  # noqa: E402
    EnrollmentTransportConflict,
    EnrollmentTransportError,
    HttpxEnrollmentTransport,
)
from shared.hosted_facilitator_protocol import (  # noqa: E402
    DeviceSigningKey,
    canonical_json_bytes,
    verify_dpop_proof,
)


ENDPOINT = "https://enroll.agentonomy.example/v1/enrollments"
NOW = 1_700_000_000


def _token(prefix: str) -> str:
    return prefix + "x" * 42


def _authentication(prefix: str, *, tenant_id: str = "tenant_1", node_id: str = "node_1", epoch: int = 1):
    key = DeviceSigningKey.generate()
    return (
        EnrollmentAuthentication(
            tenant_id=tenant_id,
            node_id=node_id,
            credential_epoch=epoch,
            private_key_pkcs8_b64=base64.urlsafe_b64encode(key.pkcs8_der)
            .rstrip(b"=")
            .decode("ascii"),
            access_token=_token(prefix),
        ),
        key,
    )


def _transport(handler, *, max_response_bytes: int = 64 * 1024):
    return HttpxEnrollmentTransport(
        ENDPOINT,
        clock=lambda: NOW,
        max_response_bytes=max_response_bytes,
        transport=httpx.MockTransport(handler),
    )


def test_enroll_posts_exact_canonical_body_without_device_authentication():
    seen: list[httpx.Request] = []
    payload = {
        "token": _token("invite"),
        "wallet_binding_id": "wallet_1",
        "expected_epoch": 0,
        "next_epoch": 1,
        "public_jwk": {"crv": "P-256", "kty": "EC", "x": "x", "y": "y"},
        "device_key_id": "device_1",
        "access_token_digest": "digest_1",
        "status": "pending",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201,
            headers={"content-type": "application/json; charset=utf-8"},
            json={"status": "active"},
        )

    result = _transport(handler).enroll(payload)

    assert result == {"status": "active"}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == ENDPOINT
    assert request.content == canonical_json_bytes(payload)
    assert request.headers["accept"] == "application/json"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept-encoding"] == "identity"
    assert "authorization" not in request.headers
    assert "dpop" not in request.headers


def test_prepare_commit_and_revoke_use_the_exact_route_and_matching_dpop_key():
    old_auth, old_key = _authentication("old", epoch=1)
    pending_auth, pending_key = _authentication("pending", epoch=2)
    revoke_auth, revoke_key = _authentication("revoke", epoch=2)
    seen: list[tuple[str, str, EnrollmentAuthentication, DeviceSigningKey]] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/prepare"):
            expected = old_auth, old_key
        elif request.url.path.endswith("/commit"):
            expected = pending_auth, pending_key
        else:
            expected = revoke_auth, revoke_key
        claims = verify_dpop_proof(
            request.headers["dpop"],
            trusted_public_jwk=expected[1].public_jwk,
            method=request.method,
            url=str(request.url),
            access_token=expected[0].access_token,
            now=NOW,
        )
        assert claims.htu == str(request.url)
        assert request.headers["authorization"] == f"DPoP {expected[0].access_token}"
        seen.append((request.method, request.url.path, expected[0], expected[1]))
        assert claims.jti
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"status": "ok"},
        )

    transport = _transport(handler)
    common = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "rotation_id": "rotation_1",
        "expected_epoch": 1,
        "next_epoch": 2,
        "status": "pending",
    }
    transport.prepare_rotation(common, authentication=old_auth)
    transport.commit_rotation(common, authentication=pending_auth)
    transport.revoke(
        {
            "tenant_id": "tenant_1",
            "node_id": "node_1",
            "revocation_id": "revocation_1",
            "credential_epoch": 2,
            "expected_epoch": 2,
            "next_epoch": 3,
            "status": "revoking",
        },
        authentication=revoke_auth,
    )

    assert [(method, path) for method, path, _, _ in seen] == [
        ("POST", "/v1/enrollments/node_1/rotations/rotation_1/prepare"),
        ("POST", "/v1/enrollments/node_1/rotations/rotation_1/commit"),
        ("DELETE", "/v1/enrollments/node_1/revocations/revocation_1"),
    ]
    assert [request.content for request in requests] == [
        canonical_json_bytes(common),
        canonical_json_bytes(common),
        canonical_json_bytes(
            {
                "tenant_id": "tenant_1",
                "node_id": "node_1",
                "revocation_id": "revocation_1",
                "credential_epoch": 2,
                "expected_epoch": 2,
                "next_epoch": 3,
                "status": "revoking",
            }
        ),
    ]


def test_transport_does_not_follow_redirects():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.example"})

    with pytest.raises(EnrollmentTransportError):
        _transport(handler).enroll({"token": _token("invite")})
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/plain", b'{"status":"active"}'),
        ("application/json", b"\xff"),
        ("application/json", b"[]"),
        ("application/json", b'{"status":1,"status":2}'),
    ],
)
def test_success_response_requires_bounded_utf8_json_object(content_type: str, content: bytes):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(201, headers={"content-type": content_type}, content=content)

    with pytest.raises(EnrollmentTransportError):
        _transport(handler).enroll({"token": _token("invite")})


def test_success_response_body_is_bounded():
    def handler(_: httpx.Request) -> httpx.Response:
        body = b"{" + b'"status":"' + b"x" * 128 + b'"}'
        return httpx.Response(201, headers={"content-type": "application/json"}, content=body)

    with pytest.raises(EnrollmentTransportError):
        _transport(handler, max_response_bytes=32).enroll({"token": _token("invite")})


def test_transport_error_after_send_is_uncertain_and_never_contains_secrets():
    invite = _token("secret-invite")

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset")

    with pytest.raises(EnrollmentTransportError) as caught:
        _transport(handler).enroll({"token": invite})
    assert not isinstance(caught.value, EnrollmentRequestNotDispatched)
    assert invite not in str(caught.value)


def test_validation_failure_before_send_is_explicitly_not_dispatched():
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json={"status": "active"})

    with pytest.raises(EnrollmentRequestNotDispatched):
        _transport(handler).enroll({"token": _token("invite"), "unsupported": object()})
    assert calls == 0


def test_4xx_is_a_secret_free_conflict_and_5xx_is_uncertain():
    secret = _token("secret-invite")

    def conflict_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            headers={"content-type": "application/json"},
            json={"detail": secret},
        )

    with pytest.raises(EnrollmentTransportConflict) as caught:
        _transport(conflict_handler).enroll({"token": secret})
    assert caught.value.status_code == 409
    assert secret not in str(caught.value)

    def unavailable_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=secret.encode("ascii"))

    with pytest.raises(EnrollmentTransportError) as caught:
        _transport(unavailable_handler).enroll({"token": secret})
    assert not isinstance(caught.value, EnrollmentTransportConflict)
    assert secret not in str(caught.value)


def test_endpoint_must_be_the_canonical_https_enrollment_route():
    with pytest.raises(ValueError):
        HttpxEnrollmentTransport("http://localhost/v1/enrollments")
    with pytest.raises(ValueError):
        HttpxEnrollmentTransport("https://enroll.agentonomy.example/v1/enrollments/")


def test_transport_endpoint_is_read_only_and_canonical():
    transport = _transport(lambda _: httpx.Response(201, json={"status": "active"}))
    assert transport.endpoint == ENDPOINT
    with pytest.raises(AttributeError):
        transport.endpoint = "https://other.example/v1/enrollments"
    with pytest.raises(AttributeError):
        transport._endpoint = "https://other.example/v1/enrollments"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://enroll.agentonomy.example:0/v1/enrollments",
        "https://enroll.agentonomy.example:65536/v1/enrollments",
        "https://enroll%2eagentonomy.example/v1/enrollments",
        "https://enroll.例子/v1/enrollments",
        "https://enroll.agentonomy.example/v1/enrollments?x=1",
        "https://enroll.agentonomy.example/v1/enrollments#fragment",
        "https://user:password@enroll.agentonomy.example/v1/enrollments",
        "https://enroll.agentonomy.example/v1/enrollments\x7f",
    ],
)
def test_endpoint_rejects_noncanonical_url_boundaries(endpoint: str):
    with pytest.raises(ValueError):
        HttpxEnrollmentTransport(endpoint)


def test_non_string_enrollment_token_is_not_dispatched():
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json={"status": "active"})

    with pytest.raises(EnrollmentRequestNotDispatched):
        _transport(handler).enroll({"token": 123})
    assert calls == 0


def test_invalid_request_and_authentication_are_not_dispatched():
    auth, _ = _authentication("old", epoch=1)
    request = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "rotation_id": "rotation_1",
        "expected_epoch": 1,
        "next_epoch": 2,
        "status": "pending",
    }
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "ok"})

    transport = _transport(handler)
    with pytest.raises(EnrollmentRequestNotDispatched):
        transport.prepare_rotation([], authentication=auth)
    with pytest.raises(EnrollmentRequestNotDispatched):
        transport.prepare_rotation(request, authentication=object())
    assert calls == 0


def test_invalid_clock_is_not_dispatched():
    auth, _ = _authentication("old", epoch=1)
    transport = HttpxEnrollmentTransport(
        ENDPOINT,
        clock=object(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "ok"})
        ),
    )
    with pytest.raises(EnrollmentRequestNotDispatched):
        transport.prepare_rotation(
            {
                "tenant_id": "tenant_1",
                "node_id": "node_1",
                "rotation_id": "rotation_1",
                "expected_epoch": 1,
                "next_epoch": 2,
                "status": "pending",
            },
            authentication=auth,
        )
