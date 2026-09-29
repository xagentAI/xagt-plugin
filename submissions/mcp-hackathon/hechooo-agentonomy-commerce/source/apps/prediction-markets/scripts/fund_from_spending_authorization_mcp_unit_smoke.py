from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import mcp_servers.prediction_markets_server as server  # noqa: E402


def _operation(status: str) -> dict:
    finalized = status == "finalized"
    return {
        "operation_id": "pm_funding_1",
        "user_id": "user-a",
        "binding_id": "binding-a",
        "venue_wallet_address": "0x" + "11" * 20,
        "bridge_address": "0x" + "22" * 20,
        "status": status,
        "amount_usdc": "2.000000",
        "resource": "clink://polymarket/funding",
        "action_id": "action_1" if finalized else None,
        "policy_decision_id": "policy_1" if finalized else None,
        "audit_event_id": "audit_1" if finalized else None,
        "reservation_id": "reservation_1" if finalized else None,
        "core_tx_hash": "0x" + "12" * 32 if finalized else None,
        "core_state": "finalized" if finalized else None,
        "bridge_status": "COMPLETED" if finalized else None,
        "venue_buying_power_before_atomic": "0",
        "venue_buying_power_after_atomic": "2000000" if finalized else None,
        "failure_reason_code": None,
        "confirmed_at": "2026-08-19T00:00:00Z" if finalized else None,
        "finalized_at": "2026-08-19T00:01:00Z" if finalized else None,
        "created_at": "2026-08-19T00:00:00Z",
        "updated_at": "2026-08-19T00:01:00Z",
        "revision": 7 if finalized else 0,
        "next_action": "complete" if finalized else "confirm",
    }


def main() -> None:
    calls: list[tuple[str, str, dict | None]] = []
    original_request_json = server._request_json
    try:
        def fake_request(
            base_url: str,
            path: str,
            payload: dict | None = None,
        ) -> dict:
            calls.append((base_url, path, payload))
            if path == "/polymarket/funding-operations":
                return _operation("created")
            if path == "/polymarket/funding-operations/pm_funding_1/confirm":
                return _operation("finalized")
            if path == "/funding/spending-reservations/reservation_1":
                return {
                    "reservation_id": "reservation_1",
                    "purchase_id": "pm_funding_1",
                    "user_id": "user-a",
                    "amount_usdc": "2.000000",
                    "resource": "clink://polymarket/funding",
                    "state": "finalized",
                    "receipt_id": "fund_receipt_reservation_1",
                    "tx_hash": "0x" + "12" * 32,
                }
            raise AssertionError(f"unexpected request: {path}")

        server._request_json = fake_request
        result = server.fund_polymarket_from_spending_authorization(
            user_id="user-a",
            amount_usdc="2",
            confirmation_id="confirmation-1",
            user_confirmed=True,
        )
    finally:
        server._request_json = original_request_json

    assert result == {
        "status": "settled",
        "operation_id": "pm_funding_1",
        "receipt_id": "fund_receipt_reservation_1",
        "tx_hash": "0x" + "12" * 32,
        "amount_usdc": "2.000000",
        "signing_url": None,
        "next_action": "complete",
    }
    assert calls == [
        (
            server.CONFIG.funding_adapter_url,
            "/polymarket/funding-operations",
            {
                "user_id": "user-a",
                "amount_usdc": "2.000000",
                "idempotency_key": "confirmation-1",
                "resource": "clink://polymarket/funding",
            },
        ),
        (
            server.CONFIG.funding_adapter_url,
            "/polymarket/funding-operations/pm_funding_1/confirm",
            {"user_id": "user-a", "confirmed": True},
        ),
        (
            server.CONFIG.clink_core_funding_service_url,
            "/funding/spending-reservations/reservation_1",
            None,
        ),
    ]
    assert list(
        inspect.signature(
            server.fund_polymarket_from_spending_authorization
        ).parameters
    ) == [
        "user_id",
        "amount_usdc",
        "confirmation_id",
        "user_confirmed",
        "resource",
        "metadata",
        "opc_installation_id",
    ]
    print(result)


if __name__ == "__main__":
    main()
