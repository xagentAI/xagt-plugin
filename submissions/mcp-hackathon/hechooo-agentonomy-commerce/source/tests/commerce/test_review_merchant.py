from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from agentonomy_commerce.merchant import ReviewMerchant, reconcile_csv


SECRET = "review-receipt-secret"
NETWORK = "eip155:137"
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
PAY_TO = "0x4444444444444444444444444444444444444444"
HEADERS = {
    "content-type": "application/json",
}


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "0x" + hashlib.sha256(raw.encode()).hexdigest()


def _csv(*rows: str) -> str:
    return "transaction_id,date,description,amount,currency,category\n" + "\n".join(rows) + "\n"


def test_duplicate_rows_still_count_toward_input_limit():
    row = "same,2026-09-01,Synthetic,-1.00,USD,software"
    assert reconcile_csv(_csv(*([row] * 1000)))["input_row_count"] == 1000
    with pytest.raises(ValueError, match="1000 rows"):
        reconcile_csv(_csv(*([row] * 1001)))


def test_amount_limit_preserves_exact_cents_in_aggregation():
    with pytest.raises(ValueError, match="out of bounds"):
        reconcile_csv(_csv("huge,2026-09-01,Synthetic,1000000000000.01,USD,revenue"))
    result = reconcile_csv(_csv(
        "a,2026-09-01,Synthetic,1000000000000.00,USD,revenue",
        "b,2026-09-01,Synthetic,0.01,USD,revenue",
        "c,2026-09-01,Synthetic,-1000000000000.00,USD,revenue"))
    assert result["net_totals"] == {"USD": "0.01"}


