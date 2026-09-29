from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import _execution_projection, create_app
from config import FacilitatorConfig
from enrollment import DeviceResponseSigner, EnrollmentService
from evm import ExecutionAuthorization, hash_execution
from execution_models import (
    BASE_CHAIN_ID,
    BASE_USDC,
    POLYGON_CHAIN,
    POLYGON_USDC,
    ExecutionIntent,
    ExecutionState,
    HostedExecution,
)
from execution_repository import ExecutionConflict, ExecutionRepository, HostedExecutionRow
from pilot_gate import PilotGatePolicy
from repository import InMemoryRepository
from replay import InMemoryReplayCoordinator
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HOSTED_BASE_USDC,
    HostedPaymentEnvelope,
    build_dpop_proof,
    canonical_json_bytes,
    sign_payment_envelope,
    verify_execution_response,
)


NOW = 2_000_000_000
ORIGIN = "http://127.0.0.1:8080"
EXECUTION_PATH = "/v1/executions"
EXECUTION_URL = ORIGIN + EXECUTION_PATH
EXECUTOR = "0x" + "44" * 20
RELAYER = "0x" + "55" * 20
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
SIGNATURE = bytes.fromhex("aa" * 64 + "1b")
RAW_TRANSACTION = bytes.fromhex(
    "02e48221058001028252089444444444444444444444444444444444444444448080c0800101"
)


def config() -> FacilitatorConfig:
    return FacilitatorConfig(
        environment="test",
        public_origin=ORIGIN,
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="redis://127.0.0.1:6379/0",
        response_key_ref="test://response",
        chain_id=BASE_CHAIN_ID,
        asset_contract=HOSTED_BASE_USDC,
    )


class Resolver:
    def resolve(self, envelope: HostedPaymentEnvelope, node) -> ExecutionIntent:
        owner_nonce = int(envelope.request_nonce, 16)
        authorization = ExecutionAuthorization(
            capability_hash=envelope.payment_capability_hash,
            reservation_hash=envelope.reservation_hash,
            owner=envelope.wallet_address,
            payee=envelope.pay_to,
            token=envelope.asset_contract,
            amount=int(envelope.amount_atomic),
            nonce=owner_nonce,
            deadline=envelope.expires_at,
            signer_epoch=1,
            relayer=RELAYER,
            chain_id=BASE_CHAIN_ID,
        )
        return ExecutionIntent(
            tenant_id=node.tenant_id,
            node_id=node.node_id,
            wallet_binding_id=node.wallet_binding_id,
            capability_id=envelope.payment_capability_id,
            reservation_id=envelope.reservation_id,
            purchase_id=envelope.purchase_id,
            request_id=envelope.request_id,
            request_hash=envelope.request_hash,
            idempotency_key=envelope.idempotency_key,
            chain=envelope.chain_id,
            token=envelope.asset_contract,
            owner=envelope.wallet_address,
            payee=envelope.pay_to,
            amount_atomic=envelope.amount_atomic,
            executor=envelope.executor_contract,
            signer_epoch=1,
            owner_nonce=owner_nonce,
            deadline=envelope.expires_at,
            capability_hash=envelope.payment_capability_hash,
            reservation_hash=envelope.reservation_hash,
            execution_scope_hash=envelope.execution_scope_hash,
            execution_digest="0x" + hash_execution(
                authorization, EXECUTOR, chain_id=BASE_CHAIN_ID
            ).hex(),
            relayer_address=RELAYER,
        )


