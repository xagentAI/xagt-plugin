from __future__ import annotations

import base64
import hashlib
from dataclasses import replace

from fastapi.testclient import TestClient

from app import create_app
from config import FacilitatorConfig
from enrollment import EnrollmentService
from repository import InMemoryRepository
from replay import InMemoryReplayCoordinator
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HOSTED_BASE_USDC,
    build_dpop_proof,
    canonical_json_bytes,
)


NOW = 2_000_000_000
ORIGIN = "http://127.0.0.1:8080"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _digest(token: str) -> str:
    return _b64url(hashlib.sha256(token.encode("ascii")).digest())


def _config(*, dpop_ttl_seconds: int = 60) -> FacilitatorConfig:
    return FacilitatorConfig(
        environment="test",
        public_origin=ORIGIN,
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="redis://127.0.0.1:6379/0",
        response_key_ref="test://response",
        chain_id=8453,
        asset_contract=HOSTED_BASE_USDC,
        enrollment_ttl_seconds=300,
        dpop_ttl_seconds=dpop_ttl_seconds,
        max_request_body_bytes=128 * 1024,
    )


class Harness:
    def __init__(self, *, dpop_ttl_seconds: int = 60) -> None:
        self.now = NOW
        self.repository = InMemoryRepository()
        self.replay = (
            ExpiringReplayCoordinator(lambda: self.now)
            if dpop_ttl_seconds < 60
            else InMemoryReplayCoordinator()
        )
        self.service = EnrollmentService(
            repository=self.repository,
            enrollment_ttl_seconds=300,
            clock=lambda: self.now,
        )
        self.response_key = DeviceSigningKey.generate()
        self.app = create_app(
            _config(dpop_ttl_seconds=dpop_ttl_seconds),
            repository=self.repository,
            replay=self.replay,
            response_signer=self._response_signer,
            clock=lambda: self.now,
        )
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.invite = self.service.issue_enrollment_token("tenant_1")

    @property
    def _response_signer(self):
        from enrollment import DeviceResponseSigner

        return DeviceResponseSigner(self.response_key)

    def enroll(self) -> tuple[dict[str, object], DeviceSigningKey, str]:
        device_key = DeviceSigningKey.generate()
        access_token = "access_" + "a" * 40
        payload = {
            "token": self.invite,
            "wallet_binding_id": "binding_1",
            "expected_epoch": 0,
            "next_epoch": 1,
            "public_jwk": device_key.public_jwk,
            "device_key_id": device_key.thumbprint,
            "access_token_digest": _digest(access_token),
            "status": "pending",
        }
        response = self.client.post(
            "/v1/enrollments",
            content=canonical_json_bytes(payload),
        )
        assert response.status_code == 201, response.text
        return response.json(), device_key, access_token

    def headers(
        self,
        *,
        key: DeviceSigningKey,
        token: str,
        method: str,
        path: str,
        jti: str,
    ) -> dict[str, str]:
        url = ORIGIN + path
        return {
            "authorization": f"DPoP {token}",
            "dpop": build_dpop_proof(
                key,
                method=method,
                url=url,
                access_token=token,
                now=self.now,
                jti=jti,
            ),
            "content-type": "application/json",
        }


class ExpiringReplayCoordinator:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.entries: dict[tuple[str, str, int, str], int] = {}

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        ttl_seconds: int,
    ) -> bool:
        now = self.clock()
        self.entries = {
            key: expiry
            for key, expiry in self.entries.items()
            if expiry > now
        }
        key = (tenant_id, node_id, credential_epoch, jti)
        if key in self.entries:
            return False
        self.entries[key] = now + ttl_seconds
        return True


def test_enrollment_accepts_exact_protocol_and_replays_after_invite_expiry() -> None:
    harness = Harness()
    first, device_key, access_token = harness.enroll()

    assert set(first) == {
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "expected_epoch",
        "next_epoch",
        "credential_epoch",
        "device_key_id",
        "access_token_digest",
        "status",
    }
    assert "access_token" not in first
    assert "response_public_jwk" not in first
    assert first["wallet_binding_id"] == "binding_1"
    assert first["access_token_digest"] == _digest(access_token)

    harness.now += 301
    replay = harness.client.post(
        "/v1/enrollments",
        content=canonical_json_bytes(
            {
                "token": harness.invite,
                "wallet_binding_id": "binding_1",
                "expected_epoch": 0,
                "next_epoch": 1,
                "public_jwk": device_key.public_jwk,
                "device_key_id": device_key.thumbprint,
                "access_token_digest": _digest(access_token),
                "status": "pending",
            }
        ),
    )
    assert replay.status_code == 201
    assert replay.json() == first


