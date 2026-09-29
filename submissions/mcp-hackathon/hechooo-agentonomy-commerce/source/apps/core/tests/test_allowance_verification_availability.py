"""HTTP recovery uses the same proof; an RPC outage is not a failed approve."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from shared.evm_rpc import NetworkRpcTransport
from test_account_console import (
    POLYGON, SPENDER, TOKEN, TX_HASH, context, create_authenticated_session, identity,
)
from test_asset_allowances import FakeRpc


@pytest.mark.parametrize("failed_method", ["eth_chainId", "eth_getTransactionReceipt", "eth_call"])
def test_rpc_outage_returns_retryable_json_without_accepting_or_resending(context, failed_method):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    create_authenticated_session(client)
    chain = FakeRpc()
    chain.transaction["from"] = owner.wallet_address
    attempts = []
    unavailable = True

    def opener(request, *, timeout):
        payload = json.loads(request.data)
        attempts.append(payload["method"])
        assert timeout == 20.0
        if unavailable and payload["method"] == failed_method:
            raise HTTPError(request.full_url, 408, "private-provider-details", {}, None)
        result = chain(POLYGON, payload["method"], payload["params"])
        response = io.BytesIO(json.dumps({
            "jsonrpc": "2.0", "id": payload["id"], "result": result,
        }).encode())
        response.headers = {"Content-Type": "application/json"}
        return response

    service.rpc_transport = NetworkRpcTransport(
        {POLYGON: "https://private-rpc.invalid/secret-key"}, opener=opener,
    )
    proof = {
        "wallet_identity_id": owner.wallet_identity_id,
        "network": POLYGON, "token_address": TOKEN,
        "spender_address": SPENDER, "allowance_tx_hash": TX_HASH,
    }
    first = client.post("/account/allowances/verify", json=proof)

    assert first.status_code == 503
    assert first.headers["Retry-After"] == "3"
    assert first.json() == {"detail": "Allowance verification is temporarily unavailable. Your transaction has not been retried; verification can resume using the same transaction hash."}
    assert "private" not in first.text and "secret-key" not in first.text
    assert repository.asset_allowances(owner.wallet_identity_id) == []

    unavailable = False
    resumed = client.post("/account/allowances/verify", json=proof)
    assert resumed.status_code == 200
    assert resumed.json()["allowance_tx_hash"] == TX_HASH
    assert resumed.json()["observed_allowance_atomic"] == "2000000"
    assert resumed.json()["status"] == "active"
    assert len(repository.asset_allowances(owner.wallet_identity_id)) == 1
    assert all(method in {"eth_chainId", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_blockNumber", "eth_call"} for method in attempts)


def test_bad_proof_is_not_misclassified_as_retryable_outage(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    create_authenticated_session(client)
    response = client.post("/account/allowances/verify", json={
        "wallet_identity_id": owner.wallet_identity_id,
        "network": POLYGON, "token_address": TOKEN,
        "spender_address": SPENDER, "allowance_tx_hash": "invalid",
    })
    assert response.status_code == 400
    assert "Retry-After" not in response.headers
    assert repository.asset_allowances(owner.wallet_identity_id) == []


@pytest.mark.parametrize("pending_stage", ["receipt", "transaction", "confirmations"])
def test_pending_chain_evidence_remains_retryable_without_resubmission(context, pending_stage):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    create_authenticated_session(client)
    chain = FakeRpc()
    chain.transaction["from"] = owner.wallet_address
    pending = True
    calls = []

    def rpc(network, method, params):
        calls.append(method)
        if pending:
            if pending_stage == "receipt" and method == "eth_getTransactionReceipt":
                return None
            if pending_stage == "transaction" and method == "eth_getTransactionByHash":
                return None
            if pending_stage == "confirmations" and method == "eth_blockNumber":
                return "0x64"
        return chain(network, method, params)

    service.rpc_transport = rpc
    proof = {
        "wallet_identity_id": owner.wallet_identity_id,
        "network": POLYGON, "token_address": TOKEN,
        "spender_address": SPENDER, "allowance_tx_hash": TX_HASH,
    }
    response = client.post("/account/allowances/verify", json=proof)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "3"
    assert "waiting for chain evidence" in response.json()["detail"]
    assert repository.asset_allowances(owner.wallet_identity_id) == []
    pending = False
    resumed = client.post("/account/allowances/verify", json=proof)
    assert resumed.status_code == 200
    assert resumed.json()["allowance_tx_hash"] == TX_HASH
    assert resumed.json()["status"] == "active"
    assert all(method in {"eth_chainId", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_blockNumber", "eth_call"} for method in calls)
