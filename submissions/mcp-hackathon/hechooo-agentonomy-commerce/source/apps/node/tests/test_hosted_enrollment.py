from __future__ import annotations

import json
import multiprocessing
import threading
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path

import pytest

from clink_node.hosted_enrollment import (
    EnrollmentConflict,
    EnrollmentRequestNotDispatched,
    EnrollmentTrust,
    HostedEnrollmentManager,
    HostedTargetTrust,
)
from clink_node.secrets import MemorySecretStore, RestrictedFileSecretStore


BASE_RESPONSE_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "axfR8uEsQkf4vOblY6RA8ncDfYEt6zOg9KE5RdiYwpY",
    "y": "T-NC4v4af5uO5-tKfA-eFivOM1drMV7Oy7ZAaDe_UfU",
}
POLYGON_RESPONSE_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "fPJ7GI0DT36KUjgDBLUaw8CJaeJ38hs1pgtI_EdmmXg",
    "y": "B3dVENuO0EApPZrGn3Qw27p9reY86YIpngS3nSJ4c9E",
}
INVITE = "i" * 43
OTHER_INVITE = "j" * 43


def trust() -> EnrollmentTrust:
    return EnrollmentTrust(
        enrollment_endpoint="https://enroll.agentonomy.example/v1/enrollments",
        targets={
            8453: HostedTargetTrust(
                chain_id=8453,
                endpoint="https://base.agentonomy.example",
                response_public_jwk=BASE_RESPONSE_JWK,
                executor_contract="0x" + "11" * 20,
            ),
            137: HostedTargetTrust(
                chain_id=137,
                endpoint="https://polygon.agentonomy.example",
                response_public_jwk=POLYGON_RESPONSE_JWK,
                executor_contract="0x" + "22" * 20,
            ),
        },
    )


def _probe_default_lock_in_subprocess(
    path: str,
    started: object,
    acquired: object,
) -> None:
    store = RestrictedFileSecretStore(Path(path))
    enrollment = HostedEnrollmentManager(
        secret_store=store,
        transport=RecordingTransport(),
        trust=trust(),
    )
    started.set()
    with enrollment._mutation_lock:
        acquired.set()


class RecordingTransport:
    endpoint = "https://enroll.agentonomy.example/v1/enrollments"

    def __init__(self) -> None:
        self.enroll_calls: list[dict[str, object]] = []
        self.prepare_calls: list[dict[str, object]] = []
        self.commit_calls: list[dict[str, object]] = []
        self.revoke_calls: list[dict[str, object]] = []
        self.fail_enroll_once = False
        self.fail_commit_once = False
        self.lose_prepare_response_once = False
        self.fail_revoke = False
        self.lose_revoke_response_once = False
        self.revocations: dict[str, dict[str, object]] = {}
        self.required_lock: RecordingLock | None = None

    def _assert_locked(self) -> None:
        if self.required_lock is not None:
            assert self.required_lock.depth == 1

    def enroll(self, request: dict[str, object]) -> dict[str, object]:
        self._assert_locked()
        self.enroll_calls.append(request)
        if self.fail_enroll_once:
            self.fail_enroll_once = False
            raise RuntimeError("response lost")
        return {
            "tenant_id": "tenant_1",
            "node_id": "node_1",
            "wallet_binding_id": request["wallet_binding_id"],
            "expected_epoch": request["expected_epoch"],
            "next_epoch": request["next_epoch"],
            "credential_epoch": 1,
            "device_key_id": request["device_key_id"],
            "access_token_digest": request["access_token_digest"],
            "status": "active",
        }

    def prepare_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: object,
    ) -> dict[str, object]:
        self._assert_locked()
        assert authentication is not None
        self.prepare_calls.append(request)
        result = {
            "rotation_id": request["rotation_id"],
            "tenant_id": request["tenant_id"],
            "node_id": request["node_id"],
            "wallet_binding_id": request["wallet_binding_id"],
            "expected_epoch": request["expected_epoch"],
            "next_epoch": request["next_epoch"],
            "device_key_id": request["device_key_id"],
            "access_token_digest": request["access_token_digest"],
            "status": "prepared",
        }
        if self.lose_prepare_response_once:
            self.lose_prepare_response_once = False
            raise RuntimeError("prepare response lost")
        return result

    def commit_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: object,
    ) -> dict[str, object]:
        self._assert_locked()
        assert authentication is not None
        self.commit_calls.append(request)
        result = {
            "rotation_id": request["rotation_id"],
            "tenant_id": request["tenant_id"],
            "node_id": request["node_id"],
            "wallet_binding_id": request["wallet_binding_id"],
            "expected_epoch": request["expected_epoch"],
            "next_epoch": request["next_epoch"],
            "credential_epoch": request["next_epoch"],
            "device_key_id": request["device_key_id"],
            "access_token_digest": request["access_token_digest"],
            "status": "active",
        }
        if self.fail_commit_once:
            self.fail_commit_once = False
            raise RuntimeError("commit response lost")
        return result

    def revoke(
        self,
        request: dict[str, object],
        *,
        authentication: object,
    ) -> dict[str, object]:
        self._assert_locked()
        assert authentication is not None
        self.revoke_calls.append(request)
        if self.fail_revoke:
            raise EnrollmentRequestNotDispatched("revoke unavailable")
        revocation_id = str(request["revocation_id"])
        result = self.revocations.setdefault(revocation_id, {
            "revocation_id": revocation_id,
            "tenant_id": request["tenant_id"],
            "node_id": request["node_id"],
            "wallet_binding_id": request["wallet_binding_id"],
            "expected_epoch": request["expected_epoch"],
            "next_epoch": request["next_epoch"],
            "credential_epoch": int(request["credential_epoch"]) + 1,
            "device_key_id": request["device_key_id"],
            "access_token_digest": request["access_token_digest"],
            "status": "revoked",
        })
        if self.lose_revoke_response_once:
            self.lose_revoke_response_once = False
            raise RuntimeError("revoke response lost")
        return result