def test_rotation_prepare_commit_and_exact_committed_replay_use_narrow_routes() -> None:
    harness = Harness()
    enrolled, old_key, old_token = harness.enroll()
    node_id = enrolled["node_id"]
    new_key = DeviceSigningKey.generate()
    new_token = "access_" + "b" * 40
    rotation_id = "rotation_1"
    common = {
        "rotation_id": rotation_id,
        "tenant_id": "tenant_1",
        "node_id": node_id,
        "wallet_binding_id": "binding_1",
        "expected_epoch": 1,
        "next_epoch": 2,
        "public_jwk": new_key.public_jwk,
        "device_key_id": new_key.thumbprint,
        "access_token_digest": _digest(new_token),
    }
    prepare_path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/prepare"
    prepared = harness.client.post(
        prepare_path,
        content=canonical_json_bytes(common),
        headers=harness.headers(
            key=old_key,
            token=old_token,
            method="POST",
            path=prepare_path,
            jti="prepare-1",
        ),
    )
    assert prepared.status_code == 200, prepared.text
    assert set(prepared.json()) == (set(common) - {"public_jwk"}) | {"status"}
    assert prepared.json()["status"] == "prepared"

    commit_path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/commit"
    old_credential = harness.client.post(
        commit_path,
        content=canonical_json_bytes(common),
        headers=harness.headers(
            key=old_key,
            token=old_token,
            method="POST",
            path=commit_path,
            jti="commit-old-credential",
        ),
    )
    assert old_credential.status_code == 401

    committed = harness.client.post(
        commit_path,
        content=canonical_json_bytes(common),
        headers=harness.headers(
            key=new_key,
            token=new_token,
            method="POST",
            path=commit_path,
            jti="commit-1",
        ),
    )
    assert committed.status_code == 200, committed.text
    assert set(committed.json()) == (set(common) - {"public_jwk"}) | {
        "credential_epoch",
        "status",
    }
    assert committed.json()["credential_epoch"] == 2
    assert committed.json()["status"] == "active"

    replay = harness.client.post(
        commit_path,
        content=canonical_json_bytes(common),
        headers=harness.headers(
            key=new_key,
            token=new_token,
            method="POST",
            path=commit_path,
            jti="commit-2",
        ),
    )
    assert replay.status_code == 200
    assert replay.json() == committed.json()

    assert harness.client.post(
        f"/v1/enrollments/{node_id}/rotate",
        content=b"{}",
    ).status_code == 404


def test_rotation_prepare_cannot_target_another_tenant_with_the_same_node_id() -> None:
    harness = Harness()
    enrolled, attacker_key, attacker_token = harness.enroll()
    node_id = str(enrolled["node_id"])
    attacker = harness.repository.get_node("tenant_1", node_id)
    assert attacker is not None

    target_key = DeviceSigningKey.generate()
    target_token = "access_" + "t" * 40
    target = replace(
        attacker,
        tenant_id="tenant_2",
        wallet_binding_id="binding_2",
        device_public_jwk=target_key.public_jwk,
        device_key_id=target_key.thumbprint,
        access_token_digest=hashlib.sha256(
            target_token.encode("ascii")
        ).digest(),
    )
    harness.repository.put_node(target)

    replacement_key = DeviceSigningKey.generate()
    replacement_token = "access_" + "r" * 40
    rotation_id = "rotation_cross_tenant"
    path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/prepare"
    payload = {
        "rotation_id": rotation_id,
        "tenant_id": target.tenant_id,
        "node_id": node_id,
        "wallet_binding_id": target.wallet_binding_id,
        "expected_epoch": target.credential_epoch,
        "next_epoch": target.credential_epoch + 1,
        "public_jwk": replacement_key.public_jwk,
        "device_key_id": replacement_key.thumbprint,
        "access_token_digest": _digest(replacement_token),
    }

    response = harness.client.post(
        path,
        content=canonical_json_bytes(payload),
        headers=harness.headers(
            key=attacker_key,
            token=attacker_token,
            method="POST",
            path=path,
            jti="prepare-cross-tenant",
        ),
    )

    assert response.status_code == 403
    assert (
        harness.repository.get_pending_rotation_by_access_digest(
            hashlib.sha256(replacement_token.encode("ascii")).digest(),
            tenant_id=target.tenant_id,
            node_id=target.node_id,
        )
        is None
    )


