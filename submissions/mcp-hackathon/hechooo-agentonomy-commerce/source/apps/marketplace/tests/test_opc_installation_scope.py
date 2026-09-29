from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.config import AppConfig
from shared.models import PaymentOption, Provider, ServiceOffering


USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x" + "4" * 40
OPC_A = "opc_" + "a" * 40
OPC_B = "opc_" + "b" * 40


class RecordingCore:
    def __init__(self) -> None:
        self.authorization_payloads: list[dict] = []
        self.action_payloads: list[dict] = []
        self.reserve_payloads: list[dict] = []
        self.reconcile_payloads: list[str] = []
        self.settle_payloads: list[tuple[str, dict]] = []
        self.authorization_ready = True
        self.reconcile_results: list[dict] = []
        self.settle_results: list[dict] = []

    def funding_readiness(self):
        return {"spender_address": SPENDER}

    def resolve_authorization(self, payload):
        self.authorization_payloads.append(payload)
        result = {
            "ready": self.authorization_ready,
            "authorization_rail": payload["authorization_rail"],
            "wallet_identity_id": "wallet_1",
            "spending_grant_id": "grant_1",
            "asset_allowance_id": "allowance_1",
            "notification_mode": "silent_under_limits",
            "user_interaction_required": False,
        }
        if not self.authorization_ready:
            result.update(
                {
                    "reason_code": "OPC_INSTALLATION_NOT_READY",
                    "next_action": "reconnect_opc",
                }
            )
        if payload.get("opc_installation_id") is not None:
            result["opc_installation_id"] = payload["opc_installation_id"]
        return result

    def create_account_session(self, _user_id):
        raise AssertionError(
            "payment_submitted recovery must not create an account session"
        )

    def create_action(self, payload):
        self.action_payloads.append(payload)
        return {"action_id": "action_1"}

    def evaluate_policy(self, _payload):
        return {"policy_decision_id": "policy_1", "approved": True}

    def update_action(self, *_args, **_kwargs):
        return {}

    def audit(self, _payload):
        return {"event_id": "audit_1"}

    def reserve(self, payload):
        self.reserve_payloads.append(payload)
        return {"reservation_id": "reserve_1"}

    def settle(self, _reservation_id, _payload):
        self.settle_payloads.append((_reservation_id, _payload))
        if self.settle_results:
            return self.settle_results.pop(0)
        return {
            "state": "settled",
            "receipt_id": "receipt_1",
            "tx_hash": "0x" + "1" * 64,
        }

    def reconcile(self, reservation_id):
        self.reconcile_payloads.append(reservation_id)
        if self.reconcile_results:
            return self.reconcile_results.pop(0)
        return {
            "state": "spending_reserved",
            "reconciliation_status": "retryable",
            "next_action": "retry_settlement",
            "tx_hash": None,
            "receipt_id": None,
            "receipt": None,
        }

    def finalize(self, _reservation_id, _payload):
        return {"state": "finalized"}


class MerchantResponse:
    is_success = True
    headers = {"content-type": "application/json"}

    def json(self):
        return {"result": "ok"}


class RecordingMerchant:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return MerchantResponse()


def build_service(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    repository = MarketplaceRepository(database_url)
    provider = Provider(
        name="OPC merchant",
        domain="merchant.example",
        source="merchant",
        status="active",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id="POST https://merchant.example/buy",
        name="Buy",
        endpoint="https://merchant.example/buy",
        method="POST",
        status="verified",
        metadata={"accepts_clink_receipt": True},
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
    core = RecordingCore()
    merchant = RecordingMerchant()
    service = PurchaseService(
        repository,
        core,
        client=merchant,
        native_provider_ids={offering.provider_id},
    )
    return database_url, repository, service, core, merchant, offering


def test_opc_installation_is_persisted_and_propagated_to_core(tmp_path):
    database_url, _repository, service, core, _merchant, offering = build_service(
        tmp_path
    )

    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"query": "coffee"},
        opc_installation_id=OPC_A,
    )
    reloaded = MarketplaceRepository(database_url).get_preview(preview.preview_id)
    result = service.execute(
        preview.preview_id,
        user_confirmed=True,
        opc_installation_id=OPC_A,
    )

    assert reloaded is not None
    assert reloaded.opc_installation_id == OPC_A
    assert result.state == "delivered"
    assert [item["opc_installation_id"] for item in core.authorization_payloads] == [
        OPC_A,
        OPC_A,
    ]
    assert core.action_payloads[0]["metadata"]["opc_installation_id"] == OPC_A
    assert core.reserve_payloads[0]["opc_installation_id"] == OPC_A


