from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app
from authority import CoreAuthorityRejected, CoreAuthorityResolver, CoreAuthorityUnavailable
from config import FacilitatorConfig
from execution_models import BASE_CHAIN, BASE_CHAIN_ID, BASE_USDC, ExecutionIntent
from execution_repository import ExecutionRepository
from pilot_gate import PilotGatePolicy
from relayer import HostedRelayer
from repository import PostgresRepository
from replay import RedisReplayCoordinator
from shared.hosted_facilitator_protocol import HostedPaymentEnvelope


NOW = 2_000_000_000
ORIGIN = "http://127.0.0.1:8080"
EXECUTOR = "0x" + "44" * 20
RELAYER = "0x" + "55" * 20
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
HASH = "0x" + "aa" * 32


class Response:
    status_code = 200
    headers = {"content-type": "application/json", "content-encoding": "identity"}

    def __init__(self, payload: object) -> None:
        self.content = json.dumps(payload).encode("utf-8")


class EchoCore:
    def __init__(self, mutate=None, *, status_code: int = 200) -> None:
        self.calls: list[dict] = []
        self.mutate = mutate
        self.status_code = status_code

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        payload = dict(kwargs["json"])
        if payload.get("payment_challenge_hash") is None:
            payload["payment_challenge_hash"] = HASH
        if self.mutate is not None:
            payload = self.mutate(payload)
        response = Response(payload)
        response.status_code = self.status_code
        return response


def envelope() -> HostedPaymentEnvelope:
    return HostedPaymentEnvelope(
        protocol_version="clink-hosted-v1",
        audience="hosted-facilitator",
        http_method="POST",
        http_path="/v1/executions",
        request_id="request_1",
        idempotency_key="idempotency_1",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        payment_capability_version="clink-payment-capability-v1",
        payment_capability_id="capability_1",
        payment_capability_hash=HASH,
        wallet_identity_id="identity_1",
        wallet_address=OWNER,
        spending_grant_id="grant_1",
        spending_grant_hash=HASH,
        asset_allowance_id="allowance_1",
        reservation_id="reservation_1",
        reservation_hash=HASH,
        action_id="action_1",
        policy_decision_id="decision_1",
        policy_snapshot_hash=HASH,
        risk_evidence_hash=HASH,
        purchase_id="purchase_1",
        merchant_id="merchant_1",
        quote_hash=HASH,
        payment_challenge_hash=HASH,
        chain_id="eip155:8453",
        asset_contract=BASE_USDC,
        amount_atomic="1000000",
        pay_to=PAYEE,
        executor_contract=EXECUTOR,
        execution_scope_hash=HASH,
        request_nonce="0x" + "07" * 32,
        issued_at=NOW - 1,
        expires_at=NOW + 59,
    )


def resolver(client: EchoCore) -> CoreAuthorityResolver:
    return CoreAuthorityResolver(
        origin=ORIGIN,
        internal_token="internal-test-token",
        relayer_address=RELAYER,
        signer_epoch=1,
        environment="test",
        client=client,
        chain=BASE_CHAIN,
        token=BASE_USDC,
        chain_id=BASE_CHAIN_ID,
    )


def test_resolver_uses_core_bearer_and_returns_exact_execution_intent() -> None:
    client = EchoCore()
    authority = resolver(client)
    value = envelope()

    intent = authority.resolve(value, SimpleNamespace(
        tenant_id=value.tenant_id,
        node_id=value.node_id,
        wallet_binding_id=value.wallet_binding_id,
    ))

    assert isinstance(intent, ExecutionIntent)
    assert intent.request_hash == value.request_hash
    assert intent.relayer_address == RELAYER
    assert client.calls[0]["headers"]["authorization"] == "Bearer internal-test-token"
    assert client.calls[0]["url"] == ORIGIN + "/funding/spending-reservations/reservation_1/hosted-authority"


def test_resolver_fails_closed_on_core_unavailability_and_does_not_leak_token() -> None:
    client = EchoCore(status_code=503)
    authority = resolver(client)

    with pytest.raises(CoreAuthorityUnavailable, match="unavailable") as error:
        authority.resolve(envelope(), SimpleNamespace(
            tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
        ))
    assert "internal-test-token" not in str(error.value)


def test_resolver_preflight_uses_narrow_core_authority_endpoint_and_exact_scope() -> None:
    client = EchoCore()
    authority = resolver(client)
    value = envelope().model_copy(update={"http_path": "/v1/preflight"})

    projection = authority.preflight(
        value,
        SimpleNamespace(
            tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
        ),
    )

    assert projection["request_hash"] == value.request_hash
    assert projection["amount_atomic"] == value.amount_atomic
    assert client.calls[0]["url"] == (
        ORIGIN
        + "/funding/spending-reservations/reservation_1/hosted-preflight-authority"
    )
    assert "execution_digest" not in client.calls[0]["json"]
    assert "relayer_address" not in client.calls[0]["json"]


def test_resolver_preflight_rejects_core_scope_mutation() -> None:
    def mutate(payload: dict) -> dict:
        payload["payment_challenge_hash"] = "0x" + "bb" * 32
        return payload

    with pytest.raises(CoreAuthorityRejected):
        resolver(EchoCore(mutate=mutate)).preflight(
            envelope().model_copy(update={"http_path": "/v1/preflight"}),
            SimpleNamespace(
                tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
            ),
        )


