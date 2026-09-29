from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from evm import (
    EIP1559Transaction,
    ExecutionAuthorization,
    encode_eip1559_unsigned,
    encode_execute_calldata,
    hash_execution,
    raw_transaction_hash,
)
from eth_utils import keccak
from execution_models import (
    BASE_CHAIN,
    BASE_CHAIN_ID,
    BASE_USDC,
    POLYGON_CHAIN,
    POLYGON_CHAIN_ID,
    POLYGON_USDC,
    ExecutionIntent,
    ExecutionState,
)
from execution_repository import (
    ExecutionRepository,
    HostedExecutionAttemptRow,
    HostedGateReservationRow,
    HostedExecutionRow,
    SIGNING_CLAIM_LEASE_SECONDS,
)
from pilot_gate import PilotGateDenied, PilotGatePolicy, worst_case_gas_usd_micros
from relayer import HostedRelayer, HostedSubmissionReconciler, RelayerExecutionError
from rpc import RpcSubmissionRejected, RpcSubmissionUnknown
from sqlalchemy import select


EXECUTOR = "0x" + "44" * 20
RELAYER = "0x" + "55" * 20
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20


class Signer:
    def __init__(self, *, recovery_id: int, key_id: str, address: str) -> None:
        self.recovery_id = recovery_id
        self.key_id = key_id
        self.expected_signer_address = address
        self.digests: list[bytes] = []

    def sign_digest(self, digest: bytes) -> bytes:
        self.digests.append(bytes(digest))
        return (1).to_bytes(32, "big") + (1).to_bytes(32, "big") + bytes([self.recovery_id])


class Rpc:
    def __init__(self, repository: ExecutionRepository, *, chain_id: int = BASE_CHAIN_ID) -> None:
        self.repository = repository
        self.chain_id = chain_id
        self.calls: list[tuple[str, list[object]]] = []
        self.submission_unknown = False
        self.known_transaction: dict[str, object] | None = None

    def call(self, method: str, params: list[object]) -> object:
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getTransactionCount":
            return "0x7"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method == "eth_maxPriorityFeePerGas":
            return "0x3b9aca00"
        if method == "eth_gasPrice":
            return "0x77359400"
        if method == "eth_getTransactionByHash":
            return self.known_transaction
        if method == "eth_sendRawTransaction":
            with self.repository.sessions() as session:
                row = session.query(HostedExecutionRow).one()
                previous_sends = sum(
                    1 for called_method, _ in self.calls[:-1]
                    if called_method == "eth_sendRawTransaction"
                )
                expected_state = (
                    ExecutionState.SUBMISSION_UNKNOWN.value
                    if previous_sends == 0
                    else ExecutionState.SUBMITTED.value
                )
                assert row.status == expected_state
                assert isinstance(row.raw_transaction, bytes) and row.raw_transaction
                assert row.raw_transaction_hash == "0x" + raw_transaction_hash(row.raw_transaction).hex()
            if self.submission_unknown:
                raise RpcSubmissionUnknown()
            return "0x" + raw_transaction_hash(bytes.fromhex(str(params[0])[2:])).hex()
        raise AssertionError(method)


class ApprovalVerifier:
    def __init__(self, approved: ExecutionIntent) -> None:
        self.approved_hash = approved.canonical_hash
        self.calls: list[str] = []

    def verify(self, candidate: ExecutionIntent) -> None:
        self.calls.append(candidate.canonical_hash)
        if candidate.canonical_hash != self.approved_hash:
            raise RelayerExecutionError("Core execution approval is invalid")


def repository(tmp_path: Path) -> ExecutionRepository:
    return ExecutionRepository(f"sqlite+pysqlite:///{tmp_path / 'relayer.sqlite3'}")


def gated_repository(
    tmp_path: Path,
    *,
    node_gas_limit: int = 10_000,
) -> ExecutionRepository:
    return ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'gated-relayer.sqlite3'}",
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000,
            max_gas_usd_micros_per_node_utc_day=node_gas_limit,
            max_gas_usd_micros_platform_utc_day=100_000,
        ),
    )


def intent(**updates: object) -> ExecutionIntent:
    authorization = ExecutionAuthorization(
        capability_hash="0x" + "aa" * 32,
        reservation_hash="0x" + "bb" * 32,
        owner=OWNER,
        payee=PAYEE,
        token=BASE_USDC,
        amount=2_000_000,
        nonce=9,
        deadline=2_000_000_000,
        signer_epoch=3,
        relayer=RELAYER,
        chain_id=BASE_CHAIN_ID,
    )
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_1",
        "capability_id": "capability_1",
        "reservation_id": "reservation_1",
        "purchase_id": "purchase_1",
        "request_id": "request_1",
        "request_hash": "0x" + "99" * 32,
        "idempotency_key": "idempotency_1",
        "chain": BASE_CHAIN,
        "token": BASE_USDC,
        "owner": OWNER,
        "payee": PAYEE,
        "amount_atomic": "2000000",
        "executor": EXECUTOR,
        "signer_epoch": 3,
        "owner_nonce": 9,
        "deadline": 2_000_000_000,
        "capability_hash": "0x" + "aa" * 32,
        "reservation_hash": "0x" + "bb" * 32,
        "execution_scope_hash": "0x" + "cc" * 32,
        "execution_digest": "0x" + hash_execution(
            authorization, EXECUTOR, chain_id=BASE_CHAIN_ID
        ).hex(),
        "relayer_address": RELAYER,
    }
    values.update(updates)
    return ExecutionIntent(**values)


