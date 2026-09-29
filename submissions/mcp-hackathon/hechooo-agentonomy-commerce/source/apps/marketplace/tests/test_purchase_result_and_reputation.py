from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import services.marketplace_app as marketplace_app
from services.identity_service import IdentityService
from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.commerce import Purchase, PurchasePreview
from shared.config import AppConfig
from shared.models import PaymentOption, Provider, ServiceOffering

USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x" + "4" * 40

class RecordingCore:
    def __init__(self, approved=True):
        self.approved = approved
        self.reserves = 0
        self.settlements = 0
        self.reconciliations = 0
        self.reservation_reads = 0
        self.reservation_result = {"state": "reserved"}

    def create_action(self, payload):
        return {"action_id": "action_1"}

    def evaluate_policy(self, payload):
        return {"policy_decision_id": "policy_1", "approved": self.approved}

    def update_action(self, *args, **kwargs):
        return {}

    def audit(self, payload):
        return {"event_id": "audit_1"}

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

    def reserve(self, payload):
        self.reserves += 1
        return {"reservation_id": "reserve_1"}

    def settle(self, reservation_id, payload):
        self.settlements += 1
        return {
            "state": "settled",
            "receipt_id": "receipt_1",
            "receipt": {"receipt_id": "receipt_1"},
        }

    def finalize(self, reservation_id, payload):
        return {"state": "finalized"}

    def reservation(self, reservation_id):
        self.reservation_reads += 1
        return self.reservation_result

    def reconcile(self, reservation_id):
        self.reconciliations += 1
        return self.reservation_result

    def external_finalize(self, reservation_id, payload):
        self.settlements += 1
        return {"state": "settled", "receipt_id": "receipt_external_1"}


class MerchantResponse:
    headers = {"content-type": "application/json"}

    def __init__(self, payload, *, success=True):
        self.payload = payload
        self.is_success = success
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return self.response


def build_repository(tmp_path, *, native=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="Risk API",
        domain="risk.example",
        source="merchant",
        status="active",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id="POST https://risk.example/check",
        name="Risk API",
        endpoint="https://risk.example/check",
        method="POST",
        status="verified",
        metadata={"accepts_clink_receipt": native},
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset=USDC,
                amount_atomic="10000",
                pay_to="0x" + "3" * 40,
                price_usd="0.01",
            )
        ],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    return repository, offering


def build_purchase_service(repository, offering, core, **kwargs):
    native_provider_ids = (
        {offering.provider_id}
        if offering.metadata.get("accepts_clink_receipt")
        else set()
    )
    return PurchaseService(
        repository,
        core,
        native_provider_ids=native_provider_ids,
        **kwargs,
    )


def database_dump(repository):
    with repository.engine.connect() as connection:
        rows = {}
        for table_name in inspect(connection).get_table_names():
            rows[table_name] = [
                tuple(map(str, row))
                for row in connection.execute(
                    text(f'SELECT * FROM "{table_name}"')
                ).all()
            ]
    return json.dumps(rows, sort_keys=True)


def event_rows(repository):
    with repository.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT purchase_id, event_type, dimensions "
                "FROM reputation_events ORDER BY purchase_id"
            )
        ).all()


def store_purchase(repository, offering, purchase_id, state, *, reason_code=None):
    now = datetime.now(UTC)
    preview_id = "preview_" + purchase_id.removeprefix("purchase_")
    payment = offering.payment_options[0].model_dump(mode="json")
    if repository.get_preview(preview_id) is None:
        repository.save_preview(
            PurchasePreview(
                preview_id=preview_id,
                offering_id=offering.offering_id,
                user_id="hermes",
                quote_hash="0xquote",
                input_hash="0xinput",
                payment=payment,
                execution_mode="clink_allowance",
                expires_at=now,
                created_at=now,
            )
        )
    purchase = Purchase(
        purchase_id=purchase_id,
        preview_id=preview_id,
        offering_id=offering.offering_id,
        user_id="hermes",
        state=state,
        execution_mode="clink_allowance",
        input_hash="0xinput",
        output_hash="0xoutput" if state == "delivered" else None,
        receipt_id=(
            "receipt_" + purchase_id.removeprefix("purchase_")
            if state in {"delivered", "paid_but_undelivered"}
            else None
        ),
        reason_code=reason_code,
        created_at=now,
        updated_at=now,
    )
    repository.save_purchase(purchase)
    return purchase


