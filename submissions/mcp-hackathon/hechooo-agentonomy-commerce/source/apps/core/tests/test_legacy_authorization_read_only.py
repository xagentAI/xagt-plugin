from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

import mcp_servers.funding_server as funding_mcp
from services.account_service.repository import AccountRepository
from services.funding_service.schemas import (
    CreateSpendingAuthorizationRequest,
    CreateSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    FinalizeSpendingReservationRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
    SpendFromSpendingAuthorizationRequest,
    SpendingAuthorization,
)
from services.funding_service.service import FundingService
from services.funding_service.ledger import LedgerRow
from shared.config import AppConfig


READ_ONLY_ERROR = "legacy spending authorizations are read-only"


def legacy_authorization() -> SpendingAuthorization:
    return SpendingAuthorization(
        spending_authorization_id="legacy_auth_1",
        user_id="legacy_user",
        agent_id="hermes",
        wallet_address="0x" + "11" * 20,
        max_amount_usdc="10",
        per_order_limit_usdc="5",
        used_amount_usdc="0",
        remaining_amount_usdc="10",
        venue="polymarket",
        chain="eip155:137",
        token="USDC",
        spender_address="0x" + "22" * 20,
        purpose="prediction_market_spending_cap",
        status="active",
        expires_at="2099-01-01T00:00:00Z",
        created_at="2026-07-01T00:00:00Z",
    )


def service_with_legacy_record(tmp_path) -> FundingService:
    record = legacy_authorization()
    storage_file = tmp_path / "funding.jsonl"
    storage_file.write_text(
        json.dumps(
            {
                "record_type": "spending_authorization",
                "record_id": record.spending_authorization_id,
                "payload": record.model_dump(mode="json"),
            }
        )
        + "\n"
    )
    return FundingService(
        config=AppConfig(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
        ),
        storage_file=storage_file,
    )


def create_request() -> CreateSpendingAuthorizationRequest:
    return CreateSpendingAuthorizationRequest(
        user_id="legacy_user",
        agent_id="hermes",
        wallet_address="0x" + "11" * 20,
        max_amount_usdc="10",
        per_order_limit_usdc="5",
        spender_address="0x" + "22" * 20,
    )


def test_service_rejects_legacy_create_spend_and_revoke_but_retains_reads(tmp_path):
    service = service_with_legacy_record(tmp_path)
    spend_request = SpendFromSpendingAuthorizationRequest(
        spending_authorization_id="legacy_auth_1",
        amount_usdc="1",
        destination="0x" + "33" * 20,
    )

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        service.create_spending_authorization(create_request())
    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        service.spend_from_spending_authorization(spend_request)
    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        service.revoke_spending_authorization("legacy_auth_1")

    assert service.get_spending_authorization("legacy_auth_1").legacy is True
    status = service.get_funding_status(user_id="legacy_user")
    assert [item.spending_authorization_id for item in status.spending_authorizations] == [
        "legacy_auth_1"
    ]


def test_service_has_no_private_legacy_mutation_escape_hatches():
    assert not hasattr(FundingService, "_legacy_reserve_spending")
    assert not hasattr(FundingService, "_legacy_spend_from_spending_authorization")
    assert not hasattr(FundingService, "_spend_spending_authorization")
    assert not hasattr(FundingService, "_settle_with_spending_authorization")


def test_expired_legacy_reads_normalize_in_memory_without_writing_jsonl(tmp_path):
    service = service_with_legacy_record(tmp_path)
    record = legacy_authorization().model_copy(
        update={"expires_at": "2020-01-01T00:00:00Z"}
    )
    service.storage_file.write_text(
        json.dumps(
            {
                "record_type": "spending_authorization",
                "record_id": record.spending_authorization_id,
                "payload": record.model_dump(mode="json"),
            }
        )
        + "\n"
    )
    before = service.storage_file.read_bytes()

    authorization = service.get_spending_authorization(record.spending_authorization_id)

    assert authorization.status == "expired"
    assert authorization.remaining_amount_usdc == "0"
    assert service.storage_file.read_bytes() == before

    status = service.get_funding_status(user_id=record.user_id)

    assert status.spending_authorizations[0].status == "expired"
    assert status.available_budget_usdc_by_venue == {}
    assert service.storage_file.read_bytes() == before