@pytest.mark.parametrize("caller_installation", [None, OPC_B])
def test_opc_mismatch_is_rejected_before_terminal_idempotent_return(
    tmp_path, caller_installation
):
    _url, _repository, service, core, merchant, offering = build_service(tmp_path)
    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"query": "coffee"},
        opc_installation_id=OPC_A,
    )
    delivered = service.execute(
        preview.preview_id,
        user_confirmed=True,
        opc_installation_id=OPC_A,
    )
    before = (
        len(core.authorization_payloads),
        len(core.action_payloads),
        len(core.reserve_payloads),
        merchant.calls,
    )

    with pytest.raises(ValueError, match="OPC installation mismatch"):
        service.execute(
            preview.preview_id,
            user_confirmed=True,
            opc_installation_id=caller_installation,
        )

    assert delivered.state == "delivered"
    assert before == (
        len(core.authorization_payloads),
        len(core.action_payloads),
        len(core.reserve_payloads),
        merchant.calls,
    )


def test_opc_mismatch_is_rejected_before_external_completion(tmp_path):
    _url, _repository, service, _core, _merchant, offering = build_service(tmp_path)
    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"query": "coffee"},
        opc_installation_id=OPC_A,
    )
    external_completion_called = False

    def complete_external(*_args, **_kwargs):
        nonlocal external_completion_called
        external_completion_called = True
        raise AssertionError("external completion must not be reached")

    service.complete_external = complete_external

    with pytest.raises(ValueError, match="OPC installation mismatch"):
        service.execute(
            preview.preview_id,
            opc_installation_id=OPC_B,
            transaction_hash="0x" + "2" * 64,
            payment_response={"success": True},
        )

    assert external_completion_called is False


def test_legacy_preview_remains_unscoped_and_idempotent(tmp_path):
    _url, repository, service, _core, merchant, offering = build_service(tmp_path)
    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"query": "coffee"},
    )

    result = service.execute(preview.preview_id, user_confirmed=True)
    replay = service.execute(preview.preview_id, user_confirmed=True)

    assert repository.get_preview(preview.preview_id).opc_installation_id is None
    assert replay.purchase_id == result.purchase_id
    assert merchant.calls == 1


def test_payment_submitted_recovery_reconciles_and_delivers_after_opc_revoke(
    tmp_path,
):
    _url, _repository, service, core, merchant, offering = build_service(tmp_path)
    core.settle_results = [
        {
            "state": "payment_submitted",
            "reconciliation_status": "retryable",
            "next_action": "retry_settlement",
            "tx_hash": None,
            "receipt_id": None,
            "receipt": None,
        }
    ]
    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"query": "coffee"},
        opc_installation_id=OPC_A,
    )

    pending = service.execute(
        preview.preview_id,
        user_confirmed=True,
        opc_installation_id=OPC_A,
    )
    assert pending.state == "payment_submitted"

    core.authorization_ready = False
    core.reconcile_results = [
        {
            "state": "settled",
            "receipt_id": "receipt_1",
            "tx_hash": "0x" + "1" * 64,
        }
    ]
    delivered = service.execute(
        preview.preview_id,
        opc_installation_id=OPC_A,
    )

    assert delivered.state == "delivered"
    assert len(core.authorization_payloads) == 2
    assert len(core.reserve_payloads) == 1
    assert len(core.settle_payloads) == 1
    assert core.reconcile_payloads == ["reserve_1"]
    assert merchant.calls == 1


def test_http_ingress_forwards_internal_opc_identity_without_exposing_it(tmp_path):
    database_url, repository, _service, core, _merchant, offering = build_service(
        tmp_path
    )
    config = replace(
        AppConfig.from_env(),
        database_url=database_url,
        redis_url="",
        internal_api_token="node-only",
        native_provider_ids=(offering.provider_id,),
    )
    app = create_marketplace_app(
        config,
        repository,
        IdentityService(repository),
        core,
    )
    headers = {"Authorization": "Bearer node-only"}

    with TestClient(app) as client:
        response = client.post(
            "/purchases/previews",
            headers=headers,
            json={
                "user_id": "user_1",
                "offering_id": offering.offering_id,
                "service_input": {"query": "coffee"},
                "opc_installation_id": OPC_A,
            },
        )

        assert response.status_code == 200
        preview_id = response.json()["preview_id"]
        assert "opc_installation_id" not in response.json()
        assert repository.get_preview(preview_id).opc_installation_id == OPC_A

        lookup = client.get(f"/purchases/previews/{preview_id}", headers=headers)
        assert lookup.status_code == 200
        assert "opc_installation_id" not in lookup.json()

        mismatch = client.post(
            f"/purchases/{preview_id}/execute",
            headers=headers,
            json={"user_confirmed": True, "opc_installation_id": OPC_B},
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"] == "OPC installation mismatch"


def test_opc_installation_migration_is_nullable_and_current_head(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}"
    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("purchase_previews")
    }
    assert columns["opc_installation_id"]["nullable"] is True
    assert columns["opc_installation_id"]["type"].length == 44
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260904_0010"
