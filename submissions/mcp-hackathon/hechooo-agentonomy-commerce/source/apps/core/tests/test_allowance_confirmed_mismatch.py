"""Core contract for confirmed allowance amount mismatches."""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.account_service.allowance_recovery import AllowanceRecoveryStore
from services.account_service.service import AllowanceAmountMismatch

from test_allowance_recovery_api import _begin, _login, _proof
from test_account_console import context
from test_asset_allowances import approve_calldata


def test_confirmed_mismatch_returns_structured_conflict_without_authority_save(
    context,
):
    client, _service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000

    attempt = client.post(
        "/account/allowances/attempts",
        json={**_begin(owner), "amount_atomic": "20000000"},
    )
    assert attempt.status_code == 200
    attempt_id = attempt.json()["attempt"]["attempt_id"]
    submitted = client.post(
        f"/account/allowances/attempts/{attempt_id}/submitted",
        json={"request_key": "ab" * 32, "allowance_tx_hash": _proof(owner)["allowance_tx_hash"]},
    )
    assert submitted.status_code == 200

    response = client.post("/account/allowances/verify", json=_proof(owner))

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == (
        "The allowance transaction is confirmed with a different amount. "
        "No transaction was resent."
    )
    assert body["code"] == "allowance_amount_mismatch"
    assert {
        "status": "confirmed_mismatch",
        "reason_code": "amount_mismatch",
        "actual_approved_amount_atomic": "5000000",
        "observed_allowance_atomic": "5000000",
        "confirmed_block": 100,
        "confirmed_block_hash": "0x" + "ab" * 32,
        "verified_at": "2026-07-15T12:00:00+00:00",
        "next_check_at": None,
    }.items() <= body["recovery"].items()
    assert body["recovery"]["amount_atomic"] == "20000000"
    assert repository.asset_allowances(owner.wallet_identity_id) == []

    events = [
        event
        for event in repository.audit_events(user_id=owner.user_id)
        if event["event_type"] == "allowance_confirmed_mismatch"
    ]
    assert len(events) == 1


def test_replayed_mismatch_and_late_result_are_terminal_and_idempotent(context):
    client, service, repository, clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    attempt = client.post(
        "/account/allowances/attempts",
        json={**_begin(owner), "amount_atomic": "20000000"},
    ).json()["attempt"]
    route = f"/account/allowances/attempts/{attempt['attempt_id']}"
    assert client.post(
        route + "/submitted",
        json={"request_key": "ab" * 32, "allowance_tx_hash": _proof(owner)["allowance_tx_hash"]},
    ).status_code == 200

    first = client.post("/account/allowances/verify", json=_proof(owner))
    def unexpected_rpc(*_args):
        raise AssertionError("terminal mismatch replay must not call the provider")

    service.rpc_transport = unexpected_rpc
    replay = client.post("/account/allowances/verify", json=_proof(owner))
    assert first.status_code == replay.status_code == 409
    assert replay.json() == first.json()

    store = AllowanceRecoveryStore(repository)
    late = store.result(
        attempt_id=attempt["attempt_id"],
        status="pending",
        reason_code="rpc_unavailable",
        now=clock() + timedelta(minutes=1),
    )
    assert late == first.json()["recovery"]
    with pytest.raises(ValueError, match="result status is invalid"):
        store.result(
            attempt_id=attempt["attempt_id"],
            status="confirmed_mismatch",
            reason_code="amount_mismatch",
            now=clock() + timedelta(minutes=1),
        )

    submitted_replay = client.post(
        route + "/submitted",
        json={"request_key": "ab" * 32, "allowance_tx_hash": _proof(owner)["allowance_tx_hash"]},
    )
    assert submitted_replay.status_code == 200
    assert submitted_replay.json() == first.json()["recovery"]
    assert len(
        [
            event
            for event in repository.audit_events(user_id=owner.user_id)
            if event["event_type"] == "allowance_confirmed_mismatch"
        ]
    ) == 1


def test_same_hash_reverification_can_resolve_legacy_attention_required(context):
    client, _service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    attempt = client.post(
        "/account/allowances/attempts",
        json={**_begin(owner), "amount_atomic": "20000000"},
    ).json()["attempt"]
    proof = _proof(owner)
    assert client.post(
        f"/account/allowances/attempts/{attempt['attempt_id']}/submitted",
        json={"request_key": "ab" * 32, "allowance_tx_hash": proof["allowance_tx_hash"]},
    ).status_code == 200

    # Simulate the old generic-400 path leaving a durable unresolved record.
    rpc.transaction["from"] = "0x" + "99" * 20
    assert client.post("/account/allowances/verify", json=proof).status_code == 400
    assert AllowanceRecoveryStore(repository).get(
        user_id=owner.user_id, attempt_id=attempt["attempt_id"]
    )["status"] == "attention_required"

    # The same authenticated, exact-hash proof can now complete the full
    # chain verification and terminally record the mismatch.
    rpc.transaction["from"] = owner.wallet_address
    response = client.post("/account/allowances/verify", json=proof)
    assert response.status_code == 409
    assert response.json()["recovery"]["status"] == "confirmed_mismatch"
    assert len(
        [
            event
            for event in repository.audit_events(user_id=owner.user_id)
            if event["event_type"] == "allowance_confirmed_mismatch"
        ]
    ) == 1


