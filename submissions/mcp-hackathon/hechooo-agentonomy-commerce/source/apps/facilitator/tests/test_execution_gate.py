from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from execution_models import BASE_CHAIN, BASE_USDC, ExecutionIntent, ExecutionState
from execution_repository import (
    ExecutionConflict,
    ExecutionRepository,
    HostedExecutionBase,
    HostedGateEventRow,
    HostedGateReservationRow,
    SIGNING_CLAIM_LEASE_SECONDS,
)
from pilot_gate import PilotGateDenied, PilotGatePolicy


NOW = 2_000_000_000
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
RELAYER = "0x" + "44" * 20
SIGNATURE = bytes.fromhex("aa" * 65)
RAW_TRANSACTION = bytes.fromhex(
    "02e48221058001028252089433333333333333333333333333333333333333338080c0800101"
)


def policy(**updates: int) -> PilotGatePolicy:
    values = {
        "max_in_flight_per_node": 10,
        "max_accepted_per_node_utc_day": 50,
        "max_accepted_per_node_lifetime": 250,
        "max_gas_usd_micros_per_node_utc_day": 1_000_000,
        "max_gas_usd_micros_platform_utc_day": 100_000_000,
        "native_asset_usd_price_ceiling_micros": 4_000_000_000,
    }
    values.update(updates)
    return PilotGatePolicy(**values)


def intent(number: int, *, node_id: str = "node_1", deadline: int | None = None) -> ExecutionIntent:
    byte = f"{number % 256:02x}"
    return ExecutionIntent(
        tenant_id="tenant_1",
        node_id=node_id,
        wallet_binding_id=f"binding_{number}",
        capability_id=f"capability_{number}",
        reservation_id=f"reservation_{number}",
        purchase_id=f"purchase_{number}",
        request_id=f"request_{number}",
        request_hash="0x" + byte * 32,
        idempotency_key=f"idempotency_{number}",
        chain=BASE_CHAIN,
        owner=OWNER,
        payee=PAYEE,
        token=BASE_USDC,
        amount_atomic="1000000",
        executor=EXECUTOR,
        signer_epoch=1,
        owner_nonce=number,
        deadline=NOW + 60 if deadline is None else deadline,
        capability_hash="0x" + f"{(number + 1) % 256:02x}" * 32,
        reservation_hash="0x" + f"{(number + 2) % 256:02x}" * 32,
        execution_scope_hash="0x" + f"{(number + 3) % 256:02x}" * 32,
        execution_digest="0x" + f"{(number + 4) % 256:02x}" * 32,
        relayer_address=RELAYER,
    )


def repository(tmp_path, configured: PilotGatePolicy) -> ExecutionRepository:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'hosted-gate.sqlite3'}",
        pilot_policy=configured,
    )


def submitted(repo: ExecutionRepository, number: int):
    execution = repo.allocate_or_return(intent(number), chain_pending_nonce=number, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.claim_submission(execution.execution_id, now=NOW)
    return repo.mark_submitted(execution.execution_id, now=NOW)


def test_metadata_declares_pilot_gate_contract() -> None:
    names = set(HostedExecutionBase.metadata.tables)
    assert {
        "hosted_gate_controls",
        "hosted_gate_reservations",
        "hosted_gate_events",
    } <= names
    ddl = "\n".join(
        str(
            CreateTable(HostedExecutionBase.metadata.tables[name]).compile(
                dialect=postgresql.dialect()
            )
        )
        for name in names
        if name.startswith("hosted_gate_")
    )
    assert "ck_hosted_gate_control_scope_type" in ddl
    assert "ck_hosted_gate_control_scope_shape" in ddl
    assert "ck_hosted_gate_reservation_state" in ddl
    assert "ck_hosted_gate_event_type" in ddl


@pytest.mark.parametrize(
    ("scope_type", "tenant_id", "node_id", "reason_code"),
    [
        ("platform", "", "", "platform_paused"),
        ("tenant", "tenant_1", "", "tenant_paused"),
        ("node", "tenant_1", "node_1", "node_paused"),
    ],
)
def test_persistent_pause_blocks_preflight_and_allocation(
    tmp_path,
    scope_type: str,
    tenant_id: str,
    node_id: str,
    reason_code: str,
) -> None:
    repo = repository(tmp_path, policy())
    repo.set_pilot_pause(
        scope_type=scope_type,
        tenant_id=tenant_id,
        node_id=node_id,
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )

    with pytest.raises(PilotGateDenied, match=reason_code) as preflight_error:
        repo.assert_pilot_gate_open(tenant_id="tenant_1", node_id="node_1", now=NOW)
    assert preflight_error.value.reason_code == reason_code
    with pytest.raises(PilotGateDenied, match=reason_code):
        repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)

    repo.set_pilot_pause(
        scope_type=scope_type,
        tenant_id=tenant_id,
        node_id=node_id,
        paused=False,
        reason_code="operator_resume",
        now=NOW + 1,
    )
    created = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW + 1)
    assert created.node_id == "node_1"