def test_delivered_result_is_returned_once_but_never_persisted(tmp_path):
    repository, offering = build_repository(tmp_path)
    cleartext = "transient-result-must-not-survive"
    client = RecordingClient(MerchantResponse({"risk": "low", "secret": cleartext}))
    core = RecordingCore()
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    result = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )
    replay = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert result["purchase"].state == "delivered"
    assert result["service_result"] == {"risk": "low", "secret": cleartext}
    assert replay["purchase"].purchase_id == result["purchase"].purchase_id
    assert replay["service_result"] is None
    assert client.calls == 1
    assert core.reserves == 1
    assert core.settlements == 1

    stored = repository.get_purchase(result["purchase"].purchase_id)
    assert stored.output_hash is not None
    assert "service_result" not in stored.metadata
    with repository.engine.connect() as connection:
        persisted = connection.execute(
            text(
                "SELECT output_hash, latency_ms, receipt_id, metadata "
                "FROM purchases WHERE purchase_id = :purchase_id"
            ),
            {"purchase_id": stored.purchase_id},
        ).one()
    assert persisted.output_hash == stored.output_hash
    assert persisted.latency_ms is not None
    assert persisted.receipt_id == "receipt_1"
    assert "service_result" not in persisted.metadata
    assert cleartext not in database_dump(repository)
    assert len(event_rows(repository)) == 1


def test_paid_but_undelivered_replay_does_not_charge_or_deliver_twice(tmp_path):
    repository, offering = build_repository(tmp_path)
    client = RecordingClient(MerchantResponse({"error": "down"}, success=False))
    core = RecordingCore()
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    first = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )
    replay = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert first["purchase"].state == "paid_but_undelivered"
    assert first["service_result"] is None
    assert replay["purchase"].state == "paid_but_undelivered"
    assert replay["service_result"] is None
    assert client.calls == core.reserves == core.settlements == 1
    assert len(event_rows(repository)) == 1
    assert repository.rebuild_reputation(offering.offering_id)["dimensions"] == {
        "identity": 50.0,
        "quote_consistency": 50.0,
        "availability": 50.0,
        "payment_success": 100.0,
        "delivery_success": 0.0,
        "dispute": 50.0,
    }