def test_polygon_mismatch_does_not_block_independent_base_preparation(context):
    client, _service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    attempt = client.post(
        "/account/allowances/attempts",
        json={**_begin(owner), "amount_atomic": "20000000"},
    ).json()["attempt"]
    assert client.post(
        f"/account/allowances/attempts/{attempt['attempt_id']}/submitted",
        json={"request_key": "ab" * 32, "allowance_tx_hash": _proof(owner)["allowance_tx_hash"]},
    ).status_code == 200
    assert client.post("/account/allowances/verify", json=_proof(owner)).status_code == 409

    base = client.post(
        "/account/allowances/attempts",
        json={
            **_begin(owner),
            "network": "eip155:8453",
            "amount_atomic": "20000000",
            "request_key": "cd" * 32,
        },
    )
    assert base.status_code == 200
    assert base.json()["created"] is True
    assert repository.asset_allowances(owner.wallet_identity_id) == []


def _mismatch_evidence(owner, **overrides):
    values = {
        "user_id": owner.user_id,
        "wallet_identity_id": owner.wallet_identity_id,
        "network": "eip155:137",
        "token_address": "0x" + "ab" * 20,
        "spender_address": "0x" + "cd" * 20,
        "allowance_tx_hash": "0x" + "12" * 32,
        "amount_atomic": "20000000",
        "actual_approved_amount_atomic": "5000000",
        "observed_allowance_atomic": "5000000",
        "confirmed_block": 100,
        "confirmed_block_hash": "0x" + "ab" * 32,
        "verified_at": "2026-09-16T13:00:00+00:00",
    }
    values.update(overrides)
    return values


def test_store_requires_exact_active_owner_tuple_and_canonical_mismatch_evidence(tmp_path):
    from test_allowance_recovery_store import _begin as begin_store
    from test_allowance_recovery_store import _identity, _repository_and_store

    repository, store, owner = _repository_and_store(tmp_path)
    attempt = begin_store(store, owner)["attempt"]
    store.submitted(
        user_id=owner.user_id,
        attempt_id=attempt["attempt_id"],
        request_key="ab" * 32,
        allowance_tx_hash="0x" + "12" * 32,
        now=owner.created_at,
    )

    for field, value in (
        ("wallet_identity_id", "wallet-other"),
        ("network", "eip155:8453"),
        ("token_address", "0x" + "99" * 20),
        ("spender_address", "0x" + "98" * 20),
        ("allowance_tx_hash", "0x" + "34" * 32),
        ("amount_atomic", "20000001"),
    ):
        with pytest.raises(ValueError):
            store.confirm_mismatch(
                attempt_id=attempt["attempt_id"],
                evidence=_mismatch_evidence(owner, **{field: value}),
                now=owner.created_at,
            )
        assert store.get(
            user_id=owner.user_id, attempt_id=attempt["attempt_id"]
        )["status"] == "pending"
    assert repository.asset_allowances(owner.wallet_identity_id) == []


def test_store_confirm_mismatch_persists_evidence_and_one_atomic_audit(tmp_path):
    from test_allowance_recovery_store import _begin as begin_store
    from test_allowance_recovery_store import _repository_and_store

    repository, store, owner = _repository_and_store(tmp_path)
    attempt = begin_store(store, owner, amount_atomic="20000000")["attempt"]
    store.submitted(
        user_id=owner.user_id,
        attempt_id=attempt["attempt_id"],
        request_key="ab" * 32,
        allowance_tx_hash="0x" + "12" * 32,
        now=owner.created_at,
    )

    result = store.confirm_mismatch(
        attempt_id=attempt["attempt_id"],
        evidence=_mismatch_evidence(owner),
        now=owner.created_at,
    )

    assert result["status"] == "confirmed_mismatch"
    assert result["reason_code"] == "amount_mismatch"
    assert result["amount_atomic"] == "20000000"
    assert result["actual_approved_amount_atomic"] == "5000000"
    assert result["observed_allowance_atomic"] == "5000000"
    assert result["confirmed_block_hash"] == "0x" + "ab" * 32
    assert result["next_check_at"] is None
    assert repository.asset_allowances(owner.wallet_identity_id) == []
    assert len(
        [
            event
            for event in repository.audit_events(user_id=owner.user_id)
            if event["event_type"] == "allowance_confirmed_mismatch"
        ]
    ) == 1