class ExecutionService:
    def __init__(self, repository: ExecutionRepository) -> None:
        self.repository = repository
        self.calls = 0

    def execute(self, intent: ExecutionIntent):
        self.calls += 1
        existing = self.repository.find_for_intent(intent)
        if existing is not None:
            return existing
        execution = self.repository.allocate_or_return(
            intent, chain_pending_nonce=7, now=NOW
        )
        execution, acquired = self.repository.claim_signing(
            execution.execution_id,
            now=NOW,
        )
        assert acquired is True
        execution = self.repository.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=RAW_TRANSACTION,
            signing_claim_generation=execution.signing_claim_generation,
            now=NOW,
        )
        execution, claimed = self.repository.claim_submission(
            execution.execution_id, now=NOW
        )
        assert claimed is True
        return self.repository.mark_submitted(execution.execution_id, now=NOW)


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        pilot_policy: PilotGatePolicy | None = None,
    ) -> None:
        self.control = InMemoryRepository()
        self.replay = InMemoryReplayCoordinator()
        self.response_key = DeviceSigningKey.generate()
        enrollment = EnrollmentService(
            repository=self.control,
            enrollment_ttl_seconds=300,
            clock=lambda: NOW,
        )
        token = enrollment.issue_enrollment_token("tenant_1")
        self.device_key = DeviceSigningKey.generate()
        self.access_token = "access_" + "a" * 40
        result = enrollment.enroll(
            token,
            public_jwk=self.device_key.public_jwk,
            wallet_binding_id="binding_1",
            expected_epoch=0,
            next_epoch=1,
            access_token_digest=base64.urlsafe_b64encode(
                hashlib.sha256(self.access_token.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii"),
            status="pending",
        )
        self.node_id = result.node_id
        self.executions = ExecutionRepository(
            f"sqlite+pysqlite:///{tmp_path / 'execution-api.sqlite3'}",
            pilot_policy=pilot_policy,
        )
        self.service = ExecutionService(self.executions)
        self.app = create_app(
            config(),
            repository=self.control,
            replay=self.replay,
            response_signer=DeviceResponseSigner(self.response_key),
            clock=lambda: NOW,
            execution_repository=self.executions,
            execution_service=self.service,
            intent_resolver=Resolver(),
        )
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.jti = 0

    def envelope(self, **updates: object) -> HostedPaymentEnvelope:
        values: dict[str, object] = {
            "protocol_version": "clink-hosted-v1",
            "audience": "hosted-facilitator",
            "http_method": "POST",
            "http_path": EXECUTION_PATH,
            "request_id": "request_1",
            "idempotency_key": "idempotency_1",
            "tenant_id": "tenant_1",
            "node_id": self.node_id,
            "wallet_binding_id": "binding_1",
            "payment_capability_version": "clink-payment-capability-v1",
            "payment_capability_id": "capability_1",
            "payment_capability_hash": "0x" + "08" * 32,
            "wallet_identity_id": "identity_1",
            "wallet_address": OWNER,
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
            "asset_contract": BASE_USDC,
            "amount_atomic": "1000000",
            "pay_to": PAYEE,
            "executor_contract": EXECUTOR,
            "execution_scope_hash": "0x" + "f6" * 32,
            "request_nonce": "0x" + "07" * 32,
            "issued_at": NOW - 1,
            "expires_at": NOW + 59,
        }
        values.update(updates)
        return HostedPaymentEnvelope(**values)

    def headers(self, *, method: str, url: str) -> dict[str, str]:
        self.jti += 1
        proof = build_dpop_proof(
            self.device_key,
            method=method,
            url=url,
            access_token=self.access_token,
            now=NOW,
            jti=f"jti_{self.jti}",
        )
        return {
            "authorization": f"DPoP {self.access_token}",
            "dpop": proof,
            "content-type": "application/json",
        }


def _execution_node(harness: Harness):
    return type(
        "Node",
        (),
        {
            "tenant_id": "tenant_1",
            "node_id": harness.node_id,
            "wallet_binding_id": "binding_1",
        },
    )()


def _unsigned_terminal_execution(
    harness: Harness,
    terminal_state: ExecutionState,
) -> HostedExecution:
    envelope = harness.envelope(
        issued_at=NOW - 50,
        expires_at=NOW - 1,
    )
    intent = Resolver().resolve(envelope, _execution_node(harness))
    allocated = harness.executions.allocate_or_return(
        intent,
        chain_pending_nonce=7,
        now=NOW - 10,
    )
    if terminal_state is ExecutionState.EXPIRED:
        return harness.executions.transition(
            allocated.execution_id,
            ExecutionState.EXPIRED,
            now=NOW,
        )
    if terminal_state is ExecutionState.RELEASED:
        return harness.executions.release_expired(allocated.execution_id, now=NOW)
    raise AssertionError(f"unsupported terminal state: {terminal_state}")


@pytest.mark.parametrize(
    "terminal_state",
    [ExecutionState.EXPIRED, ExecutionState.RELEASED],
)
def test_projection_attests_proven_unsigned_expiry(
    tmp_path: Path,
    terminal_state: ExecutionState,
) -> None:
    harness = Harness(tmp_path)
    execution = _unsigned_terminal_execution(harness, terminal_state)

    response = _execution_projection(execution, server_key_id="server-key-1")

    assert response.state == "expired"
    assert response.failure_reason_code == "UNSIGNED_EXECUTION_EXPIRED"
    assert response.transaction_hash is None
    assert response.submitted_at is None
    assert response.receipt_block_hash is None
    assert response.receipt_block_number is None
    assert response.safe_block_hash is None
    assert response.safe_block_number is None
    assert response.confirmations == 0
    assert response.watcher_version is None
    assert response.finality_boundary is None
    assert response.expired_at == NOW
    assert response.released_at == (NOW if terminal_state is ExecutionState.RELEASED else None)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("signature", SIGNATURE),
        ("raw_transaction", RAW_TRANSACTION),
        ("raw_transaction_hash", "0x" + "aa" * 32),
        ("unsigned_transaction_hash", "0x" + "bb" * 32),
        ("broadcast_attempts", 1),
        ("broadcasted_at", NOW),
        ("signing_claim_expires_at", NOW),
        ("receipt_status", 0),
        ("receipt_block_number", 100),
        ("receipt_block_hash", "0x" + "cc" * 32),
        ("confirmations", 1),
        ("safe_block_number", 100),
        ("safe_block_hash", "0x" + "dd" * 32),
        ("watcher_version", "watcher-v1"),
        ("finality_boundary", "safe"),
        ("confirmed_at", NOW),
        ("finalized_at", NOW),
        ("reverted_at", NOW),
        ("reorg_state", "review"),
        ("reorg_evidence", {"canonical": False}),
        ("reorg_reviewed_at", NOW),
        ("release_evidence", {"receipt_status": 0}),
    ],
)
def test_projection_rejects_contradictory_unsigned_terminal_evidence(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    harness = Harness(tmp_path)
    execution = _unsigned_terminal_execution(harness, ExecutionState.EXPIRED)
    contradictory = execution.model_copy(update={field: replacement})

    with pytest.raises(ExecutionConflict, match="unsigned|evidence|expiry|terminal"):
        _execution_projection(contradictory, server_key_id="server-key-1")


@pytest.mark.parametrize(
    ("terminal_state", "field", "replacement"),
    [
        (ExecutionState.EXPIRED, "expired_at", NOW - 2),
        (ExecutionState.RELEASED, "released_at", NOW - 2),
        (ExecutionState.RELEASED, "expired_at", NOW - 3),
    ],
)
def test_projection_rejects_unsigned_terminal_timestamp_before_deadline(
    tmp_path: Path,
    terminal_state: ExecutionState,
    field: str,
    replacement: int,
) -> None:
    harness = Harness(tmp_path)
    execution = _unsigned_terminal_execution(harness, terminal_state)
    contradictory = execution.model_copy(update={field: replacement})

    with pytest.raises(ExecutionConflict, match="deadline|expiry|timestamp|terminal"):
        _execution_projection(contradictory, server_key_id="server-key-1")


def test_execution_route_returns_one_signed_scope_bound_action(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    payload = canonical_json_bytes(
        {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
    )

    first = harness.client.post(
        EXECUTION_PATH,
        content=payload,
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )
    second = harness.client.post(
        EXECUTION_PATH,
        content=payload,
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )

    assert first.status_code == second.status_code == 200
    first_status = verify_execution_response(
        first.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
    )
    second_status = verify_execution_response(
        second.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
        expected_execution_id=first_status.execution_id,
    )
    assert first_status.state == second_status.state == "submitted"
    assert first_status.transaction_hash == second_status.transaction_hash
    assert harness.service.calls == 1
    stored = harness.executions.get_execution(first_status.execution_id)
    assert stored is not None and stored.broadcast_attempts == 1


def test_execution_route_returns_stable_pilot_gate_denial_before_core_work(
    tmp_path: Path,
) -> None:
    harness = Harness(
        tmp_path,
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000
        ),
    )
    harness.executions.set_pilot_pause(
        scope_type="node",
        tenant_id="tenant_1",
        node_id=harness.node_id,
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )
    envelope = harness.envelope()

    response = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "node_paused"
    assert harness.service.calls == 0


def test_paused_execution_route_returns_exact_durable_submitted_replay(
    tmp_path: Path,
) -> None:
    harness = Harness(
        tmp_path,
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000
        ),
    )
    envelope = harness.envelope()
    node = type(
        "Node",
        (),
        {
            "tenant_id": "tenant_1",
            "node_id": harness.node_id,
            "wallet_binding_id": "binding_1",
        },
    )()
    intent = Resolver().resolve(envelope, node)
    execution = harness.executions.allocate_or_return(
        intent,
        chain_pending_nonce=7,
        now=NOW,
    )
    execution, acquired = harness.executions.claim_signing(
        execution.execution_id, now=NOW
    )
    assert acquired is True
    harness.executions.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    harness.executions.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    harness.executions.claim_submission(execution.execution_id, now=NOW)
    submitted = harness.executions.mark_submitted(execution.execution_id, now=NOW)
    harness.executions.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )

    response = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )

    assert response.status_code == 200
    replay = verify_execution_response(
        response.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
        expected_execution_id=submitted.execution_id,
    )
    assert replay.state == "submitted"
    assert harness.service.calls == 0