def _receipt(merchant: ReviewMerchant, purchase_id: str, **changes: object) -> str:
    scope = {
        "receipt_id": "receipt_review_1",
        "reservation_id": "reservation_review_1",
        "spending_authorization_id": "authorization_review_1",
        "spending_grant_id": "grant_review_1",
        "asset_allowance_id": "allowance_review_1",
        "wallet_identity_id": "wallet_review_1",
        "authorization_rail": "native_allowance",
        "user_id": "review-user",
        "agent_id": "review-agent",
        "action_id": "action_review_1",
        "policy_decision_id": "policy_review_1",
        "purchase_id": purchase_id,
        "merchant_id": "commerce_analytics",
        "quote_hash": "0x" + "11" * 32,
        "payer": "0x1111111111111111111111111111111111111111",
        "pay_to": PAY_TO,
        "resource": merchant.receipt_resource,
        "amount_usdc": "0.3",
        "amount_atomic": "300000",
        "venue": "clink_marketplace",
        "product": "marketplace",
        "chain": NETWORK,
        "token": "USDC",
        "token_address": TOKEN,
        "token_decimals": 6,
        "tx_hash": "0x" + "22" * 32,
        "status": "settled",
        "next_action": "sync_venue_balance",
        "created_at": "2026-09-22T00:00:00+00:00",
        "event_log": [{"event": "spending_authorization_receipt_recorded"}],
    }
    scope.update(changes)
    signature = "sha256=" + hmac.new(
        SECRET.encode(),
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    receipt = {
        "receipt_id": scope["receipt_id"],
        "spending_authorization_id": scope["spending_authorization_id"],
        "resource": scope["resource"],
        "user_id": scope["user_id"],
        "agent_id": scope["agent_id"],
        "wallet_address": scope["payer"],
        "amount_usdc": scope["amount_usdc"],
        "venue": scope["venue"],
        "destination": scope["pay_to"],
        "chain": scope["chain"],
        "token": scope["token"],
        "token_address": scope["token_address"],
        "status": scope["status"],
        "tx_hash": scope["tx_hash"],
        "next_action": scope["next_action"],
        "created_at": scope["created_at"],
        "metadata": {
            "receipt_scope": scope,
            "receipt_signature": signature,
        },
        "event_log": scope["event_log"],
    }
    return base64.urlsafe_b64encode(
        json.dumps(receipt, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def _expected_hashes(*pairs: tuple[str, str]) -> dict[str, str]:
    return {purchase_id: _digest({"csv_text": csv_text}) for purchase_id, csv_text in pairs}


def _post(
    merchant: ReviewMerchant,
    csv_text: str,
    purchase_id: str = "purchase_review_1",
    receipt: str | None = None,
) -> httpx.Response:
    return httpx.post(
        merchant.endpoint,
        headers={
            **HEADERS,
            "Idempotency-Key": purchase_id,
            "X-CLINK-PAYMENT-RECEIPT": receipt or _receipt(merchant, purchase_id),
        },
        json={"csv_text": csv_text},
        timeout=5,
    )


def test_reconcile_csv_returns_normalized_signed_decimal_totals():
    result = reconcile_csv(
        _csv(
            "t-1,2026-09-01,Client payment,+100.00,usd,income",
            "t-2,2026-09-02,Coffee,-12.50,USD,meals",
            "t-3,2026-09-03,Refund,+2.25,USD,meals",
        )
    )

    assert result == {
        "input_row_count": 3,
        "unique_transaction_count": 3,
        "duplicate_ids": [],
        "duplicate_handling": (
            "identical duplicate rows count toward input_row_count but are "
            "ignored once for reconciliation totals; conflicting transaction_id "
            "rows are rejected"
        ),
        "income_totals": {"USD": "102.25"},
        "expense_totals": {"USD": "12.50"},
        "net_totals": {"USD": "89.75"},
        "by_category": {
            "income": {"USD": "100.00"},
            "meals": {"USD": "-10.25"},
        },
    }


def test_reconcile_csv_deduplicates_identical_rows_but_rejects_conflicts():
    csv_text = _csv(
        "t-1,2026-09-01,Client payment,100.00,USD,income",
        "t-1,2026-09-01,Client payment,100.00,usd,income",
    )
    result = reconcile_csv(csv_text)

    assert result["input_row_count"] == 2
    assert result["unique_transaction_count"] == 1
    assert result["duplicate_ids"] == ["t-1"]
    assert result["income_totals"] == {"USD": "100.00"}

    with pytest.raises(ValueError, match="conflicting duplicate"):
        reconcile_csv(
            _csv(
                "t-1,2026-09-01,Client payment,100.00,USD,income",
                "t-1,2026-09-01,Changed payment,100.00,USD,income",
            )
        )


@pytest.mark.parametrize(
    "csv_text, message",
    [
        (
            "transaction_id,date,description,amount,currency,category\n"
            "t-1,09/01/2026,Payment,1.00,USD,income\n",
            "date",
        ),
        (
            "transaction_id,date,description,amount,currency,category\n"
            "t-1,2026-09-01,Payment,1.0,USD,income\n",
            "amount",
        ),
        (
            "transaction_id,date,description,amount,currency,category\n"
            "t-1,2026-09-01,Payment,1.00,US,income\n",
            "currency",
        ),
        (
            "transaction_id,date,description,wrong,currency,category\n"
            "t-1,2026-09-01,Payment,1.00,USD,income\n",
            "header",
        ),
    ],
)
def test_reconcile_csv_rejects_invalid_rows(csv_text: str, message: str):
    with pytest.raises(ValueError, match=message):
        reconcile_csv(csv_text)


def test_reconcile_csv_rejects_mixed_currencies():
    with pytest.raises(ValueError, match="mixed currencies"):
        reconcile_csv(
            _csv(
                "t-1,2026-09-01,Payment,1.00,USD,income",
                "t-2,2026-09-02,Payment,2.00,EUR,income",
            )
        )


def test_reconcile_csv_enforces_row_and_utf8_size_bounds():
    rows = [f"t-{index},2026-09-01,Payment,1.00,USD,income" for index in range(1001)]
    with pytest.raises(ValueError, match="1000"):
        reconcile_csv(
            "transaction_id,date,description,amount,currency,category\n"
            + "\n".join(rows)
            + "\n"
        )

    with pytest.raises(ValueError, match="128 KiB"):
        reconcile_csv(
            _csv("t-1,2026-09-01," + ("x" * (128 * 1024)) + ",1.00,USD,income")
        )


def test_review_merchant_accepts_real_loopback_http_and_replays_after_restart(tmp_path: Path):
    csv_text = _csv(
        "t-1,2026-09-01,Client payment,100.00,USD,income",
        "t-2,2026-09-02,Coffee,-12.50,USD,meals",
    )
    hashes = _expected_hashes(("purchase_review_1", csv_text))
    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
        expected_input_hash=hashes.get,
    ) as merchant:
        assert merchant.endpoint.startswith("http://127.0.0.1:")
        first = _post(merchant, csv_text)
        replay = _post(merchant, csv_text)

        assert first.status_code == 200
        assert replay.status_code == 200
        assert replay.json() == first.json()
        assert first.json()["real_funds"] is False
        assert first.json()["settlement_mode"] == "simulated"
        assert first.json()["income_totals"] == {"USD": "100.00"}
        assert merchant.delivery_count == 1

    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
        expected_input_hash=hashes.get,
    ) as restarted:
        recovered = _post(restarted, csv_text)
        assert recovered.status_code == 200
        assert recovered.json() == first.json()
        assert restarted.delivery_count == 1


def test_review_merchant_binds_a_logical_resource_while_serving_loopback(tmp_path: Path):
    csv_text = _csv("t-1,2026-09-01,Payment,1.00,USD,income")
    hashes = _expected_hashes(("purchase_review_1", csv_text))
    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
        resource="https://merchant.agentonomy.invalid/v1/reconcile",
        expected_input_hash=hashes.get,
    ) as merchant:
        response = _post(merchant, csv_text)
        loopback_endpoint = merchant.endpoint

    assert response.status_code == 200
    assert loopback_endpoint.startswith("http://127.0.0.1:")