def relayer(
    repo: ExecutionRepository,
    rpc: Rpc,
    *,
    approval_verifier: object | None = None,
    clock: Callable[[], int] | None = None,
    inspection_rpc: Rpc | None = None,
) -> tuple[HostedRelayer, Signer, Signer]:
    execution_signer = Signer(
        recovery_id=27,
        key_id="kms-execution-key",
        address="0x" + "66" * 20,
    )
    gas_signer = Signer(
        recovery_id=0,
        key_id="kms-gas-key",
        address=RELAYER,
    )
    return (
        HostedRelayer(
            repository=repo,
            rpc=rpc,
            inspection_rpc=inspection_rpc,
            execution_signer=execution_signer,
            gas_signer=gas_signer,
            approval_verifier=(
                ApprovalVerifier(intent())
                if approval_verifier is None
                else approval_verifier
            ),
            executor_address=EXECUTOR,
            relayer_address=RELAYER,
            max_gas_limit=250_000,
            max_fee_per_gas_wei=10_000_000_000,
            max_priority_fee_per_gas_wei=2_000_000_000,
            clock=(lambda: 1_900_000_000) if clock is None else clock,
            chain=BASE_CHAIN,
            token=BASE_USDC,
            chain_id=BASE_CHAIN_ID,
        ),
        execution_signer,
        gas_signer,
    )


def _persist_signed_execution(repo: ExecutionRepository) -> object:
    execution = repo.allocate_or_return(intent(), chain_pending_nonce=7)
    execution, acquired = repo.claim_signing(execution.execution_id)
    assert acquired is True
    return repo.persist_signed_transaction(
        execution.execution_id,
        signature=bytes.fromhex("01" * 64 + "1b"),
        raw_transaction=bytes.fromhex(
            "02e48221058001028252089433333333333333333333333333333333333333338080c0800101"
        ),
        signing_claim_generation=execution.signing_claim_generation,
    )