def test_paused_execution_route_rejects_changed_scope_for_existing_identity(
    tmp_path: Path,
) -> None:
    harness = Harness(
        tmp_path,
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000
        ),
    )
    envelope = harness.envelope()
    node = type(
        "Node",
        (),
        {
            "tenant_id": "tenant_1",
            "node_id": harness.node_id,
            "wallet_binding_id": "binding_1",
        },
    )()
    intent = Resolver().resolve(envelope, node)
    execution = harness.executions.allocate_or_return(
        intent,
        chain_pending_nonce=7,
        now=NOW,
    )
    execution, acquired = harness.executions.claim_signing(
        execution.execution_id, now=NOW
    )
    assert acquired is True
    harness.executions.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    harness.executions.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    harness.executions.claim_submission(execution.execution_id, now=NOW)
    harness.executions.mark_submitted(execution.execution_id, now=NOW)
    harness.executions.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )
    changed = harness.envelope(amount_atomic="2000000")

    response = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, changed)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "scope_mismatch"
    assert harness.service.calls == 0


def test_execution_status_requires_same_enrolled_node_and_returns_signed_state(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    created = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )
    execution_id = verify_execution_response(
        created.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
    ).execution_id
    status_path = f"{EXECUTION_PATH}/{execution_id}"

    response = harness.client.get(
        status_path,
        headers=harness.headers(method="GET", url=ORIGIN + status_path),
    )

    assert response.status_code == 200
    status = verify_execution_response(
        response.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
        expected_execution_id=execution_id,
    )
    assert status.state == "submitted"


