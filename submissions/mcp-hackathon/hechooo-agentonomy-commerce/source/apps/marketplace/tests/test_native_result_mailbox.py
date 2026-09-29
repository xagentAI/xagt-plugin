from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import services.marketplace_app as marketplace_app
from services.identity_service import IdentityService
from shared.config import AppConfig
from tests.test_purchase_result_and_reputation import (
    MerchantResponse, RecordingClient, RecordingCore, build_purchase_service,
    build_repository, database_dump,
)


@pytest.mark.parametrize("deferred", [False, True])
def test_native_delivery_can_be_read_after_execute_without_another_payment(
    tmp_path, monkeypatch, deferred,
):
    repository, offering = build_repository(tmp_path)

    class Core(RecordingCore):
        def settle(self, reservation_id, payload):
            if deferred:
                self.settlements += 1
                return {"state": "payment_submitted", "tx_hash": "0xabc"}
            return super().settle(reservation_id, payload)

    core = Core()
    merchant_result = {"answer": "native-canary-result-not-for-permanent-storage"}
    client = RecordingClient(MerchantResponse(merchant_result))
    service = build_purchase_service(repository, offering, core, client=client)
    monkeypatch.setattr(marketplace_app, "PurchaseService", lambda *a, **kw: service)
    config = replace(AppConfig.from_env(), database_url=str(repository.engine.url),
                     redis_url="", internal_api_token="test-internal-token")
    app = TestClient(marketplace_app.create_marketplace_app(
        config, repository, IdentityService(repository), core=core,
    ))
    preview = service.create_preview(user_id="hermes", offering_id=offering.offering_id,
                                     service_input={"test": "native"})
    headers = {"Authorization": "Bearer test-internal-token"}
    endpoint = f"/purchases/{preview.preview_id}/execute"
    result = app.post(endpoint, headers=headers, json={"user_confirmed": True})
    assert result.status_code == 200
    purchase_id = result.json()["purchase"]["purchase_id"]
    if deferred:
        assert result.json()["purchase"]["state"] == "payment_submitted"
        assert app.get(f"/purchases/{purchase_id}", headers=headers).json()["service_result"] is None
        core.reservation_result = {"state": "settled", "receipt_id": "receipt_1",
                                   "receipt": {"receipt_id": "receipt_1"}, "tx_hash": "0xabc"}
        result = app.post(endpoint, headers=headers, json={"user_confirmed": True})
    assert result.json()["purchase"]["state"] == "delivered"
    fetched = app.get(f"/purchases/{purchase_id}", headers=headers)
    assert fetched.json()["service_result"] == merchant_result
    replay = app.post(endpoint, headers=headers, json={"user_confirmed": True})
    assert replay.json()["purchase"]["state"] == "delivered"
    assert core.reserves == core.settlements == client.calls == 1
    assert merchant_result["answer"] not in database_dump(repository)
