from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import inspect
import threading

import pytest
from sqlalchemy import inspect as sqlalchemy_inspect, select
from sqlalchemy.dialects import postgresql

from services.funding_service.ledger import (
    FundingLedger,
    FundingTransaction,
    PaymentCapabilityRow,
)
from shared.payment_capability import PAYMENT_CAPABILITY_VERSION, PaymentCapabilityV1


def capability_for(**updates: object) -> PaymentCapabilityV1:
    values: dict[str, object] = {
        "capability_version": PAYMENT_CAPABILITY_VERSION,
        "capability_id": "capability_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "wallet_identity_id": "identity_1",
        "wallet_address": "0x" + "11" * 20,
        "spending_grant_id": "grant_1",
        "spending_grant_hash": "0x" + "12" * 32,
        "asset_allowance_id": "allowance_1",
        "action_id": "action_1",
        "policy_decision_id": "policy_1",
        "policy_snapshot_hash": "0x" + "13" * 32,
        "risk_evidence_hash": "0x" + "14" * 32,
        "reservation_id": "reservation_1",
        "reservation_hash": "0x" + "19" * 32,
        "purchase_id": "purchase_1",
        "merchant_id": "merchant_1",
        "product": "marketplace",
        "venue": "clink_marketplace",
        "quote_hash": "0x" + "15" * 32,
        "payment_challenge_hash": "0x" + "16" * 32,
        "network": "eip155:8453",
        "asset_contract": "0x" + "22" * 20,
        "amount_atomic": "1000000",
        "pay_to": "0x" + "33" * 20,
        "executor_contract": "0x" + "44" * 20,
        "execution_scope_hash": "0x" + "17" * 32,
        "confirmation_mode": "policy_approved",
        "revocation_id": "0x" + "18" * 32,
        "issued_at": 2_000_000_000,
        "expires_at": 2_000_000_060,
    }
    values.update(updates)
    return PaymentCapabilityV1(**values)


@pytest.fixture
def ledger(tmp_path) -> FundingLedger:
    return FundingLedger(f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}")


def test_funding_payment_capability_table_is_dedicated_and_immutable(ledger) -> None:
    columns = {
        column["name"]
        for column in sqlalchemy_inspect(ledger.engine).get_columns(
            "funding_payment_capabilities"
        )
    }

    assert {
        "capability_id",
        "capability_version",
        "capability_hash",
        "reservation_id",
        "idempotency_key",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "wallet_identity_id",
        "canonical_payload",
        "issued_at",
        "expires_at",
    } <= columns
    assert PaymentCapabilityRow.__tablename__ == "funding_payment_capabilities"


def test_insert_exact_replay_returns_the_same_capability_and_one_row(ledger) -> None:
    capability = capability_for()

    with ledger.transaction() as transaction:
        first = transaction.put_payment_capability(
            capability,
            idempotency_key="reservation_idempotency_1",
        )
    with ledger.transaction() as transaction:
        replay = transaction.put_payment_capability(
            capability,
            idempotency_key="reservation_idempotency_1",
        )
        loaded = transaction.payment_capability_for_reservation("reservation_1")

    assert first == capability
    assert replay == capability
    assert loaded == capability
    with ledger.sessions() as session:
        assert session.scalar(select(PaymentCapabilityRow.capability_id)) == "capability_1"
        assert len(session.scalars(select(PaymentCapabilityRow)).all()) == 1


def test_sqlite_concurrent_exact_replays_return_one_capability(ledger) -> None:
    capability = capability_for()
    start = threading.Barrier(2)

    def insert_exact_replay():
        try:
            start.wait(timeout=2)
            with ledger.transaction() as transaction:
                return transaction.put_payment_capability(
                    capability,
                    idempotency_key="reservation_idempotency_1",
                )
        except Exception as exc:  # pragma: no cover - assertion reports the error
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: insert_exact_replay(), range(2)))

    assert all(outcome == capability for outcome in outcomes), outcomes
    with ledger.sessions() as session:
        assert len(session.scalars(select(PaymentCapabilityRow)).all()) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": "tenant_2"},
        {"node_id": "node_2"},
        {"wallet_binding_id": "binding_2"},
        {"wallet_identity_id": "identity_2"},
        {"amount_atomic": "1000001"},
    ],
)
def test_conflicting_replay_fails_closed(ledger, updates) -> None:
    capability = capability_for()
    with ledger.transaction() as transaction:
        transaction.put_payment_capability(
            capability,
            idempotency_key="reservation_idempotency_1",
        )

    with pytest.raises(ValueError, match="immutable|conflict|mismatch"):
        with ledger.transaction() as transaction:
            transaction.put_payment_capability(
                capability.model_copy(update=updates),
                idempotency_key="reservation_idempotency_1",
            )


def test_reservation_and_idempotency_bindings_cannot_be_reused(ledger) -> None:
    first = capability_for()
    second = capability_for(
        capability_id="capability_2",
        reservation_id="reservation_2",
    )
    with ledger.transaction() as transaction:
        transaction.put_payment_capability(
            first,
            idempotency_key="reservation_idempotency_1",
        )
        with pytest.raises(ValueError, match="conflict|unique|immutable"):
            transaction.put_payment_capability(
                second,
                idempotency_key="reservation_idempotency_1",
            )


def test_postgres_capability_lookup_has_row_lock_contract() -> None:
    statement = (
        select(PaymentCapabilityRow)
        .where(PaymentCapabilityRow.reservation_id == "reservation_1")
        .with_for_update()
    )

    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert "with_for_update" in inspect.getsource(FundingTransaction._locked)


def test_capability_persistence_rejects_non_capability_payload(ledger) -> None:
    with pytest.raises((TypeError, ValueError), match="capability"):
        with ledger.transaction() as transaction:
            transaction.put_payment_capability(
                {"reservation_id": "reservation_1"},
                idempotency_key="reservation_idempotency_1",
            )


def test_generic_ledger_api_cannot_store_or_read_capabilities(ledger) -> None:
    capability = capability_for()
    with pytest.raises(ValueError, match="dedicated"):
        with ledger.transaction() as transaction:
            transaction.put(
                "payment_capability",
                capability.capability_id,
                capability.model_dump(mode="json"),
            )
    with pytest.raises(ValueError, match="dedicated"):
        ledger.list_records("payment_capability")
