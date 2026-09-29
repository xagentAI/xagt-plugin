from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.serialization import load_der_private_key
from starlette.requests import Request

from app import _ApiFailure, _auth_token, _dpop_header, create_app
from authority import CoreAuthorityRejected, CoreAuthorityUnavailable
from config import FacilitatorConfig
from enrollment import DeviceResponseSigner, EnrollmentService
from execution_repository import ExecutionRepository
from pilot_gate import PilotGatePolicy
from repository import InMemoryRepository
from replay import InMemoryReplayCoordinator, ReplayUnavailable
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HOSTED_BASE_USDC,
    HostedPaymentEnvelope,
    build_dpop_proof,
    canonical_json_bytes,
    sign_payment_envelope,
)


NOW = 2_000_000_000
ORIGIN = "http://127.0.0.1:8080"
PREFLIGHT_URL = f"{ORIGIN}/v1/preflight"


def config() -> FacilitatorConfig:
    return FacilitatorConfig(
        environment="test",
        public_origin=ORIGIN,
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="redis://127.0.0.1:6379/0",
        response_key_ref="test://response",
        chain_id=8453,
        asset_contract=HOSTED_BASE_USDC,
        enrollment_ttl_seconds=300,
        dpop_ttl_seconds=60,
        max_request_body_bytes=128 * 1024,
    )


def request_with_header(name: str, value: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(name.encode("ascii"), value.encode("utf-8"))],
        }
    )


@pytest.mark.parametrize(
    ("header_name", "reader", "value"),
    [
        ("authorization", _auth_token, "DPoP " + "é" * 8_192),
        ("dpop", _dpop_header, "é" * 65_536),
        ("authorization", _auth_token, "DPoP " + "A" * 8_193),
        ("dpop", _dpop_header, "A" * 65_537),
    ],
)
def test_auth_headers_reject_non_ascii_or_oversized_values_before_verification(
    header_name: str,
    reader,
    value: str,
) -> None:
    with pytest.raises(_ApiFailure, match="authentication failed"):
        reader(request_with_header(header_name, value))


def envelope(node_id: str, **overrides: object) -> HostedPaymentEnvelope:
    values: dict[str, object] = {
        "protocol_version": "clink-hosted-v1",
        "audience": "hosted-facilitator",
        "http_method": "POST",
        "http_path": "/v1/preflight",
        "request_id": "request_1",
        "idempotency_key": "idempotency_1",
        "tenant_id": "tenant_1",
        "node_id": node_id,
        "wallet_binding_id": "binding_1",
        "payment_capability_version": "clink-payment-capability-v1",
        "payment_capability_id": "capability_1",
        "payment_capability_hash": "0x" + "08" * 32,
        "wallet_identity_id": "identity_1",
        "wallet_address": "0x" + "11" * 20,
        "spending_grant_id": "grant_1",
        "spending_grant_hash": "0x" + "a1" * 32,
        "asset_allowance_id": "allowance_1",
        "reservation_id": "reservation_1",
        "reservation_hash": "0x" + "18" * 32,
        "action_id": "action_1",
        "policy_decision_id": "decision_1",
        "policy_snapshot_hash": "0x" + "b2" * 32,
        "risk_evidence_hash": "0x" + "c3" * 32,
        "purchase_id": "purchase_1",
        "merchant_id": "merchant_1",
        "quote_hash": "0x" + "d4" * 32,
        "payment_challenge_hash": "0x" + "e5" * 32,
        "chain_id": "eip155:8453",
        "asset_contract": "0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913",
        "amount_atomic": "1000000",
        "pay_to": "0x" + "33" * 20,
        "executor_contract": "0x" + "44" * 20,
        "execution_scope_hash": "0x" + "f6" * 32,
        "request_nonce": "0x" + "07" * 32,
        "issued_at": NOW - 1,
        "expires_at": NOW + 59,
    }
    values.update(overrides)
    return HostedPaymentEnvelope(**values)


