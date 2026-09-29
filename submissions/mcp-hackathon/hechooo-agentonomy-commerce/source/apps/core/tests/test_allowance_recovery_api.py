"""A browser session is not the lifetime of an allowance transaction."""
from datetime import timedelta

import pytest

from test_account_console import (
    POLYGON, SPENDER, TOKEN, TX_HASH, context, create_authenticated_session,
    identity,
)
from test_asset_allowances import FakeRpc


def _login(context):
    client, service, repository, clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    create_authenticated_session(client)
    rpc = FakeRpc()
    rpc.transaction["from"] = owner.wallet_address
    service.rpc_transport = rpc
    return client, service, repository, clock, owner, rpc


def _proof(owner):
    return dict(wallet_identity_id=owner.wallet_identity_id, network=POLYGON,
                token_address=TOKEN, spender_address=SPENDER, allowance_tx_hash=TX_HASH)


def _begin(owner):
    return {key: value for key, value in _proof(owner).items() if key != "allowance_tx_hash"} | {
        "amount_atomic": "2000000", "request_key": "ab" * 32,
    }


def _records(client):
    response = client.get("/account", headers={"Accept": "application/json"})
    assert response.status_code == 200
    return response.json()["allowance_recovery"]


def test_failed_rpc_retains_hash_before_verification_and_survives_new_login(context):
    client, service, repository, clock, owner, rpc = _login(context)

    def unavailable(*_args):
        # Persistence must already have committed before the first RPC call.
        assert _records(client)[0]["allowance_tx_hash"] == TX_HASH
        raise RuntimeError("private provider details")

    service.rpc_transport = unavailable
    response = client.post("/account/allowances/verify", json=_proof(owner))
    assert response.status_code == 503
    assert repository.asset_allowances(owner.wallet_identity_id) == []
    assert _records(client)[0]["status"] == "pending"
    clock.now += timedelta(minutes=16)
    expired = client.get("/account", headers={"Accept": "application/json"})
    assert expired.status_code in {401, 410}
    create_authenticated_session(client)
    assert _records(client)[0]["allowance_tx_hash"] == TX_HASH
    service.rpc_transport = rpc
    assert client.post("/account/allowances/verify", json=_proof(owner)).status_code == 200
    assert _records(client)[0]["status"] == "verified"
    assert all(call[1] != "eth_sendRawTransaction" for call in rpc.calls)


def test_prepare_is_single_use_send_permission_and_no_hash_survives_expiry(context):
    client, _service, _repo, clock, owner, _rpc = _login(context)
    first = client.post("/account/allowances/attempts", json=_begin(owner))
    assert first.status_code == 200
    assert first.json()["created"] is True
    repeated = client.post("/account/allowances/attempts", json=_begin(owner))
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    competing = client.post("/account/allowances/attempts", json={**_begin(owner), "request_key": "cd" * 32})
    assert competing.status_code == 409
    clock.now += timedelta(hours=1)
    create_authenticated_session(client)
    record = _records(client)[0]
    assert record["status"] == "awaiting_wallet"
    assert record["allowance_tx_hash"] is None
    assert "request_key" not in str(record)
    # A plausible legacy hash cannot silently clear an uncertain send.
    assert client.post("/account/allowances/verify", json=_proof(owner)).status_code == 409


def test_submitted_hash_attaches_before_rpc_and_cannot_be_rejected_or_replaced(context):
    client, service, _repo, _clock, owner, _rpc = _login(context)
    first = client.post("/account/allowances/attempts", json=_begin(owner)).json()
    attempt_id = first["attempt"]["attempt_id"]
    calls = []
    service.rpc_transport = lambda *args: calls.append(args)
    route = f"/account/allowances/attempts/{attempt_id}"
    attach = client.post(route + "/submitted", json={"request_key": "ab" * 32, "allowance_tx_hash": TX_HASH})
    assert attach.status_code == 200
    assert attach.json()["status"] == "pending"
    assert calls == []
    assert client.post(route + "/rejected", json={"request_key": "ab" * 32}).status_code == 409
    assert client.post(route + "/submitted", json={"request_key": "ab" * 32, "allowance_tx_hash": "0x" + "55" * 32}).status_code == 409
    assert _records(client)[0]["allowance_tx_hash"] == TX_HASH


def test_only_correlated_definite_rejection_releases_empty_attempt(context):
    client, _service, _repo, _clock, owner, _rpc = _login(context)
    attempt = client.post("/account/allowances/attempts", json=_begin(owner)).json()["attempt"]
    url = f"/account/allowances/attempts/{attempt['attempt_id']}/rejected"
    assert client.post(url, json={"request_key": "cd" * 32}).status_code == 409
    assert client.post(url, json={"request_key": "ab" * 32}).status_code == 200
    assert _records(client)[0]["status"] == "rejected"
    assert client.post("/account/allowances/attempts", json={**_begin(owner), "request_key": "ef" * 32}).json()["created"] is True


@pytest.mark.parametrize("action", ["submitted", "rejected"])
def test_invalid_attempt_identifier_is_a_safe_client_error(context, action):
    client, _service, _repo, _clock, _owner, _rpc = _login(context)
    body = {"request_key": "ab" * 32}
    if action == "submitted":
        body["allowance_tx_hash"] = TX_HASH
    response = client.post(
        f"/account/allowances/attempts/{'x' * 97}/{action}", json=body,
    )
    assert response.status_code == 404
    assert _records(client) == []


def test_cross_user_and_csrf_cannot_read_or_change_attempt(context):
    client, _service, repo, _clock, owner, _rpc = _login(context)
    attempt = client.post("/account/allowances/attempts", json=_begin(owner)).json()["attempt"]
    csrf = client.post("/account/allowances/attempts", json=_begin(owner), headers={"X-CSRF-Token": "wrong"})
    assert csrf.status_code == 403
    repo.save_wallet_identity(identity("user_2", "b"))
    create_authenticated_session(client, "user_2")
    assert _records(client) == []
    assert client.post("/account/allowances/attempts", json=_begin(owner)).status_code == 404
    assert client.post(f"/account/allowances/attempts/{attempt['attempt_id']}/submitted", json={"request_key": "ab" * 32, "allowance_tx_hash": TX_HASH}).status_code == 404


@pytest.mark.parametrize("field,value", [("network", "eip155:1"), ("spender_address", "0x" + "99" * 20), ("token_address", "0x" + "99" * 20)])
def test_prepare_rejects_unconfigured_tuple_without_persisting(context, field, value):
    client, _service, _repo, _clock, owner, _rpc = _login(context)
    assert client.post("/account/allowances/attempts", json={**_begin(owner), field: value}).status_code == 400
    assert _records(client) == []