def test_execution_status_hides_execution_from_another_runtime_chain(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    created = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )
    execution_id = verify_execution_response(
        created.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
    ).execution_id
    with harness.executions.sessions() as session:
        row = session.get(HostedExecutionRow, execution_id)
        assert row is not None
        row.chain = POLYGON_CHAIN
        row.token = POLYGON_USDC
        session.commit()

    status_path = f"{EXECUTION_PATH}/{execution_id}"
    response = harness.client.get(
        status_path,
        headers=harness.headers(method="GET", url=ORIGIN + status_path),
    )

    assert response.status_code == 404


def test_execution_route_refuses_service_result_outside_core_intent(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    delegate = harness.service

    class MismatchedExecutionService:
        def execute(self, intent: ExecutionIntent):
            execution = delegate.execute(intent)
            return execution.model_copy(update={"amount_atomic": "2000000"})

    harness.app = create_app(
        config(),
        repository=harness.control,
        replay=harness.replay,
        response_signer=DeviceResponseSigner(harness.response_key),
        clock=lambda: NOW,
        execution_repository=harness.executions,
        execution_service=MismatchedExecutionService(),
        intent_resolver=Resolver(),
    )
    harness.client = TestClient(harness.app, base_url=ORIGIN)
    envelope = harness.envelope()

    response = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "execution_conflict"


def test_execution_lookup_by_idempotency_returns_the_durable_signed_projection(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    created = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )
    execution_id = verify_execution_response(
        created.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
    ).execution_id

    lookup_path = f"/v1/execution-lookups/{envelope.idempotency_key}"
    response = harness.client.get(
        lookup_path,
        headers=harness.headers(method="GET", url=ORIGIN + lookup_path),
    )

    assert response.status_code == 200
    status = verify_execution_response(
        response.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
        expected_execution_id=execution_id,
    )
    assert status.execution_id == execution_id
    assert status.idempotency_key == envelope.idempotency_key
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("tenant_id", "tenant_other"),
        ("node_id", "node_other"),
        ("wallet_binding_id", "binding_other"),
        ("chain", "eip155:137"),
    ],
)
def test_execution_lookup_hides_identity_wallet_and_chain_scope_mismatch(
    tmp_path: Path,
    field_name: str,
    value: str,
) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    created = harness.client.post(
        EXECUTION_PATH,
        content=canonical_json_bytes(
            {"payment_jws": sign_payment_envelope(harness.device_key, envelope)}
        ),
        headers=harness.headers(method="POST", url=EXECUTION_URL),
    )
    execution_id = verify_execution_response(
        created.json()["response_jws"],
        harness.response_key.public_jwk,
        envelope,
        now=NOW,
    ).execution_id
    with harness.executions.sessions() as session:
        row = session.get(HostedExecutionRow, execution_id)
        assert row is not None
        setattr(row, field_name, value)
        if field_name == "chain":
            row.token = POLYGON_USDC
        session.commit()

    lookup_path = f"/v1/execution-lookups/{envelope.idempotency_key}"
    response = harness.client.get(
        lookup_path,
        headers=harness.headers(method="GET", url=ORIGIN + lookup_path),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "execution_not_found"


def test_projection_preserves_reverted_receipt_when_safely_released(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    envelope = harness.envelope()
    execution = harness.service.execute(
        Resolver().resolve(
            envelope,
            type(
                "Node",
                (),
                {
                    "tenant_id": "tenant_1",
                    "node_id": harness.node_id,
                    "wallet_binding_id": "binding_1",
                },
            )(),
        )
    )
    reverted = harness.executions.revert(
        execution.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        now=NOW + 1,
    )
    released = harness.executions.release_reverted(
        reverted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence={
            "receipt_status": 0,
            "canonical_receipt": True,
            "finality_boundary_timestamp": execution.deadline,
            "capability_used": False,
            "owner_nonce_used": False,
            "payment_event_found": False,
            "transfer_event_found": False,
        },
        now=execution.deadline,
    )

    response = _execution_projection(released, server_key_id="server-key-1")

    assert response.state == "released"
    assert response.failure_reason_code == "SAFE_REVERT_RELEASE"
    assert response.transaction_hash == released.raw_transaction_hash
    assert response.submitted_at == released.broadcasted_at
    assert response.receipt_block_number == 100
    assert response.receipt_block_hash == "0x" + "99" * 32
    assert response.safe_block_number == 100
    assert response.safe_block_hash == "0x" + "99" * 32
    assert response.reverted_at == NOW + 1
    assert response.released_at == execution.deadline
    assert response.watcher_version == "watcher-v1"
    assert response.release_evidence is not None
    assert set(response.release_evidence.model_dump()) == {
        "receipt_status",
        "canonical_receipt",
        "finality_boundary_timestamp",
        "capability_used",
        "owner_nonce_used",
        "payment_event_found",
        "transfer_event_found",
    }