def test_early_pause_checks_do_not_amplify_persistent_audit_events(tmp_path) -> None:
    repo = repository(tmp_path, policy())
    repo.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW,
    )

    for offset in (1, 2):
        with pytest.raises(PilotGateDenied, match="platform_paused"):
            repo.assert_pilot_gate_open(
                tenant_id="tenant_1",
                node_id="node_1",
                now=NOW + offset,
            )

    with repo.sessions() as session:
        events = list(
            session.scalars(
                select(HostedGateEventRow).order_by(HostedGateEventRow.created_at)
            )
        )
    assert [(event.event_type, event.reason_code) for event in events] == [
        ("pause_changed", "operator_pause")
    ]


def test_in_flight_limit_is_atomic_and_replay_does_not_consume_again(tmp_path) -> None:
    repo = repository(tmp_path, policy(max_in_flight_per_node=2))
    first = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    second = repo.allocate_or_return(intent(2), chain_pending_nonce=2, now=NOW)
    replay = repo.allocate_or_return(intent(1), chain_pending_nonce=99, now=NOW)
    assert replay.execution_id == first.execution_id

    with pytest.raises(PilotGateDenied) as denied:
        repo.allocate_or_return(intent(3), chain_pending_nonce=3, now=NOW)
    assert denied.value.reason_code == "node_in_flight_limit"

    repo.release_expired(first.execution_id, now=NOW + 61)
    third = repo.allocate_or_return(intent(3), chain_pending_nonce=3, now=NOW + 61)
    assert third.execution_id not in {first.execution_id, second.execution_id}


def test_early_gate_check_only_blocks_pauses_not_idempotent_quota_replays(
    tmp_path,
) -> None:
    repo = repository(tmp_path, policy(max_in_flight_per_node=1))
    repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)

    repo.assert_pilot_gate_open(
        tenant_id="tenant_1",
        node_id="node_1",
        now=NOW,
    )

    with pytest.raises(PilotGateDenied) as denied:
        repo.allocate_or_return(intent(2), chain_pending_nonce=2, now=NOW)
    assert denied.value.reason_code == "node_in_flight_limit"


def test_allocation_rechecks_exact_replay_after_acquiring_gate_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path, policy(max_in_flight_per_node=1))
    payment_intent = intent(1)
    existing = repo.allocate_or_return(
        payment_intent,
        chain_pending_nonce=1,
        now=NOW,
    )
    original_lookup = repo._existing_for_intent
    lookup_count = 0

    def simulate_race(session, replay_intent):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        return original_lookup(session, replay_intent)

    monkeypatch.setattr(repo, "_existing_for_intent", simulate_race)

    replay = repo.allocate_or_return(
        payment_intent,
        chain_pending_nonce=99,
        now=NOW,
    )

    assert lookup_count == 2
    assert replay.execution_id == existing.execution_id


