from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
for _app in ("apps/facilitator", "apps/core", "apps/node"):
    _path = str(ROOT / _app)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from clink_node.config import (  # noqa: E402
    EventBackend,
    InteractionMode,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageBackend,
)
from clink_node.paths import NodePaths  # noqa: E402
from config import FacilitatorConfig  # noqa: E402
from execution_models import (  # noqa: E402
    BASE_CHAIN,
    BASE_CHAIN_ID,
    BASE_USDC,
    ExecutionIntent,
)
from execution_repository import ExecutionRepository  # noqa: E402
from replay import RedisReplayCoordinator, ReplayUnavailable  # noqa: E402
from repository import (  # noqa: E402
    InMemoryRepository,
    PostgresRepository,
    RepositoryUnavailable,
)
from app import create_app  # noqa: E402
from replay import InMemoryReplayCoordinator  # noqa: E402
from services.funding_service.hosted_client import (  # noqa: E402
    HostedExecutionRequest,
    HostedFacilitatorClient,
)
from shared.hosted_facilitator_protocol import (  # noqa: E402
    DeviceSigningKey,
    HostedExecutionResponse,
    sign_execution_response,
)
from shared.payment_capability import PaymentCapabilityV1  # noqa: E402


def _server_settings(tmp_path: Path) -> NodeSettings:
    return NodeSettings.load(
        ROOT / "clink.node.server.example.toml",
        env={
            "CLINK_HOME": str(tmp_path / ".clink"),
            "CLINK_DATABASE_URL": "postgresql+psycopg://node:secret@db/clink",
            "CLINK_REDIS_URL": "rediss://redis.internal:6380/0",
            "CLINK_VAULT_ADDR": "https://vault.internal",
            "CLINK_VAULT_TOKEN": "vault-token-from-secret-store",
            "CLINK_PUBLIC_BASE_URL": "https://node.example.com",
        },
        paths=NodePaths.from_home(tmp_path / ".clink"),
    )


def _intent(**updates: object) -> ExecutionIntent:
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
        "owner": "0x" + "11" * 20,
        "payee": "0x" + "22" * 20,
        "token": BASE_USDC,
        "amount_atomic": "1000000",
        "executor": "0x" + "33" * 20,
        "signer_epoch": 1,
        "owner_nonce": 7,
        "deadline": 2_000_000_060,
        "capability_hash": "0x" + "55" * 32,
        "reservation_hash": "0x" + "66" * 32,
        "execution_scope_hash": "0x" + "77" * 32,
        "execution_digest": "0x" + "88" * 32,
        "relayer_address": "0x" + "44" * 20,
    }
    values.update(updates)
    return ExecutionIntent(**values)


def _production_config(**overrides: object) -> FacilitatorConfig:
    values: dict[str, object] = {
        "environment": "production",
        "public_origin": "https://facilitator.example.com",
        "postgres_url": (
            "postgresql+psycopg://facilitator:secret@db/facilitator"
            "?sslmode=verify-full"
        ),
        "redis_url": "rediss://redis.internal:6380/0",
        "response_key_ref": "alias/clink-hosted-response",
        "core_authority_origin": "https://core.internal.example",
        "core_internal_token": "token-injected-at-runtime",
        "chain_id": BASE_CHAIN_ID,
        "asset_contract": BASE_USDC,
    }
    values.update(overrides)
    return FacilitatorConfig(**values)


def _capability() -> PaymentCapabilityV1:
    return PaymentCapabilityV1(
        capability_id="capability_1",
        user_id="user_1",
        agent_id="agent_1",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        wallet_identity_id="wallet_identity_1",
        wallet_address="0x" + "11" * 20,
        spending_grant_id="grant_1",
        spending_grant_hash="0x" + "aa" * 32,
        asset_allowance_id="allowance_1",
        action_id="action_1",
        policy_decision_id="policy_1",
        policy_snapshot_hash="0x" + "bb" * 32,
        risk_evidence_hash="0x" + "cc" * 32,
        reservation_id="reservation_1",
        reservation_hash="0x" + "dd" * 32,
        purchase_id="purchase_1",
        merchant_id="merchant_1",
        product="marketplace",
        venue="clink_marketplace",
        quote_hash="0x" + "ee" * 32,
        payment_challenge_hash="0x" + "ff" * 32,
        network=BASE_CHAIN,
        asset_contract=BASE_USDC,
        amount_atomic="1000000",
        pay_to="0x" + "22" * 20,
        executor_contract="0x" + "33" * 20,
        execution_scope_hash="0x" + "44" * 32,
        confirmation_mode="user_approved",
        revocation_id="0x" + "55" * 32,
        issued_at=100,
        expires_at=160,
    )


