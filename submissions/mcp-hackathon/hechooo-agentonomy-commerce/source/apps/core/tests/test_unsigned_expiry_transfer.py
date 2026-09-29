from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from services.funding_service.ledger import FundingTransaction
from test_direct_transfer_hosted import hosted_context
from test_direct_transfer_service import command
from test_task_2b_hosted_routing import _execution_response


UNSIGNED_EXPIRY = "UNSIGNED_EXECUTION_EXPIRED"


def _unsigned_expiry_response(request, *, server_key_id="server-key", **updates):
    """Build a no-transaction Hosted expiry projection for one prepared request."""

    deadline = request.envelope.expires_at
    # The current shared fixture does not yet construct the dedicated expired
    # shape directly. Start from a valid submitted response, then replace its
    # outcome fields with the no-transaction expiry projection. The consumer
    # re-validates this payload at the Core boundary.
    response = _execution_response(request, state="submitted")
    values = {
        "state": "expired",
        "transaction_hash": None,
        "receipt_block_hash": None,
        "receipt_block_number": None,
        "safe_block_hash": None,
        "safe_block_number": None,
        "confirmations": 0,
        "failure_reason_code": UNSIGNED_EXPIRY,
        "submitted_at": None,
        "confirmed_at": None,
        "finalized_at": None,
        "reverted_at": None,
        "reorg_reviewed_at": None,
        "released_at": None,
        "expired_at": deadline,
        "watcher_version": None,
        "finality_boundary": None,
        "release_evidence": None,
        "server_key_id": server_key_id,
        # The execution creation time is semantic proof and must not rotate.
        "issued_at": request.envelope.issued_at,
    }
    values.update(updates)
    return response.model_copy(update=values)


def _stage_submission_unknown(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(
        tmp_path, monkeypatch, submit_unknown=True
    )
    initial = service.create(command())
    assert initial["status"] == "pending", initial
    assert len(client.submit_calls) == 1
    prepared = client.submit_calls[0]
    now = datetime.fromtimestamp(prepared.envelope.expires_at + 5, UTC)
    service.clock = lambda: now
    funding._utc_now = lambda: now.replace(tzinfo=None)
    return service, funding, repo, client, prepared, now


def _install_recovery_reply(monkeypatch, client, reply):
    def recover_by_idempotency(request):
        client.lookup_calls.append(request)
        return reply(request)

    monkeypatch.setattr(client, "recover_by_idempotency", recover_by_idempotency)


def _unsigned_audits(repo):
    return [
        event
        for event in repo.audit_events(user_id="u", agent_id="hermes")
        if event["event_type"] == "hosted_unsigned_expiry_evidence_recorded"
    ]


def test_direct_transfer_unsigned_expiry_releases_real_budget_once(tmp_path, monkeypatch):
    service, funding, repo, client, prepared, now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )
    _install_recovery_reply(
        monkeypatch,
        client,
        lambda request: _unsigned_expiry_response(request),
    )

    reservation_id = service._reservation(
        "transfer_" + service._hash(["u", "hermes", "test-1"])[:48]
    )
    assert reservation_id is not None
    reservation_id = reservation_id["reservation_id"]
    before_daily = repo.spending_grant_daily_usage(
        "grant_1",
        datetime.fromisoformat(funding.get_reservation(reservation_id)["usage_date"]).date(),
    )
    before_hourly = repo.spending_grant_rolling_hour_usage("grant_1", now)
    assert before_daily == (Decimal("0"), Decimal("2"))
    assert before_hourly == (Decimal("0"), Decimal("2"))

    released = service.create(command())
    fetched = service.get(released["transfer_id"], user_id="u", agent_id="hermes")
    replay = service.create(command())

    assert released["status"] == fetched["status"] == replay["status"] == "failed"
    assert released["reason_code"] == fetched["reason_code"] == replay["reason_code"] == UNSIGNED_EXPIRY
    assert released["next_action"] == fetched["next_action"] == replay["next_action"] == "none"
    assert len(client.submit_calls) == 1
    assert len(client.lookup_calls) == 1

    row = funding.get_reservation(released["reservation_id"])
    assert row["state"] == "released"
    assert row["budget_accounting_state"] == "released"
    assert row["reconciliation_status"] == "failed"
    assert row["next_action"] == "terminal"
    assert row["release_reason"] == UNSIGNED_EXPIRY
    assert row["tx_hash"] is None
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("0")
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("0")
    assert repo.spending_grant_daily_usage(
        "grant_1", datetime.fromisoformat(row["usage_date"]).date()
    ) == (Decimal("0"), Decimal("0"))
    assert repo.spending_grant_rolling_hour_usage("grant_1", now) == (
        Decimal("0"),
        Decimal("0"),
    )
    evidence = row["hosted_unsigned_expiry_evidence"]
    assert evidence["issued_at"] == prepared.envelope.issued_at
    assert "server_key_id" not in evidence
    assert len(_unsigned_audits(repo)) == 1