def test_daily_and_lifetime_counts_remain_consumed_after_safe_release(tmp_path) -> None:
    daily_repo = repository(
        tmp_path / "daily",
        policy(max_in_flight_per_node=10, max_accepted_per_node_utc_day=2),
    )
    first = daily_repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    second = daily_repo.allocate_or_return(intent(2), chain_pending_nonce=2, now=NOW)
    daily_repo.release_expired(first.execution_id, now=NOW + 61)
    daily_repo.release_expired(second.execution_id, now=NOW + 61)
    with pytest.raises(PilotGateDenied) as daily_denied:
        daily_repo.allocate_or_return(intent(3), chain_pending_nonce=3, now=NOW + 62)
    assert daily_denied.value.reason_code == "node_daily_limit"

    lifetime_repo = repository(
        tmp_path / "lifetime",
        policy(
            max_in_flight_per_node=10,
            max_accepted_per_node_utc_day=10,
            max_accepted_per_node_lifetime=2,
        ),
    )
    first = lifetime_repo.allocate_or_return(intent(11), chain_pending_nonce=1, now=NOW)
    second = lifetime_repo.allocate_or_return(intent(12), chain_pending_nonce=2, now=NOW)
    lifetime_repo.release_expired(first.execution_id, now=NOW + 61)
    lifetime_repo.release_expired(second.execution_id, now=NOW + 61)
    with pytest.raises(PilotGateDenied) as lifetime_denied:
        lifetime_repo.allocate_or_return(
            intent(13, deadline=NOW + 86_500),
            chain_pending_nonce=3,
            now=NOW + 86_400,
        )
    assert lifetime_denied.value.reason_code == "node_lifetime_limit"


def test_gas_budget_is_reserved_idempotently_and_fail_closed(tmp_path) -> None:
    repo = repository(
        tmp_path,
        policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=150,
        ),
    )
    one = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    one, acquired = repo.claim_signing(one.execution_id, now=NOW)
    assert acquired is True
    assert repo.reserve_pilot_gas(
        one.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=one.signing_claim_generation,
        now=NOW,
    ) == 100
    assert repo.reserve_pilot_gas(
        one.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=one.signing_claim_generation,
        now=NOW,
    ) == 100

    two = repo.allocate_or_return(intent(2, node_id="node_2"), chain_pending_nonce=2, now=NOW)
    two, acquired = repo.claim_signing(two.execution_id, now=NOW)
    assert acquired is True
    assert repo.reserve_pilot_gas(
        two.execution_id,
        gas_cost_usd_micros=50,
        signing_claim_generation=two.signing_claim_generation,
        now=NOW,
    ) == 50

    with pytest.raises(PilotGateDenied) as platform_denied:
        repo.reserve_pilot_gas(
            two.execution_id,
            gas_cost_usd_micros=51,
            signing_claim_generation=two.signing_claim_generation,
            now=NOW,
        )
    assert platform_denied.value.reason_code == "platform_daily_gas_limit"

    with pytest.raises(PilotGateDenied) as node_denied:
        repo.reserve_pilot_gas(
            one.execution_id,
            gas_cost_usd_micros=101,
            signing_claim_generation=one.signing_claim_generation,
            now=NOW,
        )
    assert node_denied.value.reason_code == "node_daily_gas_limit"