def legacy_reservation(state: str) -> dict:
    return {
        "reservation_id": "reserve_legacy_1",
        "purchase_id": "legacy_purchase_1",
        "idempotency_key": "legacy_purchase_1",
        "spending_authorization_id": "legacy_auth_1",
        "authorization_path": "legacy",
        "action_id": "action_legacy_1",
        "policy_decision_id": "policy_legacy_1",
        "merchant_id": "polymarket",
        "quote_hash": "0x" + "aa" * 32,
        "amount_usdc": "1",
        "amount_atomic": "1000000",
        "network": "eip155:137",
        "asset": "USDC",
        "destination": "0x" + "33" * 20,
        "resource": "polymarket:funding",
        "venue": "polymarket",
        "state": state,
        "receipt_id": None,
        "tx_hash": None,
        "created_at": "2026-07-01T00:00:00Z",
    }


def persist_legacy_reservation(service: FundingService, reservation: dict) -> None:
    # Legacy rows are migration fixtures only; bypass the production write API.
    with service.ledger.sessions.begin() as session:
        session.add(
            LedgerRow(
                record_id=reservation["reservation_id"],
                record_type="reservation",
                payload=reservation,
                updated_at=datetime.now(UTC),
                purchase_id=reservation["purchase_id"],
                idempotency_key=reservation["idempotency_key"],
                action_id=reservation["action_id"],
                policy_decision_id=reservation["policy_decision_id"],
                reservation_id=reservation["reservation_id"],
                tx_hash=reservation.get("tx_hash"),
            )
        )


def test_authoritative_ledger_rejects_direct_legacy_reservation_write(tmp_path):
    service = service_with_legacy_record(tmp_path)
    reservation = legacy_reservation("spending_reserved")

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        with service.ledger.transaction() as tx:
            tx.put(
                "reservation",
                reservation["reservation_id"],
                reservation,
                purchase_id=reservation["purchase_id"],
                idempotency_key=reservation["idempotency_key"],
                action_id=reservation["action_id"],
                policy_decision_id=reservation["policy_decision_id"],
                reservation_id=reservation["reservation_id"],
            )

    assert service.get_reservation(reservation["reservation_id"]) is None


@pytest.mark.parametrize(
    "operation",
    [
        lambda service, row: service._pending_reservation(row, "still pending"),
        lambda service, row: service._retryable_reservation(row, "retry later"),
        lambda service, row: service._save_reconciliation_error(
            row["reservation_id"], row["tx_hash"], "rpc unavailable"
        ),
        lambda service, row: _put_legacy_reservation(service, row),
        lambda service, row: _mutate_legacy_budget(service, row, "release"),
        lambda service, row: _mutate_legacy_budget(service, row, "settle"),
    ],
    ids=("pending", "retryable", "save-error", "put", "release", "settle"),
)
def test_private_legacy_reservation_mutation_sinks_fail_without_side_effects(
    tmp_path, operation
):
    rpc_calls = []
    service = service_with_legacy_record(tmp_path)
    service.rpc_transport = lambda method, params: rpc_calls.append((method, params))
    reservation = {
        **legacy_reservation("payment_submitted"),
        "tx_hash": "0x" + "bb" * 32,
        "settlement_rail": "clink_allowance",
    }
    persist_legacy_reservation(service, reservation)
    jsonl_before = service.storage_file.read_bytes()

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        operation(service, reservation)

    assert service.get_reservation(reservation["reservation_id"]) == reservation
    assert service.storage_file.read_bytes() == jsonl_before
    assert rpc_calls == []


def _put_legacy_reservation(service: FundingService, reservation: dict) -> None:
    with service.ledger.transaction() as tx:
        service._put_reservation(
            tx, {**reservation, "last_reconciliation_error": "mutated"}
        )


def _mutate_legacy_budget(
    service: FundingService, reservation: dict, operation: str
) -> None:
    with service.ledger.transaction() as tx:
        if operation == "release":
            tx.release_unified_budget(reservation, now=service._utc_now())
        else:
            tx.settle_unified_budget(reservation, now=service._utc_now())