def _hosted_outcome(settings: NodeSettings) -> tuple[str, str, str, str]:
    device_key = DeviceSigningKey.generate()
    response_key = DeviceSigningKey.generate()
    capability = _capability()
    request_ref: dict[str, HostedExecutionRequest] = {}

    def transport_factory() -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            prepared = request_ref["request"]
            response = HostedExecutionResponse(
                request_id="request_1",
                request_hash=prepared.envelope.request_hash,
                idempotency_key="idempotency_1",
                execution_id="exec_1",
                capability_id="capability_1",
                capability_hash=capability.capability_hash,
                reservation_id="reservation_1",
                reservation_hash=capability.reservation_hash,
                purchase_id="purchase_1",
                execution_scope_hash=capability.execution_scope_hash,
                owner=capability.wallet_address,
                payee=capability.pay_to,
                token=BASE_USDC,
                amount_atomic=capability.amount_atomic,
                executor=capability.executor_contract,
                signer_epoch=1,
                owner_nonce=prepared.envelope.request_nonce,
                deadline=160,
                chain_id=BASE_CHAIN,
                state="submitted",
                transaction_hash="0x" + "77" * 32,
                receipt_block_hash=None,
                receipt_block_number=None,
                safe_block_hash=None,
                safe_block_number=None,
                confirmations=0,
                failure_reason_code=None,
                issued_at=103,
                submitted_at=103,
                confirmed_at=None,
                finalized_at=None,
                reverted_at=None,
                reorg_reviewed_at=None,
                released_at=None,
                expired_at=None,
                server_key_id=response_key.thumbprint,
            )
            return httpx.Response(
                200,
                json={"response_jws": sign_execution_response(response_key, response)},
                headers={"content-type": "application/json"},
            )

        return httpx.MockTransport(handler)

    client = HostedFacilitatorClient(
        origin="https://facilitator.example.com",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        access_token="test-access-token",
        device_key=device_key,
        server_public_jwk=response_key.public_jwk,
        chain_id="eip155:8453",
        clock=lambda: 103,
        monotonic=lambda: 1.0,
        transport_factory=transport_factory,
    )
    request = client.prepare_execution(
        capability,
        request_id="request_1",
        idempotency_key="idempotency_1",
        request_nonce="0x" + "66" * 32,
        now=103,
    )
    request_ref["request"] = request
    result = client.submit(request)
    return settings.profile.value, result.state, result.request_hash, result.transaction_hash


def test_personal_and_server_profiles_share_the_same_core_outcome_boundary(
    tmp_path: Path,
) -> None:
    personal = NodeSettings.defaults(
        Profile.PERSONAL,
        paths=NodePaths.from_home(tmp_path / "personal"),
    )
    server = _server_settings(tmp_path / "server")

    assert personal.validation_errors() == []
    assert server.validation_errors() == []
    assert (personal.profile, server.profile) == (Profile.PERSONAL, Profile.SERVER)
    assert personal.interaction.mode is InteractionMode.LOCAL
    assert server.interaction.mode is InteractionMode.SELF_HOSTED
    assert personal.storage.backend is StorageBackend.SQLITE
    assert server.storage.backend is StorageBackend.POSTGRES
    assert personal.events.backend is EventBackend.MEMORY
    assert server.events.backend is EventBackend.REDIS
    assert personal.secrets.backend is SecretBackend.KEYCHAIN
    assert server.secrets.backend is SecretBackend.VAULT

    personal_outcome = _hosted_outcome(personal)
    server_outcome = _hosted_outcome(server)
    assert personal_outcome[1:] == server_outcome[1:]


def test_production_startup_fails_closed_without_core_authority() -> None:
    with pytest.raises(ValueError, match="Core authority origin"):
        _production_config(core_authority_origin="")
    with pytest.raises(ValueError, match="Core authority token"):
        _production_config(core_internal_token="")

    with pytest.raises(ValueError, match="PostgreSQL repository"):
        create_app(
            _production_config(),
            repository=InMemoryRepository(),
            replay=InMemoryReplayCoordinator(),
            response_signer=object(),
            clock=lambda: 2_000_000_000,
        )


def test_execution_replay_survives_repository_restart(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hosted.sqlite3'}"
    first_repository = ExecutionRepository(database_url)
    first = first_repository.allocate_or_return(_intent(), chain_pending_nonce=37)

    restarted_repository = ExecutionRepository(database_url)
    replay = restarted_repository.allocate_or_return(_intent(), chain_pending_nonce=99)

    assert replay.execution_id == first.execution_id
    assert replay.relayer_nonce == first.relayer_nonce == 37


class _RedisOutage:
    def set(self, *_args, **_kwargs):
        raise OSError("redis is unavailable")


def test_redis_outage_is_fail_closed() -> None:
    coordinator = RedisReplayCoordinator(
        "rediss://redis.internal:6380/0",
        client=_RedisOutage(),
    )

    with pytest.raises(ReplayUnavailable):
        coordinator.consume_dpop_jti(
            tenant_id="tenant_1",
            node_id="node_1",
            credential_epoch=1,
            jti="jti_1",
            ttl_seconds=60,
        )


def test_postgres_outage_is_fail_closed_without_claiming_live_database() -> None:
    repository = object.__new__(PostgresRepository)

    class _SessionContext:
        def __enter__(self):
            raise SQLAlchemyError("database is unavailable")

        def __exit__(self, *_args):
            return False

    class _SessionFactory:
        def begin(self):
            return _SessionContext()

    repository.sessions = _SessionFactory()

    def unavailable(_session):
        raise SQLAlchemyError("database is unavailable")

    with pytest.raises(RepositoryUnavailable):
        repository._run(unavailable)


def test_server_example_documents_hosted_private_network_secret_references() -> None:
    example = (ROOT / "clink.node.server.example.toml").read_text(encoding="utf-8")

    assert "CLINK_FACILITATOR_MODE=hosted" in example
    assert "CLINK_HOSTED_FACILITATOR_URL=https://facilitator.internal.example" in example
    assert "CLINK_CORE_AUTHORITY_ORIGIN=https://core.internal.example" in example
    assert "CLINK_CORE_INTERNAL_API_TOKEN=secret://" in example
    assert "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY=secret://" in example
    assert "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN=secret://" in example
    assert "BEGIN PRIVATE KEY" not in example