class Harness:
    def __init__(self) -> None:
        self.repo = InMemoryRepository()
        self.replay = InMemoryReplayCoordinator()
        self.response_key = DeviceSigningKey.generate()
        self.service = EnrollmentService(
            repository=self.repo,
            enrollment_ttl_seconds=300,
            clock=lambda: NOW,
        )
        self.enrollment_token = self.service.issue_enrollment_token("tenant_1")
        self.device_key = DeviceSigningKey.generate()
        self.access_token = "access_" + "a" * 40
        result = self.service.enroll(
            self.enrollment_token,
            public_jwk=self.device_key.public_jwk,
            wallet_binding_id="binding_1",
            expected_epoch=0,
            next_epoch=1,
            access_token_digest=base64.urlsafe_b64encode(
                hashlib.sha256(self.access_token.encode()).digest()
            )
            .rstrip(b"=")
            .decode("ascii"),
            status="pending",
        )
        self.node_id = result.node_id
        self.authority = PreflightAuthority()
        self.app = create_app(
            config(),
            repository=self.repo,
            replay=self.replay,
            response_signer=DeviceResponseSigner(self.response_key),
            clock=lambda: NOW,
            intent_resolver=self.authority,
        )
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.jti = 0

    def next_jti(self) -> str:
        self.jti += 1
        return f"jti_{self.jti}"

    def headers(
        self,
        *,
        key: DeviceSigningKey | None = None,
        token: str | None = None,
        url: str = PREFLIGHT_URL,
        jti: str | None = None,
        method: str = "POST",
    ) -> dict[str, str]:
        access_token = token or self.access_token
        proof = build_dpop_proof(
            key or self.device_key,
            method=method,
            url=url,
            access_token=access_token,
            now=NOW,
            jti=jti or self.next_jti(),
        )
        return {
            "authorization": f"DPoP {access_token}",
            "dpop": proof,
            "content-type": "application/json",
        }

    def request(
        self,
        item: HostedPaymentEnvelope | None = None,
        *,
        key: DeviceSigningKey | None = None,
        token: str | None = None,
        jti: str | None = None,
        body: bytes | None = None,
    ):
        item = item or envelope(self.node_id)
        payload = body or canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(key or self.device_key, item)}
        )
        return self.client.post(
            "/v1/preflight",
            content=payload,
            headers=self.headers(key=key, token=token, jti=jti),
        )


class PreflightAuthority:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[HostedPaymentEnvelope, Any]] = []

    def preflight(self, item: HostedPaymentEnvelope, node: Any) -> None:
        self.calls.append((item, node))
        if self.error is not None:
            raise self.error


@pytest.fixture
def harness() -> Harness:
    return Harness()


def verify_response(response_key: DeviceSigningKey, token: str) -> dict[str, Any]:
    private = load_der_private_key(response_key.pkcs8_der, password=None)
    public = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(response_key.public_jwk))
    claims = jwt.decode(token, public, algorithms=["ES256"], options={"verify_aud": False})
    assert claims["server_key_id"] == response_key.thumbprint
    return claims


def test_preflight_returns_signed_dry_run_and_never_execution_fields(harness: Harness) -> None:
    response = harness.request()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"response_jws"}
    receipt = verify_response(harness.response_key, body["response_jws"])
    assert receipt["state"] == "dry_run_accepted"
    assert receipt["request_hash"] == envelope(harness.node_id).request_hash
    assert receipt["transaction_hash"] is None
    assert receipt["submitted_at"] is None
    assert receipt["confirmed_at"] is None
    assert len(harness.authority.calls) == 1


def test_preflight_pause_denial_precedes_core_authority(
    harness: Harness,
    tmp_path,
) -> None:
    executions = ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'preflight-gate.sqlite3'}",
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000
        ),
    )
    executions.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )
    harness.app = create_app(
        config(),
        repository=harness.repo,
        replay=harness.replay,
        response_signer=DeviceResponseSigner(harness.response_key),
        clock=lambda: NOW,
        execution_repository=executions,
        intent_resolver=harness.authority,
    )
    harness.client = TestClient(harness.app, base_url=ORIGIN)

    response = harness.request()

    assert response.status_code == 409
    assert response.json()["code"] == "platform_paused"
    assert harness.authority.calls == []