class RecordingLock(AbstractContextManager):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.depth = 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1
        return self

    def __exit__(self, *_args: object) -> None:
        self.depth -= 1
        self._lock.release()


_LOCKS: dict[int, RecordingLock] = {}


def manager(
    store: MemorySecretStore,
    transport: RecordingTransport,
    *,
    enrollment_trust: EnrollmentTrust | None = None,
) -> HostedEnrollmentManager:
    lock = _LOCKS.setdefault(id(store), RecordingLock())
    transport.required_lock = lock
    return HostedEnrollmentManager(
        secret_store=store,
        transport=transport,
        trust=enrollment_trust or trust(),
        mutation_lock=lock,
    )


def test_enrollment_reuses_pending_credentials_after_response_loss() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    transport.fail_enroll_once = True
    enrollment = manager(store, transport)

    with pytest.raises(RuntimeError, match="response lost"):
        enrollment.enroll(
            invite_code=INVITE,
            wallet_binding_id="wallet_binding_1",
        )

    persisted = store.get("hosted-enrollment-v1")
    assert persisted is not None
    assert INVITE.encode("ascii") not in persisted
    assert b'"state":"enrollment_pending"' in persisted

    recovered = manager(store, transport).enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    assert recovered.state == "active"
    assert recovered.node_id == "node_1"
    assert len(transport.enroll_calls) == 2
    assert transport.enroll_calls[0] == transport.enroll_calls[1]
    assert store.get("hosted-enrollment-v1") is not None
    assert b'"state":"active"' in store.get("hosted-enrollment-v1")


def test_pending_enrollment_rejects_a_different_invite_or_wallet() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    transport.fail_enroll_once = True
    enrollment = manager(store, transport)
    with pytest.raises(RuntimeError):
        enrollment.enroll(
            invite_code=INVITE,
            wallet_binding_id="wallet_binding_1",
        )

    with pytest.raises(EnrollmentConflict):
        enrollment.enroll(
            invite_code=OTHER_INVITE,
            wallet_binding_id="wallet_binding_1",
        )
    with pytest.raises(EnrollmentConflict):
        enrollment.enroll(
            invite_code=INVITE,
            wallet_binding_id="wallet_binding_2",
        )
    assert len(transport.enroll_calls) == 1


def test_active_enrollment_is_restored_without_network_after_restart() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    active = manager(store, transport).enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )

    restarted = manager(store, transport)
    assert restarted.current() == active
    assert len(transport.enroll_calls) == 1