def test_dpop_replay_is_retained_for_the_entire_accepted_proof_lifetime() -> None:
    harness = Harness(dpop_ttl_seconds=1)
    enrolled, device_key, access_token = harness.enroll()
    node_id = str(enrolled["node_id"])
    replacement_key = DeviceSigningKey.generate()
    replacement_token = "access_" + "n" * 40
    rotation_id = "rotation_replay_window"
    path = f"/v1/enrollments/{node_id}/rotations/{rotation_id}/prepare"
    payload = {
        "rotation_id": rotation_id,
        "tenant_id": "tenant_1",
        "node_id": node_id,
        "wallet_binding_id": "binding_1",
        "expected_epoch": 1,
        "next_epoch": 2,
        "public_jwk": replacement_key.public_jwk,
        "device_key_id": replacement_key.thumbprint,
        "access_token_digest": _digest(replacement_token),
    }
    headers = harness.headers(
        key=device_key,
        token=access_token,
        method="POST",
        path=path,
        jti="prepare-retention",
    )

    # Authentication consumes the JTI before this scope mismatch.  A replay
    # must stay blocked for as long as the signed proof itself is accepted.
    rejected = harness.client.post(
        path,
        content=canonical_json_bytes(
            {**payload, "wallet_binding_id": "binding_wrong"}
        ),
        headers=headers,
    )
    assert rejected.status_code == 403

    harness.now += 2
    replayed = harness.client.post(
        path,
        content=canonical_json_bytes(payload),
        headers=headers,
    )
    assert replayed.status_code == 401
    assert replayed.json()["code"] == "dpop_replay"


def test_revoke_replay_accepts_only_exact_revoked_route_and_active_preflight_auth_stays_active_only() -> None:
    harness = Harness()
    enrolled, device_key, access_token = harness.enroll()
    node_id = enrolled["node_id"]
    revocation_id = "revocation_1"
    path = f"/v1/enrollments/{node_id}/revocations/{revocation_id}"
    body = {
        "revocation_id": revocation_id,
        "tenant_id": "tenant_1",
        "node_id": node_id,
        "wallet_binding_id": "binding_1",
        "credential_epoch": 1,
        "expected_epoch": 1,
        "next_epoch": 2,
        "device_key_id": device_key.thumbprint,
        "access_token_digest": _digest(access_token),
        "status": "revoking",
    }
    revoked = harness.client.request(
        "DELETE",
        path,
        content=canonical_json_bytes(body),
        headers=harness.headers(
            key=device_key,
            token=access_token,
            method="DELETE",
            path=path,
            jti="revoke-1",
        ),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {
        "revocation_id": revocation_id,
        "tenant_id": "tenant_1",
        "node_id": node_id,
        "wallet_binding_id": "binding_1",
        "expected_epoch": 1,
        "next_epoch": 2,
        "credential_epoch": 2,
        "device_key_id": device_key.thumbprint,
        "access_token_digest": _digest(access_token),
        "status": "revoked",
    }

    replay = harness.client.request(
        "DELETE",
        path,
        content=canonical_json_bytes(body),
        headers=harness.headers(
            key=device_key,
            token=access_token,
            method="DELETE",
            path=path,
            jti="revoke-2",
        ),
    )
    assert replay.status_code == 200
    assert replay.json() == revoked.json()

    preflight_path = "/v1/preflight"
    preflight = harness.client.post(
        preflight_path,
        content=canonical_json_bytes({"payment_jws": "unused"}),
        headers=harness.headers(
            key=device_key,
            token=access_token,
            method="POST",
            path=preflight_path,
            jti="revoked-preflight",
        ),
    )
    assert preflight.status_code == 401
    assert preflight.json()["code"] == "invalid_authentication"

    mismatched = dict(body, next_epoch=3)
    rejected = harness.client.request(
        "DELETE",
        path,
        content=canonical_json_bytes(mismatched),
        headers=harness.headers(
            key=device_key,
            token=access_token,
            method="DELETE",
            path=path,
            jti="revoke-3",
        ),
    )
    assert rejected.status_code in {400, 401, 409}
