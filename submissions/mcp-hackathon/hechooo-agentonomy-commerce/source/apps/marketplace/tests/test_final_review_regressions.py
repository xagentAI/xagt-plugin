from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from services.quote_service import QuoteService
from shared.ephemeral import EphemeralStore
from shared.models import PaymentOption, Provider, ServiceOffering
from storage.tables import PurchaseFinalizationRow


ROOT = Path(__file__).resolve().parents[1]
USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x" + "4" * 40


class RecordingCore:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.side_effects = 0
        self.releases = 0

    def create_action(self, _payload):
        self.side_effects += 1
        return {"action_id": "action_1"}

    def evaluate_policy(self, _payload):
        self.side_effects += 1
        return {"policy_decision_id": "policy_1", "approved": True}

    def update_action(self, *_args, **_kwargs):
        self.side_effects += 1
        return {}

    def audit(self, _payload):
        self.side_effects += 1
        return {"event_id": "audit_policy_1"}

    def funding_readiness(self):
        return {"spender_address": SPENDER}

    def resolve_authorization(self, payload):
        result = {
            "ready": True,
            "authorization_rail": payload["authorization_rail"],
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
        }
        if payload["authorization_rail"] == "native_allowance":
            result["asset_allowance_id"] = "asset_allowance_1"
        return result

    def reserve(self, _payload):
        self.side_effects += 1
        return {"reservation_id": "reserve_1"}

    def settle(self, _reservation_id, _payload):
        self.side_effects += 1
        return {"state": "settled", "receipt_id": "receipt_1", "receipt": {}}

    def external_finalize(self, _reservation_id, _payload):
        self.side_effects += 1
        self.events.append("external_payment_verified")
        return {"state": "settled", "tx_hash": "0x" + "a" * 64}

    def finalize(self, _reservation_id, _payload):
        self.side_effects += 1
        self.events.append("core_terminal_finalized")
        return {"state": "finalized", "tx_hash": "0x" + "a" * 64}

    def reservation(self, _reservation_id):
        return {"state": "settled", "tx_hash": "0x" + "a" * 64}

    def release(self, _reservation_id, _reason):
        self.side_effects += 1
        self.releases += 1
        return {"state": "released"}


class MerchantResponse:
    is_success = True
    headers = {"content-type": "application/json"}

    def json(self):
        return {"result": "ok"}


class RecordingMerchantClient:
    def __init__(self, events=None, store=None, key=None) -> None:
        self.events = events if events is not None else []
        self.store = store
        self.key = key
        self.calls = []

    def request(self, *_args, **kwargs):
        if self.store is not None:
            assert self.store.get(self.key) == {"subject": "alice"}
        assert kwargs["json"] is not None
        self.events.append("merchant_delivered")
        self.calls.append(kwargs)
        return MerchantResponse()


def marketplace(tmp_path, *, accepts_clink_receipt=True, expensive_first=False):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'final-review.sqlite3'}"
    )
    provider = Provider(
        name="Trusted merchant",
        domain="trusted.example",
        source="merchant",
        status="active",
        verified_wallets=["0x" + "1" * 40],
        metadata={"identity": "merchant-attested"},
    )
    cheap = PaymentOption(
        scheme="exact",
        network="eip155:137",
        asset=USDC,
        amount_atomic="10000",
        pay_to="0x" + "2" * 40,
        price_usd="0.01",
    )
    expensive = PaymentOption(
        scheme="exact",
        network="eip155:137",
        asset=USDC,
        amount_atomic="1000000",
        pay_to="0x" + "2" * 40,
        price_usd="1.00",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id="POST https://trusted.example/check",
        name="Trusted service",
        endpoint="https://trusted.example/check",
        method="POST",
        status="verified",
        metadata={"accepts_clink_receipt": accepts_clink_receipt},
        payment_options=[expensive, cheap] if expensive_first else [cheap, expensive],
    )
    repository.upsert_provider(provider, wallet_address="0x" + "1" * 40)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    return repository, provider, offering


def commit_peer_candidate(repository, provider, offering, *, pay_to, token, cursor):
    candidate_provider = provider.model_copy(
        update={
            "name": "Forged peer identity",
            "status": "discovered",
            "verified_wallets": ["0x" + "f" * 40],
            "metadata": {"identity": "peer-controlled"},
        }
    )
    payment = offering.payment_options[0].model_copy(update={"pay_to": pay_to})
    candidate = offering.model_copy(
        update={
            "source": "peer",
            "status": "discovered",
            "payment_options": [payment],
        }
    )
    assert repository.commit_registry_page(
        "peer_1",
        token,
        [(candidate_provider, candidate, candidate.source_id)],
        cursor=cursor,
        etag=None,
        status="running",
    )