def test_rotation_commit_response_loss_resumes_with_same_pending_credential() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_commit_once = True

    with pytest.raises(RuntimeError, match="commit response lost"):
        enrollment.rotate()

    pending = manager(store, transport).current()
    assert pending.state == "rotation_pending"
    assert pending.node_id == active.node_id
    recovered = manager(store, transport).resume_rotation()
    assert recovered.state == "active"
    assert recovered.credential_epoch == active.credential_epoch + 1
    assert len(transport.prepare_calls) == 1
    assert len(transport.commit_calls) == 2
    assert transport.commit_calls[0] == transport.commit_calls[1]


def test_rotation_prepare_response_loss_resumes_with_same_pending_request() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.lose_prepare_response_once = True

    with pytest.raises(RuntimeError, match="prepare response lost"):
        enrollment.rotate()

    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "rotation_pending"
    recovered = manager(store, transport).resume_rotation()

    assert recovered.state == "active"
    assert recovered.credential_epoch == 2
    assert len(transport.prepare_calls) == 2
    assert transport.prepare_calls[0] == transport.prepare_calls[1]
    assert len(transport.commit_calls) == 1


def test_revoke_recovers_pending_rotation_before_using_new_active_credential() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_commit_once = True

    with pytest.raises(RuntimeError, match="commit response lost"):
        enrollment.rotate()
    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "rotation_pending"
    assert pending.pending_access_token is not None
    pending_digest = transport.commit_calls[0]["access_token_digest"]

    enrollment.revoke()

    assert len(transport.commit_calls) == 2
    assert len(transport.revoke_calls) == 1
    request = transport.revoke_calls[0]
    assert request["credential_epoch"] == active.credential_epoch + 1
    assert request["expected_epoch"] == active.credential_epoch + 1
    assert request["next_epoch"] == active.credential_epoch + 2
    assert request["access_token_digest"] == pending_digest
    assert store.get("hosted-enrollment-v1") is None


def test_revoke_does_not_run_when_pending_rotation_recovery_fails() -> None:
    store = MemorySecretStore({})

    class CommitRecoveryFailureTransport(RecordingTransport):
        commit_attempts = 0

        def commit_rotation(self, request, *, authentication):
            self.commit_attempts += 1
            result = super().commit_rotation(
                request,
                authentication=authentication,
            )
            if self.commit_attempts == 2:
                raise RuntimeError("commit recovery failed")
            return result

    transport = CommitRecoveryFailureTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_commit_once = True
    with pytest.raises(RuntimeError, match="commit response lost"):
        enrollment.rotate()

    with pytest.raises(RuntimeError, match="commit recovery failed"):
        enrollment.revoke()

    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "rotation_pending"
    assert transport.revoke_calls == []


def test_revoke_not_dispatched_after_rotation_recovery_keeps_new_active_epoch() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_commit_once = True
    with pytest.raises(RuntimeError, match="commit response lost"):
        enrollment.rotate()

    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.pending_access_token is not None
    pending_digest = transport.commit_calls[0]["access_token_digest"]
    transport.fail_revoke = True

    with pytest.raises(EnrollmentRequestNotDispatched):
        enrollment.revoke()

    recovered = manager(store, transport).current()
    assert recovered is not None
    assert recovered.state == "active"
    assert recovered.credential_epoch == active.credential_epoch + 1
    assert recovered.access_token_digest == pending_digest
    assert recovered.pending_access_token is None
    assert transport.revoke_calls[0]["credential_epoch"] == recovered.credential_epoch


def test_revoke_failure_preserves_active_bundle_and_success_removes_it() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_revoke = True

    with pytest.raises(RuntimeError, match="revoke unavailable"):
        enrollment.revoke()
    assert manager(store, transport).current() == active

    transport.fail_revoke = False
    enrollment.revoke()
    assert store.get("hosted-enrollment-v1") is None


def test_uncertain_revoke_failure_keeps_pending_even_with_unavailable_message() -> None:
    store = MemorySecretStore({})

    class OrdinaryFailureTransport(RecordingTransport):
        def revoke(self, request, *, authentication):
            self._assert_locked()
            assert authentication is not None
            self.revoke_calls.append(request)
            raise RuntimeError("revoke unavailable")

    transport = OrdinaryFailureTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )

    with pytest.raises(RuntimeError, match="revoke unavailable"):
        enrollment.revoke()

    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "revocation_pending"
    assert pending.revocation_pending is True
    assert pending.revocation_id is not None