def test_direct_transfer_unsigned_expiry_replay_allows_server_key_rotation(tmp_path, monkeypatch):
    service, funding, repo, client, prepared, _now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )
    _install_recovery_reply(
        monkeypatch,
        client,
        lambda request: _unsigned_expiry_response(request),
    )
    released = service.create(command())
    original = funding.get_reservation(released["reservation_id"])

    rotated = _unsigned_expiry_response(prepared, server_key_id="rotated-key")
    replayed = funding._apply_hosted_response(released["reservation_id"], rotated)

    assert replayed == original
    assert funding.get_reservation(released["reservation_id"])[
        "hosted_unsigned_expiry_evidence"
    ] == original["hosted_unsigned_expiry_evidence"]
    assert len(client.submit_calls) == 1
    assert len(_unsigned_audits(repo)) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to_address", "0x" + "4" * 40),
        ("amount_atomic", "3000000"),
        ("reservation_id", "reservation_other"),
    ],
)
def test_direct_transfer_unsigned_expiry_scope_conflict_never_releases(
    tmp_path, monkeypatch, field, value
):
    service, funding, repo, client, _prepared, _now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )

    def conflicting_reply(request):
        updates = {}
        if field == "to_address":
            updates["payee"] = value
        elif field == "amount_atomic":
            updates[field] = value
        else:
            updates[field] = value
        return _unsigned_expiry_response(request, **updates)

    _install_recovery_reply(monkeypatch, client, conflicting_reply)
    result = service.create(command())

    assert result["status"] != "failed"
    row = funding.get_reservation(result["reservation_id"])
    assert row["state"] == "spending_reserved"
    assert row["budget_accounting_state"] == "reserved"
    assert row.get("hosted_unsigned_expiry_evidence") is None
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("0")
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert _unsigned_audits(repo) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tx_hash", "0x" + "ab" * 32),
        ("receipt_id", "receipt_prior"),
        ("receipt", {"status": "settled"}),
        ("hosted_watcher_evidence", {"state": "reverted"}),
    ],
)
def test_direct_transfer_unsigned_expiry_known_prior_evidence_never_releases(
    tmp_path, monkeypatch, field, value
):
    service, funding, repo, client, _prepared, _now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )
    transfer_id = "transfer_" + service._hash(["u", "hermes", "test-1"])[:48]
    reservation = funding.get_reservation(
        service._reservation(transfer_id)["reservation_id"]
    )
    if field == "tx_hash":
        with funding.ledger.transaction() as tx:
            tx.put(
                "reservation",
                reservation["reservation_id"],
                {**reservation, field: value},
                purchase_id=reservation["purchase_id"],
                idempotency_key=reservation["idempotency_key"],
                action_id=reservation["action_id"],
                policy_decision_id=reservation["policy_decision_id"],
                reservation_id=reservation["reservation_id"],
                tx_hash=value,
            )
    else:
        with funding.ledger.transaction() as tx:
            tx.put(
                "reservation",
                reservation["reservation_id"],
                {**reservation, field: value},
                purchase_id=reservation["purchase_id"],
                idempotency_key=reservation["idempotency_key"],
                action_id=reservation["action_id"],
                policy_decision_id=reservation["policy_decision_id"],
                reservation_id=reservation["reservation_id"],
            )
    _install_recovery_reply(
        monkeypatch,
        client,
        lambda request: _unsigned_expiry_response(request),
    )

    result = service.create(command())

    assert result["status"] != "failed"
    row = funding.get_reservation(reservation["reservation_id"])
    assert row["budget_accounting_state"] == "reserved"
    assert row.get("hosted_unsigned_expiry_evidence") is None
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert _unsigned_audits(repo) == []


def test_direct_transfer_generic_expiry_requires_operator_review(tmp_path, monkeypatch):
    service, funding, repo, client, _prepared, _now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )
    _install_recovery_reply(
        monkeypatch,
        client,
        lambda request: _unsigned_expiry_response(
            request, failure_reason_code="AUTHORIZATION_EXPIRED"
        ),
    )

    result = service.create(command())

    assert result["status"] == "review_required"
    assert result["next_action"] == "contact_operator"
    assert result["reason_code"] == "AUTHORIZATION_EXPIRED"
    row = funding.get_reservation(result["reservation_id"])
    assert row["budget_accounting_state"] == "reserved"
    assert row["reconciliation_status"] == "manual_review_required"
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert _unsigned_audits(repo) == []


@pytest.mark.parametrize("failure", ["evidence", "release"])
def test_direct_transfer_unsigned_expiry_rolls_back_evidence_and_budget(
    tmp_path, monkeypatch, failure
):
    service, funding, repo, client, _prepared, _now = _stage_submission_unknown(
        tmp_path, monkeypatch
    )
    if failure == "evidence":
        def fail_evidence(*args, **kwargs):
            raise ValueError("simulated evidence failure")

        monkeypatch.setattr(
            FundingTransaction,
            "record_hosted_unsigned_expiry_evidence",
            fail_evidence,
        )
    else:
        def fail_release(*args, **kwargs):
            raise ValueError("simulated release failure")

        monkeypatch.setattr(FundingTransaction, "release_unified_budget", fail_release)
    _install_recovery_reply(
        monkeypatch,
        client,
        lambda request: _unsigned_expiry_response(request),
    )

    result = service.create(command())

    assert result["status"] != "failed"
    row = funding.get_reservation(result["reservation_id"])
    assert row["state"] == "spending_reserved"
    assert row["budget_accounting_state"] == "reserved"
    assert row.get("hosted_unsigned_expiry_evidence") is None
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("0")
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert _unsigned_audits(repo) == []
