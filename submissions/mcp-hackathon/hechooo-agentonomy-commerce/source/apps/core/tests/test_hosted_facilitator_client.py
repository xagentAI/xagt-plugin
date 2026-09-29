from __future__ import annotations

import json
import httpx
import pytest

from services.funding_service.hosted_client import (
    HostedExecutionUnknown,
    HostedFacilitatorClient,
    HostedExecutionNotFound,
)
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HostedExecutionResponse,
    sign_execution_response,
)
from shared.payment_capability import PaymentCapabilityV1


TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
HASH = "0x" + "44" * 32


def capability() -> PaymentCapabilityV1:
    return PaymentCapabilityV1(
        capability_id="capability_1",
        user_id="user_1",
        agent_id="agent_1",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="wallet_binding_1",
        wallet_identity_id="wallet_identity_1",
        wallet_address=OWNER,
        spending_grant_id="grant_1",
        spending_grant_hash=HASH,
        asset_allowance_id="allowance_1",
        action_id="action_1",
        policy_decision_id="policy_1",
        policy_snapshot_hash=HASH,
        risk_evidence_hash=HASH,
        reservation_id="reservation_1",
        reservation_hash=HASH,
        purchase_id="purchase_1",
        merchant_id="merchant_1",
        product="marketplace",
        venue="clink_marketplace",
        quote_hash=HASH,
        payment_challenge_hash=HASH,
        network="eip155:8453",
        asset_contract=TOKEN,
        amount_atomic="1000000",
        pay_to=PAYEE,
        executor_contract=EXECUTOR,
        execution_scope_hash=HASH,
        confirmation_mode="user_approved",
        revocation_id=HASH,
        issued_at=100,
        expires_at=160,
    )


def response_for(client: HostedFacilitatorClient, request, server_key, **updates):
    values = {
        "request_id": request.envelope.request_id,
        "request_hash": request.envelope.request_hash,
        "idempotency_key": request.envelope.idempotency_key,
        "execution_id": "exec_1",
        "capability_id": request.envelope.payment_capability_id,
        "capability_hash": request.envelope.payment_capability_hash,
        "reservation_id": request.envelope.reservation_id,
        "reservation_hash": request.envelope.reservation_hash,
        "purchase_id": request.envelope.purchase_id,
        "execution_scope_hash": request.envelope.execution_scope_hash,
        "owner": request.envelope.wallet_address,
        "payee": request.envelope.pay_to,
        "token": request.envelope.asset_contract,
        "amount_atomic": request.envelope.amount_atomic,
        "executor": request.envelope.executor_contract,
        "signer_epoch": 1,
        "owner_nonce": request.envelope.request_nonce,
        "deadline": request.envelope.expires_at,
        "chain_id": request.envelope.chain_id,
        "state": "submitted",
        "transaction_hash": "0x" + "aa" * 32,
        "receipt_block_hash": None,
        "receipt_block_number": None,
        "safe_block_hash": None,
        "safe_block_number": None,
        "confirmations": 0,
        "failure_reason_code": None,
        "issued_at": 103,
        "submitted_at": 103,
        "confirmed_at": None,
        "finalized_at": None,
        "reverted_at": None,
        "reorg_reviewed_at": None,
        "released_at": None,
        "expired_at": None,
        "watcher_version": "hosted-base-watcher-v1",
        "server_key_id": server_key.thumbprint,
    }
    values.update(updates)
    response = HostedExecutionResponse(**values)
    return {"response_jws": sign_execution_response(server_key, response)}


def client_with_transport(handler, *, now=103):
    device_key = DeviceSigningKey.generate()
    server_key = DeviceSigningKey.generate()

    def transport_factory():
        return httpx.MockTransport(handler)

    client = HostedFacilitatorClient(
        origin="https://hosted.example",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="wallet_binding_1",
        access_token="access-token",
        device_key=device_key,
        server_public_jwk=server_key.public_jwk,
        chain_id="eip155:8453",
        clock=lambda: now,
        monotonic=lambda: 1.0,
        transport_factory=transport_factory,
    )
    return client, server_key


