from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import postgresql

from evm import raw_transaction_hash
from execution_models import (
    BASE_CHAIN,
    BASE_USDC,
    ExecutionIntent,
    ExecutionState,
    MAX_UINT256,
    POLYGON_CHAIN,
    POLYGON_USDC,
)
from execution_repository import (
    ExecutionConflict,
    ExecutionRepository,
    HostedExecutionAttemptRow,
    HostedExecutionBase,
    HostedExecutionObservationRow,
    HostedExecutionRow,
    RelayerNonceRow,
    SIGNING_CLAIM_LEASE_SECONDS,
)


NOW = 2_000_000_000
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
RELAYER = "0x" + "44" * 20
SIGNATURE = bytes.fromhex("aa" * 65)
RAW_TRANSACTION = bytes.fromhex(
    "02e48221058001028252089433333333333333333333333333333333333333338080c0800101"
)
RAW_TRANSACTION_2 = bytes.fromhex(
    "02e48221050101028252089433333333333333333333333333333333333333338080c0800202"
)


def intent(**updates: object) -> ExecutionIntent:
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "capability_id": "capability_1",
        "reservation_id": "reservation_1",
        "purchase_id": "purchase_1",
        "request_id": "request_1",
        "request_hash": "0x" + "99" * 32,
        "idempotency_key": "idempotency_1",
        "chain": BASE_CHAIN,
        "owner": OWNER,
        "payee": PAYEE,
        "token": BASE_USDC,
        "amount_atomic": "1000000",
        "executor": EXECUTOR,
        "signer_epoch": 1,
        "owner_nonce": 7,
        "deadline": NOW + 60,
        "capability_hash": "0x" + "55" * 32,
        "reservation_hash": "0x" + "66" * 32,
        "execution_scope_hash": "0x" + "77" * 32,
        "execution_digest": "0x" + "88" * 32,
        "relayer_address": RELAYER,
    }
    values.update(updates)
    return ExecutionIntent(**values)


@pytest.fixture
def repository(tmp_path) -> ExecutionRepository:
    return ExecutionRepository(f"sqlite+pysqlite:///{tmp_path / 'hosted.sqlite3'}")


def _submitted(repository: ExecutionRepository):
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    return repository.mark_submitted(execution.execution_id)


def _attempt_count(repository: ExecutionRepository, execution_id: str) -> int:
    with repository.sessions() as session:
        return len(
            session.scalars(
                select(HostedExecutionAttemptRow).where(
                    HostedExecutionAttemptRow.execution_id == execution_id
                )
            ).all()
        )


def _observation_count(repository: ExecutionRepository, execution_id: str) -> int:
    with repository.sessions() as session:
        return len(
            session.scalars(
                select(HostedExecutionObservationRow).where(
                    HostedExecutionObservationRow.execution_id == execution_id
                )
            ).all()
        )


def test_postgres_metadata_declares_durable_execution_constraints() -> None:
    names = set(HostedExecutionBase.metadata.tables)
    assert {
        "hosted_executions",
        "hosted_relayer_nonce_allocations",
        "hosted_execution_attempts",
        "hosted_execution_observations",
    } <= names

    ddl = "\n".join(
        str(
            CreateTable(HostedExecutionBase.metadata.tables[name]).compile(
                dialect=postgresql.dialect()
            )
        )
        for name in names
    )
    assert "uq_hosted_execution_capability" in ddl
    assert "uq_hosted_execution_reservation" in ddl
    assert "uq_hosted_execution_purchase" in ddl
    indexes = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in HostedExecutionRow.__table__.indexes
    )
    assert "uq_hosted_execution_active_chain_relayer_nonce" in indexes
    assert "WHERE status NOT IN ('expired', 'released')" in indexes
    assert "signing_claim_generation" in ddl
    assert "ck_hosted_execution_signing_claim_expiry" in ddl
    assert "CHECK" in ddl
    assert "owner_nonce VARCHAR(78)" in ddl
    assert "owner_nonce BIGINT" not in ddl


def test_fresh_schema_rejects_terminal_execution_without_finality_boundary(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)

    with pytest.raises(IntegrityError):
        with repository.sessions() as session:
            row = session.get(HostedExecutionRow, submitted.execution_id)
            assert row is not None
            row.status = ExecutionState.CONFIRMED.value
            row.receipt_status = 1
            row.receipt_block_number = 100
            row.receipt_block_hash = "0x" + "aa" * 32
            row.confirmations = 2
            row.safe_block_number = 101
            row.safe_block_hash = "0x" + "bb" * 32
            row.finality_boundary = None
            session.commit()


def test_allocate_or_return_is_exact_and_idempotent(repository: ExecutionRepository) -> None:
    first = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    replay = repository.allocate_or_return(intent(), chain_pending_nonce=100)

    assert first.execution_id == replay.execution_id
    assert first.relayer_nonce == replay.relayer_nonce == 37
    assert first.status is ExecutionState.PREFLIGHT_APPROVED
    with repository.sessions() as session:
        assert len(session.scalars(select(HostedExecutionRow)).all()) == 1
        nonce = session.get(RelayerNonceRow, (BASE_CHAIN, RELAYER))
        assert nonce is not None
        assert nonce.next_nonce == 38
        row = session.get(HostedExecutionRow, first.execution_id)
        assert row is not None
        assert row.owner_nonce == "7"