def test_external_delivery_result_is_transient_and_replay_is_safe(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    cleartext = "external-result-must-not-survive"
    client = RecordingClient(MerchantResponse({"risk": "low", "secret": cleartext}))
    core = RecordingCore()
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    pending = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    result = service.complete_external(
        pending["purchase"].purchase_id,
        transaction_hash="0xabc",
        payment_response={"signature": "0xsigned"},
    )
    replay = service.complete_external(
        pending["purchase"].purchase_id,
        transaction_hash="0xabc",
        payment_response={"signature": "0xsigned"},
    )

    assert result["purchase"].state == "delivered"
    assert result["service_result"] == {"risk": "low", "secret": cleartext}
    assert replay["purchase"].state == "delivered"
    assert replay["service_result"] is None
    assert client.calls == 1
    assert core.settlements == 1
    assert len(event_rows(repository)) == 1
    assert cleartext not in database_dump(repository)


def test_fastapi_execute_serializes_transient_result(tmp_path, monkeypatch):
    repository, offering = build_repository(tmp_path)
    service = build_purchase_service(
        repository,
        offering,
        RecordingCore(),
        client=RecordingClient(MerchantResponse({"risk": "low"})),
    )
    monkeypatch.setattr(
        marketplace_app,
        "PurchaseService",
        lambda *args, **kwargs: service,
    )
    config = replace(
        AppConfig.from_env(),
        database_url=str(repository.engine.url),
        redis_url="",
        internal_api_token="agent-token",
    )
    app = TestClient(
        marketplace_app.create_marketplace_app(
            config, repository, IdentityService(repository), core=RecordingCore()
        )
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    response = app.post(
        f"/purchases/{preview.preview_id}/execute",
        headers={"Authorization": "Bearer agent-token"},
        json={"user_confirmed": True, "spending_authorization_id": "auth_1"},
    )
    replay = app.post(
        f"/purchases/{preview.preview_id}/execute",
        headers={"Authorization": "Bearer agent-token"},
        json={"user_confirmed": True, "spending_authorization_id": "auth_1"},
    )

    assert response.status_code == 200
    assert response.json()["purchase"]["state"] == "delivered"
    assert response.json()["service_result"] == {"risk": "low"}
    assert replay.status_code == 200
    assert replay.json()["purchase"]["state"] == "delivered"
    assert replay.json()["service_result"] is None


def test_fastapi_external_first_result_and_terminal_replay(tmp_path, monkeypatch):
    repository, offering = build_repository(tmp_path, native=False)
    service = build_purchase_service(
        repository,
        offering,
        RecordingCore(),
        client=RecordingClient(MerchantResponse({"risk": "low"})),
    )
    monkeypatch.setattr(marketplace_app, "PurchaseService", lambda *args, **kwargs: service)
    config = replace(
        AppConfig.from_env(),
        database_url=str(repository.engine.url),
        redis_url="",
        internal_api_token="agent-token",
    )
    app = TestClient(
        marketplace_app.create_marketplace_app(
            config, repository, IdentityService(repository), core=RecordingCore()
        )
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    headers = {"Authorization": "Bearer agent-token"}
    pending = app.post(
        f"/purchases/{preview.preview_id}/execute",
        headers=headers,
        json={"user_confirmed": True, "spending_authorization_id": "auth_1"},
    )
    purchase_id = pending.json()["purchase"]["purchase_id"]
    service._save_result_mailbox(purchase_id, {"risk": "premature"})
    premature = app.get(f"/purchases/{purchase_id}", headers=headers)

    first = app.post(
        f"/purchases/{purchase_id}/external-complete",
        headers=headers,
        json={"transaction_hash": "0xabc", "payment_response": {"signature": "0xsigned"}},
    )
    fetched = app.get(f"/purchases/{purchase_id}", headers=headers)
    replay = app.post(
        f"/purchases/{purchase_id}/external-complete",
        headers=headers,
        json={"transaction_hash": "0xabc", "payment_response": {"signature": "0xsigned"}},
    )

    assert pending.json()["purchase"]["state"] == "signing_required"
    assert pending.json()["service_result"] is None
    assert premature.json()["service_result"] is None
    assert first.json()["purchase"]["state"] == "delivered"
    assert first.json()["service_result"] == {"risk": "low"}
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "delivered"
    assert fetched.json()["service_result"] == {"risk": "low"}
    assert replay.json()["purchase"]["state"] == "delivered"
    assert replay.json()["service_result"] is None
    assert "service_result" not in repository.get_purchase(purchase_id).metadata


def test_fastapi_confirmation_retry_advances(tmp_path, monkeypatch):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore(approved=False)
    service = build_purchase_service(
        repository,
        offering,
        core,
        client=RecordingClient(MerchantResponse({"risk": "low"})),
    )
    monkeypatch.setattr(marketplace_app, "PurchaseService", lambda *args, **kwargs: service)
    config = replace(
        AppConfig.from_env(),
        database_url=str(repository.engine.url),
        redis_url="",
        internal_api_token="agent-token",
    )
    app = TestClient(
        marketplace_app.create_marketplace_app(
            config, repository, IdentityService(repository), core=core
        )
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    headers = {"Authorization": "Bearer agent-token"}
    waiting = app.post(
        f"/purchases/{preview.preview_id}/execute",
        headers=headers,
        json={"user_confirmed": False, "spending_authorization_id": None},
    )
    core.approved = True

    delivered = app.post(
        f"/purchases/{preview.preview_id}/execute",
        headers=headers,
        json={"user_confirmed": True, "spending_authorization_id": "auth_1"},
    )

    assert waiting.json()["purchase"]["state"] == "confirmation_required"
    assert delivered.json()["purchase"]["state"] == "delivered"
    assert delivered.json()["service_result"] == {"risk": "low"}


def test_preview_expiration_does_not_affect_merchant_reputation(tmp_path):
    repository, offering = build_repository(tmp_path)
    service = build_purchase_service(
        repository, offering, RecordingCore(), preview_ttl=-1
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    result = service.execute(preview.preview_id)
    snapshot = repository.rebuild_reputation(offering.offering_id)

    assert result["purchase"].state == "failed"
    assert result["service_result"] is None
    assert event_rows(repository) == []
    assert snapshot["sample_size"] == 0
    assert snapshot["dimensions"]["payment_success"] == 50
    assert snapshot["dimensions"]["delivery_success"] == 50


def test_quote_drift_does_not_affect_merchant_reputation(tmp_path):
    repository, offering = build_repository(tmp_path)
    service = build_purchase_service(repository, offering, RecordingCore())
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    changed_payment = offering.payment_options[0].model_copy(
        update={"amount_atomic": "20000"}
    )
    repository.upsert_offering(
        offering.model_copy(update={"payment_options": [changed_payment]}),
        verified_at=datetime.now(UTC),
    )

    result = service.execute(preview.preview_id)

    assert result["purchase"].state == "failed"
    assert result["purchase"].reason_code == "QUOTE_DRIFT"
    assert event_rows(repository) == []
    assert repository.rebuild_reputation(offering.offering_id)["sample_size"] == 0


def test_reputation_event_is_idempotent_and_first_terminal_outcome_wins(tmp_path):
    repository, offering = build_repository(tmp_path)
    store_purchase(repository, offering, "purchase_1", "delivered")
    first = repository.record_reputation_event(
        offering.offering_id,
        "delivered",
        "purchase_1",
        {"payment_success": 100, "delivery_success": 100},
    )
    duplicate = repository.record_reputation_event(
        offering.offering_id,
        "delivered",
        "purchase_1",
        {"payment_success": 100, "delivery_success": 100},
    )

    assert duplicate == first
    assert event_rows(repository)[0][1] == "delivered"
    assert repository.rebuild_reputation(offering.offering_id)["dimensions"][
        "delivery_success"
    ] == 100


@pytest.mark.parametrize(
    ("offering_mismatch", "event_type", "dimensions"),
    [
        (False, "paid_but_undelivered", {"payment_success": 100, "delivery_success": 0}),
        (False, "delivered", {"payment_success": 100, "delivery_success": 99}),
        (True, "delivered", {"payment_success": 100, "delivery_success": 100}),
    ],
)
def test_reputation_event_rejects_conflicting_duplicate(
    tmp_path, offering_mismatch, event_type, dimensions
):
    repository, offering = build_repository(tmp_path)
    store_purchase(repository, offering, "purchase_1", "delivered")
    repository.record_reputation_event(
        offering.offering_id,
        "delivered",
        "purchase_1",
        {"payment_success": 100, "delivery_success": 100},
    )
    conflicting_offering_id = "offering_other" if offering_mismatch else offering.offering_id

    with pytest.raises(ValueError, match="conflicting reputation event"):
        repository.record_reputation_event(
            conflicting_offering_id,
            event_type,
            "purchase_1",
            dimensions,
        )


def test_reputation_event_requires_matching_terminal_purchase(tmp_path):
    repository, offering = build_repository(tmp_path)

    with pytest.raises(ValueError, match="purchase"):
        repository.record_reputation_event(
            offering.offering_id,
            "delivered",
            "purchase_missing",
            {"payment_success": 100, "delivery_success": 100},
        )

    store_purchase(repository, offering, "purchase_waiting", "spending_reserved")
    with pytest.raises(ValueError, match="terminal state"):
        repository.record_reputation_event(
            offering.offering_id,
            "delivered",
            "purchase_waiting",
            {"payment_success": 100, "delivery_success": 100},
        )


@pytest.mark.parametrize("event_type", ["", "refunded", "delivered<script>"])
def test_reputation_event_rejects_unknown_event_types(tmp_path, event_type):
    repository, offering = build_repository(tmp_path)
    with pytest.raises(ValueError, match="event type"):
        repository.record_reputation_event(
            offering.offering_id,
            event_type,
            "purchase_1",
            {"delivery_success": 100},
        )


@pytest.mark.parametrize(
    "dimensions",
    [
        {"made_up": 100},
        {"delivery_success": -0.01},
        {"delivery_success": 100.01},
        {"delivery_success": float("nan")},
        {"delivery_success": float("inf")},
        {"delivery_success": True},
        {},
    ],
)
def test_reputation_event_rejects_unsafe_dimensions(tmp_path, dimensions):
    repository, offering = build_repository(tmp_path)
    with pytest.raises(ValueError, match="dimension"):
        repository.record_reputation_event(
            offering.offering_id,
            "delivered",
            "purchase_1",
            dimensions,
        )


def test_rebuild_is_deterministic_order_independent_and_empty_safe(tmp_path):
    first, first_offering = build_repository(tmp_path / "first")
    second, second_offering = build_repository(tmp_path / "second")
    events = [
        ("purchase_b", "delivered", {"delivery_success": 99.9}),
        ("purchase_a", "paid_but_undelivered", {"delivery_success": 0.1}),
    ]
    for purchase_id, event_type, dimensions in events:
        store_purchase(first, first_offering, purchase_id, event_type)
        first.record_reputation_event(
            first_offering.offering_id, event_type, purchase_id, dimensions
        )
    for purchase_id, event_type, dimensions in reversed(events):
        store_purchase(second, second_offering, purchase_id, event_type)
        second.record_reputation_event(
            second_offering.offering_id, event_type, purchase_id, dimensions
        )

    expected = first.rebuild_reputation(first_offering.offering_id)
    assert second.rebuild_reputation(second_offering.offering_id) == expected
    assert first.rebuild_reputation(first_offering.offering_id) == expected
    assert expected["sample_size"] == 2
    assert expected["confidence"] == 0.04
    assert expected["dimensions"]["delivery_success"] == 50

    empty, empty_offering = build_repository(tmp_path / "empty")
    empty_snapshot = empty.rebuild_reputation(empty_offering.offering_id)
    assert empty_snapshot["sample_size"] == 0
    assert empty_snapshot["confidence"] == 0.0
    assert isinstance(empty_snapshot["dimensions"], dict)


def alembic_config(monkeypatch, database_url):
    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def assert_reputation_event_schema(engine):
    inspector = inspect(engine)
    assert inspector.has_table("reputation_events")
    columns = {column["name"]: column for column in inspector.get_columns("reputation_events")}
    assert set(columns) == {
        "event_id",
        "offering_id",
        "purchase_id",
        "event_type",
        "dimensions",
        "created_at",
    }
    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("reputation_events")
    }
    unique_columns.update(
        tuple(item["column_names"])
        for item in inspector.get_indexes("reputation_events")
        if item.get("unique")
    )
    assert ("purchase_id",) in unique_columns


def assert_purchase_preview_capability_schema(engine):
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("purchase_previews")
    }
    assert "payment_capability" in columns
    assert columns["payment_capability"]["nullable"] is False


def test_reputation_migration_fresh_database(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'fresh.sqlite3'}"
    config = alembic_config(monkeypatch, database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert_reputation_event_schema(engine)
    assert_purchase_preview_capability_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260904_0010"


def test_reputation_migration_upgrades_existing_0004_database(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'upgrade.sqlite3'}"
    config = alembic_config(monkeypatch, database_url)
    command.upgrade(config, "20260713_0004")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS reputation_events")

    command.upgrade(config, "head")

    assert_reputation_event_schema(engine)
    assert_purchase_preview_capability_schema(engine)


def test_reputation_migration_accepts_existing_table(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing.sqlite3'}"
    config = alembic_config(monkeypatch, database_url)
    command.upgrade(config, "20260713_0004")
    engine = create_engine(database_url)
    from storage.tables import ReputationEventRow

    ReputationEventRow.__table__.create(engine)
    assert inspect(engine).has_table("reputation_events")

    command.upgrade(config, "head")

    assert_reputation_event_schema(engine)


def test_reputation_migration_downgrade_removes_only_event_table(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'downgrade.sqlite3'}"
    config = alembic_config(monkeypatch, database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "20260713_0004")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert not inspector.has_table("reputation_events")
    assert inspector.has_table("purchases")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260713_0004"