def test_gas_budget_is_charged_to_signing_day_not_admission_day(tmp_path) -> None:
    day_start = (NOW // 86_400) * 86_400
    admitted_at = day_start + 86_390
    signed_at = day_start + 86_410
    repo = repository(
        tmp_path,
        policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    first = repo.allocate_or_return(
        intent(1, deadline=signed_at + 60),
        chain_pending_nonce=1,
        now=admitted_at,
    )
    first, acquired = repo.claim_signing(first.execution_id, now=signed_at)
    assert acquired is True
    repo.reserve_pilot_gas(
        first.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=first.signing_claim_generation,
        now=signed_at,
    )

    second = repo.allocate_or_return(
        intent(2, deadline=signed_at + 60),
        chain_pending_nonce=2,
        now=signed_at,
    )
    second, acquired = repo.claim_signing(second.execution_id, now=signed_at)
    assert acquired is True
    with pytest.raises(PilotGateDenied) as denied:
        repo.reserve_pilot_gas(
            second.execution_id,
            gas_cost_usd_micros=1,
            signing_claim_generation=second.signing_claim_generation,
            now=signed_at,
        )

    assert denied.value.reason_code == "node_daily_gas_limit"
    with repo.sessions() as session:
        reservation = session.get(HostedGateReservationRow, first.execution_id)
        assert reservation is not None
        assert reservation.utc_day == admitted_at // 86_400
        assert reservation.gas_utc_day == signed_at // 86_400


def test_safe_release_clears_gas_reservation_but_keeps_admission_audit(tmp_path) -> None:
    repo = repository(tmp_path, policy())
    execution = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )

    repo.release_expired(execution.execution_id, now=NOW + 61)

    with repo.sessions() as session:
        reservation = session.get(HostedGateReservationRow, execution.execution_id)
        assert reservation is not None
        assert reservation.state == "released"
        assert reservation.gas_cost_usd_micros == 0
        events = list(
            session.scalars(
                select(HostedGateEventRow).where(
                    HostedGateEventRow.execution_id == execution.execution_id
                )
            ).all()
        )
    assert [event.event_type for event in events] == [
        "allowed",
        "gas_reserved",
        "released",
    ]


def test_signed_transaction_requires_a_durable_gas_reservation(tmp_path) -> None:
    repo = repository(tmp_path, policy())
    execution = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True

    with pytest.raises(ExecutionConflict, match="gas.*reservation"):
        repo.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=RAW_TRANSACTION,
            signing_claim_generation=execution.signing_claim_generation,
            now=NOW,
        )

    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    signed = repo.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    assert signed.raw_transaction is not None


def test_stale_signing_claim_cannot_replace_the_new_workers_gas_reservation(
    tmp_path,
) -> None:
    repo = repository(tmp_path, policy())
    execution = repo.allocate_or_return(
        intent(1, deadline=NOW + SIGNING_CLAIM_LEASE_SECONDS + 10),
        chain_pending_nonce=1,
        now=NOW,
    )
    first, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    recovered, acquired = repo.claim_signing(
        execution.execution_id,
        now=NOW + SIGNING_CLAIM_LEASE_SECONDS,
    )
    assert acquired is True

    with pytest.raises(ExecutionConflict, match="signing claim"):
        repo.reserve_pilot_gas(
            execution.execution_id,
            gas_cost_usd_micros=1234,
            signing_claim_generation=first.signing_claim_generation,
            now=NOW + SIGNING_CLAIM_LEASE_SECONDS,
        )

    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=recovered.signing_claim_generation,
        now=NOW + SIGNING_CLAIM_LEASE_SECONDS,
    )


def test_pause_after_gas_reservation_blocks_signed_transaction_persistence(
    tmp_path,
) -> None:
    repo = repository(tmp_path, policy())
    execution = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW + 1,
    )

    with pytest.raises(PilotGateDenied) as denied:
        repo.persist_signed_transaction(
            execution.execution_id,
            signature=SIGNATURE,
            raw_transaction=RAW_TRANSACTION,
            signing_claim_generation=execution.signing_claim_generation,
            now=NOW + 1,
        )

    assert denied.value.reason_code == "platform_paused"
    stored = repo.get_execution(execution.execution_id)
    assert stored is not None
    assert stored.status.value == "signing"
    assert stored.signature is None
    assert stored.raw_transaction is None


def test_pause_blocks_explicit_rebroadcast_without_mutating_attempts(tmp_path) -> None:
    repo = repository(tmp_path, policy())
    execution = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=1234,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.claim_submission(execution.execution_id, now=NOW)
    repo.set_pilot_pause(
        scope_type="platform",
        paused=True,
        reason_code="operator_pause",
        now=NOW + 1,
    )

    with pytest.raises(PilotGateDenied) as denied:
        repo.rebroadcast_raw_transaction(execution.execution_id, now=NOW + 1)

    assert denied.value.reason_code == "platform_paused"
    stored = repo.get_execution(execution.execution_id)
    assert stored is not None
    assert stored.broadcast_attempts == 1