def test_find_for_intent_returns_exact_existing_without_allocating_nonce(
    repository: ExecutionRepository,
) -> None:
    assert repository.find_for_intent(intent()) is None
    first = repository.allocate_or_return(intent(), chain_pending_nonce=37)

    replay = repository.find_for_intent(intent())

    assert replay is not None
    assert replay.execution_id == first.execution_id
    assert replay.relayer_nonce == 37
    with pytest.raises(ExecutionConflict, match="immutable execution scope"):
        repository.find_for_intent(intent(amount_atomic="1000001"))


def test_list_watchable_ids_uses_bounded_cursor_and_watchable_states(
    repository: ExecutionRepository,
) -> None:
    statuses = [
        "preflight_approved",
        "signing",
        "submitted",
        "submission_unknown",
        "submission_rejected",
        "confirmed",
        "finalized",
        "requested",
    ]
    execution_ids: list[str] = []
    for index, status in enumerate(statuses, start=1):
        stored = repository.allocate_or_return(
            intent(
                capability_id=f"capability_{index}",
                reservation_id=f"reservation_{index}",
                purchase_id=f"purchase_{index}",
                idempotency_key=f"idempotency_{index}",
            ),
            chain_pending_nonce=36 + index,
        )
        execution_ids.append(stored.execution_id)
        with repository.sessions() as session:
            row = session.get(HostedExecutionRow, stored.execution_id)
            assert row is not None
            row.status = status
            if status in {"confirmed", "finalized"}:
                row.receipt_status = 1
                row.receipt_block_number = 1
                row.receipt_block_hash = "0x" + "aa" * 32
                row.confirmations = 2
                row.safe_block_number = 2
                row.safe_block_hash = "0x" + "bb" * 32
                row.finality_boundary = "safe"
            session.commit()

    watchable_ids = sorted(execution_ids[:7])
    polygon = repository.allocate_or_return(
        intent(
            capability_id="polygon_watch_capability",
            reservation_id="polygon_watch_reservation",
            purchase_id="polygon_watch_purchase",
            idempotency_key="polygon_watch_idempotency",
            chain=POLYGON_CHAIN,
            token=POLYGON_USDC,
        ),
        chain_pending_nonce=100,
    )
    with repository.sessions() as session:
        row = session.get(HostedExecutionRow, polygon.execution_id)
        assert row is not None
        row.status = ExecutionState.SUBMITTED.value
        session.commit()

    assert repository.list_watchable_ids(chain=BASE_CHAIN, after_execution_id=None, limit=10) == watchable_ids
    assert repository.list_watchable_ids(
        chain=POLYGON_CHAIN,
        after_execution_id=None,
        limit=5,
    ) == [polygon.execution_id]
    assert repository.list_watchable_ids(
        chain=BASE_CHAIN,
        after_execution_id=watchable_ids[1], limit=2
    ) == watchable_ids[2:4]
    with pytest.raises(ValueError):
        repository.list_watchable_ids(chain=BASE_CHAIN, after_execution_id=None, limit=0)


def test_reverted_without_release_evidence_remains_watchable(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    repository.revert(
        submitted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
    )

    assert submitted.execution_id in repository.list_watchable_ids(
        chain=BASE_CHAIN,
        after_execution_id=None,
        limit=10,
    )


def test_allocate_or_return_rejects_changed_scope(repository: ExecutionRepository) -> None:
    repository.allocate_or_return(intent(), chain_pending_nonce=37)

    with pytest.raises(ExecutionConflict, match="immutable|scope|execution"):
        repository.allocate_or_return(
            intent(amount_atomic="1000001"), chain_pending_nonce=37
        )


@pytest.mark.parametrize("pending", [-1, 1.0, "37"])
def test_allocate_requires_canonical_pending_nonce(
    repository: ExecutionRepository, pending: object
) -> None:
    with pytest.raises(ExecutionConflict, match="pending nonce"):
        repository.allocate_or_return(intent(), chain_pending_nonce=pending)


def test_concurrent_workers_create_one_execution_and_one_nonce(
    repository: ExecutionRepository,
) -> None:
    def allocate(_worker: int):
        return repository.allocate_or_return(intent(), chain_pending_nonce=37)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(allocate, range(2)))

    assert len({result.execution_id for result in results}) == 1
    assert {result.relayer_nonce for result in results} == {37}
    with repository.sessions() as session:
        assert len(session.scalars(select(HostedExecutionRow)).all()) == 1
        nonce = session.get(RelayerNonceRow, (BASE_CHAIN, RELAYER))
        assert nonce is not None
        assert nonce.next_nonce == 38