@pytest.mark.parametrize("sink", ["receipt", "native-prepare"])
def test_private_legacy_spend_sinks_fail_before_jsonl_or_rpc(tmp_path, sink):
    rpc_calls = []
    service = service_with_legacy_record(tmp_path)
    service.rpc_transport = lambda method, params: rpc_calls.append((method, params))
    request = SpendFromSpendingAuthorizationRequest(
        spending_authorization_id="legacy_auth_1",
        amount_usdc="1",
        destination="0x" + "33" * 20,
        resource="polymarket:funding",
    )
    jsonl_before = service.storage_file.read_bytes()

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        if sink == "receipt":
            service._record_spending_receipt(
                legacy_authorization(),
                request,
                "0x" + "cc" * 32,
                receipt_id="fund_receipt_legacy_escape",
            )
        else:
            service._prepare_native_transaction(legacy_authorization(), request)

    assert service.storage_file.read_bytes() == jsonl_before
    assert rpc_calls == []


@pytest.mark.parametrize("sink", ["receipt", "native-prepare"])
def test_forged_nonlegacy_authorization_without_unified_refs_fails_before_sinks(
    tmp_path, sink
):
    relayer_key = "0x" + "44" * 32
    service = service_with_legacy_record(tmp_path)
    service.config.clink_native_facilitator_relayer_private_key = relayer_key
    service.config.x402_payment_token_address = "0x" + "55" * 20
    rpc_calls = []
    service.rpc_transport = lambda method, params: rpc_calls.append((method, params)) or {
        "eth_getTransactionCount": "0x1",
        "eth_gasPrice": "0x1",
        "eth_estimateGas": "0x186a0",
    }[method]
    authorization = legacy_authorization().model_copy(
        update={
            "legacy": False,
            "spender_address": service._native_relayer_address(),
        }
    )
    request = SpendFromSpendingAuthorizationRequest(
        spending_authorization_id=authorization.spending_authorization_id,
        amount_usdc="1",
        destination="0x" + "33" * 20,
        resource="polymarket:funding",
    )
    jsonl_before = service.storage_file.read_bytes()

    with pytest.raises(ValueError, match="unified authorization provenance"):
        if sink == "receipt":
            service._record_spending_receipt(
                authorization,
                request,
                "0x" + "cc" * 32,
                receipt_id="fund_receipt_forged_nonlegacy",
            )
        else:
            service._prepare_native_transaction(authorization, request)

    assert service.storage_file.read_bytes() == jsonl_before
    assert rpc_calls == []


def test_native_rebroadcast_sink_rejects_forged_unified_row_before_rpc(tmp_path):
    service = service_with_legacy_record(tmp_path)
    AccountRepository(service.config.funding_database_url)
    reservation = {
        **legacy_reservation("payment_submitted"),
        "authorization_path": "unified_grant",
        "wallet_identity_id": "wallet_identity_forged",
        "spending_grant_id": "spending_grant_forged",
        "asset_allowance_id": "asset_allowance_forged",
        "product": "prediction_markets",
        "token_address": "0x" + "55" * 20,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "spender_address": "0x" + "66" * 20,
        "settlement_rail": "clink_allowance",
        "settlement_sender": "0x" + "66" * 20,
        "settlement_nonce": 1,
        "settlement_raw_transaction": "0xsigned",
        "tx_hash": "0x" + "bb" * 32,
    }
    persist_legacy_reservation(service, reservation)
    rpc_calls = []
    service.rpc_transport = lambda method, params: rpc_calls.append((method, params))

    with pytest.raises(ValueError, match="unified authorization references"):
        service._reconcile_native_reservation(reservation)

    assert rpc_calls == []