def test_cross_day_rebroadcast_fails_closed_when_new_day_gas_is_full(tmp_path) -> None:
    next_day = ((NOW // 86_400) + 1) * 86_400 + 1
    repo = repository(
        tmp_path,
        policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    old = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    old, acquired = repo.claim_signing(old.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        old.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=old.signing_claim_generation,
        now=NOW,
    )
    repo.persist_signed_transaction(
        old.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=old.signing_claim_generation,
        now=NOW,
    )
    repo.claim_submission(old.execution_id, now=NOW)
    repo.mark_submission_rejected(
        old.execution_id,
        reason_code="insufficient_funds",
        now=NOW,
    )

    current = repo.allocate_or_return(
        intent(2, deadline=next_day + 60),
        chain_pending_nonce=2,
        now=next_day,
    )
    current, acquired = repo.claim_signing(current.execution_id, now=next_day)
    assert acquired is True
    repo.reserve_pilot_gas(
        current.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=current.signing_claim_generation,
        now=next_day,
    )

    with pytest.raises(PilotGateDenied) as denied:
        repo.rebroadcast_raw_transaction(old.execution_id, now=next_day)

    assert denied.value.reason_code == "node_daily_gas_limit"
    stored = repo.get_execution(old.execution_id)
    assert stored is not None
    assert stored.broadcast_attempts == 1
    with repo.sessions() as session:
        reservation = session.get(HostedGateReservationRow, old.execution_id)
        assert reservation is not None
        assert reservation.gas_utc_day == NOW // 86_400


def test_cross_day_first_submission_rechecks_current_day_gas_budget(tmp_path) -> None:
    next_day = ((NOW // 86_400) + 1) * 86_400 + 1
    repo = repository(
        tmp_path,
        policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    old = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    old, acquired = repo.claim_signing(old.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        old.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=old.signing_claim_generation,
        now=NOW,
    )
    repo.persist_signed_transaction(
        old.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=old.signing_claim_generation,
        now=NOW,
    )

    current = repo.allocate_or_return(
        intent(2, deadline=next_day + 60),
        chain_pending_nonce=2,
        now=next_day,
    )
    current, acquired = repo.claim_signing(current.execution_id, now=next_day)
    assert acquired is True
    repo.reserve_pilot_gas(
        current.execution_id,
        gas_cost_usd_micros=100,
        signing_claim_generation=current.signing_claim_generation,
        now=next_day,
    )

    with pytest.raises(PilotGateDenied) as denied:
        repo.claim_submission(old.execution_id, now=next_day)

    assert denied.value.reason_code == "node_daily_gas_limit"
    stored = repo.get_execution(old.execution_id)
    assert stored is not None
    assert stored.status.value == "signed"
    assert stored.broadcast_attempts == 0
    with repo.sessions() as session:
        reservation = session.get(HostedGateReservationRow, old.execution_id)
        assert reservation is not None
        assert reservation.gas_utc_day == NOW // 86_400


def test_cross_day_rebroadcast_moves_existing_gas_charge_to_current_day(tmp_path) -> None:
    next_day = ((NOW // 86_400) + 1) * 86_400 + 1
    repo = repository(
        tmp_path,
        policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    execution = repo.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = repo.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    repo.reserve_pilot_gas(
        execution.execution_id,
        gas_cost_usd_micros=40,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    repo.claim_submission(execution.execution_id, now=NOW)
    repo.mark_submission_rejected(
        execution.execution_id,
        reason_code="insufficient_funds",
        now=NOW,
    )

    assert repo.rebroadcast_raw_transaction(execution.execution_id, now=next_day) == RAW_TRANSACTION

    with repo.sessions() as session:
        reservation = session.get(HostedGateReservationRow, execution.execution_id)
        assert reservation is not None
        assert reservation.gas_cost_usd_micros == 40
        assert reservation.gas_utc_day == next_day // 86_400
        events = list(
            session.scalars(
                select(HostedGateEventRow).where(
                    HostedGateEventRow.execution_id == execution.execution_id
                )
            ).all()
        )
    assert [(event.event_type, event.reason_code) for event in events][-1] == (
        "gas_reserved",
        "gas_budget_reassigned",
    )


def test_migrated_signed_execution_gets_conservative_gas_charge_before_broadcast(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migrated.sqlite3'}"
    legacy = ExecutionRepository(database_url)
    execution = legacy.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = legacy.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    legacy.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    with legacy.sessions() as session:
        session.add(
            HostedGateReservationRow(
                execution_id=execution.execution_id,
                tenant_id="tenant_1",
                node_id="node_1",
                idempotency_key="idempotency_1",
                utc_day=NOW // 86_400,
                state="reserved",
                gas_cost_usd_micros=0,
                gas_utc_day=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    legacy.close()

    repo = ExecutionRepository(
        database_url,
        pilot_policy=policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    submitted, claimed = repo.claim_submission(execution.execution_id, now=NOW)

    assert claimed is True
    assert submitted.status.value == "submission_unknown"
    with repo.sessions() as session:
        gate = session.get(HostedGateReservationRow, execution.execution_id)
        assert gate is not None
        assert gate.gas_cost_usd_micros == 100
        assert gate.gas_utc_day == NOW // 86_400


def test_migrated_unknown_execution_gets_conservative_gas_charge_before_rebroadcast(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migrated-unknown.sqlite3'}"
    legacy = ExecutionRepository(database_url)
    execution = legacy.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = legacy.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    legacy.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    legacy.claim_submission(execution.execution_id, now=NOW)
    with legacy.sessions() as session:
        session.add(
            HostedGateReservationRow(
                execution_id=execution.execution_id,
                tenant_id="tenant_1",
                node_id="node_1",
                idempotency_key="idempotency_1",
                utc_day=NOW // 86_400,
                state="reserved",
                gas_cost_usd_micros=0,
                gas_utc_day=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    legacy.close()

    repo = ExecutionRepository(
        database_url,
        pilot_policy=policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=1_000,
        ),
    )
    raw = repo.rebroadcast_raw_transaction(execution.execution_id, now=NOW)

    assert raw == RAW_TRANSACTION
    with repo.sessions() as session:
        gate = session.get(HostedGateReservationRow, execution.execution_id)
        assert gate is not None
        assert gate.gas_cost_usd_micros == 100
        assert gate.gas_utc_day == NOW // 86_400


def test_migrated_unknown_rebroadcast_fails_closed_when_gas_budget_is_too_low(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migrated-denied.sqlite3'}"
    legacy = ExecutionRepository(database_url)
    execution = legacy.allocate_or_return(intent(1), chain_pending_nonce=1, now=NOW)
    execution, acquired = legacy.claim_signing(execution.execution_id, now=NOW)
    assert acquired is True
    legacy.persist_signed_transaction(
        execution.execution_id,
        signature=SIGNATURE,
        raw_transaction=RAW_TRANSACTION,
        signing_claim_generation=execution.signing_claim_generation,
        now=NOW,
    )
    legacy.claim_submission(execution.execution_id, now=NOW)
    with legacy.sessions() as session:
        session.add(
            HostedGateReservationRow(
                execution_id=execution.execution_id,
                tenant_id="tenant_1",
                node_id="node_1",
                idempotency_key="idempotency_1",
                utc_day=NOW // 86_400,
                state="reserved",
                gas_cost_usd_micros=0,
                gas_utc_day=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    legacy.close()

    repo = ExecutionRepository(
        database_url,
        pilot_policy=policy(
            max_gas_usd_micros_per_node_utc_day=100,
            max_gas_usd_micros_platform_utc_day=99,
        ),
    )
    with pytest.raises(PilotGateDenied) as denied:
        repo.rebroadcast_raw_transaction(execution.execution_id, now=NOW)

    assert denied.value.reason_code == "platform_daily_gas_limit"
    stored = repo.get_execution(execution.execution_id)
    assert stored is not None
    assert stored.broadcast_attempts == 1


def test_finalized_and_reverted_executions_settle_gate_without_refunding_gas(
    tmp_path,
) -> None:
    repo = repository(tmp_path, policy())
    successful = submitted(repo, 1)
    confirmed = repo.confirm(
        successful.execution_id,
        receipt_status=1,
        receipt_block_number=100,
        receipt_block_hash="0x" + "99" * 32,
        confirmations=2,
        safe_block_number=100,
        safe_block_hash="0x" + "99" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
    )
    repo.finalize(confirmed.execution_id, finality_boundary="safe", now=NOW + 1)

    reverted_execution = submitted(repo, 2)
    repo.revert(
        reverted_execution.execution_id,
        receipt_status=0,
        receipt_block_number=101,
        receipt_block_hash="0x" + "98" * 32,
        confirmations=2,
        safe_block_number=101,
        safe_block_hash="0x" + "98" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
    )

    with repo.sessions() as session:
        finalized_gate = session.get(
            HostedGateReservationRow, successful.execution_id
        )
        reverted_gate = session.get(
            HostedGateReservationRow, reverted_execution.execution_id
        )
        assert finalized_gate is not None and finalized_gate.state == "settled"
        assert reverted_gate is not None and reverted_gate.state == "settled"
        assert finalized_gate.gas_cost_usd_micros == 1234
        assert reverted_gate.gas_cost_usd_micros == 1234


def test_reverted_gate_releases_once_after_watcher_release_proof(tmp_path) -> None:
    repo = repository(tmp_path, policy())
    execution = submitted(repo, 3)
    repo.revert(
        execution.execution_id,
        receipt_status=0,
        receipt_block_number=101,
        receipt_block_hash="0x" + "98" * 32,
        confirmations=2,
        safe_block_number=101,
        safe_block_hash="0x" + "98" * 32,
        accepted_transfer=False,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        now=NOW + 1,
    )
    release_evidence = {
        "receipt_status": 0,
        "canonical_receipt": True,
        "finality_boundary_timestamp": execution.deadline,
        "capability_used": False,
        "owner_nonce_used": False,
        "payment_event_found": False,
        "transfer_event_found": False,
    }

    released = repo.release_reverted(
        execution.execution_id,
        receipt_status=0,
        receipt_block_number=101,
        receipt_block_hash="0x" + "98" * 32,
        confirmations=2,
        safe_block_number=101,
        safe_block_hash="0x" + "98" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence=release_evidence,
        now=execution.deadline,
    )
    replay = repo.release_reverted(
        execution.execution_id,
        receipt_status=0,
        receipt_block_number=101,
        receipt_block_hash="0x" + "98" * 32,
        confirmations=2,
        safe_block_number=101,
        safe_block_hash="0x" + "98" * 32,
        watcher_version="watcher-v1",
        finality_boundary="safe",
        release_evidence=release_evidence,
        now=execution.deadline + 1,
    )

    assert released.status is ExecutionState.RELEASED
    assert replay.released_at == released.released_at
    with repo.sessions() as session:
        gate = session.get(HostedGateReservationRow, execution.execution_id)
        assert gate is not None
        assert gate.state == "released"
        assert gate.gas_cost_usd_micros == 1234
        events = session.scalars(
            select(HostedGateEventRow).where(
                HostedGateEventRow.execution_id == execution.execution_id,
                HostedGateEventRow.event_type == "released",
            )
        ).all()
        assert len(events) == 1


def test_concurrent_allocation_cannot_cross_node_limit(tmp_path) -> None:
    repo = repository(tmp_path, policy(max_in_flight_per_node=1))

    def allocate(number: int) -> str:
        try:
            return repo.allocate_or_return(
                intent(number), chain_pending_nonce=number, now=NOW
            ).execution_id
        except PilotGateDenied as exc:
            return exc.reason_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(allocate, (1, 2)))

    assert sum(result.startswith("exec_") for result in results) == 1
    assert results.count("node_in_flight_limit") == 1