def test_pending_nonce_is_authoritative_without_regressing_stored_allocator(
    repository: ExecutionRepository,
) -> None:
    first = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    second = repository.allocate_or_return(
        intent(
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
            idempotency_key="idempotency_2",
        ),
        chain_pending_nonce=5,
    )
    third = repository.allocate_or_return(
        intent(
            capability_id="capability_3",
            reservation_id="reservation_3",
            purchase_id="purchase_3",
            idempotency_key="idempotency_3",
        ),
        chain_pending_nonce=100,
    )

    assert (first.relayer_nonce, second.relayer_nonce, third.relayer_nonce) == (
        37,
        38,
        100,
    )
    replay = repository.allocate_or_return(intent(), chain_pending_nonce=101)
    assert replay.execution_id == first.execution_id
    assert replay.relayer_nonce == 37


def test_idempotency_is_scoped_by_tenant_and_node(repository: ExecutionRepository) -> None:
    first = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    second = repository.allocate_or_return(
        intent(
            tenant_id="tenant_2",
            node_id="node_2",
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
        ),
        chain_pending_nonce=37,
    )

    assert first.execution_id != second.execution_id
    replay = repository.allocate_or_return(
        intent(
            tenant_id="tenant_2",
            node_id="node_2",
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
        ),
        chain_pending_nonce=38,
    )
    assert replay.execution_id == second.execution_id