def test_review_merchant_rejects_tampered_receipts_and_body_reuse(tmp_path: Path):
    csv_text = _csv("t-1,2026-09-01,Payment,1.00,USD,income")
    other_csv = _csv("t-1,2026-09-01,Payment,2.00,USD,income")
    hashes = _expected_hashes(("purchase_review_1", csv_text))
    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
        expected_input_hash=hashes.get,
    ) as merchant:
        missing = httpx.post(
            merchant.endpoint,
            headers={**HEADERS, "Idempotency-Key": "purchase_review_1"},
            json={"csv_text": csv_text},
            timeout=5,
        )
        altered = _post(
            merchant,
            csv_text,
            receipt=_receipt(merchant, "purchase_review_1", pay_to="0x" + "55" * 20),
        )
        accepted = _post(merchant, csv_text)
        changed = _post(merchant, other_csv)

        assert missing.status_code == 401
        assert altered.status_code == 401
        assert accepted.status_code == 200
        assert changed.status_code == 409


def test_review_merchant_requires_runtime_input_hash(tmp_path: Path):
    csv_text = _csv("t-1,2026-09-01,Payment,1.00,USD,income")
    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
    ) as merchant:
        response = _post(merchant, csv_text)

    assert response.status_code == 503


def test_review_merchant_rejects_signed_scope_bounds(tmp_path: Path):
    csv_text = _csv("t-1,2026-09-01,Payment,1.00,USD,income")
    hashes = _expected_hashes(("purchase_review_1", csv_text))
    with ReviewMerchant(
        tmp_path,
        receipt_secret=SECRET,
        network=NETWORK,
        token=TOKEN,
        pay_to=PAY_TO,
        port=0,
        expected_input_hash=hashes.get,
    ) as merchant:
        too_expensive = _post(
            merchant,
            csv_text,
            receipt=_receipt(merchant, "purchase_review_1", amount_usdc="0.80"),
        )
        unsettled = _post(
            merchant,
            csv_text,
            receipt=_receipt(merchant, "purchase_review_1", status="pending"),
        )

    assert too_expensive.status_code == 401
    assert unsettled.status_code == 401