def test_store_confirm_mismatch_rolls_back_record_when_audit_fails(tmp_path, monkeypatch):
    from test_allowance_recovery_store import _begin as begin_store
    from test_allowance_recovery_store import _repository_and_store

    repository, store, owner = _repository_and_store(tmp_path)
    attempt = begin_store(store, owner, amount_atomic="20000000")["attempt"]
    store.submitted(
        user_id=owner.user_id,
        attempt_id=attempt["attempt_id"],
        request_key="ab" * 32,
        allowance_tx_hash="0x" + "12" * 32,
        now=owner.created_at,
    )

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr(repository, "_append_account_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit sink unavailable"):
        store.confirm_mismatch(
            attempt_id=attempt["attempt_id"],
            evidence=_mismatch_evidence(owner),
            now=owner.created_at,
        )

    assert store.get(
        user_id=owner.user_id, attempt_id=attempt["attempt_id"]
    )["status"] == "pending"
    assert not repository.audit_events(user_id=owner.user_id)


def test_inactive_identity_cannot_confirm_mismatch_or_create_audit(tmp_path):
    from test_allowance_recovery_store import _begin as begin_store
    from test_allowance_recovery_store import _repository_and_store

    repository, store, owner = _repository_and_store(tmp_path)
    attempt = begin_store(store, owner)["attempt"]
    store.submitted(
        user_id=owner.user_id,
        attempt_id=attempt["attempt_id"],
        request_key="ab" * 32,
        allowance_tx_hash="0x" + "12" * 32,
        now=owner.created_at,
    )
    repository.revoke_wallet_identity_and_pause_active_grants(owner.wallet_identity_id, owner.created_at)

    with pytest.raises(ValueError, match="not active"):
        store.confirm_mismatch(
            attempt_id=attempt["attempt_id"],
            evidence=_mismatch_evidence(owner),
            now=owner.created_at,
        )
    assert store.get(user_id=owner.user_id, attempt_id=attempt["attempt_id"])["status"] == "pending"
    assert not [
        event
        for event in repository.audit_events(user_id=owner.user_id)
        if event["event_type"] == "allowance_confirmed_mismatch"
    ]


def test_exception_evidence_is_typed_and_keeps_prepared_tuple_immutable(context):
    client, service, _repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    with pytest.raises(AllowanceAmountMismatch) as raised:
        service.verify_asset_allowance(**_proof(owner), expected_amount_atomic=20_000_000)
    exception = raised.value
    assert exception.recovery_record is None
    assert exception.evidence["user_id"] == owner.user_id
    assert exception.evidence["expected_amount_atomic"] == "20000000"
    assert exception.evidence["actual_approved_amount_atomic"] == "5000000"
    assert exception.evidence["observed_allowance_atomic"] == "5000000"
    assert exception.evidence["confirmed_block"] == 100
    assert exception.evidence["confirmed_block_hash"] == "0x" + "ab" * 32


@pytest.mark.parametrize("field", ["blockHash"])
def test_mismatch_requires_equal_canonical_receipt_and_transaction_block_hashes(
    context, field
):
    _client, service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    rpc.transaction[field] = "0x" + "34" * 32
    with pytest.raises(ValueError, match="block hash"):
        service.verify_asset_allowance(**_proof(owner), expected_amount_atomic=20_000_000)
    assert repository.asset_allowances(owner.wallet_identity_id) == []


@pytest.mark.parametrize("failure", [
    "wrong_chain",
    "wrong_sender",
    "wrong_token",
    "wrong_spender",
    "wrong_transaction_hash",
    "failed_receipt",
    "low_confirmations",
    "observation_unavailable",
])
def test_mismatch_never_bypasses_independent_chain_proof(failure, context):
    _client, service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    if failure == "wrong_chain":
        rpc.chain_id = 1
    elif failure == "wrong_sender":
        rpc.transaction["from"] = "0x" + "99" * 20
    elif failure == "wrong_token":
        rpc.transaction["to"] = "0x" + "98" * 20
    elif failure == "wrong_spender":
        rpc.transaction["input"] = approve_calldata(
            spender="0x" + "97" * 20, amount=5_000_000
        )
    elif failure == "wrong_transaction_hash":
        rpc.transaction["hash"] = "0x" + "96" * 32
    elif failure == "failed_receipt":
        rpc.receipt["status"] = "0x0"
    elif failure == "low_confirmations":
        rpc.current_block = 100
    elif failure == "observation_unavailable":
        rpc.fail_eth_call = True

    with pytest.raises((ValueError, RuntimeError)) as raised:
        service.verify_asset_allowance(
            **_proof(owner), expected_amount_atomic=20_000_000
        )
    assert not isinstance(raised.value, AllowanceAmountMismatch)
    assert repository.asset_allowances(owner.wallet_identity_id) == []


def test_expected_none_never_creates_mismatch_terminal_status(context):
    _client, service, repository, _clock, owner, rpc = _login(context)
    rpc.transaction["input"] = approve_calldata(amount=5_000_000)
    rpc.allowance = 5_000_000
    allowance = service.verify_asset_allowance(**_proof(owner))
    assert allowance.approved_amount_atomic == 5_000_000
    assert repository.asset_allowances(owner.wallet_identity_id) == [allowance]