def test_manifest_metadata_cannot_self_select_native_allowance(tmp_path):
    repository, _provider, offering = marketplace(tmp_path)

    preview = PurchaseService(repository, RecordingCore()).create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )

    assert preview.execution_mode == "external_x402_signature"


def test_trusted_native_provider_allowlist_selects_allowance(tmp_path):
    repository, provider, offering = marketplace(tmp_path)

    preview = PurchaseService(
        repository,
        RecordingCore(),
        native_provider_ids={provider.provider_id},
    ).create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )

    assert preview.execution_mode == "clink_allowance"
    assert preview.payment_capability == {
        "rail": "clink_allowance",
        "mandate_compatible": True,
        "auto_pay_compatible": True,
        "requires_purchase_signature": False,
        "reason_code": None,
    }


def test_quote_reports_native_rail_as_mandate_capable_but_not_yet_authorized(tmp_path):
    repository, provider, _offering = marketplace(tmp_path)

    quote = QuoteService(
        repository,
        native_provider_ids={provider.provider_id},
    ).compare("Trusted")[0]

    assert quote.execution_mode == "clink_allowance"
    assert quote.payment_capability == {
        "rail": "clink_allowance",
        "mandate_compatible": True,
        "auto_pay_compatible": False,
        "requires_purchase_signature": False,
        "reason_code": "CORE_AUTHORIZATION_CHECK_REQUIRED",
    }


def test_stale_verification_result_cannot_promote_replacement_candidate(tmp_path):
    repository, provider, offering = marketplace(tmp_path)
    repository.initialize_registry_cursor(
        "peer_1", cursor="0", etag=None, status="pending"
    )
    token = "peer-owner-token"
    assert repository.acquire_registry_lease("peer_1", token)
    commit_peer_candidate(
        repository,
        provider,
        offering,
        pay_to="0x" + "3" * 40,
        token=token,
        cursor="1",
    )
    verified_candidate, payload_hash = repository.get_offering_verification_snapshot(
        offering.offering_id
    )
    assert verified_candidate.payment_options[0].pay_to == "0x" + "3" * 40

    commit_peer_candidate(
        repository,
        provider,
        offering,
        pay_to="0x" + "4" * 40,
        token=token,
        cursor="2",
    )
    completion = repository.complete_offering_verification(
        offering.offering_id,
        True,
        expected_payload_hash=payload_hash,
    )

    assert completion == {
        "applied": False,
        "status": "verifying",
        "reason": "verification_target_changed",
    }
    canonical = repository.get_offering(offering.offering_id)
    assert canonical.payment_options[0].pay_to == offering.payment_options[0].pay_to


def test_external_x402_continues_through_execute_and_finalizes_after_delivery(tmp_path):
    repository, _provider, offering = marketplace(
        tmp_path, accepts_clink_receipt=False
    )
    events = []
    core = RecordingCore(events)
    client = RecordingMerchantClient(events)
    service = PurchaseService(repository, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )
    pending = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )
    events.clear()

    result = service.execute(
        preview.preview_id,
        transaction_hash="0x" + "b" * 64,
        payment_response={
            "network": "eip155:137",
            "asset": "USDC",
            "amount_atomic": "10000",
            "pay_to": "0x" + "2" * 40,
            "signature": "0xsigned",
        },
    )

    assert pending.state == "signing_required"
    assert result.state == "delivered"
    assert result.receipt_id == "0x" + "a" * 64
    assert events == [
        "external_payment_verified",
        "merchant_delivered",
        "core_terminal_finalized",
    ]
    with repository.sessions() as session:
        assert session.query(PurchaseFinalizationRow).count() == 0


def test_expired_ephemeral_input_fails_before_any_core_side_effect(tmp_path):
    now = [100.0]
    store = EphemeralStore(clock=lambda: now[0])
    repository, provider, offering = marketplace(tmp_path)
    core = RecordingCore()
    client = RecordingMerchantClient()
    service = PurchaseService(
        repository,
        core,
        client=client,
        ephemeral_store=store,
        native_provider_ids={provider.provider_id},
        preview_ttl=60,
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )
    now[0] += 61

    result = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert result.state == "failed"
    assert result.reason_code == "INPUT_UNAVAILABLE"
    assert core.side_effects == 0
    assert client.calls == []


