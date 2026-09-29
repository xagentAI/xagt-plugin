import socket

from fastapi.testclient import TestClient

from agentonomy_commerce.api import create_app
from agentonomy_commerce.settings import Settings


CSV = ("transaction_id,date,description,amount,currency,category\n"
       "t1,2026-09-01,Hosting,-12.50,USD,software\n"
       "t2,2026-09-02,Invoice,40.00,USD,revenue\n"
       "t1,2026-09-01,Hosting,-12.50,USD,software\n")
TOKEN = "local-test-only-" + "q" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def settings_for(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return Settings(tmp_path, TOKEN, "a" * 40, "hechooo-agentonomy-commerce", port)


def preview(client, key, csv_text=CSV):
    response = client.post("/v1/previews", json={"offering_id": "csv-reconciliation-v1", "csv_text": csv_text},
                           headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    return response.json()


def test_real_http_purchase_result_budget_and_replay_survive_restart(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings), headers=HEADERS) as client:
        initial = client.get("/v1/budget").json()
        assert initial["used_amount_usdc"] == "0.00"
        pending = preview(client, "restart-input")

    with TestClient(create_app(settings), headers=HEADERS) as client:
        assert preview(client, "restart-input")["preview_id"] == pending["preview_id"]
        response = client.post("/v1/purchases", json={"preview_id": pending["preview_id"]})
        assert response.status_code == 200, response.text
        bought = response.json()
        assert bought["state"] == "delivered", bought
        assert bought["service_transport"] == "http"
        assert bought["service_result"]["unique_transaction_count"] == 2
        assert bought["service_result"]["duplicate_ids"] == ["t1"]
        assert bought["service_result"]["net_totals"] == {"USD": "27.50"}
        budget = client.get("/v1/budget").json()
        assert budget["used_amount_usdc"] == "0.30"
        assert budget["remaining_amount_usdc"] == "0.70"
        assert budget["settlement_submissions"] == 1

    with TestClient(create_app(settings), headers=HEADERS) as client:
        recovered = client.get(f"/v1/purchases/{bought['purchase_id']}").json()
        assert recovered["service_result"] == bought["service_result"]
        replay = client.post("/v1/purchases", json={"preview_id": pending["preview_id"]}).json()
        assert replay["purchase_id"] == bought["purchase_id"]
        assert replay["service_result"] == bought["service_result"]
        after = client.get("/v1/budget").json()
        assert after["used_amount_usdc"] == "0.30"
        assert after["settlement_submissions"] == 1
        assert after["merchant_deliveries"] == 1
        assert "receipt_signing_key" not in str(recovered)
        assert "wallet_identity_id" not in str(recovered)


def test_idempotency_conflict_invalid_input_and_exhausted_budget(tmp_path):
    with TestClient(create_app(settings_for(tmp_path)), headers=HEADERS) as client:
        first = preview(client, "same-key")
        conflict = client.post("/v1/previews", json={"offering_id": "csv-reconciliation-v1",
                               "csv_text": CSV.replace("40.00", "41.00")},
                               headers={"Idempotency-Key": "same-key"})
        assert conflict.status_code == 409
        invalid = client.post("/v1/previews", json={"offering_id": "csv-reconciliation-v1", "csv_text": "not,csv"},
                              headers={"Idempotency-Key": "bad-input"})
        assert invalid.status_code == 422
        assert client.get("/v1/budget").json()["used_amount_usdc"] == "0.00"
        for index in range(3):
            current = first if index == 0 else preview(client, f"purchase-{index}")
            result = client.post("/v1/purchases", json={"preview_id": current["preview_id"]}).json()
            assert result["state"] == "delivered", result
        fourth = preview(client, "budget-block")
        blocked = client.post("/v1/purchases", json={"preview_id": fourth["preview_id"]}).json()
        assert blocked["state"] == "confirmation_required", blocked
        assert blocked["reason_code"] == "BUDGET_EXCEEDED"
        assert client.get("/v1/budget").json()["used_amount_usdc"] == "0.90"


def test_valid_unicode_csv_does_not_break_worker_channel(tmp_path):
    import json
    text = ("transaction_id,date,description,amount,currency,category\n"
            "t1,2026-09-01," + "💸" * 32000 + ",-1.00,USD,software\n")
    assert len(text.encode("utf-8")) < 131072
    with TestClient(create_app(settings_for(tmp_path)), headers=HEADERS) as client:
        response = client.post("/v1/previews", content=json.dumps({
            "offering_id": "csv-reconciliation-v1", "csv_text": text,
        }, ensure_ascii=False).encode("utf-8"), headers={
            "Content-Type": "application/json", "Idempotency-Key": "unicode-input"})
        assert response.status_code == 200, response.text
        assert response.json()["preview_id"]
        assert client.get("/v1/budget").json()["used_amount_usdc"] == "0.00"