def test_persists_one_exact_raw_transaction_before_broadcast(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, execution_signer, gas_signer = relayer(repo, rpc)

    result = service.execute(intent())

    assert result.status is ExecutionState.SUBMITTED
    assert result.relayer_nonce == 7
    assert result.broadcast_attempts == 1
    assert result.raw_transaction_hash == "0x" + raw_transaction_hash(result.raw_transaction).hex()
    assert len(execution_signer.digests) == 1
    assert len(gas_signer.digests) == 1
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1


def test_nonce_observations_use_the_independent_inspection_rpc(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    submission_rpc = Rpc(repo)
    inspection_rpc = Rpc(repo)
    service, _execution_signer, _gas_signer = relayer(
        repo,
        submission_rpc,
        inspection_rpc=inspection_rpc,
    )

    result = service.execute(intent())

    assert result.status is ExecutionState.SUBMITTED
    assert [
        params[1]
        for method, params in inspection_rpc.calls
        if method == "eth_getTransactionCount"
    ] == ["pending", "latest"]
    assert not any(
        method == "eth_getTransactionCount" for method, _ in submission_rpc.calls
    )
    assert [method for method, _ in submission_rpc.calls].count(
        "eth_sendRawTransaction"
    ) == 1


def test_reserves_conservative_gas_budget_before_gas_signing(tmp_path: Path) -> None:
    repo = gated_repository(tmp_path)
    rpc = Rpc(repo)
    hosted, _execution_signer, gas_signer = relayer(repo, rpc)

    execution = hosted.execute(intent())

    expected_cost = worst_case_gas_usd_micros(
        120_000,
        5_000_000_000,
        1_000_000,
    )
    with repo.sessions() as session:
        gate = session.get(HostedGateReservationRow, execution.execution_id)
        assert gate is not None
        assert gate.gas_cost_usd_micros == expected_cost
    assert len(gas_signer.digests) == 1


def test_gas_budget_denial_happens_before_gas_signature_or_raw_transaction(
    tmp_path: Path,
) -> None:
    repo = gated_repository(tmp_path, node_gas_limit=599)
    rpc = Rpc(repo)
    hosted, _execution_signer, gas_signer = relayer(repo, rpc)

    with pytest.raises(PilotGateDenied) as denied:
        hosted.execute(intent())

    assert denied.value.reason_code == "node_daily_gas_limit"
    persisted = repo.find_for_intent(intent())
    assert persisted is not None
    assert persisted.status is ExecutionState.SIGNING
    assert persisted.raw_transaction is None
    assert gas_signer.digests == []


def test_pause_after_signing_is_not_swallowed_before_broadcast(tmp_path: Path) -> None:
    repo = gated_repository(tmp_path)
    rpc = Rpc(repo)
    service, _execution_signer, gas_signer = relayer(repo, rpc)
    original_sign = gas_signer.sign_digest

    def pause_then_sign(digest: bytes) -> bytes:
        repo.set_pilot_pause(
            scope_type="platform",
            paused=True,
            reason_code="operator_pause",
            now=1_900_000_000,
        )
        return original_sign(digest)

    gas_signer.sign_digest = pause_then_sign  # type: ignore[method-assign]

    with pytest.raises(PilotGateDenied) as denied:
        service.execute(intent())

    assert denied.value.reason_code == "platform_paused"
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0


def test_ambiguous_submission_keeps_same_execution_and_does_not_auto_rebroadcast(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    rpc.submission_unknown = True
    service, execution_signer, gas_signer = relayer(repo, rpc)

    first = service.execute(intent())
    second = service.inspect_submission(first.execution_id)

    assert first.execution_id == second.execution_id
    assert second.status is ExecutionState.SUBMISSION_UNKNOWN
    assert second.raw_transaction == first.raw_transaction
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1
    assert len(execution_signer.digests) == 1
    assert len(gas_signer.digests) == 1
    with repo.sessions() as session:
        attempts = session.scalars(select(HostedExecutionAttemptRow)).all()
        assert [(row.attempt_number, row.attempt_kind) for row in attempts] == [
            (0, "signed"),
            (1, "broadcast_claimed"),
        ]


def test_idempotent_replay_returns_persisted_execution_when_relayer_rpc_is_down(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())

    class OfflineRpc:
        def call(self, method: str, params: list[object]) -> object:
            raise RuntimeError(f"unexpected RPC dependency: {method} {params!r}")

    replay_service, _, _ = relayer(repo, OfflineRpc())
    replay = replay_service.execute(intent())

    assert replay.execution_id == first.execution_id
    assert replay.status is ExecutionState.SUBMITTED
    assert replay.raw_transaction_hash == first.raw_transaction_hash


def test_status_replay_does_not_depend_on_core_verifier_after_execution_exists(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())

    class OfflineApproval:
        def verify(self, candidate: ExecutionIntent) -> None:
            raise RuntimeError("Core unavailable")

    replay_service, _, _ = relayer(
        repo,
        rpc,
        approval_verifier=OfflineApproval(),
    )
    replay = replay_service.execute(intent())

    assert replay.execution_id == first.execution_id
    assert replay.status is ExecutionState.SUBMITTED


def test_retry_after_lost_submit_response_recognizes_same_chain_transaction(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    rpc.submission_unknown = True
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    rpc.submission_unknown = False
    rpc.known_transaction = {
        "hash": first.raw_transaction_hash,
        "from": RELAYER,
        "to": EXECUTOR,
        "nonce": hex(first.relayer_nonce),
        "value": "0x0",
        "type": "0x2",
        "chainId": hex(BASE_CHAIN_ID),
        "input": _expected_input(first),
    }

    second = service.execute(intent())

    assert second.execution_id == first.execution_id
    assert second.status is ExecutionState.SUBMISSION_UNKNOWN
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1


def test_rejects_core_digest_mismatch_before_signing_or_broadcast(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, execution_signer, gas_signer = relayer(repo, rpc)

    with pytest.raises(RelayerExecutionError, match="authorization digest"):
        service.execute(intent(execution_digest="0x" + "dd" * 32))

    assert execution_signer.digests == []
    assert gas_signer.digests == []
    assert rpc.calls == []


def test_relayer_rejects_rpc_bound_to_another_chain_before_allocation(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo, chain_id=137)
    service, execution_signer, gas_signer = relayer(repo, rpc)

    with pytest.raises(RelayerExecutionError, match="RPC chain"):
        service.execute(intent())

    assert execution_signer.digests == []
    assert gas_signer.digests == []
    assert [method for method, _ in rpc.calls] == ["eth_chainId"]
    with repo.sessions() as session:
        assert session.scalars(select(HostedExecutionRow)).all() == []


def test_recomputed_digest_cannot_bypass_core_approval(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, execution_signer, gas_signer = relayer(repo, rpc)
    changed_payee = "0x" + "77" * 20
    authorization = ExecutionAuthorization(
        capability_hash="0x" + "aa" * 32,
        reservation_hash="0x" + "bb" * 32,
        owner=OWNER,
        payee=changed_payee,
        token=BASE_USDC,
        amount=2_000_000,
        nonce=9,
        deadline=2_000_000_000,
        signer_epoch=3,
        relayer=RELAYER,
        chain_id=BASE_CHAIN_ID,
    )
    forged = intent(
        payee=changed_payee,
        execution_digest="0x" + hash_execution(
            authorization, EXECUTOR, chain_id=BASE_CHAIN_ID
        ).hex(),
    )

    with pytest.raises(RelayerExecutionError, match="Core execution approval"):
        service.execute(forged)

    assert execution_signer.digests == []
    assert gas_signer.digests == []
    assert rpc.calls == []


def test_signer_keys_and_addresses_must_be_distinct(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    same_key = Signer(
        recovery_id=27,
        key_id="same-key",
        address=RELAYER,
    )

    with pytest.raises(ValueError, match="signer keys must differ"):
        HostedRelayer(
            repository=repo,
            rpc=rpc,
            execution_signer=same_key,
            gas_signer=Signer(recovery_id=0, key_id="same-key", address=RELAYER),
            approval_verifier=ApprovalVerifier(intent()),
            executor_address=EXECUTOR,
            relayer_address=RELAYER,
            max_gas_limit=250_000,
            max_fee_per_gas_wei=10_000_000_000,
            max_priority_fee_per_gas_wei=2_000_000_000,
            clock=lambda: 1_900_000_000,
            chain=BASE_CHAIN,
            token=BASE_USDC,
            chain_id=BASE_CHAIN_ID,
        )


def test_weak_transaction_lookup_does_not_mark_submitted(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    rpc.submission_unknown = True
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    rpc.known_transaction = {"hash": first.raw_transaction_hash}

    with pytest.raises(RelayerExecutionError, match="lookup is inconsistent"):
        service.inspect_submission(first.execution_id)
    result = repo.get_execution(first.execution_id)
    assert result is not None and result.status is ExecutionState.SUBMISSION_UNKNOWN


def test_definite_provider_rejection_stays_reserved_without_auto_retry(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)

    class RejectingRpc(Rpc):
        def call(self, method: str, params: list[object]) -> object:
            if method == "eth_sendRawTransaction":
                self.calls.append((method, params))
                raise RpcSubmissionRejected("insufficient_funds")
            return super().call(method, params)

    rpc = RejectingRpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    second = service.execute(intent())

    assert first.status is ExecutionState.SUBMISSION_REJECTED
    assert first.submission_failure_code == "insufficient_funds"
    assert second.execution_id == first.execution_id
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1


def test_concurrent_execution_claims_signing_and_broadcast_once(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, execution_signer, gas_signer = relayer(repo, rpc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: service.execute(intent()), range(2)))

    assert len({result.execution_id for result in results}) == 1
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1
    assert len(execution_signer.digests) == 1
    assert len(gas_signer.digests) == 1


def test_execute_recovers_an_expired_signing_claim_before_deadline(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    now = [1_900_000_000]
    service, execution_signer, gas_signer = relayer(
        repo,
        rpc,
        clock=lambda: now[0],
    )
    execution = repo.allocate_or_return(
        intent(),
        chain_pending_nonce=7,
        now=now[0],
    )
    claimed, acquired = repo.claim_signing(execution.execution_id, now=now[0])
    assert acquired is True
    assert claimed.status is ExecutionState.SIGNING

    now[0] += SIGNING_CLAIM_LEASE_SECONDS
    result = service.execute(intent())

    assert result.status is ExecutionState.SUBMITTED
    assert len(execution_signer.digests) == 1
    assert len(gas_signer.digests) == 1
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1


def test_signing_that_crosses_the_real_deadline_is_never_persisted_or_broadcast(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    now = [1_999_999_990]
    service, _execution_signer, gas_signer = relayer(
        repo,
        rpc,
        clock=lambda: now[0],
    )
    original_sign = gas_signer.sign_digest

    def cross_deadline(digest: bytes) -> bytes:
        signature = original_sign(digest)
        now[0] = 2_000_000_000
        return signature

    gas_signer.sign_digest = cross_deadline  # type: ignore[method-assign]

    with pytest.raises(RelayerExecutionError, match="deadline"):
        service.execute(intent())

    stored = repo.find_for_intent(intent())
    assert stored is not None
    assert stored.status is ExecutionState.SIGNING
    assert stored.raw_transaction is None
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0


def test_signed_transaction_is_not_automatically_broadcast_after_deadline(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    timestamps = iter(
        [
            1_999_999_998,  # execute/claim
            1_999_999_999,  # signed transaction persistence
            2_000_000_000,  # pre-submission deadline recheck
        ]
    )
    service, _execution_signer, _gas_signer = relayer(
        repo,
        rpc,
        clock=lambda: next(timestamps),
    )

    result = service.execute(intent())

    assert result.status is ExecutionState.SIGNED
    assert result.raw_transaction is not None
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0


def test_core_approval_verifier_error_is_redacted(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)

    class LeakyVerifier:
        def verify(self, candidate: ExecutionIntent) -> None:
            raise RelayerExecutionError(
                "https://user:secret@example.invalid/internal approval failed"
            )

    service, _, _ = relayer(repo, rpc, approval_verifier=LeakyVerifier())

    with pytest.raises(RelayerExecutionError) as caught:
        service.execute(intent())

    assert str(caught.value) == "Core execution approval is invalid"
    assert "secret" not in str(caught.value)
    assert rpc.calls == []


def test_provider_and_signer_failures_are_secret_free(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    class SecretRpc(Rpc):
        def call(self, method: str, params: list[object]) -> object:
            raise RuntimeError("https://api-key@rpc.example/private")

    service, _, _ = relayer(repo, SecretRpc(repo))

    with pytest.raises(RelayerExecutionError) as captured:
        service.execute(intent())

    assert "api-key" not in str(captured.value)
    assert "private" not in str(captured.value)


@pytest.mark.parametrize(
    ("method", "result", "message"),
    [
        ("eth_estimateGas", "0x3d091", "gas estimate"),
        ("eth_gasPrice", "0x2540be401", "fee quote"),
        ("eth_maxPriorityFeePerGas", "0x77359401", "priority fee"),
    ],
)
def test_provider_cannot_raise_gas_or_fee_above_operator_limits(
    tmp_path: Path,
    method: str,
    result: str,
    message: str,
) -> None:
    repo = repository(tmp_path)

    class ExpensiveRpc(Rpc):
        def call(self, current_method: str, params: list[object]) -> object:
            if current_method == method:
                self.calls.append((current_method, params))
                return result
            return super().call(current_method, params)

    rpc = ExpensiveRpc(repo)
    service, _, gas_signer = relayer(repo, rpc)

    with pytest.raises(RelayerExecutionError, match=message):
        service.execute(intent())

    assert gas_signer.digests == []
    assert all(current != "eth_sendRawTransaction" for current, _ in rpc.calls)


def test_explicit_rebroadcast_uses_only_the_persisted_raw_transaction(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())

    second = service.rebroadcast_identical(first.execution_id)

    assert second.execution_id == first.execution_id
    assert second.raw_transaction == first.raw_transaction
    assert second.raw_transaction_hash == first.raw_transaction_hash
    assert second.broadcast_attempts == 2
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 2


def test_explicit_rebroadcast_recovers_signed_execution_after_crash(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    signed = _persist_signed_execution(repo)

    recovered = service.rebroadcast_identical(signed.execution_id)

    assert recovered.status is ExecutionState.SUBMITTED
    assert recovered.raw_transaction == signed.raw_transaction
    assert recovered.broadcast_attempts == 1
    sends = [params for method, params in rpc.calls if method == "eth_sendRawTransaction"]
    assert sends == [["0x" + signed.raw_transaction.hex()]]


def test_reconciler_inspects_and_submits_through_distinct_rpc_clients(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    inspection_rpc = Rpc(repo)
    submission_rpc = Rpc(repo)
    signed = _persist_signed_execution(repo)
    reconciler = HostedSubmissionReconciler(
        repository=repo,
        rpc=submission_rpc,
        inspection_rpc=inspection_rpc,
        executor_address=EXECUTOR,
        relayer_address=RELAYER,
        clock=lambda: 1_900_000_000,
        chain=BASE_CHAIN,
        token=BASE_USDC,
        chain_id=BASE_CHAIN_ID,
    )

    recovered = reconciler.rebroadcast_identical(signed.execution_id)

    assert recovered.status is ExecutionState.SUBMITTED
    assert [method for method, _ in inspection_rpc.calls] == [
        "eth_chainId",
        "eth_getTransactionByHash",
    ]
    assert [method for method, _ in submission_rpc.calls] == [
        "eth_chainId",
        "eth_sendRawTransaction",
    ]


def test_reconciler_rejects_wrong_submission_chain_before_claiming_signed_work(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    inspection_rpc = Rpc(repo)
    submission_rpc = Rpc(repo, chain_id=POLYGON_CHAIN_ID)
    signed = _persist_signed_execution(repo)
    reconciler = HostedSubmissionReconciler(
        repository=repo,
        rpc=submission_rpc,
        inspection_rpc=inspection_rpc,
        executor_address=EXECUTOR,
        relayer_address=RELAYER,
        clock=lambda: 1_900_000_000,
        chain=BASE_CHAIN,
        token=BASE_USDC,
        chain_id=BASE_CHAIN_ID,
    )

    with pytest.raises(RelayerExecutionError, match="submission RPC chain"):
        reconciler.rebroadcast_identical(signed.execution_id)

    stored = repo.get_execution(signed.execution_id)
    assert stored is not None
    assert stored.status is ExecutionState.SIGNED
    assert stored.broadcast_attempts == 0
    assert [method for method, _ in submission_rpc.calls] == ["eth_chainId"]


def test_explicit_rebroadcast_recovers_unknown_execution_after_crash(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    class RetryRpc(Rpc):
        def call(self, method: str, params: list[object]) -> object:
            if method == "eth_sendRawTransaction" and any(
                current == "eth_sendRawTransaction" for current, _ in self.calls
            ):
                self.calls.append((method, params))
                return "0x" + raw_transaction_hash(bytes.fromhex(str(params[0])[2:])).hex()
            return super().call(method, params)

    rpc = RetryRpc(repo)
    rpc.submission_unknown = True
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    assert first.status is ExecutionState.SUBMISSION_UNKNOWN
    rpc.submission_unknown = False

    recovered = service.rebroadcast_identical(first.execution_id)

    assert recovered.status is ExecutionState.SUBMITTED
    assert recovered.raw_transaction == first.raw_transaction
    assert recovered.broadcast_attempts == 2
    sends = [params for method, params in rpc.calls if method == "eth_sendRawTransaction"]
    assert sends == [["0x" + first.raw_transaction.hex()]] * 2


def test_explicit_rebroadcast_does_not_send_when_exact_transaction_is_found(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    signed = _persist_signed_execution(repo)
    rpc.known_transaction = {
        "hash": signed.raw_transaction_hash,
        "from": RELAYER,
        "to": EXECUTOR,
        "nonce": hex(signed.relayer_nonce),
        "value": "0x0",
        "type": "0x2",
        "chainId": hex(BASE_CHAIN_ID),
        "input": _expected_input(signed),
    }

    recovered = service.rebroadcast_identical(signed.execution_id)

    assert recovered.status is ExecutionState.SUBMITTED
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0


def test_reconciler_inspection_reports_whether_exact_transaction_was_found(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    signed = _persist_signed_execution(repo)

    missing, missing_found = service._submission_reconciler.inspect_submission_with_evidence(
        signed.execution_id
    )
    assert missing.status is ExecutionState.SIGNED
    assert missing_found is False

    rpc.known_transaction = {
        "hash": signed.raw_transaction_hash,
        "from": RELAYER,
        "to": EXECUTOR,
        "nonce": hex(signed.relayer_nonce),
        "value": "0x0",
        "type": "0x2",
        "chainId": hex(BASE_CHAIN_ID),
        "input": _expected_input(signed),
    }
    found, exact_found = service._submission_reconciler.inspect_submission_with_evidence(
        signed.execution_id
    )
    assert found.status is ExecutionState.SUBMITTED
    assert exact_found is True


def test_explicit_rebroadcast_honors_pilot_pause_before_sending_signed_raw(
    tmp_path: Path,
) -> None:
    repo = gated_repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    signed = repo.allocate_or_return(intent(), chain_pending_nonce=7)
    signed, acquired = repo.claim_signing(signed.execution_id)
    assert acquired is True
    repo.reserve_pilot_gas(
        signed.execution_id,
        gas_cost_usd_micros=1,
        signing_claim_generation=signed.signing_claim_generation,
        now=1_900_000_000,
    )
    signed = repo.persist_signed_transaction(
        signed.execution_id,
        signature=bytes.fromhex("01" * 64 + "1b"),
        raw_transaction=bytes.fromhex(
            "02e48221058001028252089433333333333333333333333333333333333333338080c0800101"
        ),
        signing_claim_generation=signed.signing_claim_generation,
    )
    repo.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=1_900_000_000,
    )

    with pytest.raises(PilotGateDenied) as denied:
        service.rebroadcast_identical(signed.execution_id)

    assert denied.value.reason_code == "platform_paused"
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0


def test_explicit_rebroadcast_persists_a_second_definite_provider_rejection(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)

    class RejectingRpc(Rpc):
        reason_code = "insufficient_funds"

        def call(self, method: str, params: list[object]) -> object:
            if method == "eth_sendRawTransaction":
                self.calls.append((method, params))
                raise RpcSubmissionRejected(self.reason_code)
            return super().call(method, params)

    rpc = RejectingRpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    rpc.reason_code = "replacement_underpriced"

    second = service.rebroadcast_identical(first.execution_id)

    assert second.status is ExecutionState.SUBMISSION_REJECTED
    assert second.submission_failure_code == "replacement_underpriced"
    assert second.broadcast_attempts == 2
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 2


def test_rebroadcast_rejects_wrong_rpc_chain_before_durable_mutation(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    first = service.execute(intent())
    rpc.calls.clear()
    rpc.chain_id = POLYGON_CHAIN_ID

    with pytest.raises(RelayerExecutionError, match="RPC chain"):
        service.rebroadcast_identical(first.execution_id)

    stored = repo.get_execution(first.execution_id)
    assert stored is not None
    assert stored.status is first.status
    assert stored.broadcast_attempts == first.broadcast_attempts
    assert stored.updated_at == first.updated_at
    assert stored.broadcasted_at == first.broadcasted_at
    assert [method for method, _ in rpc.calls] == ["eth_chainId"]


def test_cross_chain_rebroadcast_is_rejected_before_mutating_execution(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    rpc = Rpc(repo)
    service, _, _ = relayer(repo, rpc)
    polygon_authorization = ExecutionAuthorization(
        capability_hash="0x" + "aa" * 32,
        reservation_hash="0x" + "bb" * 32,
        owner=OWNER,
        payee=PAYEE,
        token=POLYGON_USDC,
        amount=2_000_000,
        nonce=9,
        deadline=2_000_000_000,
        signer_epoch=3,
        relayer=RELAYER,
        chain_id=POLYGON_CHAIN_ID,
    )
    polygon_intent = intent(
        capability_id="polygon_capability",
        reservation_id="polygon_reservation",
        purchase_id="polygon_purchase",
        idempotency_key="polygon_idempotency",
        chain=POLYGON_CHAIN,
        token=POLYGON_USDC,
        execution_digest="0x"
        + hash_execution(
            polygon_authorization,
            EXECUTOR,
            chain_id=POLYGON_CHAIN_ID,
        ).hex(),
    )
    execution = repo.allocate_or_return(polygon_intent, chain_pending_nonce=7)
    execution, acquired = repo.claim_signing(execution.execution_id)
    assert acquired is True
    repo.persist_signed_transaction(
        execution.execution_id,
        signature=bytes.fromhex("01" * 64 + "1b"),
        raw_transaction=bytes.fromhex(
            "02e48221058001028252089433333333333333333333333333333333333333338080c0800101"
        ),
        signing_claim_generation=execution.signing_claim_generation,
    )
    repo.mark_submitted(execution.execution_id)

    with pytest.raises(RelayerExecutionError, match="chain or token"):
        service.rebroadcast_identical(execution.execution_id)

    stored = repo.get_execution(execution.execution_id)
    assert stored is not None
    assert stored.status is ExecutionState.SUBMITTED
    assert rpc.calls == []


def _expected_input(execution) -> str:
    authorization = ExecutionAuthorization(
        capability_hash=execution.capability_hash,
        reservation_hash=execution.reservation_hash,
        owner=execution.owner,
        payee=execution.payee,
        token=execution.token,
        amount=int(execution.amount_atomic),
        nonce=execution.owner_nonce,
        deadline=execution.deadline,
        signer_epoch=execution.signer_epoch,
        relayer=execution.relayer_address,
    )
    from evm import encode_execute_calldata

    return "0x" + encode_execute_calldata(authorization, execution.signature).hex()


# Base's OP Stack fee predeploys.  These fixtures deliberately keep the fee
# values small so the tests can distinguish L2-only rounding from an all-in
# native-wei reservation without depending on live RPC values.
BASE_GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000f"
BASE_L1_BLOCK = "0x4200000000000000000000000000000000000015"
OPERATOR_FEE_SCALAR_SELECTOR = "0x" + keccak(text="operatorFeeScalar()")[:4].hex()
OPERATOR_FEE_CONSTANT_SELECTOR = "0x" + keccak(text="operatorFeeConstant()")[:4].hex()


def _abi_word(value: int) -> str:
    return "0x" + value.to_bytes(32, "big").hex()


class BaseTotalFeeRpc(Rpc):
    """Deterministic Base fee predeploy responses for total-fee tests."""

    def __init__(
        self,
        repository: ExecutionRepository,
        *,
        l1_fee_upper_bound: int,
        operator_fee_scalar: int,
        operator_fee_constant: int,
    ) -> None:
        super().__init__(repository)
        self.l1_fee_upper_bound = l1_fee_upper_bound
        self.operator_fee_scalar = operator_fee_scalar
        self.operator_fee_constant = operator_fee_constant
        self.oracle_sizes: list[int] = []
        self.operator_getters: list[str] = []

    def call(self, method: str, params: list[object]) -> object:
        if method == "eth_estimateGas":
            self.calls.append((method, params))
            return "0x1"
        if method == "eth_maxPriorityFeePerGas":
            self.calls.append((method, params))
            return "0x1"
        if method == "eth_gasPrice":
            self.calls.append((method, params))
            return "0x1"
        if method == "eth_call":
            self.calls.append((method, params))
            request = params[0]
            assert isinstance(request, dict)
            target = str(request.get("to", "")).lower()
            data = str(request.get("data", "")).lower()
            if target == BASE_GAS_PRICE_ORACLE:
                assert data.startswith("0x") and len(data) == 74
                self.oracle_sizes.append(int(data[10:], 16))
                return _abi_word(self.l1_fee_upper_bound)
            if target == BASE_L1_BLOCK:
                self.operator_getters.append(data[:10])
                if data[:10] == OPERATOR_FEE_SCALAR_SELECTOR:
                    return _abi_word(self.operator_fee_scalar)
                if data[:10] == OPERATOR_FEE_CONSTANT_SELECTOR:
                    return _abi_word(self.operator_fee_constant)
            raise AssertionError((method, params))
        return super().call(method, params)


def total_fee_repository(tmp_path: Path) -> ExecutionRepository:
    return ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'total-fee-relayer.sqlite3'}",
        pilot_policy=PilotGatePolicy(
            # The high synthetic price makes the reservation visibly change
            # when the L1/operator terms are included instead of rounding away.
            native_asset_usd_price_ceiling_micros=10**15,
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )


def total_fee_relayer(
    repo: ExecutionRepository,
    rpc: BaseTotalFeeRpc,
    *,
    max_total_fee_wei: int,
) -> tuple[HostedRelayer, Signer, Signer]:
    execution_signer = Signer(
        recovery_id=27,
        key_id="kms-execution-key",
        address="0x" + "66" * 20,
    )
    gas_signer = Signer(
        recovery_id=0,
        key_id="kms-gas-key",
        address=RELAYER,
    )
    return (
        HostedRelayer(
            repository=repo,
            rpc=rpc,
            execution_signer=execution_signer,
            gas_signer=gas_signer,
            approval_verifier=ApprovalVerifier(intent()),
            executor_address=EXECUTOR,
            relayer_address=RELAYER,
            max_gas_limit=250_000,
            max_fee_per_gas_wei=10_000_000_000,
            max_priority_fee_per_gas_wei=2_000_000_000,
            max_total_fee_wei=max_total_fee_wei,
            clock=lambda: 1_900_000_000,
            chain=BASE_CHAIN,
            token=BASE_USDC,
            chain_id=BASE_CHAIN_ID,
        ),
        execution_signer,
        gas_signer,
    )


def expected_base_total_fee_wei(
    *,
    l1_fee_upper_bound: int,
    operator_fee_scalar: int,
    operator_fee_constant: int,
) -> int:
    gas_limit = 2  # estimate=1 plus the relayer's 20% buffer
    max_fee_per_gas = 3  # gasPrice=1, priorityFee=1 => 2*1+1
    l2_fee = gas_limit * max_fee_per_gas
    operator_fee = (operator_fee_scalar * gas_limit) // 1_000_000
    return l2_fee + l1_fee_upper_bound + operator_fee + operator_fee_constant


def expected_unsigned_base_transaction_size(execution) -> int:
    assert execution.signature is not None
    authorization = ExecutionAuthorization(
        capability_hash=execution.capability_hash,
        reservation_hash=execution.reservation_hash,
        owner=execution.owner,
        payee=execution.payee,
        token=execution.token,
        amount=int(execution.amount_atomic),
        nonce=execution.owner_nonce,
        deadline=execution.deadline,
        signer_epoch=execution.signer_epoch,
        relayer=execution.relayer_address,
        chain_id=BASE_CHAIN_ID,
    )
    transaction = EIP1559Transaction(
        nonce=execution.relayer_nonce,
        max_priority_fee_per_gas=1,
        max_fee_per_gas=3,
        gas_limit=2,
        to=EXECUTOR,
        data=encode_execute_calldata(authorization, execution.signature),
        chain_id=BASE_CHAIN_ID,
    )
    return len(encode_eip1559_unsigned(transaction))


@pytest.mark.parametrize(
    ("operator_fee_scalar", "operator_fee_constant"),
    [(0, 0), (2_000_000, 7)],
    ids=["zero-operator-fee", "nonzero-operator-fee"],
)
def test_base_total_fee_within_cap_uses_l1_and_operator_bounds_for_pilot_reservation(
    tmp_path: Path,
    operator_fee_scalar: int,
    operator_fee_constant: int,
) -> None:
    l1_fee_upper_bound = 1_000
    total_fee = expected_base_total_fee_wei(
        l1_fee_upper_bound=l1_fee_upper_bound,
        operator_fee_scalar=operator_fee_scalar,
        operator_fee_constant=operator_fee_constant,
    )
    repo = total_fee_repository(tmp_path)
    rpc = BaseTotalFeeRpc(
        repo,
        l1_fee_upper_bound=l1_fee_upper_bound,
        operator_fee_scalar=operator_fee_scalar,
        operator_fee_constant=operator_fee_constant,
    )
    hosted, _execution_signer, gas_signer = total_fee_relayer(
        repo,
        rpc,
        max_total_fee_wei=total_fee,
    )

    execution = hosted.execute(intent())

    assert execution.status is ExecutionState.SUBMITTED
    assert len(gas_signer.digests) == 1
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 1
    assert rpc.oracle_sizes == [expected_unsigned_base_transaction_size(execution)]
    assert set(rpc.operator_getters) == {
        OPERATOR_FEE_SCALAR_SELECTOR,
        OPERATOR_FEE_CONSTANT_SELECTOR,
    }
    expected_reserved = worst_case_gas_usd_micros(
        1,
        total_fee,
        10**15,
    )
    with repo.sessions() as session:
        gate = session.get(HostedGateReservationRow, execution.execution_id)
        assert gate is not None
        assert gate.gas_cost_usd_micros == expected_reserved
        assert gate.gas_cost_usd_micros == 2


def test_base_total_fee_cap_rejects_all_in_fee_before_gas_signing_persist_or_broadcast(
    tmp_path: Path,
) -> None:
    l1_fee_upper_bound = 1_000
    total_fee = expected_base_total_fee_wei(
        l1_fee_upper_bound=l1_fee_upper_bound,
        operator_fee_scalar=2_000_000,
        operator_fee_constant=7,
    )
    repo = total_fee_repository(tmp_path)
    rpc = BaseTotalFeeRpc(
        repo,
        l1_fee_upper_bound=l1_fee_upper_bound,
        operator_fee_scalar=2_000_000,
        operator_fee_constant=7,
    )
    hosted, _execution_signer, gas_signer = total_fee_relayer(
        repo,
        rpc,
        max_total_fee_wei=total_fee - 1,
    )

    with pytest.raises(RelayerExecutionError, match="total fee"):
        hosted.execute(intent())

    stored = repo.find_for_intent(intent())
    assert stored is not None
    assert stored.status is ExecutionState.SIGNING
    assert stored.raw_transaction is None
    assert gas_signer.digests == []
    assert [method for method, _ in rpc.calls].count("eth_sendRawTransaction") == 0