def test_revoke_response_loss_resumes_same_remote_revocation_after_restart() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.lose_revoke_response_once = True

    with pytest.raises(RuntimeError, match="revoke response lost"):
        enrollment.revoke()

    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "revocation_pending"
    assert pending.node_id == active.node_id
    manager(store, transport).resume_revocation()
    assert store.get("hosted-enrollment-v1") is None
    assert len(transport.revoke_calls) == 2
    assert transport.revoke_calls[0] == transport.revoke_calls[1]


def test_trust_requires_exact_base_and_polygon_https_targets() -> None:
    valid = trust()
    with pytest.raises(ValueError, match="Base and Polygon"):
        replace(valid, targets={8453: valid.targets[8453]})
    with pytest.raises(ValueError, match="HTTPS"):
        replace(
            valid,
            targets={
                **valid.targets,
                137: replace(
                    valid.targets[137],
                    endpoint="http://polygon.agentonomy.example",
                ),
            },
        )


def test_hosted_target_trust_binds_nonzero_executor_and_fingerprint() -> None:
    base = HostedTargetTrust(
        chain_id=8453,
        endpoint="https://base.agentonomy.example",
        response_public_jwk=BASE_RESPONSE_JWK,
        executor_contract="0x" + "11" * 20,
    )
    assert base.executor_contract == "0x" + "11" * 20

    with pytest.raises(ValueError, match="executor"):
        HostedTargetTrust(
            chain_id=8453,
            endpoint="https://base.agentonomy.example",
            response_public_jwk=BASE_RESPONSE_JWK,
            executor_contract="0x" + "00" * 20,
        )
    with pytest.raises(ValueError, match="executor"):
        HostedTargetTrust(
            chain_id=8453,
            endpoint="https://base.agentonomy.example",
            response_public_jwk=BASE_RESPONSE_JWK,
            executor_contract="0x" + "AA" * 20,
        )

    original = trust()
    changed = EnrollmentTrust(
        enrollment_endpoint=original.enrollment_endpoint,
        targets={
            **original.targets,
            8453: HostedTargetTrust(
                chain_id=8453,
                endpoint=original.targets[8453].endpoint,
                response_public_jwk=original.targets[8453].response_public_jwk,
                executor_contract="0x" + "22" * 20,
            ),
        },
    )
    assert changed.trust_fingerprint != original.trust_fingerprint


@pytest.mark.parametrize(
    "endpoint",
    [
        "HTTPS://enroll.agentonomy.example/v1/enrollments",
        "https://enroll.agentonomy.example:443/v1/enrollments",
        "https://enroll.agentonomy.example:0/v1/enrollments",
        "https://enroll%2eagentonomy.example/v1/enrollments",
        "https://enroll.例子/v1/enrollments",
    ],
)
def test_enrollment_trust_rejects_noncanonical_endpoint(endpoint: str) -> None:
    valid = trust()
    with pytest.raises(ValueError):
        EnrollmentTrust(
            enrollment_endpoint=endpoint,
            targets=valid.targets,
        )


def test_manager_requires_transport_endpoint_to_match_trust() -> None:
    class OtherEndpointTransport(RecordingTransport):
        endpoint = "https://other.agentonomy.example/v1/enrollments"

    with pytest.raises(ValueError, match="endpoint"):
        manager(MemorySecretStore({}), OtherEndpointTransport())

    class MissingEndpointTransport:
        def enroll(self, request):
            raise AssertionError("must not send")

        def prepare_rotation(self, request, *, authentication):
            raise AssertionError("must not send")

        def commit_rotation(self, request, *, authentication):
            raise AssertionError("must not send")

        def revoke(self, request, *, authentication):
            raise AssertionError("must not send")

    with pytest.raises(ValueError, match="endpoint"):
        HostedEnrollmentManager(
            secret_store=MemorySecretStore({}),
            transport=MissingEndpointTransport(),
            trust=trust(),
        )