def test_preflight_authority_rejection_happens_before_signing_or_binding(harness: Harness) -> None:
    harness.authority.error = CoreAuthorityRejected("scope rejected")

    response = harness.request(jti="jti-authority-rejected")

    assert response.status_code == 409
    assert response.json()["code"] == "preflight_conflict"
    assert harness.repo._preflights == {}


def test_preflight_authority_unavailable_happens_before_signing_or_binding(harness: Harness) -> None:
    harness.authority.error = CoreAuthorityUnavailable("authority unavailable")

    response = harness.request(jti="jti-authority-unavailable")

    assert response.status_code == 503
    assert response.json()["code"] == "authority_unavailable"
    assert harness.repo._preflights == {}


def test_preflight_rejects_non_base_capability_before_core_authority(harness: Harness) -> None:
    response = harness.request(
        envelope(
            harness.node_id,
            chain_id="eip155:137",
            asset_contract="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        ),
        jti="jti-non-base",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "scope_mismatch"
    assert harness.authority.calls == []


def test_exact_idempotent_retry_with_fresh_dpop_jti_returns_identical_signed_response(
    harness: Harness,
) -> None:
    first = harness.request(jti="jti-first")
    second = harness.request(jti="jti-second")

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()


def test_replay_and_mutation_conflicts_fail_closed(harness: Harness) -> None:
    first = harness.request(jti="jti-replay")
    assert first.status_code == 200
    replay = harness.request(jti="jti-replay")
    assert replay.status_code == 401

    changed = harness.request(
        envelope(harness.node_id, amount_atomic="2"), jti="jti-mutated"
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "tenant_2"},
        {"node_id": "node_other"},
        {"wallet_binding_id": "binding_other"},
        {"http_path": "/v1/executions"},
    ],
)
def test_preflight_rejects_wrong_scope_without_moving_money(
    harness: Harness,
    change: dict[str, object],
) -> None:
    values: dict[str, object] = {"node_id": harness.node_id}
    values.update(change)
    response = harness.request(envelope(**values), jti=harness.next_jti())

    assert response.status_code in {400, 403}


def test_wrong_device_or_token_is_rejected(harness: Harness) -> None:
    attacker = DeviceSigningKey.generate()
    wrong_key = harness.request(key=attacker, jti="jti-wrong-key")
    assert wrong_key.status_code == 401

    wrong_token = harness.request(token="wrong-token", jti="jti-wrong-token")
    assert wrong_token.status_code == 401


def test_oversized_or_unknown_body_is_bounded_and_error_has_no_secret(harness: Harness) -> None:
    oversized = harness.request(
        body=b"{" + b"x" * (config().max_request_body_bytes + 1)
    )
    assert oversized.status_code == 413
    assert "jti" not in oversized.text
    unknown = harness.client.post(
        "/v1/preflight",
        content=canonical_json_bytes({"payment_jws": "x", "extra": True}),
        headers=harness.headers(jti="jti-unknown"),
    )
    assert unknown.status_code == 400


def test_redis_outage_fails_closed_before_durable_success(harness: Harness) -> None:
    class Down:
        def consume_dpop_jti(self, **_: object) -> bool:
            raise ReplayUnavailable("redis unavailable")

    app = create_app(
        config(),
        repository=harness.repo,
        replay=Down(),
        response_signer=DeviceResponseSigner(harness.response_key),
        clock=lambda: NOW,
        intent_resolver=harness.authority,
    )
    client = TestClient(app, base_url=ORIGIN)
    response = client.post(
        "/v1/preflight",
        content=canonical_json_bytes(
            {
                "payment_jws": sign_payment_envelope(
                    harness.device_key, envelope(harness.node_id)
                )
            }
        ),
        headers=harness.headers(jti="jti-redis-down"),
    )
    assert response.status_code == 503


def test_legacy_one_step_rotation_and_revocation_routes_are_removed(harness: Harness) -> None:
    rotate_path = f"/v1/enrollments/{harness.node_id}/rotate"
    revoke_path = f"/v1/enrollments/{harness.node_id}"
    assert harness.client.post(rotate_path, content=b"{}").status_code == 404
    assert harness.client.request("DELETE", revoke_path, content=b"{}").status_code == 404
