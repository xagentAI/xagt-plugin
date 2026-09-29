"""Focused end-to-end coverage for the local Commerce purchase loop.

These tests deliberately use the real Marketplace repository and purchase
service through ``CommerceRuntime``.  The CoreBridge remains the only source
of authorization and settlement decisions; the tests do not install a fake
Core implementation.
"""

from __future__ import annotations

from examples.commerce.marketplace import CommerceRuntime


ORDERS = {
    "orders": [
        {"amount": "12.50", "category": "produce"},
        {"amount": "7.25", "category": "staples"},
        {"amount": "2.00", "category": "produce"},
    ]
}


def _offering(runtime: CommerceRuntime, price: str) -> dict:
    matches = [
        item
        for item in runtime.search("analysis")["items"]
        if item["price_usd"] == price
    ]
    assert len(matches) == 1
    return matches[0]


def test_catalog_exposes_two_verified_order_analysis_prices(tmp_path):
    with CommerceRuntime(tmp_path) as runtime:
        catalog = runtime.search("analysis")

        assert {item["price_usd"] for item in catalog["items"]} == {
            "0.30",
            "0.80",
        }
        for item in catalog["items"]:
            assert item["offering_id"]
            assert item["offer_id"] == item["offering_id"]
            details = runtime.details(item["offering_id"])
            assert details["offering"]["offering_id"] == item["offering_id"]


def test_purchase_delivers_order_analysis_and_updates_core_budget(tmp_path):
    with CommerceRuntime(tmp_path) as runtime:
        item = _offering(runtime, "0.30")
        preview = runtime.preview(item["offering_id"], ORDERS)

        result = runtime.execute(preview["preview_id"])

        assert result["state"] == "delivered"
        assert result["service_result"] == {
            "count": 3,
            "total": "21.75",
            "by_category": {"produce": "14.50", "staples": "7.25"},
        }
        snapshot = runtime.snapshot()
        assert snapshot["used_amount_usdc"] == "0.30"
        assert snapshot["reserved_amount_usdc"] == "0.00"
        assert snapshot["remaining_amount_usdc"] == "0.70"
        assert snapshot["settlement_submissions"] == 1
        assert snapshot["merchant_deliveries"] == 1
        assert "receipt_signing_key" not in snapshot


def test_replaying_same_preview_does_not_settle_or_deliver_twice(tmp_path):
    with CommerceRuntime(tmp_path) as runtime:
        item = _offering(runtime, "0.30")
        preview = runtime.preview(item["offering_id"], ORDERS)
        first = runtime.execute(preview["preview_id"])
        before = runtime.snapshot()

        replay = runtime.execute(preview["preview_id"])
        after = runtime.snapshot()

        assert replay["purchase_id"] == first["purchase_id"]
        assert replay["state"] == "delivered"
        assert replay["service_result"] == first["service_result"]
        assert after["settlement_submissions"] == before["settlement_submissions"] == 1
        assert after["merchant_deliveries"] == before["merchant_deliveries"] == 1


def test_second_purchase_over_budget_is_rejected_without_settlement(tmp_path):
    with CommerceRuntime(tmp_path) as runtime:
        cheap = _offering(runtime, "0.30")
        expensive = _offering(runtime, "0.80")
        runtime.execute(runtime.preview(cheap["offering_id"], ORDERS)["preview_id"])
        preview = runtime.preview(expensive["offering_id"], ORDERS)
        before = runtime.snapshot()

        blocked = runtime.execute(preview["preview_id"])

        after = runtime.snapshot()
        assert blocked["state"] == "confirmation_required"
        assert blocked["reason_code"] == "BUDGET_EXCEEDED"
        assert after["used_amount_usdc"] == before["used_amount_usdc"] == "0.30"
        assert after["settlement_submissions"] == before["settlement_submissions"] == 1


def test_revoked_authorization_is_rejected_before_settlement(tmp_path):
    with CommerceRuntime(tmp_path) as runtime:
        item = _offering(runtime, "0.30")
        preview = runtime.preview(item["offering_id"], ORDERS)
        runtime.revoke()

        blocked = runtime.execute(preview["preview_id"])

        snapshot = runtime.snapshot()
        assert blocked["state"] == "confirmation_required"
        assert blocked["reason_code"] == "SPENDING_GRANT_REQUIRED"
        assert runtime.core.snapshot()["grant_status"] == "revoked"
        assert snapshot["used_amount_usdc"] == "0.00"
        assert snapshot["settlement_submissions"] == 0


def test_paid_but_undelivered_replay_is_terminal_and_free(tmp_path):
    with CommerceRuntime(tmp_path, fail_delivery=True) as runtime:
        item = _offering(runtime, "0.30")
        preview = runtime.preview(item["offering_id"], ORDERS)

        first = runtime.execute(preview["preview_id"])
        before = runtime.snapshot()
        replay = runtime.execute(preview["preview_id"])
        after = runtime.snapshot()

        assert first["state"] == "paid_but_undelivered"
        assert replay["purchase_id"] == first["purchase_id"]
        assert replay["state"] == "paid_but_undelivered"
        assert after["settlement_submissions"] == before["settlement_submissions"] == 1
        assert after["merchant_deliveries"] == before["merchant_deliveries"] == 1