def test_owner_nonce_full_uint256_round_trips_without_bigint_overflow(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(
        intent(owner_nonce=MAX_UINT256), chain_pending_nonce=37
    )

    assert execution.owner_nonce == MAX_UINT256
    with repository.sessions() as session:
        row = session.get(HostedExecutionRow, execution.execution_id)
        assert row is not None
        assert row.owner_nonce == str(MAX_UINT256)


def test_signed_persistence_submission_unknown_and_exact_rebroadcast(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    signed = repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    assert signed.status is ExecutionState.SIGNED
    assert signed.raw_transaction_hash == "0x" + raw_transaction_hash(RAW_TRANSACTION).hex()
    with pytest.raises(ExecutionConflict, match="raw transaction"):
        repository.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=b"\xbb" * 80,
            signing_claim_generation=execution.signing_claim_generation,
        )

    submitted = repository.mark_submitted(execution.execution_id)
    assert submitted.status is ExecutionState.SUBMITTED
    unknown = repository.mark_submission_unknown(execution.execution_id)
    assert unknown.status is ExecutionState.SUBMISSION_UNKNOWN
    assert repository.rebroadcast_raw_transaction(execution.execution_id) == RAW_TRANSACTION

    with repository.sessions() as session:
        attempts = session.scalars(
            select(HostedExecutionAttemptRow).where(
                HostedExecutionAttemptRow.execution_id == execution.execution_id
            )
        ).all()
        assert [attempt.raw_transaction_hash for attempt in attempts] == [
            signed.raw_transaction_hash,
            signed.raw_transaction_hash,
            signed.raw_transaction_hash,
        ]
        assert "raw_transaction" not in HostedExecutionAttemptRow.__table__.columns

    with pytest.raises(ExecutionConflict, match="raw transaction|replacement"):
        repository.rebroadcast_raw_transaction(
            execution.execution_id, raw_transaction=b"different"
        )
    with pytest.raises(ExecutionConflict, match="state|replacement"):
        repository.transition(execution.execution_id, ExecutionState.SIGNED)


def test_mark_submitted_replay_does_not_add_broadcast_attempt(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    attempts_before = _attempt_count(repository, submitted.execution_id)

    replay = repository.mark_submitted(submitted.execution_id, now=NOW + 1)

    assert replay.status is ExecutionState.SUBMITTED
    assert replay.broadcast_attempts == submitted.broadcast_attempts == 1
    assert _attempt_count(repository, submitted.execution_id) == attempts_before


def test_mark_submission_unknown_replay_does_not_add_attempt_or_observation(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    unknown = repository.mark_submission_unknown(submitted.execution_id)
    attempts_before = _attempt_count(repository, unknown.execution_id)
    observations_before = _observation_count(repository, unknown.execution_id)

    replay = repository.mark_submission_unknown(unknown.execution_id, now=NOW + 1)

    assert replay.status is ExecutionState.SUBMISSION_UNKNOWN
    assert replay.broadcast_attempts == unknown.broadcast_attempts == 1
    assert _attempt_count(repository, unknown.execution_id) == attempts_before
    assert _observation_count(repository, unknown.execution_id) == observations_before


def test_definite_rejection_has_an_explicit_replay_safe_state(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    claimed, acquired = repository.claim_submission(execution.execution_id, now=NOW)
    replayed_claim, replay_acquired = repository.claim_submission(
        execution.execution_id, now=NOW + 1
    )
    assert claimed.status is ExecutionState.SUBMISSION_UNKNOWN
    assert acquired is True
    assert replayed_claim.execution_id == claimed.execution_id
    assert replay_acquired is False

    rejected = repository.mark_submission_rejected(
        execution.execution_id,
        reason_code="insufficient_funds",
        now=NOW + 2,
    )
    replay = repository.mark_submission_rejected(
        execution.execution_id,
        reason_code="insufficient_funds",
        now=NOW + 3,
    )

    assert rejected.status is ExecutionState.SUBMISSION_REJECTED
    assert replay.status is ExecutionState.SUBMISSION_REJECTED
    assert replay.submission_failure_code == "insufficient_funds"
    assert replay.broadcast_attempts == 1
    assert _attempt_count(repository, execution.execution_id) == 2
    with pytest.raises(ExecutionConflict, match="failure reason"):
        repository.mark_submission_rejected(
            execution.execution_id,
            reason_code="invalid_sender",
            now=NOW + 4,
        )


def test_rejected_execution_keeps_signed_raw_for_explicit_reconciliation(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    repository.claim_submission(execution.execution_id, now=NOW)
    repository.mark_submission_rejected(
        execution.execution_id,
        reason_code="insufficient_funds",
        now=NOW,
    )

    with pytest.raises(ExecutionConflict, match="transition|released"):
        repository.transition(
            execution.execution_id,
            ExecutionState.RELEASED,
            now=NOW + 61,
        )

    assert (
        repository.rebroadcast_raw_transaction(
            execution.execution_id,
            now=NOW + 61,
        )
        == RAW_TRANSACTION
    )
    persisted = repository.get_execution(execution.execution_id)
    assert persisted is not None
    assert persisted.status is ExecutionState.SUBMISSION_REJECTED
    assert persisted.raw_transaction == RAW_TRANSACTION


def test_confirm_replay_is_exact_and_changed_evidence_conflicts(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    confirmation = {
        "receipt_status": 1,
        "receipt_block_number": 100,
        "receipt_block_hash": "0x" + "99" * 32,
        "confirmations": 2,
        "safe_block_number": 100,
        "safe_block_hash": "0x" + "99" * 32,
        "watcher_version": "watcher-v1",
        "finality_boundary": "safe",
        "evidence": {"boundary": "safe", "reason": "receipt_observed"},
    }

    confirmed = repository.confirm(submitted.execution_id, **confirmation)
    observations_before = _observation_count(repository, confirmed.execution_id)
    replay = repository.confirm(
        confirmed.execution_id,
        **confirmation,
        now=NOW + 1,
    )

    assert replay.status is ExecutionState.CONFIRMED
    assert replay.updated_at == confirmed.updated_at
    assert _observation_count(repository, confirmed.execution_id) == observations_before

    changed_evidence = {"boundary": "safe", "reason": "different_receipt"}
    with pytest.raises(ExecutionConflict, match="observation|evidence|replay"):
        repository.confirm(
            confirmed.execution_id,
            **{**confirmation, "evidence": changed_evidence},
            now=NOW + 2,
        )
    assert _observation_count(repository, confirmed.execution_id) == observations_before


def test_revert_replay_is_exact_and_changed_evidence_conflicts(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    reversion = {
        "receipt_status": 0,
        "receipt_block_number": 100,
        "receipt_block_hash": "0x" + "99" * 32,
        "confirmations": 2,
        "safe_block_number": 100,
        "safe_block_hash": "0x" + "99" * 32,
        "accepted_transfer": False,
        "watcher_version": "watcher-v1",
        "finality_boundary": "safe",
        "evidence": {"accepted_transfer": False, "reason": "receipt_reverted"},
    }

    reverted = repository.revert(submitted.execution_id, **reversion)
    observations_before = _observation_count(repository, reverted.execution_id)
    replay = repository.revert(
        reverted.execution_id,
        **reversion,
        now=NOW + 1,
    )

    assert replay.status is ExecutionState.REVERTED
    assert replay.finality_boundary == "safe"
    assert replay.updated_at == reverted.updated_at
    assert _observation_count(repository, reverted.execution_id) == observations_before

    changed_evidence = {
        "accepted_transfer": False,
        "reason": "different_receipt",
    }
    with pytest.raises(ExecutionConflict, match="observation|evidence|replay"):
        repository.revert(
            reverted.execution_id,
            **{**reversion, "evidence": changed_evidence},
            now=NOW + 2,
        )
    assert _observation_count(repository, reverted.execution_id) == observations_before


def test_released_revert_requires_post_deadline_proof_and_replays_exactly(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    reverted = repository.revert(
        submitted.execution_id,
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
    release_evidence = {
        "receipt_status": 0,
        "canonical_receipt": True,
        "finality_boundary_timestamp": submitted.deadline,
        "capability_used": False,
        "owner_nonce_used": False,
        "payment_event_found": False,
        "transfer_event_found": False,
    }

    released = repository.release_reverted(
        reverted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence=release_evidence,
        now=NOW + 60,
    )

    assert released.status is ExecutionState.RELEASED
    assert released.receipt_block_hash == "0x" + "99" * 32
    assert released.reverted_at == NOW + 1
    assert released.released_at == NOW + 60
    assert released.release_evidence == release_evidence
    replay = repository.release_reverted(
        released.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence=release_evidence,
        now=NOW + 61,
    )
    assert replay.status is ExecutionState.RELEASED
    assert replay.released_at == released.released_at

    changed = {**release_evidence, "finality_boundary_timestamp": submitted.deadline + 1}
    with pytest.raises(ExecutionConflict, match="release|evidence|deadline"):
        repository.release_reverted(
            released.execution_id,
            receipt_status=0,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=2,
            safe_block_number=100,
            safe_block_hash="0x" + "99" * 32,
            watcher_version="watcher-v1",
            finality_boundary="safe",
            release_evidence=changed,
            now=NOW + 62,
        )


def test_reverted_before_deadline_releases_on_later_finality_boundary(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    reverted = repository.revert(
        submitted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=102,
        safe_block_hash="0x" + "aa" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        evidence={
            "accepted_transfer": False,
            "boundary": "safe",
            "finality_boundary": "safe",
            "confirmations": 2,
            "receipt_block_number": 100,
            "safe_block_number": 102,
            "watcher_version": "watcher-v1",
            "capability_used": False,
            "owner_nonce_used": False,
            "payment_event_found": False,
            "transfer_event_found": False,
            "finality_boundary_timestamp": submitted.deadline - 1,
        },
        now=NOW + 1,
    )

    released = repository.release_reverted(
        reverted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=3,
        safe_block_number=103,
        safe_block_hash="0x" + "bb" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence={
            "receipt_status": 0,
            "canonical_receipt": True,
            "finality_boundary_timestamp": submitted.deadline,
            "capability_used": False,
            "owner_nonce_used": False,
            "payment_event_found": False,
            "transfer_event_found": False,
        },
        now=submitted.deadline,
    )

    assert released.status is ExecutionState.RELEASED
    assert released.receipt_block_number == 100
    assert released.receipt_block_hash == "0x" + "99" * 32
    assert released.confirmations == 3
    assert released.safe_block_number == 103
    assert released.safe_block_hash == "0x" + "bb" * 32


def test_revert_release_rejects_finality_before_authorization_deadline(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    reverted = repository.revert(
        submitted.execution_id,
        receipt_status=0,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
    )
    with pytest.raises(ExecutionConflict, match="deadline"):
        repository.release_reverted(
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
                "finality_boundary_timestamp": submitted.deadline - 1,
                "capability_used": False,
                "owner_nonce_used": False,
                "payment_event_found": False,
                "transfer_event_found": False,
            },
        )

def test_finalize_replay_is_exact(repository: ExecutionRepository) -> None:
    submitted = _submitted(repository)
    confirmed = repository.confirm(
        submitted.execution_id,
        receipt_status=1,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
    )
    observations_before = _observation_count(repository, confirmed.execution_id)

    finalized = repository.finalize(confirmed.execution_id, finality_boundary="safe", now=NOW + 1)
    replay = repository.finalize(finalized.execution_id, finality_boundary="safe", now=NOW + 2)

    assert finalized.status is ExecutionState.FINALIZED
    assert replay.status is ExecutionState.FINALIZED
    assert replay.updated_at == finalized.updated_at
    assert _observation_count(repository, finalized.execution_id) == observations_before


def test_polygon_finality_is_persisted_and_requires_finalized_boundary(
    repository: ExecutionRepository,
) -> None:
    submitted = repository.allocate_or_return(
        intent(
            capability_id="polygon_capability",
            reservation_id="polygon_reservation",
            purchase_id="polygon_purchase",
            idempotency_key="polygon_idempotency",
            chain=POLYGON_CHAIN,
            token=POLYGON_USDC,
        ),
        chain_pending_nonce=37,
    )
    submitted, acquired = repository.claim_signing(submitted.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        submitted.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=submitted.signing_claim_generation,
    )
    submitted = repository.mark_submitted(submitted.execution_id)

    confirmation = {
        "receipt_status": 1,
        "receipt_block_number": 100,
        "receipt_block_hash": "0x" + "aa" * 32,
        "confirmations": 3,
        "safe_block_number": 103,
        "safe_block_hash": "0x" + "bb" * 32,
        "watcher_version": "hosted-watcher-v1",
        "finality_boundary": "finalized",
        "evidence": {
            "accepted_transfer": True,
            "boundary": "finalized",
            "confirmations": 3,
            "finality_boundary": "finalized",
            "receipt_block_number": 100,
            "safe_block_number": 103,
            "watcher_version": "hosted-watcher-v1",
        },
    }
    confirmed = repository.confirm(submitted.execution_id, **confirmation)

    assert confirmed.finality_boundary == "finalized"
    with repository.sessions() as session:
        row = session.get(HostedExecutionRow, submitted.execution_id)
        assert row is not None
        assert row.finality_boundary == "finalized"

    with pytest.raises(ExecutionConflict, match="finality boundary"):
        repository.finalize(submitted.execution_id, finality_boundary="safe")

    finalized = repository.finalize(
        submitted.execution_id,
        finality_boundary="finalized",
    )
    assert finalized.status is ExecutionState.FINALIZED
    assert finalized.finality_boundary == "finalized"


def test_generic_transition_cannot_claim_chain_outcome_without_evidence(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    repository.mark_submitted(execution.execution_id)

    with pytest.raises(ExecutionConflict, match="evidence|watcher|dedicated"):
        repository.transition(execution.execution_id, ExecutionState.CONFIRMED)
    assert repository.get_execution(execution.execution_id).status is ExecutionState.SUBMITTED


def test_generic_transition_cannot_bypass_the_signing_claim_fence(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)

    with pytest.raises(ExecutionConflict, match="signing claim|dedicated"):
        repository.transition(execution.execution_id, ExecutionState.SIGNING, now=NOW)

    persisted = repository.get_execution(execution.execution_id)
    assert persisted is not None
    assert persisted.status is ExecutionState.PREFLIGHT_APPROVED
    assert persisted.signing_claim_generation == 0


def test_release_is_allowed_only_before_signed_material(repository: ExecutionRepository) -> None:
    execution = repository.allocate_or_return(
        intent(deadline=NOW - 1), chain_pending_nonce=37
    )
    released = repository.release_expired(execution.execution_id, now=NOW)
    assert released.status is ExecutionState.RELEASED

    with pytest.raises(ExecutionConflict, match="terminal|released|transition|not allowed"):
        repository.transition(execution.execution_id, ExecutionState.SIGNING)


def test_expiry_and_signing_respect_the_deadline(repository: ExecutionRepository) -> None:
    execution = repository.allocate_or_return(
        intent(deadline=NOW + 10), chain_pending_nonce=37
    )

    with pytest.raises(ExecutionConflict, match="deadline|expired"):
        repository.transition(execution.execution_id, ExecutionState.RELEASED, now=NOW)
    with pytest.raises(ExecutionConflict, match="deadline|expired"):
        repository.transition(execution.execution_id, ExecutionState.EXPIRED, now=NOW)

    execution, acquired = repository.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    with pytest.raises(ExecutionConflict, match="deadline|expired"):
        repository.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=RAW_TRANSACTION,
            signing_claim_generation=execution.signing_claim_generation,
            now=NOW + 10,
        )


def test_expired_signing_claim_is_recoverable_and_stale_worker_is_fenced(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(
        intent(deadline=NOW + SIGNING_CLAIM_LEASE_SECONDS + 10),
        chain_pending_nonce=37,
        now=NOW,
    )
    first, acquired = repository.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True

    active, acquired = repository.claim_signing(
        execution.execution_id,
        now=NOW + SIGNING_CLAIM_LEASE_SECONDS - 1,
    )
    assert acquired is False
    assert active.updated_at == first.updated_at

    recovered, acquired = repository.claim_signing(
        execution.execution_id,
        now=NOW + SIGNING_CLAIM_LEASE_SECONDS,
    )
    assert acquired is True
    assert recovered.updated_at != first.updated_at

    with pytest.raises(ExecutionConflict, match="signing claim"):
        repository.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=RAW_TRANSACTION,
            signing_claim_generation=first.signing_claim_generation,
            now=recovered.updated_at,
        )

    signed = repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=recovered.signing_claim_generation,
        now=recovered.updated_at,
    )
    assert signed.status is ExecutionState.SIGNED


def test_watcher_activity_does_not_extend_the_signing_claim_lease(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(
        intent(deadline=NOW + SIGNING_CLAIM_LEASE_SECONDS + 10),
        chain_pending_nonce=37,
        now=NOW,
    )
    claimed, acquired = repository.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    assert claimed.signing_claim_expires_at == NOW + SIGNING_CLAIM_LEASE_SECONDS

    repository.record_watcher_attempt(
        execution.execution_id,
        now_ns=(NOW + SIGNING_CLAIM_LEASE_SECONDS - 1) * 1_000_000_000,
    )
    recovered, acquired = repository.claim_signing(
        execution.execution_id,
        now=NOW + SIGNING_CLAIM_LEASE_SECONDS,
    )

    assert acquired is True
    assert recovered.signing_claim_generation == claimed.signing_claim_generation + 1


def test_only_one_worker_reclaims_an_expired_signing_lease(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(
        intent(deadline=NOW + SIGNING_CLAIM_LEASE_SECONDS + 10),
        chain_pending_nonce=37,
        now=NOW,
    )
    repository.claim_signing(execution.execution_id, now=NOW)
    reclaim_at = NOW + SIGNING_CLAIM_LEASE_SECONDS

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: repository.claim_signing(
                    execution.execution_id,
                    now=reclaim_at,
                ),
                range(2),
            )
        )

    assert [acquired for _execution, acquired in results].count(True) == 1
    assert [acquired for _execution, acquired in results].count(False) == 1


def test_unsigned_released_nonce_is_reused_before_allocating_a_higher_nonce(
    repository: ExecutionRepository,
) -> None:
    first = repository.allocate_or_return(
        intent(deadline=NOW + 1),
        chain_pending_nonce=37,
        now=NOW,
    )
    assert first.relayer_nonce == 37
    repository.release_expired(first.execution_id, now=NOW + 1)

    second = repository.allocate_or_return(
        intent(
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
            request_id="request_2",
            idempotency_key="idempotency_2",
            owner_nonce=8,
            deadline=NOW + 60,
        ),
        chain_pending_nonce=37,
        now=NOW + 1,
    )
    third = repository.allocate_or_return(
        intent(
            capability_id="capability_3",
            reservation_id="reservation_3",
            purchase_id="purchase_3",
            request_id="request_3",
            idempotency_key="idempotency_3",
            owner_nonce=9,
            deadline=NOW + 60,
        ),
        chain_pending_nonce=37,
        now=NOW + 1,
    )

    assert second.relayer_nonce == 37
    assert third.relayer_nonce == 38


def test_released_gap_is_reused_when_pending_nonce_reports_queued_higher_work(
    repository: ExecutionRepository,
) -> None:
    gap = repository.allocate_or_return(
        intent(deadline=NOW + 1),
        chain_pending_nonce=37,
        chain_confirmed_nonce=37,
        now=NOW,
    )
    active = repository.allocate_or_return(
        intent(
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
            request_id="request_2",
            idempotency_key="idempotency_2",
            owner_nonce=8,
        ),
        chain_pending_nonce=38,
        chain_confirmed_nonce=37,
        now=NOW,
    )
    assert (gap.relayer_nonce, active.relayer_nonce) == (37, 38)
    repository.release_expired(gap.execution_id, now=NOW + 1)

    recovered = repository.allocate_or_return(
        intent(
            capability_id="capability_3",
            reservation_id="reservation_3",
            purchase_id="purchase_3",
            request_id="request_3",
            idempotency_key="idempotency_3",
            owner_nonce=9,
        ),
        chain_pending_nonce=39,
        chain_confirmed_nonce=37,
        now=NOW + 1,
    )

    assert recovered.relayer_nonce == 37


def test_historical_signed_terminal_nonce_taints_all_unsigned_siblings(
    repository: ExecutionRepository,
) -> None:
    unsigned = repository.allocate_or_return(
        intent(deadline=NOW + 1),
        chain_pending_nonce=37,
        chain_confirmed_nonce=37,
        now=NOW,
    )
    repository.release_expired(unsigned.execution_id, now=NOW + 1)

    signed = repository.allocate_or_return(
        intent(
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
            request_id="request_2",
            idempotency_key="idempotency_2",
            owner_nonce=8,
            deadline=NOW + 60,
        ),
        chain_pending_nonce=38,
        chain_confirmed_nonce=37,
        now=NOW + 1,
    )
    signed, acquired = repository.claim_signing(signed.execution_id, now=NOW + 1)
    assert acquired is True
    repository.persist_signed_transaction(
        signed.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=signed.signing_claim_generation,
        now=NOW + 1,
    )
    repository.claim_submission(signed.execution_id, now=NOW + 1)
    repository.mark_submission_rejected(
        signed.execution_id,
        reason_code="insufficient_funds",
        now=NOW + 1,
    )

    # Simulate a row released by the pre-fix implementation. The unsigned
    # sibling at nonce 37 must not make that nonce recyclable again.
    with repository.sessions() as session:
        row = session.get(HostedExecutionRow, signed.execution_id)
        assert row is not None
        row.status = ExecutionState.RELEASED.value
        row.released_at = NOW + 61
        row.updated_at = NOW + 61
        session.commit()

    recovered = repository.allocate_or_return(
        intent(
            capability_id="capability_3",
            reservation_id="reservation_3",
            purchase_id="purchase_3",
            request_id="request_3",
            idempotency_key="idempotency_3",
            owner_nonce=9,
        ),
        chain_pending_nonce=38,
        chain_confirmed_nonce=37,
        now=NOW + 62,
    )

    assert recovered.relayer_nonce == 38


def test_confirm_finalize_and_later_reorg_review_require_evidence(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    repository.mark_submitted(execution.execution_id)
    confirmed = repository.confirm(
        execution.execution_id,
        receipt_status=1,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        now=NOW + 1,
    )
    assert confirmed.status is ExecutionState.CONFIRMED
    assert confirmed.confirmed_at == NOW + 1
    with repository.sessions() as session:
        observation = session.scalar(
            select(HostedExecutionObservationRow).where(
                HostedExecutionObservationRow.execution_id == execution.execution_id
            )
        )
        assert observation is not None
        assert observation.tx_hash == confirmed.raw_transaction_hash
    finalized = repository.finalize(execution.execution_id, finality_boundary="safe", now=NOW + 10)
    assert finalized.status is ExecutionState.FINALIZED
    assert finalized.confirmed_at == NOW + 1
    assert finalized.finalized_at == NOW + 10
    reviewed = repository.mark_reorg_review(
        execution.execution_id,
        evidence={"canonical": False, "reason": "block_hash_changed"},
        now=NOW + 11,
    )
    assert reviewed.status is ExecutionState.REORG_REVIEW
    assert reviewed.reorg_reviewed_at == NOW + 11


def test_revert_and_release_keep_explicit_transition_times(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)
    reverted = repository.revert(
        submitted.execution_id,
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
    assert reverted.reverted_at == NOW + 1

    expiring = repository.allocate_or_return(
        intent(
            capability_id="capability_release",
            reservation_id="reservation_release",
            purchase_id="purchase_release",
            idempotency_key="idempotency_release",
            deadline=NOW - 1,
        ),
        chain_pending_nonce=38,
    )
    released = repository.release_expired(expiring.execution_id, now=NOW + 2)
    assert released.released_at == NOW + 2


def test_evidence_is_public_allowlisted_and_watcher_version_bounded(
    repository: ExecutionRepository,
) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    repository.mark_submitted(execution.execution_id)

    with pytest.raises(ExecutionConflict, match="evidence|field|public"):
        repository.confirm(
            execution.execution_id,
            receipt_status=1,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=2,
            safe_block_number=100,
            safe_block_hash="0x" + "99" * 32,
            watcher_version="watcher-v1",
            finality_boundary="safe",
            evidence={"provider_credential": "secret"},
        )
    with pytest.raises(ExecutionConflict, match="watcher|version"):
        repository.confirm(
            execution.execution_id,
            receipt_status=1,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=2,
            safe_block_number=100,
            safe_block_hash="0x" + "99" * 32,
            watcher_version="w" * 129,
            finality_boundary="safe",
        )


def test_reverted_receipt_requires_no_accepted_transfer(repository: ExecutionRepository) -> None:
    execution = repository.allocate_or_return(intent(), chain_pending_nonce=37)
    execution, acquired = repository.claim_signing(execution.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
    )
    repository.mark_submitted(execution.execution_id)
    with pytest.raises(ExecutionConflict, match="confirmation|safe"):
        repository.revert(
            execution.execution_id,
            receipt_status=0,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=1,
            safe_block_number=100,
            safe_block_hash="0x" + "99" * 32,
            accepted_transfer=False,
            watcher_version="watcher-v1",
            finality_boundary="safe",
        )
    with pytest.raises(ExecutionConflict, match="safe"):
        repository.revert(
            execution.execution_id,
            receipt_status=0,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=2,
            safe_block_number=99,
            safe_block_hash="0x" + "99" * 32,
            accepted_transfer=False,
            watcher_version="watcher-v1",
            finality_boundary="safe",
        )
    with pytest.raises(ExecutionConflict, match="safe"):
        repository.revert(
            execution.execution_id,
            receipt_status=0,
            receipt_block_number=100,
            receipt_block_hash="0x" + "99" * 32,
            confirmations=2,
            safe_block_number=100,
            safe_block_hash="",
            accepted_transfer=False,
            watcher_version="watcher-v1",
            finality_boundary="safe",
        )
    reverted = repository.revert(
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
    )
    assert reverted.status is ExecutionState.REVERTED
    assert reverted.finality_boundary == "safe"

    execution_2 = repository.allocate_or_return(
        intent(
            capability_id="capability_2",
            reservation_id="reservation_2",
            purchase_id="purchase_2",
            idempotency_key="idempotency_2",
        ),
        chain_pending_nonce=37,
    )
    execution_2, acquired = repository.claim_signing(execution_2.execution_id)
    assert acquired is True
    repository.persist_signed_transaction(
        execution_2.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION_2,
        signing_claim_generation=execution_2.signing_claim_generation,
    )
    repository.mark_submitted(execution_2.execution_id)
    with pytest.raises(ExecutionConflict, match="transfer|revert"):
        repository.revert(
            execution_2.execution_id,
            receipt_status=0,
            receipt_block_number=100,
            receipt_block_hash="0x" + "98" * 32,
            confirmations=2,
            safe_block_number=100,
            safe_block_hash="0x" + "98" * 32,
            accepted_transfer=True,
            watcher_version="watcher-v1",
            finality_boundary="safe",
        )


def test_find_for_identity_uses_exact_tenant_node_idempotency_tuple(
    repository: ExecutionRepository,
) -> None:
    submitted = _submitted(repository)

    found = repository.find_for_identity(
        tenant_id="tenant_1",
        node_id="node_1",
        idempotency_key="idempotency_1",
    )

    assert found is not None
    assert found.execution_id == submitted.execution_id
    assert (
        repository.find_for_identity(
            tenant_id="tenant_other",
            node_id="node_1",
            idempotency_key="idempotency_1",
        )
        is None
    )
    assert (
        repository.find_for_identity(
            tenant_id="tenant_1",
            node_id="node_other",
            idempotency_key="idempotency_1",
        )
        is None
    )
    assert (
        repository.find_for_identity(
            tenant_id="tenant_1",
            node_id="node_1",
            idempotency_key="idempotency_other",
        )
        is None
    )