def test_prepare_and_recover_use_same_signed_scope_and_get_only_for_recovery():
    calls = []
    client_ref = {}
    server_ref = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        request_body = json.loads(request.content) if request.content else {}
        assert request.headers["dpop"]
        if request.method == "POST":
            assert set(request_body) == {"payment_jws"}
            body = response_for(client_ref["client"], client_ref["request"], server_ref["key"])
        else:
            body = response_for(
                client_ref["client"],
                client_ref["request"],
                server_ref["key"],
                execution_id="exec_1",
            )
        return httpx.Response(200, json=body, headers={"content-type": "application/json"})

    client, server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )
    client_ref.update(client=client, request=request)
    server_ref["key"] = server_key

    submitted = client.submit(request)
    recovered = client.recover(request, submitted.execution_id)

    assert submitted.execution_id == recovered.execution_id == "exec_1"
    assert request.envelope.request_hash == recovered.request_hash
    assert calls == [("POST", "/v1/executions"), ("GET", "/v1/executions/exec_1")]


def test_ambiguous_post_is_not_retried_as_another_post():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("provider timeout")

    client, _server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )

    with pytest.raises(HostedExecutionUnknown):
        client.submit(request)
    assert calls == ["POST"]


def test_untrusted_post_response_is_unknown_and_must_not_be_posted_again():
    calls = []
    request_ref = {}
    wrong_server_key = DeviceSigningKey.generate()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        body = response_for(
            request_ref["client"],
            request_ref["request"],
            wrong_server_key,
        )
        return httpx.Response(
            200,
            json=body,
            headers={"content-type": "application/json"},
        )

    client, _trusted_server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )
    request_ref.update(client=client, request=request)

    with pytest.raises(HostedExecutionUnknown):
        client.submit(request)
    assert calls == ["POST"]


@pytest.mark.parametrize("failure_stage", ["send", "read", "close"])
def test_any_post_exception_after_dispatch_is_unknown(
    monkeypatch, failure_stage: str
):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if failure_stage == "send":
            raise RuntimeError("transport callback failed")
        return httpx.Response(
            200,
            content=b'{"response_jws":"not-used"}',
            headers={"content-type": "application/json"},
        )

    if failure_stage == "read":
        async def fail_read(self, response):
            raise RuntimeError("response read failed")

        monkeypatch.setattr(HostedFacilitatorClient, "_read_response", fail_read)
    elif failure_stage == "close":
        async def fail_close(self):
            raise RuntimeError("response close failed")

        monkeypatch.setattr(httpx.Response, "aclose", fail_close)

    client, _server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )

    with pytest.raises(HostedExecutionUnknown):
        client.submit(request)
    assert calls == ["POST"]


def test_recover_by_idempotency_is_get_only_and_verifies_the_same_scope():
    calls = []
    request_ref = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        assert request.method == "GET"
        assert request.url.path == "/v1/execution-lookups/reservation_1"
        body = response_for(
            request_ref["client"], request_ref["request"], request_ref["server_key"]
        )
        return httpx.Response(
            200,
            json=body,
            headers={"content-type": "application/json"},
        )

    client, server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )
    request_ref.update(client=client, request=request, server_key=server_key)

    recovered = client.recover_by_idempotency(request)

    assert recovered.execution_id == "exec_1"
    assert calls == [("GET", "/v1/execution-lookups/reservation_1", b"")]


def test_recover_by_idempotency_distinguishes_definitive_not_found():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/execution-lookups/reservation_1"
        return httpx.Response(
            404,
            json={"detail": "execution not found"},
            headers={"content-type": "application/json"},
        )

    client, _server_key = client_with_transport(handler)
    request = client.prepare_execution(
        capability(), request_id="request_1", idempotency_key="reservation_1", now=103
    )

    with pytest.raises(HostedExecutionNotFound):
        client.recover_by_idempotency(request)


def test_invalid_trusted_key_and_partial_origin_fail_closed():
    with pytest.raises(ValueError, match="origin"):
        HostedFacilitatorClient(
            origin="https://hosted.example/v1",
            tenant_id="tenant_1",
            node_id="node_1",
            wallet_binding_id="wallet_binding_1",
            access_token="token",
            device_key=DeviceSigningKey.generate(),
            server_public_jwk=DeviceSigningKey.generate().public_jwk,
            chain_id="eip155:8453",
        )