def test_input_remains_available_until_terminal_purchase_is_saved(tmp_path):
    store = EphemeralStore()
    repository, provider, offering = marketplace(tmp_path)
    core = RecordingCore()
    service = PurchaseService(
        repository,
        core,
        ephemeral_store=store,
        native_provider_ids={provider.provider_id},
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )
    service.client = RecordingMerchantClient(store=store, key=preview.preview_id)

    result = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert result.state == "delivered"
    assert store.get(preview.preview_id) is None
    store.set(preview.preview_id, {"subject": "stale"}, 60)
    service.execute(preview.preview_id)
    assert store.get(preview.preview_id) is None


def test_external_input_expiry_after_reservation_releases_without_payment(tmp_path):
    now = [100.0]
    store = EphemeralStore(clock=lambda: now[0])
    repository, _provider, offering = marketplace(tmp_path)
    core = RecordingCore()
    client = RecordingMerchantClient()
    service = PurchaseService(
        repository,
        core,
        client=client,
        ephemeral_store=store,
        preview_ttl=60,
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
    )
    pending = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )
    side_effects_before_continuation = core.side_effects
    now[0] += 61

    result = service.execute(
        preview.preview_id,
        transaction_hash="0x" + "b" * 64,
        payment_response={"signature": "0xsigned"},
    )

    assert pending.state == "signing_required"
    assert result.state == "failed"
    assert result.reason_code == "INPUT_UNAVAILABLE"
    assert core.releases == 1
    assert core.side_effects == side_effects_before_continuation + 1
    assert client.calls == []


def test_registry_sync_preserves_trusted_provider_identity_payload(tmp_path):
    repository, provider, offering = marketplace(tmp_path)
    repository.initialize_registry_cursor(
        "peer_1", cursor="0", etag=None, status="pending"
    )
    token = "peer-owner-token"
    assert repository.acquire_registry_lease("peer_1", token)

    commit_peer_candidate(
        repository,
        provider,
        offering,
        pay_to="0x" + "3" * 40,
        token=token,
        cursor="1",
    )

    stored = repository.get_provider(provider.provider_id)
    assert stored.name == provider.name
    assert stored.verified_wallets == provider.verified_wallets
    assert stored.metadata == provider.metadata
    assert stored.status == "active"


def test_price_cap_filters_search_quotes_and_preview_index_space(tmp_path):
    repository, _provider, offering = marketplace(tmp_path, expensive_first=True)

    result = repository.search("Trusted", max_price_usd="0.05")
    quotes = QuoteService(repository).compare("Trusted", max_price_usd="0.05")
    preview = PurchaseService(repository, RecordingCore()).create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"subject": "alice"},
        max_price_usd="0.05",
    )

    assert [str(option.price_usd) for option in result[0].payment_options] == ["0.01"]
    assert [str(quote.payment["price_usd"]) for quote in quotes] == ["0.01"]
    assert str(preview.payment["price_usd"]) == "0.01"
    with pytest.raises(ValueError, match="payment option"):
        PurchaseService(repository, RecordingCore()).create_preview(
            user_id="hermes",
            offering_id=offering.offering_id,
            service_input={"subject": "alice"},
            payment_index=1,
            max_price_usd="0.05",
        )


def test_production_redis_contract_disables_disk_persistence():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    redis = compose.split("\n  redis:", 1)[1].split("\n  migrate:", 1)[0]

    assert '"--appendonly", "no"' in redis
    assert '"--save", ""' in redis
    assert "tmpfs:" in redis
    assert "volumes:" not in redis
    assert "marketplace-redis" not in compose


def test_compose_separates_schema_owner_from_api_and_worker_roles():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    init_script = ROOT / "scripts/postgres-init-roles.sh"

    for name in (
        "POSTGRES_ADMIN_PASSWORD",
        "POSTGRES_MIGRATION_PASSWORD",
        "POSTGRES_API_PASSWORD",
        "POSTGRES_WORKER_PASSWORD",
    ):
        assert name in compose
    assert "postgres-init-roles.sh" in compose
    assert init_script.exists()
    script = init_script.read_text(encoding="utf-8")
    assert "clink_marketplace_migrate" in script
    assert "clink_marketplace_api" in script
    assert "clink_marketplace_worker" in script
    assert "ALTER DEFAULT PRIVILEGES" in script
    assert "REVOKE CREATE ON SCHEMA public" in script


def test_base_migration_contains_only_explicit_revision_0001_schema(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'base-revision.sqlite3'}"
    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))

    command.upgrade(config, "20260712_0001")

    schema = inspect(create_engine(database_url))
    assert not schema.has_table("merchant_sessions")
    assert not schema.has_table("reputation_events")
    assert not schema.has_table("worker_stage_runs")
    assert "candidate_payload" not in {
        column["name"] for column in schema.get_columns("offerings")
    }
    assert "execution_claim_token" not in {
        column["name"] for column in schema.get_columns("purchases")
    }