def test_trust_is_deeply_immutable_and_pinned_across_restart() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    original = trust()
    manager(store, transport, enrollment_trust=original).enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )

    with pytest.raises(TypeError):
        original.targets[8453] = original.targets[137]
    with pytest.raises(TypeError):
        original.targets[8453].response_public_jwk["x"] = "mutated"

    changed = EnrollmentTrust(
        enrollment_endpoint=original.enrollment_endpoint,
        targets={
            8453: replace(
                original.targets[8453],
                endpoint="https://new-base.agentonomy.example",
            ),
            137: original.targets[137],
        },
    )
    with pytest.raises(EnrollmentConflict, match="trust"):
        manager(store, transport, enrollment_trust=changed).current()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "state": "garbage"},
        lambda value: {**value, "rotation_prepared": "false"},
        lambda value: {**value, "schema_version": True},
    ],
)
def test_corrupt_bundle_fields_fail_closed(mutation) -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(invite_code=INVITE, wallet_binding_id="wallet_binding_1")
    encoded = store.get("hosted-enrollment-v1")
    assert encoded is not None
    payload = mutation(json.loads(encoded))
    store.set(
        "hosted-enrollment-v1",
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )

    with pytest.raises(ValueError, match="bundle"):
        manager(store, transport).current()


def test_duplicate_bundle_json_keys_fail_closed() -> None:
    store = MemorySecretStore(
        {
            "hosted-enrollment-v1": (
                b'{"schema_version":1,"schema_version":1}'
            )
        }
    )
    with pytest.raises(ValueError, match="bundle"):
        manager(store, RecordingTransport()).current()


def test_rotation_response_must_bind_identity_and_exact_epochs() -> None:
    store = MemorySecretStore({})

    class WrongEpochTransport(RecordingTransport):
        def prepare_rotation(self, request, *, authentication):
            result = super().prepare_rotation(
                request,
                authentication=authentication,
            )
            return {**result, "next_epoch": int(result["next_epoch"]) + 1}

    transport = WrongEpochTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(invite_code=INVITE, wallet_binding_id="wallet_binding_1")

    with pytest.raises(EnrollmentConflict, match="next_epoch"):
        enrollment.rotate()


def test_enrollment_response_requires_complete_binding() -> None:
    class MissingStatusTransport(RecordingTransport):
        def enroll(self, request):
            response = super().enroll(request)
            response.pop("status")
            return response

    store = MemorySecretStore({})
    with pytest.raises(EnrollmentConflict, match="status"):
        manager(store, MissingStatusTransport()).enroll(
            invite_code=INVITE,
            wallet_binding_id="wallet_binding_1",
        )


def test_commit_response_requires_expected_and_next_epoch() -> None:
    class MissingCommitEpochTransport(RecordingTransport):
        def commit_rotation(self, request, *, authentication):
            response = super().commit_rotation(
                request,
                authentication=authentication,
            )
            response.pop("next_epoch")
            return response

    store = MemorySecretStore({})
    transport = MissingCommitEpochTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    with pytest.raises(EnrollmentConflict, match="next_epoch"):
        enrollment.rotate()


def test_revocation_response_requires_complete_binding() -> None:
    class MissingRevocationEpochTransport(RecordingTransport):
        def revoke(self, request, *, authentication):
            response = super().revoke(
                request,
                authentication=authentication,
            )
            response.pop("next_epoch")
            return response

    store = MemorySecretStore({})
    transport = MissingRevocationEpochTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    with pytest.raises(EnrollmentConflict, match="next_epoch"):
        enrollment.revoke()
    pending = manager(store, transport).current()
    assert pending is not None
    assert pending.state == "revocation_pending"


def test_pending_bundle_cannot_create_active_authentication() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    enrollment = manager(store, transport)
    enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    transport.fail_commit_once = True
    with pytest.raises(RuntimeError, match="commit response lost"):
        enrollment.rotate()
    pending_rotation = manager(store, transport).current()
    assert pending_rotation is not None
    with pytest.raises(EnrollmentConflict, match="active"):
        pending_rotation.authentication()

    transport.fail_commit_once = False
    transport.lose_revoke_response_once = True
    enrollment.resume_rotation()
    with pytest.raises(RuntimeError, match="revoke response lost"):
        enrollment.revoke()
    pending_revocation = manager(store, transport).current()
    assert pending_revocation is not None
    with pytest.raises(EnrollmentConflict, match="active"):
        pending_revocation.authentication()