def test_resolver_rejects_wrong_core_token_and_mutated_authority() -> None:
    with pytest.raises(CoreAuthorityRejected):
        resolver(EchoCore(status_code=401)).resolve(
            envelope(), SimpleNamespace(
                tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
            )
        )

    def mutate(payload: dict) -> dict:
        payload["amount_atomic"] = "2000000"
        return payload

    with pytest.raises(CoreAuthorityRejected):
        resolver(EchoCore(mutate=mutate)).resolve(
            envelope(), SimpleNamespace(
                tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
            )
        )


def test_verify_rejects_resolver_relayer_scope_mismatch() -> None:
    client = EchoCore()
    authority = resolver(client)
    value = envelope()
    intent = authority.resolve(value, SimpleNamespace(
        tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1"
    ))

    authority.verify(intent)

    with pytest.raises(CoreAuthorityRejected):
        authority.verify(intent.model_copy(update={"relayer_address": "0x" + "66" * 20}))

    with pytest.raises(CoreAuthorityRejected):
        authority.verify(intent.model_copy(update={"execution_digest": "0x" + "bb" * 32}))


def test_production_app_rejects_relayer_using_different_core_authority(tmp_path: Path) -> None:
    client = EchoCore()
    first = resolver(client)
    second = resolver(EchoCore())

    class Signer:
        key_id = "key"
        expected_signer_address = "0x" + "77" * 20

        def sign_digest(self, _digest: bytes) -> bytes:
            return bytes.fromhex("aa" * 65)

    class Rpc:
        def call(self, _method: str, _params: list):
            return "0x0"

    execution_repository = ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'execution.sqlite3'}",
        pilot_policy=PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=1_000_000
        ),
    )
    # HostedRelayer construction is intentionally exercised only far enough
    # to assert production dependency identity; no transaction is submitted.
    class GasSigner(Signer):
        key_id = "gas"
        expected_signer_address = RELAYER

    relayer = HostedRelayer(
        repository=execution_repository,
        rpc=Rpc(),
        execution_signer=Signer(),
        gas_signer=GasSigner(),
        approval_verifier=second,
        executor_address=EXECUTOR,
        relayer_address=RELAYER,
        max_gas_limit=100000,
        max_fee_per_gas_wei=1,
        max_priority_fee_per_gas_wei=1,
        clock=lambda: NOW,
        chain=BASE_CHAIN,
        token=BASE_USDC,
        chain_id=BASE_CHAIN_ID,
    )
    config = FacilitatorConfig(
        environment="production",
        public_origin="https://hosted.example.com",
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="rediss://redis.example.com:6380/0",
        response_key_ref="alias/hosted-response",
        core_authority_origin="https://core.example.com",
        core_internal_token="internal-test-token",
        chain_id=BASE_CHAIN_ID,
        asset_contract=BASE_USDC,
    )
    with pytest.raises(ValueError, match="shared Core authority"):
        create_app(
            config,
            repository=object.__new__(PostgresRepository),
            replay=object.__new__(RedisReplayCoordinator),
            response_signer=object(),
            clock=lambda: NOW,
            execution_repository=execution_repository,
            execution_service=relayer,
            intent_resolver=first,
        )


def test_production_app_requires_pilot_policy_on_execution_repository(
    tmp_path: Path,
) -> None:
    authority = resolver(EchoCore())
    execution_repository = ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'execution-no-gate.sqlite3'}"
    )
    relayer = object.__new__(HostedRelayer)
    relayer._repository = execution_repository
    relayer._approval_verifier = authority
    config = FacilitatorConfig(
        environment="production",
        public_origin="https://hosted.example.com",
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="rediss://redis.example.com:6380/0",
        response_key_ref="alias/hosted-response",
        core_authority_origin="https://core.example.com",
        core_internal_token="internal-test-token",
        chain_id=BASE_CHAIN_ID,
        asset_contract=BASE_USDC,
    )

    with pytest.raises(ValueError, match="PilotGate policy"):
        create_app(
            config,
            repository=object.__new__(PostgresRepository),
            replay=object.__new__(RedisReplayCoordinator),
            response_signer=object(),
            clock=lambda: NOW,
            execution_repository=execution_repository,
            execution_service=relayer,
            intent_resolver=authority,
        )


def test_production_app_requires_relayer_to_share_execution_repository(
    tmp_path: Path,
) -> None:
    authority = resolver(EchoCore())
    pilot_policy = PilotGatePolicy(native_asset_usd_price_ceiling_micros=1_000_000)
    api_repository = ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'execution-api.sqlite3'}",
        pilot_policy=pilot_policy,
    )
    relayer_repository = ExecutionRepository(
        f"sqlite+pysqlite:///{tmp_path / 'execution-relayer.sqlite3'}",
        pilot_policy=pilot_policy,
    )
    relayer = object.__new__(HostedRelayer)
    relayer._repository = relayer_repository
    relayer._approval_verifier = authority
    config = FacilitatorConfig(
        environment="production",
        public_origin="https://hosted.example.com",
        postgres_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="rediss://redis.example.com:6380/0",
        response_key_ref="alias/hosted-response",
        core_authority_origin="https://core.example.com",
        core_internal_token="internal-test-token",
        chain_id=BASE_CHAIN_ID,
        asset_contract=BASE_USDC,
    )

    with pytest.raises(ValueError, match="shared execution repository"):
        create_app(
            config,
            repository=object.__new__(PostgresRepository),
            replay=object.__new__(RedisReplayCoordinator),
            response_signer=object(),
            clock=lambda: NOW,
            execution_repository=api_repository,
            execution_service=relayer,
            intent_resolver=authority,
        )
