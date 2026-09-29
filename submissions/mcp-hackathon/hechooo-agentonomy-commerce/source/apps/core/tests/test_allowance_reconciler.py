from datetime import timedelta
import importlib.util
import pytest

from test_allowance_recovery_api import _login, _proof, _records
from test_account_console import context


def test_background_reconciliation_is_available_and_read_only_after_session_expiry(context):
    assert importlib.util.find_spec("services.account_service.allowance_reconciler") is not None
    from services.account_service.allowance_reconciler import AllowanceReconciler
    from services.account_service.allowance_recovery import AllowanceRecoveryStore

    client, service, repository, clock, owner, rpc = _login(context)
    receipt = rpc.receipt
    rpc.receipt = None
    assert client.post("/account/allowances/verify", json=_proof(owner)).status_code == 503
    attempt_id = _records(client)[0]["attempt_id"]
    clock.now += timedelta(minutes=16)
    assert client.get("/account", headers={"Accept": "application/json"}).status_code in {401, 410}
    store = AllowanceRecoveryStore(repository)
    worker = AllowanceReconciler(service, store, clock=clock)
    assert worker.run_once() == 1
    assert store.get(user_id=owner.user_id, attempt_id=attempt_id)["status"] == "pending"
    rpc.receipt = receipt
    clock.now += timedelta(minutes=6)
    assert worker.run_once() == 1
    assert store.get(user_id=owner.user_id, attempt_id=attempt_id)["status"] == "verified"
    assert worker.run_once() == 0
    assert len(repository.asset_allowances(owner.wallet_identity_id)) == 1
    assert set(call[1] for call in rpc.calls) <= {"eth_chainId", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_blockNumber", "eth_call"}


def test_invalid_proof_is_not_automatically_unlocked(context):
    assert importlib.util.find_spec("services.account_service.allowance_reconciler") is not None
    from services.account_service.allowance_reconciler import AllowanceReconciler
    from services.account_service.allowance_recovery import AllowanceRecoveryStore

    client, service, repository, clock, owner, rpc = _login(context)
    store = AllowanceRecoveryStore(repository)
    record = store.register_proof(user_id=owner.user_id, now=clock(), **_proof(owner))
    rpc.transaction["from"] = "0x" + "99" * 20
    worker = AllowanceReconciler(service, store, clock=clock)
    assert worker.run_once() == 1
    result = store.get(user_id=owner.user_id, attempt_id=record["attempt_id"])
    assert result["status"] == "attention_required"
    assert result["reason_code"] == "invalid_evidence"
    assert repository.asset_allowances(owner.wallet_identity_id) == []
    assert worker.run_once() == 0


def test_revoked_wallet_stops_background_retry_without_restoring_authority(context):
    from services.account_service.allowance_reconciler import AllowanceReconciler
    from services.account_service.allowance_recovery import AllowanceRecoveryStore
    from test_allowance_recovery_api import _begin

    _client, service, repository, clock, owner, rpc = _login(context)
    store = AllowanceRecoveryStore(repository)
    record = store.register_proof(user_id=owner.user_id, now=clock(), **_proof(owner))
    repository.revoke_wallet_identity_and_pause_active_grants(owner.wallet_identity_id, clock())
    worker = AllowanceReconciler(service, store, clock=clock)
    assert worker.run_once() == 1
    result = store.get(user_id=owner.user_id, attempt_id=record["attempt_id"])
    assert result["status"] == "attention_required"
    assert result["reason_code"] == "wallet_unavailable"
    assert result["next_check_at"] is None
    assert worker.run_once() == 0
    assert rpc.calls == []
    assert repository.asset_allowances(owner.wallet_identity_id) == []
    with pytest.raises(ValueError, match="not active"):
        store.begin(user_id=owner.user_id, now=clock(), **_begin(owner))


def test_attempt_amount_must_match_actual_transaction_before_authority_is_saved(context):
    assert importlib.util.find_spec("services.account_service.allowance_reconciler") is not None
    from services.account_service.allowance_reconciler import AllowanceReconciler
    from services.account_service.allowance_recovery import AllowanceRecoveryStore
    from test_allowance_recovery_api import _begin

    client, service, repository, clock, owner, _rpc = _login(context)
    attempt = client.post("/account/allowances/attempts", json={**_begin(owner), "amount_atomic": "20000000"}).json()["attempt"]
    assert client.post(f"/account/allowances/attempts/{attempt['attempt_id']}/submitted",
                       json={"request_key": "ab" * 32, "allowance_tx_hash": _proof(owner)["allowance_tx_hash"]}).status_code == 200
    store = AllowanceRecoveryStore(repository)
    worker = AllowanceReconciler(service, store, clock=clock)
    assert worker.run_once() == 1
    result = store.get(user_id=owner.user_id, attempt_id=attempt["attempt_id"])
    assert result["status"] == "confirmed_mismatch"
    assert result["reason_code"] == "amount_mismatch"
    assert result["amount_atomic"] == "20000000"
    assert result["actual_approved_amount_atomic"] == "2000000"
    assert repository.asset_allowances(owner.wallet_identity_id) == []