def test_default_file_lock_serializes_remote_lifecycle_across_store_instances(
    tmp_path: Path,
) -> None:
    class BlockingLifecycleTransport(RecordingTransport):
        def __init__(self) -> None:
            super().__init__()
            self.first_prepare_entered = threading.Event()
            self.second_prepare_entered = threading.Event()
            self.release_first_prepare = threading.Event()
            self._active_remote_calls = 0
            self.max_active_remote_calls = 0
            self._guard = threading.Lock()

        def prepare_rotation(self, request, *, authentication):
            with self._guard:
                self._active_remote_calls += 1
                self.max_active_remote_calls = max(
                    self.max_active_remote_calls,
                    self._active_remote_calls,
                )
                first = self._active_remote_calls == 1
            try:
                if first:
                    self.first_prepare_entered.set()
                    assert self.release_first_prepare.wait(3)
                else:
                    self.second_prepare_entered.set()
                return super().prepare_rotation(
                    request,
                    authentication=authentication,
                )
            finally:
                with self._guard:
                    self._active_remote_calls -= 1

    path = tmp_path / "secrets.json"
    store_one = RestrictedFileSecretStore(path)
    store_two = RestrictedFileSecretStore(path)
    transport = BlockingLifecycleTransport()
    first = HostedEnrollmentManager(
        secret_store=store_one,
        transport=transport,
        trust=trust(),
    )
    second = HostedEnrollmentManager(
        secret_store=store_two,
        transport=transport,
        trust=trust(),
    )
    first.enroll(invite_code=INVITE, wallet_binding_id="wallet_binding_1")

    errors: list[BaseException] = []

    def run(manager: HostedEnrollmentManager) -> None:
        try:
            manager.rotate()
        except BaseException as exc:  # pragma: no cover - assertion below
            errors.append(exc)

    thread_one = threading.Thread(target=run, args=(first,))
    thread_two = threading.Thread(target=run, args=(second,))
    thread_one.start()
    assert transport.first_prepare_entered.wait(3)
    thread_two.start()
    assert not transport.second_prepare_entered.wait(0.2)
    transport.release_first_prepare.set()
    thread_one.join(3)
    thread_two.join(3)

    assert errors == []
    assert transport.max_active_remote_calls == 1
    assert len(transport.prepare_calls) == 2
    assert first.current().credential_epoch == 3


def test_default_file_lock_serializes_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    parent = HostedEnrollmentManager(
        secret_store=RestrictedFileSecretStore(path),
        transport=RecordingTransport(),
        trust=trust(),
    )
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    acquired = context.Event()
    process = context.Process(
        target=_probe_default_lock_in_subprocess,
        args=(str(path), started, acquired),
    )

    with parent._mutation_lock:
        process.start()
        assert started.wait(3)
        assert not acquired.wait(0.2)

    assert acquired.wait(3)
    process.join(3)
    assert process.exitcode == 0


def test_different_explicit_lock_is_not_silently_replaced_for_one_store() -> None:
    store = MemorySecretStore({})
    transport = RecordingTransport()
    first_lock = RecordingLock()
    second_lock = RecordingLock()
    HostedEnrollmentManager(
        secret_store=store,
        transport=transport,
        trust=trust(),
        mutation_lock=first_lock,
    )
    with pytest.raises(ValueError, match="mutation lock"):
        HostedEnrollmentManager(
            secret_store=store,
            transport=transport,
            trust=trust(),
            mutation_lock=second_lock,
        )


def test_file_store_rejects_custom_mutation_lock_and_default_shares_path_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "secrets.json"
    with pytest.raises(ValueError, match="file-backed"):
        HostedEnrollmentManager(
            secret_store=RestrictedFileSecretStore(path),
            transport=RecordingTransport(),
            trust=trust(),
            mutation_lock=RecordingLock(),
        )

    first = HostedEnrollmentManager(
        secret_store=RestrictedFileSecretStore(path),
        transport=RecordingTransport(),
        trust=trust(),
    )
    second = HostedEnrollmentManager(
        secret_store=RestrictedFileSecretStore(path),
        transport=RecordingTransport(),
        trust=trust(),
    )
    assert first._mutation_lock._state is second._mutation_lock._state


def test_secret_bearing_bundle_repr_is_redacted() -> None:
    store = MemorySecretStore({})
    enrollment = manager(store, RecordingTransport())
    active = enrollment.enroll(
        invite_code=INVITE,
        wallet_binding_id="wallet_binding_1",
    )
    persisted = store.get("hosted-enrollment-v1")
    assert persisted is not None
    assert active.access_token.encode("ascii") in persisted
    assert active.access_token not in repr(active)
    assert active.private_key_pkcs8_b64 not in repr(active)
