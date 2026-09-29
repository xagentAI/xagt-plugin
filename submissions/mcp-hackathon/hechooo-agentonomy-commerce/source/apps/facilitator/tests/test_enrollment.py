from __future__ import annotations

import base64
import hashlib

import pytest

from enrollment import EnrollmentError, EnrollmentService
from repository import InMemoryRepository
from shared.hosted_facilitator_protocol import DeviceSigningKey


NOW = 2_000_000_000


def _digest(token: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(token.encode("ascii")).digest()).rstrip(
        b"="
    ).decode("ascii")


def service(
    repo: InMemoryRepository | None = None,
) -> tuple[EnrollmentService, InMemoryRepository]:
    repository = repo or InMemoryRepository()
    return (
        EnrollmentService(
            repository=repository,
            enrollment_ttl_seconds=300,
            clock=lambda: NOW,
        ),
        repository,
    )


def enroll_request(service: EnrollmentService, *, wallet_binding_id: str = "binding_1"):
    invite = service.issue_enrollment_token("tenant_1")
    device_key = DeviceSigningKey.generate()
    access_token = "access_" + "a" * 40
    node = service.enroll(
        invite,
        public_jwk=device_key.public_jwk,
        wallet_binding_id=wallet_binding_id,
        expected_epoch=0,
        next_epoch=1,
        access_token_digest=_digest(access_token),
        status="pending",
    )
    return invite, node, device_key, access_token


def test_issue_and_enroll_store_only_client_digest() -> None:
    enrollment, repo = service()
    _, node, _, access_token = enroll_request(enrollment)

    assert node.tenant_id == "tenant_1"
    assert node.credential_epoch == 1
    assert node.access_token_digest == hashlib.sha256(access_token.encode()).digest()
    assert access_token not in repr(node)
    assert repo.get_node("tenant_1", node.node_id) == node


def test_enrollment_rejects_replay_with_different_binding_or_invalid_digest() -> None:
    enrollment, _ = service()
    invite, node, device_key, access_token = enroll_request(enrollment)

    # The service intentionally collapses replay conflicts into a generic
    # enrollment failure so the rejected binding is not disclosed.
    with pytest.raises(EnrollmentError, match="invalid|consumed"):
        enrollment.enroll(
            invite,
            public_jwk=device_key.public_jwk,
            wallet_binding_id="binding_2",
            expected_epoch=0,
            next_epoch=1,
            access_token_digest=_digest(access_token),
            status="pending",
        )
    with pytest.raises(EnrollmentError, match="digest"):
        enrollment.enroll(
            enrollment.issue_enrollment_token("tenant_1"),
            public_jwk=device_key.public_jwk,
            wallet_binding_id="binding_1",
            expected_epoch=0,
            next_epoch=1,
            access_token_digest="not-a-digest",
            status="pending",
        )
    assert node.tenant_id == "tenant_1"


def test_staged_rotation_requires_exact_prepared_binding() -> None:
    enrollment, repo = service()
    _, node, _, _ = enroll_request(enrollment)
    new_key = DeviceSigningKey.generate()
    new_token = "access_" + "b" * 40
    common = {
        "rotation_id": "rotation_1",
        "tenant_id": node.tenant_id,
        "node_id": node.node_id,
        "wallet_binding_id": node.wallet_binding_id,
        "expected_epoch": 1,
        "next_epoch": 2,
        "public_jwk": new_key.public_jwk,
        "device_key_id": new_key.thumbprint,
        "access_token_digest": _digest(new_token),
    }
    prepared = enrollment.prepare_rotation(**common)
    assert prepared.status == "prepared"
    assert repo.get_node_by_access_digest(prepared.pending_access_token_digest) is None

    committed = enrollment.commit_rotation(**common)
    assert committed.credential_epoch == 2
    assert committed.device_public_jwk == new_key.public_jwk
    assert committed.access_token_digest == prepared.pending_access_token_digest
    assert enrollment.commit_rotation(**common) == committed


def test_revoke_is_idempotent_for_exact_request() -> None:
    enrollment, _ = service()
    _, node, device_key, access_token = enroll_request(enrollment)
    request = {
        "revocation_id": "revocation_1",
        "tenant_id": node.tenant_id,
        "node_id": node.node_id,
        "wallet_binding_id": node.wallet_binding_id,
        "credential_epoch": 1,
        "expected_epoch": 1,
        "next_epoch": 2,
        "device_key_id": device_key.thumbprint,
        "access_token_digest": _digest(access_token),
        "status": "revoking",
    }
    revoked = enrollment.revoke(**request)
    assert revoked.status == "revoked"
    assert revoked.credential_epoch == 2
    assert enrollment.revoke(**request) == revoked
