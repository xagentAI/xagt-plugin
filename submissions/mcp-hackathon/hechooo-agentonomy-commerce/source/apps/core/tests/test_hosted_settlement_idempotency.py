from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from services.account_service.repository import AuditEventRow
from test_hosted_settlement import (
    capability as fake_capability,
    finalized_response,
    response_for,
    safely_released_response,
    service_for,
)
from test_task_2b_hosted_routing import (
    BASE,
    _RecordingHostedClient,
    _hosted_settlement_context,
)


def _audit_event_ids(service, reservation_id: str) -> list[str]:
    with service.ledger.sessions() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.payment_id == reservation_id)
        ).all()
    return [event.event_id for event in events]


def test_public_reconcile_replays_finalized_without_second_settlement(
    tmp_path: Path,
) -> None:
    client = _RecordingHostedClient(
        BASE,
        submit_state="submitted",
        recover_state="finalized",
    )
    repository, service, reserved, authorization = _hosted_settlement_context(
        tmp_path,
        network=BASE,
        hosted_clients={BASE: client},
    )

    submitted = service.settle_reservation(reserved["reservation_id"], authorization)
    assert submitted["state"] == "payment_submitted"
    first = service.reconcile_reservation(reserved["reservation_id"])
    assert first["state"] == "settled"
    with service.ledger.transaction() as transaction:
        row_before_reconcile = transaction.get(reserved["reservation_id"])
    receipts_before_reconcile = service._load_latest("receipt")
    audit_before_reconcile = _audit_event_ids(service, reserved["reservation_id"])

    replay = service.reconcile_reservation(reserved["reservation_id"])
    replay_again = service.reconcile_reservation(reserved["reservation_id"])

    assert replay == replay_again == first
    assert len(client.submit_calls) == 1
    assert len(client.recover_calls) == 3
    assert service._load_latest("receipt") == receipts_before_reconcile
    assert (
        _audit_event_ids(service, reserved["reservation_id"]) == audit_before_reconcile
    )
    with service.ledger.transaction() as transaction:
        assert transaction.get(reserved["reservation_id"]) == row_before_reconcile
    grant = repository.spending_grant("grant_1")
    assert grant.used_amount_usdc == 1
    assert grant.reserved_amount_usdc == 0


def test_changed_finalized_evidence_is_rejected_without_mutation() -> None:
    capability = fake_capability()
    service = service_for(capability)
    service._apply_hosted_response(
        capability.reservation_id,
        finalized_response(capability),
    )
    row_before = dict(service.ledger.tx.row)
    events_before = list(service.ledger.tx.events)

    changed = finalized_response(capability).model_copy(
        update={"safe_block_hash": "0x" + "dd" * 32}
    )
    with pytest.raises(ValueError, match="conflict"):
        service._apply_hosted_response(capability.reservation_id, changed)

    assert service.ledger.tx.row == row_before
    assert service.ledger.tx.events == events_before


def test_settled_finalized_replay_requires_stored_execution_identity() -> None:
    capability = fake_capability()
    service = service_for(capability)
    service._apply_hosted_response(
        capability.reservation_id,
        finalized_response(capability),
    )
    service.ledger.tx.row["hosted_execution_id"] = None
    row_before = dict(service.ledger.tx.row)
    events_before = list(service.ledger.tx.events)

    with pytest.raises(ValueError, match="conflict|identity"):
        service._apply_hosted_response(
            capability.reservation_id,
            finalized_response(capability),
        )

    assert service.ledger.tx.row == row_before
    assert service.ledger.tx.events == events_before


def test_pending_response_from_reserved_still_records_submission() -> None:
    capability = fake_capability()
    service = service_for(capability, state="spending_reserved")

    result = service._apply_hosted_response(
        capability.reservation_id,
        response_for(capability, state="submitted"),
    )

    assert result["state"] == "payment_submitted"
    assert result["budget_accounting_state"] == "reserved"
    assert result["reconciliation_status"] == "pending"
    assert result["next_action"] == "reconcile_hosted_execution"


def test_released_response_from_reserved_still_releases_budget() -> None:
    capability = fake_capability()
    service = service_for(capability, state="spending_reserved")

    result = service._apply_hosted_response(
        capability.reservation_id,
        safely_released_response(capability),
    )

    assert result["state"] == "released"
    assert result["budget_accounting_state"] == "released"
    assert result["next_action"] == "terminal"
    assert service.ledger.tx.events.count("release") == 1


def test_settled_response_can_enter_reorg_review() -> None:
    capability = fake_capability()
    service = service_for(capability)
    settled = service._apply_hosted_response(
        capability.reservation_id,
        finalized_response(capability),
    )
    settle_count = service.ledger.tx.events.count("settle")

    reorg = response_for(
        capability,
        state="reorg_review",
        receipt_block_hash="0x" + "bb" * 32,
        receipt_block_number=100,
        safe_block_hash="0x" + "cc" * 32,
        safe_block_number=102,
        confirmations=3,
        confirmed_at=101,
        reorg_reviewed_at=102,
        failure_reason_code="REORG_DETECTED",
        finality_boundary="safe",
    )
    result = service._apply_hosted_response(capability.reservation_id, reorg)

    assert settled["state"] == "settled"
    assert result["state"] == "reorg_review"
    assert result["budget_accounting_state"] == "settled"
    assert result["receipt"] == settled["receipt"]
    assert service.ledger.tx.events.count("settle") == settle_count
    assert service.ledger.tx.events.count("reorg") == 1


@pytest.mark.parametrize(
    "state",
    ["submitted", "confirmed", "submission_rejected", "rejected", "released"],
)
def test_settled_response_rejects_late_non_reorg_state_without_mutation(
    state: str,
) -> None:
    capability = fake_capability()
    service = service_for(capability)
    service._apply_hosted_response(
        capability.reservation_id,
        finalized_response(capability),
    )
    row_before = dict(service.ledger.tx.row)
    events_before = list(service.ledger.tx.events)

    if state == "confirmed":
        response = response_for(
            capability,
            state=state,
            receipt_block_hash="0x" + "bb" * 32,
            receipt_block_number=100,
            safe_block_hash="0x" + "cc" * 32,
            safe_block_number=102,
            confirmations=1,
            confirmed_at=101,
            finality_boundary="safe",
        )
    elif state == "submission_rejected":
        response = response_for(
            capability,
            state=state,
            failure_reason_code="RPC_REJECTED",
        )
    elif state == "rejected":
        response = response_for(
            capability,
            state=state,
            transaction_hash=None,
            submitted_at=None,
            failure_reason_code="REJECTED",
        )
    elif state == "released":
        response = safely_released_response(capability)
    else:
        response = response_for(capability, state=state)

    with pytest.raises(ValueError, match="regress|conflict"):
        service._apply_hosted_response(
            capability.reservation_id,
            response,
        )

    assert service.ledger.tx.row == row_before
    assert service.ledger.tx.events == events_before