@pytest.mark.parametrize(
    ("state", "operation"),
    [
        (
            "spending_reserved",
            lambda service: service.settle_reservation(
                "reserve_legacy_1", SettleSpendingReservationRequest()
            ),
        ),
        (
            "settled",
            lambda service: service.finalize_reservation(
                "reserve_legacy_1",
                FinalizeSpendingReservationRequest(delivery_status="delivered"),
            ),
        ),
        (
            "spending_reserved",
            lambda service: service.release_reservation(
                "reserve_legacy_1", ReleaseSpendingReservationRequest(reason="cancelled")
            ),
        ),
        (
            "spending_reserved",
            lambda service: service.finalize_external_payment(
                "reserve_legacy_1",
                FinalizeExternalPaymentRequest(
                    transaction_hash="0x" + "bb" * 32,
                    payment_response={
                        "network": "base",
                        "asset": "usdc",
                        "amount_atomic": "1000000",
                        "pay_to": "0x" + "11" * 20,
                        "nonce": "0x" + "22" * 32,
                        "valid_after": "0",
                        "valid_before": "1",
                    },
                ),
            ),
        ),
        (
            "payment_submitted",
            lambda service: service.reconcile_reservation("reserve_legacy_1"),
        ),
    ],
    ids=("settle", "finalize", "release", "external-finalize", "reconcile"),
)
def test_every_legacy_reservation_lifecycle_operation_fails_closed(
    tmp_path, state, operation
):
    service = service_with_legacy_record(tmp_path)
    reservation = legacy_reservation(state)
    persist_legacy_reservation(service, reservation)

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        operation(service)

    assert service.get_reservation(reservation["reservation_id"]) == reservation


def test_service_rejects_reserving_against_a_legacy_authorization(tmp_path):
    service = service_with_legacy_record(tmp_path)
    service._verify_marketplace_provenance = lambda _: SimpleNamespace(
        authorization_path="legacy",
        action=SimpleNamespace(user_id="legacy_user", agent_id="hermes"),
    )
    request = CreateSpendingReservationRequest(
        purchase_id="legacy_purchase_1",
        idempotency_key="legacy_purchase_1",
        spending_authorization_id="legacy_auth_1",
        action_id="action_legacy_1",
        policy_decision_id="policy_legacy_1",
        merchant_id="polymarket",
        quote_hash="0x" + "aa" * 32,
        amount_usdc="1",
        amount_atomic="1000000",
        network="eip155:137",
        asset="USDC",
        destination="0x" + "33" * 20,
        resource="polymarket:funding",
        venue="polymarket",
    )

    with pytest.raises(ValueError, match=READ_ONLY_ERROR):
        service.reserve_spending(request)


def test_http_and_mcp_expose_only_legacy_read_surfaces(tmp_path, monkeypatch):
    service = service_with_legacy_record(tmp_path)
    config = AppConfig(clink_internal_api_token="test-internal-token")
    monkeypatch.setenv(
        "CLINK_FUNDING_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'http.sqlite3'}",
    )
    monkeypatch.setenv("FUNDING_SESSION_FILE", str(tmp_path / "http.jsonl"))
    funding_app = importlib.import_module("services.funding_service.app")
    monkeypatch.setattr(funding_app, "SERVICE", service)
    monkeypatch.setattr(funding_app, "APP_CONFIG", config)
    app = funding_app.create_app()

    async def call_http():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://funding.internal"
        ) as client:
            headers = {"Authorization": "Bearer test-internal-token"}
            create = await client.post(
                "/funding/spending-authorizations",
                headers=headers,
                json=create_request().model_dump(),
            )
            spend = await client.post(
                "/funding/spending-authorizations/legacy_auth_1/spend",
                headers=headers,
                json={
                    "spending_authorization_id": "legacy_auth_1",
                    "amount_usdc": "1",
                    "destination": "0x" + "33" * 20,
                },
            )
            revoke = await client.post(
                "/funding/spending-authorizations/legacy_auth_1/revoke",
                headers=headers,
                json={},
            )
            read = await client.get(
                "/funding/spending-authorizations/legacy_auth_1", headers=headers
            )
            status = await client.get(
                "/funding/status", headers=headers, params={"user_id": "legacy_user"}
            )
            return create, spend, revoke, read, status

    create, spend, revoke, read, status = asyncio.run(call_http())
    assert all(
        response.status_code in {404, 405} for response in (create, spend, revoke)
    )
    assert read.status_code == 200
    assert read.json()["legacy"] is True
    assert status.status_code == 200
    assert status.json()["spending_authorizations"][0]["legacy"] is True

    tool_names = {
        tool.name for tool in asyncio.run(funding_mcp.MCP_SERVER.list_tools())
    }
    assert tool_names == {"funding_service_health", "get_funding_status"}
