from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Barrier, Event, Lock
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    create_engine,
    inspect as sa_inspect,
    text,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError, StatementError
from sqlalchemy.schema import CreateTable

import services.funding_adapter_service.repository as funding_repository
import services.funding_adapter_service.schemas as funding_schemas
import services.funding_adapter_service.coordinator as funding_coordinator


USER_ID = "telegram_user_1"
AGENT_ID = "hermes_agent_1"
OPERATION_ID = "pm_funding_operation_1"
IDEMPOTENCY_KEY = "pm_funding_idempotency_1"
BINDING_ID = "pm_binding_1"
VENUE_WALLET = "0x1111111111111111111111111111111111111111"
BRIDGE_ADDRESS = "0x2222222222222222222222222222222222222222"
SOURCE_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
DESTINATION_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
SPENDER_ADDRESS = "0x4444444444444444444444444444444444444444"
OPC_INSTALLATION_ID = "opc_" + "a" * 40
OTHER_OPC_INSTALLATION_ID = "opc_" + "b" * 40
REQUEST_HASH = "0x" + "a" * 64
QUOTE_HASH = "0x" + "b" * 64
TX_HASH = "0x" + "c" * 64
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
UINT256_MAX_ATOMIC = str(2**256 - 1)


def _amount_usdc(amount_atomic: str) -> str:
    padded = amount_atomic.zfill(7)
    return f"{padded[:-6]}.{padded[-6:]}"


def _operation(**updates: object):
    operation_type = getattr(funding_schemas, "PolymarketFundingOperation")
    values: dict[str, object] = {
        "operation_id": OPERATION_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "binding_id": BINDING_ID,
        "venue_wallet_address": VENUE_WALLET,
        "bridge_address": BRIDGE_ADDRESS,
        "source_network": "eip155:137",
        "source_token_address": SOURCE_TOKEN,
        "destination_network": "eip155:137",
        "destination_token_address": DESTINATION_TOKEN,
        "amount_usdc": "1.000000",
        "amount_atomic": "1000000",
        "resource": "polymarket:funding:pm_binding_1",
        "request_hash": REQUEST_HASH,
        "quote_hash": QUOTE_HASH,
        "wallet_identity_id": "wallet_identity_1",
        "spending_grant_id": "spending_grant_1",
        "asset_allowance_id": "asset_allowance_1",
        "spender_address": SPENDER_ADDRESS,
        "venue_buying_power_before_atomic": "0",
        "risk_assessment_id": "risk_pm_funding_operation_1",
        "risk_level": "low",
        "risk_score": 0,
        "risk_action": "approve",
        "risk_assessed_at": NOW,
        "status": "created",
        "revision": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    if "risk_assessment_id" not in updates:
        values["risk_assessment_id"] = f"risk_{values['idempotency_key']}"
    return operation_type.model_validate(values)


def _target(**updates: object):
    values: dict[str, object] = {
        "deposit_id": "pm_deposit_1",
        "user_id": USER_ID,
        "binding_id": BINDING_ID,
        "venue_wallet_address": VENUE_WALLET,
        "bridge_address": BRIDGE_ADDRESS,
        "source_network": "eip155:137",
        "source_token_address": SOURCE_TOKEN,
        "destination_network": "eip155:137",
        "destination_token_address": DESTINATION_TOKEN,
        "status": "ready",
        "created_at": NOW,
    }
    values.update(updates)
    return funding_schemas.PolymarketBridgeDeposit.model_validate(values)


def _seeded_repository(database):
    repository = funding_repository.SQLiteBridgeRepository(database)
    repository.save_deposit_target(_target())
    return repository


def _replacement(operation, *, status: str, **updates: object):
    values: dict[str, object] = {
        "status": status,
        "revision": operation.revision + 1,
        "updated_at": operation.updated_at + timedelta(seconds=1),
    }
    values.update(updates)
    return operation.model_copy(update=values)


def _advance(repository, current, status: str, **updates: object):
    if status == "reserved" and current.status == "policy_approved":
        current = _advance(repository, current, "reservation_creating")
    if status == "finalized" and current.status == "venue_credited":
        current = _advance(repository, current, "finalizing")
    defaults: dict[str, object] = {}
    if status == "confirmed":
        defaults["confirmed_at"] = current.updated_at + timedelta(seconds=1)
    if status == "action_created":
        defaults["action_id"] = "core_action_1"
    if status == "policy_approved":
        defaults["policy_decision_id"] = "core_policy_1"
    if status == "reserved":
        defaults.update(
            audit_event_id="core_audit_1",
            reservation_id="core_reservation_1",
            core_state="spending_reserved",
        )
    if status == "submitted":
        defaults.update(core_tx_hash=TX_HASH, core_state="payment_submitted")
    if status in {"chain_confirmed", "bridge_pending"}:
        defaults.update(core_tx_hash=TX_HASH, core_state="settled")
    defaults.update(updates)
    replacement = _replacement(current, status=status, **defaults)
    result = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=replacement,
    )
    assert result is not None
    return result


def _terminalize(repository, current, status: str):
    if status == "finalized":
        for next_status in (
            "confirmed",
            "action_creating",
            "action_created",
            "policy_evaluating",
            "policy_approved",
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
            "submitted",
            "chain_confirmed",
            "bridge_pending",
        ):
            current = _advance(repository, current, next_status)
        current = _advance(
            repository,
            current,
            "venue_credited",
            bridge_observation_id="pm_observation_terminal_scope",
            bridge_status="COMPLETED",
            venue_buying_power_after_atomic="1000000",
        )
        return _advance(
            repository,
            current,
            "finalized",
            core_state="finalized",
            finalized_at=current.updated_at + timedelta(seconds=1),
        )

    replacement = _replacement(
        current,
        status=status,
        failure_reason_code="OPERATION_TERMINATED",
    )
    result = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=replacement,
    )
    assert result is not None
    return result


def _create_v1_sqlite_database(database) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        funding_repository.BridgeSchemaVersionRow.__table__.create(connection)
        funding_repository.BridgeDepositTargetRow.__table__.create(connection)
        funding_repository.BridgeDepositClaimRow.__table__.create(connection)
        funding_repository.BridgeObservationRow.__table__.create(connection)
        connection.execute(
            funding_repository.BridgeSchemaVersionRow.__table__.insert().values(
                singleton=1, version=1
            )
        )
        connection.execute(
            funding_repository.BridgeDepositTargetRow.__table__.insert().values(
                deposit_id="pm_deposit_legacy",
                user_id=USER_ID,
                binding_id=BINDING_ID,
                venue_wallet_address=VENUE_WALLET,
                bridge_address=BRIDGE_ADDRESS,
                source_network="eip155:137",
                source_token_address=SOURCE_TOKEN,
                destination_network="eip155:137",
                destination_token_address=DESTINATION_TOKEN,
                status="ready",
                created_at=NOW,
            )
        )
        connection.execute(
            funding_repository.BridgeObservationRow.__table__.insert().values(
                observation_id="pm_observation_legacy",
                user_id=USER_ID,
                binding_id=BINDING_ID,
                venue_wallet_address=VENUE_WALLET,
                bridge_address=BRIDGE_ADDRESS,
                source_network="eip155:137",
                source_token_address=SOURCE_TOKEN,
                destination_network="eip155:137",
                destination_token_address=DESTINATION_TOKEN,
                status="COMPLETED",
                tx_hash=TX_HASH,
                amount_atomic="1000000",
                checked_at=NOW,
                bridge_created_time_ms=1787121600000,
            )
        )
    engine.dispose()


def _without_opc_installation_schema_item(create_sql: str) -> str:
    """Render the deployed v2/v3 operation table from current SQLite DDL."""
    open_paren = create_sql.index("(")
    close_paren = create_sql.rindex(")")
    body = create_sql[open_paren + 1 : close_paren]
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for offset, character in enumerate(body):
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            items.append(body[start:offset])
            start = offset + 1
    items.append(body[start:])
    legacy_items = [
        item
        for item in items
        if not item.strip().lower().startswith("opc_installation_id ")
        and not item.strip().lower().startswith(
            "constraint ck_pm_funding_opc_installation "
        )
    ]
    assert len(items) - len(legacy_items) == 2
    return (
        create_sql[: open_paren + 1]
        + ",".join(legacy_items)
        + create_sql[close_paren:]
    )


def _downgrade_sqlite_operation_schema(database, *, version: int) -> None:
    """Turn a current fixture into the exact column shape used by v2/v3."""
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            f"DROP TRIGGER {funding_repository._OPERATION_UPDATE_GUARD_NAME}"
        )
        connection.execute(
            f"DROP TRIGGER {funding_repository._OPERATION_INSERT_GUARD_NAME}"
        )
        create_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'polymarket_funding_operations'"
        ).fetchone()[0]
        legacy_sql = _without_opc_installation_schema_item(create_sql).replace(
            "CREATE TABLE polymarket_funding_operations",
            "CREATE TABLE polymarket_funding_operations_legacy",
            1,
        )
        connection.execute(legacy_sql)
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(polymarket_funding_operations)"
            )
            if row[1] != "opc_installation_id"
        ]
        rendered_columns = ", ".join(f'"{column}"' for column in columns)
        connection.execute(
            "INSERT INTO polymarket_funding_operations_legacy "
            f"({rendered_columns}) SELECT {rendered_columns} "
            "FROM polymarket_funding_operations"
        )
        connection.execute("DROP TABLE polymarket_funding_operations")
        connection.execute(
            "ALTER TABLE polymarket_funding_operations_legacy "
            "RENAME TO polymarket_funding_operations"
        )
        for statement in funding_repository._sqlite_operation_guard_statements(
            version=version
        ).values():
            connection.execute(statement)
        connection.execute(
            "UPDATE polymarket_bridge_schema_version "
            "SET version = ? WHERE singleton = 1",
            (version,),
        )


def test_funding_operation_model_is_frozen_strict_exact_and_secret_free() -> None:
    operation = _operation()

    assert operation.amount_usdc == "1.000000"
    assert operation.amount_atomic == "1000000"
    assert operation.venue_buying_power_before_atomic == "0"
    assert operation.created_at.tzinfo is UTC
    assert operation.model_dump().keys().isdisjoint(
        {"secret", "private_key", "raw_response", "raw_transaction", "signed_transaction"}
    )
    assert "secret" not in repr(operation).lower()
    assert "raw_transaction" not in repr(operation).lower()

    with pytest.raises(ValidationError):
        operation.status = "confirmed"
    with pytest.raises(ValidationError):
        _operation(amount_usdc=1.0)
    with pytest.raises(ValidationError):
        _operation(amount_atomic=1_000_000)
    with pytest.raises(ValidationError, match="amount_usdc and amount_atomic"):
        _operation(amount_usdc="2.000000")
    with pytest.raises(ValidationError):
        _operation(raw_transaction="0xmust-not-be-accepted")


def test_funding_models_accept_only_canonical_optional_opc_installation_id() -> None:
    assert _operation(
        opc_installation_id=OPC_INSTALLATION_ID
    ).opc_installation_id == OPC_INSTALLATION_ID
    assert _prepare_request(
        opc_installation_id=OPC_INSTALLATION_ID
    ).opc_installation_id == OPC_INSTALLATION_ID
    assert _confirm_request(
        opc_installation_id=OPC_INSTALLATION_ID
    ).opc_installation_id == OPC_INSTALLATION_ID
    assert funding_schemas.AdvancePolymarketFundingOperationRequest(
        user_id=USER_ID,
        opc_installation_id=OPC_INSTALLATION_ID,
    ).opc_installation_id == OPC_INSTALLATION_ID

    for invalid in (
        "opc_" + "A" * 40,
        "opc_" + "a" * 39,
        "opc_" + "g" * 40,
        "installation_" + "a" * 40,
    ):
        with pytest.raises(ValidationError):
            _prepare_request(opc_installation_id=invalid)


def test_funding_operation_failure_proof_is_explicit_and_validation_is_redacted() -> None:
    operation = _operation()
    assert operation.core_replacement_forbidden is False
    assert operation.core_failure_evidence_kind is None

    marker = "raw-transaction-secret-marker"
    values = operation.model_dump()
    values["request_hash"] = marker
    with pytest.raises(ValidationError) as captured:
        type(operation).model_validate(values)
    assert marker not in str(captured.value)


def test_funding_operation_is_not_an_http_request_dto_and_repository_errors_are_fixed(
    tmp_path,
) -> None:
    assert "not an HTTP request DTO" in (
        funding_schemas.PolymarketFundingOperation.__doc__ or ""
    )
    repository = _seeded_repository(tmp_path / "structured-error.sqlite3")
    marker = "raw-transaction-secret-marker"
    invalid = _operation().model_copy(update={"resource": marker + " with spaces"})

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is invalid",
    ) as captured:
        repository.create_funding_operation(invalid)
    assert marker not in str(captured.value)
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_funding_operation_preserves_uint256_precision_and_rejects_noncanonical_values(
    tmp_path,
) -> None:
    operation = _operation(
        amount_usdc=_amount_usdc(UINT256_MAX_ATOMIC),
        amount_atomic=UINT256_MAX_ATOMIC,
        venue_buying_power_before_atomic=UINT256_MAX_ATOMIC,
    )
    assert operation.amount_atomic == UINT256_MAX_ATOMIC
    assert operation.amount_usdc == _amount_usdc(UINT256_MAX_ATOMIC)
    credited = _operation(
        status="venue_credited",
        confirmed_at=NOW,
        action_id="core_action_precision",
        policy_decision_id="core_policy_precision",
        audit_event_id="core_audit_precision",
        reservation_id="core_reservation_precision",
        core_tx_hash=TX_HASH,
        core_state="settled",
        bridge_observation_id="pm_observation_precision",
        bridge_status="COMPLETED",
        venue_buying_power_after_atomic=UINT256_MAX_ATOMIC,
    )
    assert credited.venue_buying_power_after_atomic == UINT256_MAX_ATOMIC
    repository = _seeded_repository(tmp_path / "uint256.sqlite3")
    stored, created = repository.create_funding_operation(operation)
    assert created is True
    assert stored.amount_atomic == UINT256_MAX_ATOMIC
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=OPERATION_ID,
    ).amount_usdc == _amount_usdc(UINT256_MAX_ATOMIC)

    invalid_updates = (
        {"amount_usdc": "1"},
        {"amount_usdc": "01.000000"},
        {"amount_usdc": "1.00000"},
        {"amount_atomic": "0", "amount_usdc": "0.000000"},
        {"amount_atomic": str(2**256), "amount_usdc": _amount_usdc(str(2**256))},
        {"venue_buying_power_before_atomic": "00"},
        {"venue_buying_power_before_atomic": str(2**256)},
        {"request_hash": "0x" + "A" * 64},
        {"revision": -1},
        {"created_at": datetime(2026, 8, 19, 12, 0)},
    )
    for updates in invalid_updates:
        with pytest.raises(ValidationError):
            _operation(**updates)


def test_funding_operation_status_contract_includes_plan_and_recovery_states() -> None:
    statuses = {
        "created",
        "confirmed",
        "action_creating",
        "action_unknown",
        "action_created",
        "policy_evaluating",
        "policy_unknown",
        "policy_approved",
        "reservation_creating",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "settlement_unknown",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
        "venue_credited",
        "finalizing",
        "finalized",
        "failed",
        "released",
        "manual_review",
    }
    assert set(get_args(funding_schemas.FundingOperationStatus)) == statuses
    with pytest.raises(ValidationError):
        _operation(status="retrying_transfer")


def test_funding_status_contract_owns_actions_and_pending_subset() -> None:
    statuses = set(get_args(funding_schemas.FundingOperationStatus))

    assert funding_schemas.FUNDING_OPERATION_STATUSES == statuses
    assert funding_schemas.FUNDING_OPERATION_PENDING_STATUSES < statuses
    assert funding_schemas.FUNDING_OPERATION_PENDING_STATUSES == statuses - {
        "created",
        "finalized",
        "failed",
        "released",
    }
    assert all(
        funding_schemas.funding_operation_next_action(status)
        for status in statuses
    )


def test_coordinator_views_use_canonical_action_for_every_status() -> None:
    operation = _operation()

    for status in funding_schemas.FUNDING_OPERATION_STATUSES:
        view = funding_coordinator.PolymarketFundingCoordinator.view(
            operation.model_copy(update={"status": status})
        )
        assert view.next_action == funding_schemas.funding_operation_next_action(
            status
        )


def test_unknown_states_only_recover_forward_and_settlement_never_rolls_back(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "unknown-recovery.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    current = _advance(repository, current, "confirmed")
    current = _advance(repository, current, "action_creating")
    current = _advance(repository, current, "action_unknown")
    current = _advance(repository, current, "action_created")
    current = _advance(repository, current, "policy_evaluating")
    current = _advance(repository, current, "policy_unknown")
    current = _advance(repository, current, "policy_approved")
    current = _advance(repository, current, "reserved")
    current = _advance(repository, current, "settlement_submitting")

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation transition is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status="settlement_submitting",
            replacement=_replacement(current, status="transaction_prepared"),
        )

    current = _advance(repository, current, "settlement_unknown")
    current = _advance(
        repository,
        current,
        "submitted",
        core_tx_hash=TX_HASH,
        core_state="payment_submitted",
    )
    assert current.status == "submitted"


def test_broadcast_states_require_definite_core_failure_proof_before_release(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "release-proof.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
        "settlement_unknown",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation failure proof is required",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(
                current,
                status="released",
                failure_reason_code="AMBIGUOUS_SUBMISSION",
            ),
        )

    released = _replacement(
        current,
        status="released",
        core_tx_hash=TX_HASH,
        core_state="released",
        core_replacement_forbidden=True,
        core_failure_evidence_kind="failed_receipt",
        failure_reason_code="DEFINITE_FAILED_RECEIPT",
    )
    assert repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=released,
    ) == released


def test_submitted_operation_cannot_be_released_without_failed_core_evidence(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "submitted-release-proof.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation failure proof is required",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status="submitted",
            replacement=_replacement(
                current,
                status="released",
                core_state="released",
                failure_reason_code="PROOFLESS_RELEASE",
            ),
        )


@pytest.mark.parametrize(
    ("old_status", "terminal_status"),
    [
        ("settlement_submitting", "released"),
        ("settlement_submitting", "failed"),
        ("settlement_unknown", "released"),
        ("settlement_unknown", "failed"),
        ("submitted", "released"),
        ("submitted", "failed"),
    ],
)
def test_raw_broadcast_state_terminal_transition_requires_definite_core_proof(
    tmp_path, old_status: str, terminal_status: str
) -> None:
    repository = _seeded_repository(
        tmp_path / f"raw-{old_status}-{terminal_status}.sqlite3"
    )
    current, _ = repository.create_funding_operation(_operation())
    path = [
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
    ]
    if old_status == "settlement_unknown":
        path.append("settlement_unknown")
    elif old_status == "submitted":
        path.append("submitted")
    for status in path:
        current = _advance(repository, current, status)

    terminal_core_state = (
        "released" if terminal_status == "released" else "spending_reserved"
    )
    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    status=terminal_status,
                    core_state=terminal_core_state,
                    failure_reason_code="PROOFLESS_BROADCAST_FAILURE",
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )


def test_raw_pre_broadcast_release_remains_allowed(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "raw-pre-broadcast-release.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
    ):
        current = _advance(repository, current, status)

    with repository.engine.begin() as connection:
        connection.execute(
            funding_repository.PolymarketFundingOperationRow.__table__.update()
            .where(
                funding_repository.PolymarketFundingOperationRow.operation_id
                == current.operation_id
            )
            .values(
                status="released",
                core_state="released",
                failure_reason_code="PRE_BROADCAST_RELEASED",
                revision=current.revision + 1,
                updated_at=current.updated_at + timedelta(seconds=1),
            )
        )
    released = repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=current.operation_id,
    )
    assert released is not None
    assert released.status == "released"


def test_raw_broadcast_terminal_partial_proof_cannot_bypass_guard_with_null(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "raw-partial-proof.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    status="failed",
                    core_tx_hash=TX_HASH,
                    core_state=None,
                    core_replacement_forbidden=True,
                    core_failure_evidence_kind="failed_receipt",
                    failure_reason_code="PARTIAL_BROADCAST_PROOF",
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )


@pytest.mark.parametrize(
    "terminal_values",
    [
        {
            "status": "failed",
            "failure_reason_code": None,
        },
        {
            "status": "failed",
            "core_tx_hash": TX_HASH,
            "core_state": None,
            "core_replacement_forbidden": True,
            "core_failure_evidence_kind": "failed_receipt",
            "failure_reason_code": "PARTIAL_BROADCAST_PROOF",
        },
    ],
)
def test_raw_terminal_insert_requires_reason_and_complete_core_proof(
    tmp_path, terminal_values: dict[str, object]
) -> None:
    repository = _seeded_repository(tmp_path / "raw-terminal-insert.sqlite3")
    values = _operation().model_dump()
    values.update(terminal_values)

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                values,
            )


def test_settlement_unknown_status_reads_are_monotonic_and_settled_moves_forward(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "settlement-monotonic.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
        "settlement_unknown",
    ):
        current = _advance(repository, current, status)

    payment_submitted = _replacement(
        current,
        status="settlement_unknown",
        core_state="payment_submitted",
        core_tx_hash=TX_HASH,
    )
    current = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=payment_submitted,
    )
    assert current == payment_submitted

    with pytest.raises(funding_repository.BridgeRepositoryError):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(
                current,
                status="settlement_unknown",
                core_state="spending_reserved",
                core_tx_hash=None,
            ),
        )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(
                current,
                status="settlement_unknown",
                core_state="settled",
            ),
        )

    chain_confirmed = _replacement(
        current,
        status="chain_confirmed",
        core_state="settled",
    )
    assert repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=chain_confirmed,
    ) == chain_confirmed


def test_raw_settlement_unknown_cannot_store_settled_or_regress_core_state(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "raw-settlement-monotonic.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
        "settlement_unknown",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    core_state="settled",
                    core_tx_hash=TX_HASH,
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )

    payment_submitted = _replacement(
        current,
        status="settlement_unknown",
        core_state="payment_submitted",
        core_tx_hash=TX_HASH,
    )
    current = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=payment_submitted,
    )
    assert current == payment_submitted

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    core_state="spending_reserved",
                    core_tx_hash=None,
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )


def test_finalization_requires_core_bridge_and_buying_power_proof(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "finalize-proof.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(current, status="venue_credited"),
        )

    current = _advance(
        repository,
        current,
        "venue_credited",
        bridge_observation_id="pm_observation_credited",
        bridge_status="COMPLETED",
        venue_buying_power_after_atomic="1000000",
    )
    current = _advance(repository, current, "finalizing")
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(
                current,
                status="finalized",
                finalized_at=current.updated_at + timedelta(seconds=1),
            ),
        )

    finalized = _replacement(
        current,
        status="finalized",
        core_state="finalized",
        finalized_at=current.updated_at + timedelta(seconds=1),
    )
    assert repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=finalized,
    ) == finalized


def test_same_status_cas_only_updates_recovery_fields_for_that_stage(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "same-status.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation checkpoint is invalid for status",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=_replacement(current, status=current.status, action_id="late_action"),
        )

    observed = _replacement(
        current,
        status="bridge_pending",
        bridge_observation_id="pm_observation_pending",
        bridge_status="PROCESSING",
    )
    assert repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=observed,
    ) == observed


def test_sqlite_operation_create_replay_scope_and_payload_drift(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "bridge.sqlite3")
    operation = _operation()

    stored, created = repository.create_funding_operation(operation)
    replay, replay_created = repository.create_funding_operation(operation)

    assert created is True
    assert replay_created is False
    assert stored == replay == operation
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=OPERATION_ID,
    ) == operation
    assert repository.get_funding_operation(
        user_id="telegram_user_2",
        binding_id=BINDING_ID,
        operation_id=OPERATION_ID,
    ) is None
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id="pm_binding_2",
        operation_id=OPERATION_ID,
    ) is None
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    ) == operation
    assert repository.get_funding_operation_by_idempotency(
        user_id="telegram_user_2",
        binding_id=BINDING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    ) is None

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation context conflict",
    ):
        repository.create_funding_operation(
            _operation(amount_usdc="2.000000", amount_atomic="2000000")
        )


def test_operation_requires_the_same_persisted_bridge_target_scope(tmp_path) -> None:
    repository = funding_repository.SQLiteBridgeRepository(tmp_path / "bridge.sqlite3")
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation context conflict",
    ):
        repository.create_funding_operation(_operation())

    repository.save_deposit_target(_target())
    stored, created = repository.create_funding_operation(_operation())
    assert created is True
    assert stored.bridge_address == BRIDGE_ADDRESS


def test_idempotency_replay_ignores_new_operation_id_but_is_binding_scoped(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "bridge.sqlite3")
    original, created = repository.create_funding_operation(_operation())
    assert created is True

    replay, replay_created = repository.create_funding_operation(
        _operation(operation_id="pm_funding_operation_regenerated")
    )
    assert replay_created is False
    assert replay.operation_id == original.operation_id == OPERATION_ID
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    ) == original
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id="pm_binding_2",
        idempotency_key=IDEMPOTENCY_KEY,
    ) is None

    repository.save_deposit_target(
        _target(deposit_id="pm_deposit_2", binding_id="pm_binding_2")
    )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation context conflict",
    ):
        repository.create_funding_operation(
            _operation(
                operation_id="pm_funding_operation_other_binding",
                binding_id="pm_binding_2",
            )
        )


def test_opc_installation_scope_is_immutable_across_replay_cas_and_raw_sql(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "opc-immutable.sqlite3")
    original, created = repository.create_funding_operation(
        _operation(opc_installation_id=OPC_INSTALLATION_ID)
    )
    assert created is True

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation context conflict",
    ):
        repository.create_funding_operation(
            _operation(opc_installation_id=OTHER_OPC_INSTALLATION_ID)
        )

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation immutable context conflict",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=original.revision,
            expected_status=original.status,
            replacement=_replacement(
                original,
                status="confirmed",
                confirmed_at=original.updated_at + timedelta(seconds=1),
                opc_installation_id=OTHER_OPC_INSTALLATION_ID,
            ),
        )

    with pytest.raises(IntegrityError, match="funding operation update guard"):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == original.operation_id
                )
                .values(
                    opc_installation_id=OTHER_OPC_INSTALLATION_ID,
                    revision=original.revision + 1,
                    updated_at=original.updated_at + timedelta(seconds=1),
                )
            )


def test_active_target_rejects_new_idempotency_but_replays_existing_operation(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "active-target.sqlite3")
    original, created = repository.create_funding_operation(_operation())
    assert created is True

    replay, replay_created = repository.create_funding_operation(
        _operation(operation_id="pm_funding_operation_replay")
    )
    assert replay_created is False
    assert replay == original

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation",
    ):
        repository.create_funding_operation(
            _operation(
                operation_id="pm_funding_operation_second",
                idempotency_key="pm_funding_idempotency_second",
            )
        )


def test_repository_startup_rejects_historical_duplicate_active_targets(
    tmp_path,
) -> None:
    database = tmp_path / "historical-active-target-conflict.sqlite3"
    repository = _seeded_repository(database)
    operations = [
        _operation(),
        _operation(
            operation_id="pm_funding_operation_historical_second",
            idempotency_key="pm_funding_idempotency_historical_second",
        ),
    ]
    with repository.engine.begin() as connection:
        connection.execute(
            funding_repository.PolymarketFundingOperationRow.__table__.insert(),
            [operation.model_dump() for operation in operations],
        )
    repository.engine.dispose()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="conflicting active funding operations",
    ):
        funding_repository.SQLiteBridgeRepository(database)


@pytest.mark.parametrize("terminal_status", ["finalized", "failed", "released"])
def test_terminal_target_operation_allows_new_idempotency(
    tmp_path,
    terminal_status: str,
) -> None:
    repository = _seeded_repository(
        tmp_path / f"terminal-target-{terminal_status}.sqlite3"
    )
    original, created = repository.create_funding_operation(_operation())
    assert created is True
    terminal = _terminalize(repository, original, terminal_status)
    assert terminal.status == terminal_status

    second = _operation(
        operation_id=f"pm_funding_operation_{terminal_status}_second",
        idempotency_key=f"pm_funding_idempotency_{terminal_status}_second",
    )
    stored, second_created = repository.create_funding_operation(second)

    assert second_created is True
    assert stored == second


def test_two_sqlite_repositories_create_exactly_one_operation(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    _seeded_repository(database)
    barrier = Barrier(2)

    def create():
        repository = funding_repository.SQLiteBridgeRepository(database)
        barrier.wait()
        return repository.create_funding_operation(_operation())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))

    assert sorted(created for _operation_value, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM polymarket_funding_operations"
        ).fetchone()[0] == 1


def test_two_sqlite_repositories_allow_only_one_active_target_operation(
    tmp_path,
) -> None:
    database = tmp_path / "active-target-race.sqlite3"
    _seeded_repository(database)
    barrier = Barrier(2)

    def create(index: int):
        repository = funding_repository.SQLiteBridgeRepository(database)
        barrier.wait()
        try:
            return repository.create_funding_operation(
                _operation(
                    operation_id=f"pm_funding_operation_race_{index}",
                    idempotency_key=f"pm_funding_idempotency_race_{index}",
                )
            )
        except funding_repository.BridgeRepositoryError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))

    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(result == "funding operation is already in progress" for result in results) == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM polymarket_funding_operations"
        ).fetchone()[0] == 1


def test_operation_cas_has_one_winner_and_preserves_immutable_provenance(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    first_repository = _seeded_repository(database)
    second_repository = funding_repository.SQLiteBridgeRepository(database)
    created, _ = first_repository.create_funding_operation(_operation())
    confirmed = _replacement(created, status="confirmed", confirmed_at=NOW + timedelta(seconds=1))
    barrier = Barrier(2)

    def transition(repository):
        barrier.wait()
        return repository.compare_and_set_funding_operation(
            expected_revision=0,
            expected_status="created",
            replacement=confirmed,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transition, (first_repository, second_repository)))

    assert sum(result is not None for result in results) == 1
    assert first_repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=OPERATION_ID,
    ) == confirmed

    drifted = _replacement(
        confirmed,
        status="action_creating",
        bridge_address="0x5555555555555555555555555555555555555555",
    )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation immutable context conflict",
    ):
        first_repository.compare_and_set_funding_operation(
            expected_revision=1,
            expected_status="confirmed",
            replacement=drifted,
        )


def test_cas_supports_plan_states_and_unknown_state_cannot_roll_back(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "bridge.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in ("confirmed", "action_creating", "action_unknown"):
        current = _advance(repository, current, status)

    rollback = _replacement(current, status="action_creating")
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation transition is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status="action_unknown",
            replacement=rollback,
        )

    repository = _seeded_repository(tmp_path / "complete-plan.sqlite3")
    second = _operation(
        operation_id="pm_funding_operation_2",
        idempotency_key="pm_funding_idempotency_2",
    )
    current, _ = repository.create_funding_operation(second)
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
        "venue_credited",
        "finalized",
    ):
        updates: dict[str, object] = {}
        if status == "venue_credited":
            updates.update(
                bridge_observation_id="pm_observation_complete",
                bridge_status="COMPLETED",
                venue_buying_power_after_atomic="1000000",
            )
        if status == "finalized":
            updates.update(
                core_state="finalized",
                finalized_at=current.updated_at + timedelta(seconds=1),
            )
        current = _advance(repository, current, status, **updates)


def test_reserved_operation_can_cas_to_released_and_then_is_terminal(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "released.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
    ):
        current = _advance(repository, current, status)

    released = _replacement(
        current,
        status="released",
        core_state="released",
        failure_reason_code="PRE_BROADCAST_RELEASED",
    )
    current = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status="reserved",
        replacement=released,
    )
    assert current == released
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is terminal",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status="released",
            replacement=_replacement(current, status="released"),
        )


@pytest.mark.parametrize("terminal_status", ["finalized", "failed", "released"])
def test_terminal_operation_states_are_immutable(tmp_path, terminal_status: str) -> None:
    repository = _seeded_repository(
        tmp_path / f"{terminal_status}.sqlite3"
    )
    terminal, _ = repository.create_funding_operation(_operation())
    if terminal_status == "finalized":
        for status in (
            "confirmed",
            "action_creating",
            "action_created",
            "policy_evaluating",
            "policy_approved",
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
            "submitted",
            "chain_confirmed",
            "bridge_pending",
        ):
            terminal = _advance(repository, terminal, status)
        terminal = _advance(
            repository,
            terminal,
            "venue_credited",
            bridge_observation_id="pm_observation_terminal",
            bridge_status="COMPLETED",
            venue_buying_power_after_atomic="1000000",
        )
        terminal = _advance(
            repository,
            terminal,
            "finalized",
            core_state="finalized",
            finalized_at=terminal.updated_at + timedelta(seconds=1),
        )
    else:
        replacement = _replacement(
            terminal,
            status=terminal_status,
            failure_reason_code="OPERATION_TERMINATED",
        )
        terminal = repository.compare_and_set_funding_operation(
            expected_revision=terminal.revision,
            expected_status=terminal.status,
            replacement=replacement,
        )
        assert terminal is not None

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is terminal",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=terminal.revision,
            expected_status=terminal.status,
            replacement=_replacement(terminal, status=terminal.status),
        )


def test_operation_checkpoint_ids_and_canonical_transaction_are_write_once(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "bridge.sqlite3")
    current, _ = repository.create_funding_operation(_operation())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
    ):
        current = _advance(repository, current, status)

    for field, changed_value in (
        ("action_id", "core_action_2"),
        ("reservation_id", "core_reservation_2"),
        ("core_tx_hash", "0x" + "d" * 64),
        ("confirmed_at", NOW + timedelta(minutes=2)),
    ):
        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="funding operation checkpoint conflict",
        ):
            repository.compare_and_set_funding_operation(
                expected_revision=current.revision,
                expected_status=current.status,
                replacement=_replacement(
                    current,
                    status="chain_confirmed",
                    core_state="settled",
                    **{field: changed_value},
                ),
            )


def test_sqlite_v1_to_current_migration_preserves_bridge_rows_and_is_idempotent(tmp_path) -> None:
    database = tmp_path / "bridge-v1.sqlite3"
    _create_v1_sqlite_database(database)

    repository = funding_repository.SQLiteBridgeRepository(database)
    assert funding_repository.BRIDGE_SCHEMA_VERSION == 4
    assert repository.find_deposit_target_for_binding(
        user_id=USER_ID,
        binding_id=BINDING_ID,
    ) is not None
    with repository.engine.connect() as connection:
        assert "polymarket_funding_operations" in set(
            sa_inspect(connection).get_table_names()
        )
        assert connection.scalar(
            text(
                "SELECT version FROM polymarket_bridge_schema_version "
                "WHERE singleton = 1"
            )
        ) == funding_repository.BRIDGE_SCHEMA_VERSION

    reopened = funding_repository.SQLiteBridgeRepository(database)
    with reopened.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM polymarket_bridge_deposit_targets")
        ) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM polymarket_bridge_observations")
        ) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM polymarket_funding_operations")
        ) == 0
        trigger_names = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND tbl_name='polymarket_funding_operations'"
                )
            )
        }
        assert funding_repository._OPERATION_UPDATE_GUARD_NAME in trigger_names
        index_names = {
            item["name"]
            for item in sa_inspect(connection).get_indexes(
                "polymarket_bridge_deposit_targets"
            )
        }
        assert funding_repository._TARGET_OPERATION_SCOPE_INDEX_NAME in index_names


@pytest.mark.parametrize("legacy_version", [2, 3])
def test_sqlite_legacy_to_v4_migration_adds_nullable_installation_scope(
    tmp_path, legacy_version: int
) -> None:
    database = tmp_path / f"bridge-v{legacy_version}.sqlite3"
    repository = _seeded_repository(database)
    operation, _created = repository.create_funding_operation(_operation())
    repository.engine.dispose()
    _downgrade_sqlite_operation_schema(database, version=legacy_version)

    migrated = funding_repository.SQLiteBridgeRepository(database)

    restored = migrated.get_funding_operation(
        user_id=operation.user_id,
        binding_id=operation.binding_id,
        operation_id=operation.operation_id,
    )
    assert restored == operation
    assert restored.opc_installation_id is None
    with migrated.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT version FROM polymarket_bridge_schema_version "
                "WHERE singleton = 1"
            )
        ) == funding_repository.BRIDGE_SCHEMA_VERSION
        assert funding_repository._operation_update_guard_exists(
            connection, version=funding_repository.BRIDGE_SCHEMA_VERSION
        )
        columns = {
            column[1]
            for column in connection.exec_driver_sql(
                "PRAGMA table_info(polymarket_funding_operations)"
            )
        }
        assert "opc_installation_id" in columns


def test_sqlite_v2_guard_fingerprint_matches_deployed_schema() -> None:
    expected = {
        "trg_pm_funding_operation_insert_guard": (
            "8d5a0cb9ece5db9d4f7b115e4a06c95eb3cb22b37fd1c25097a81cb20cf977ef"
        ),
        "trg_pm_funding_operation_update_guard": (
            "b05e080b08c26995a4c99b7d2257b2a9f7db7f0e3107dcad34a6a4965aa5d744"
        ),
    }
    actual = {
        name: sha256(
            funding_repository._normalize_guard_sql(statement).encode("utf-8")
        ).hexdigest()
        for name, statement in funding_repository._sqlite_operation_guard_statements(
            version=2
        ).items()
    }

    assert actual == expected


def test_current_v2_missing_update_guard_fails_closed(tmp_path) -> None:
    database = tmp_path / "missing-guard.sqlite3"
    repository = _seeded_repository(database)
    with repository.engine.begin() as connection:
        connection.execute(
            text(
                f"DROP TRIGGER {funding_repository._OPERATION_UPDATE_GUARD_NAME}"
            )
        )
    repository.engine.dispose()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(database)


def test_current_v2_same_name_noop_guards_fail_closed(tmp_path) -> None:
    database = tmp_path / "noop-guards.sqlite3"
    repository = _seeded_repository(database)
    with repository.engine.begin() as connection:
        connection.execute(
            text(
                f"DROP TRIGGER {funding_repository._OPERATION_UPDATE_GUARD_NAME}"
            )
        )
        connection.execute(
            text(
                f"DROP TRIGGER {funding_repository._OPERATION_INSERT_GUARD_NAME}"
            )
        )
        connection.execute(
            text(
                f"CREATE TRIGGER {funding_repository._OPERATION_UPDATE_GUARD_NAME} "
                "BEFORE UPDATE ON polymarket_funding_operations "
                "BEGIN SELECT 1; END"
            )
        )
        connection.execute(
            text(
                f"CREATE TRIGGER {funding_repository._OPERATION_INSERT_GUARD_NAME} "
                "BEFORE INSERT ON polymarket_funding_operations "
                "BEGIN SELECT 1; END"
            )
        )
    repository.engine.dispose()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(database)


def test_current_v2_same_name_noop_check_fails_closed(tmp_path) -> None:
    database = tmp_path / "noop-check.sqlite3"
    repository = _seeded_repository(database)
    repository.engine.dispose()
    canonical = (
        "CONSTRAINT ck_pm_funding_risk_score "
        "CHECK (risk_score BETWEEN 0 AND 100)"
    )
    replacement = (
        "CONSTRAINT ck_pm_funding_risk_score "
        "CHECK (1 = 1)"
    )
    with sqlite3.connect(database) as connection:
        create_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='polymarket_funding_operations'"
        ).fetchone()[0]
        assert canonical in create_sql
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_master SET sql=? "
            "WHERE type='table' AND name='polymarket_funding_operations'",
            (create_sql.replace(canonical, replacement),),
        )
        connection.execute("PRAGMA writable_schema=OFF")
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_version + 1}")

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(database)


@pytest.mark.parametrize("version", [1, funding_repository.BRIDGE_SCHEMA_VERSION])
def test_all_table_names_with_malformed_schema_fail_before_migration(
    tmp_path, version: int
) -> None:
    database = tmp_path / f"malformed-v{version}.sqlite3"
    if version == 1:
        _create_v1_sqlite_database(database)
        with sqlite3.connect(database) as connection:
            connection.execute(
                "ALTER TABLE polymarket_bridge_deposit_targets "
                "RENAME COLUMN source_token_address TO source_token_bad"
            )
    else:
        repository = _seeded_repository(database)
        repository.engine.dispose()
        with sqlite3.connect(database) as connection:
            connection.execute(
                f"DROP TRIGGER {funding_repository._OPERATION_UPDATE_GUARD_NAME}"
            )
            connection.execute(
                "ALTER TABLE polymarket_funding_operations "
                "RENAME COLUMN resource TO resource_bad"
            )

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version FROM polymarket_bridge_schema_version WHERE singleton=1"
        ).fetchone()[0] == version


def test_v1_partial_current_partial_and_future_schemas_fail_before_ddl(tmp_path) -> None:
    v1_partial = tmp_path / "v1-partial.sqlite3"
    with sqlite3.connect(v1_partial) as connection:
        connection.execute(
            "CREATE TABLE polymarket_bridge_schema_version "
            "(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO polymarket_bridge_schema_version VALUES (1, 1)"
        )
        connection.execute(
            "CREATE TABLE polymarket_bridge_deposit_targets "
            "(deposit_id TEXT PRIMARY KEY)"
        )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(v1_partial)
    with sqlite3.connect(v1_partial) as connection:
        assert "polymarket_funding_operations" not in {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert connection.execute(
            "SELECT version FROM polymarket_bridge_schema_version WHERE singleton=1"
        ).fetchone()[0] == 1

    current_partial = tmp_path / "current-partial.sqlite3"
    _create_v1_sqlite_database(current_partial)
    with sqlite3.connect(current_partial) as connection:
        connection.execute(
            "UPDATE polymarket_bridge_schema_version SET version=? WHERE singleton=1",
            (funding_repository.BRIDGE_SCHEMA_VERSION,),
        )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository.SQLiteBridgeRepository(current_partial)
    with sqlite3.connect(current_partial) as connection:
        assert "polymarket_funding_operations" not in {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    future = tmp_path / "future.sqlite3"
    with sqlite3.connect(future) as connection:
        connection.execute(
            "CREATE TABLE polymarket_bridge_schema_version "
            "(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO polymarket_bridge_schema_version VALUES (?, ?)",
            (1, funding_repository.BRIDGE_SCHEMA_VERSION + 1),
        )
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is newer than this binary",
    ):
        funding_repository.SQLiteBridgeRepository(future)
    with sqlite3.connect(future) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        } == {"polymarket_bridge_schema_version"}


def test_operation_table_has_portable_constraints_and_all_plan_statuses() -> None:
    table = funding_repository.PolymarketFundingOperationRow.__table__
    assert len(funding_repository._WRITE_ONCE_OPERATION_FIELDS) == len(
        set(funding_repository._WRITE_ONCE_OPERATION_FIELDS)
    )
    assert any(isinstance(item, CheckConstraint) for item in table.constraints)
    assert any(isinstance(item, UniqueConstraint) for item in table.constraints)

    sqlite_ddl = str(CreateTable(table).compile(dialect=sqlite.dialect())).lower()
    postgres_ddl = str(
        CreateTable(table).compile(dialect=postgresql.dialect())
    ).lower()
    for ddl in (sqlite_ddl, postgres_ddl):
        for fragment in (
            "check",
            "unique",
            "lower",
            "length",
            "transaction_prepared",
            "released",
            UINT256_MAX_ATOMIC,
        ):
            assert fragment.lower() in ddl
        assert "raw_transaction" not in ddl
        assert "private_key" not in ddl
        assert "raw_response" not in ddl


@pytest.mark.parametrize("dialect_name", ("sqlite", "postgresql"))
@pytest.mark.parametrize(
    "corruption",
    ("column_type", "column_nullability", "check", "unique", "foreign_key"),
)
def test_schema_signature_rejects_same_name_wrong_definition_for_each_dialect(
    dialect_name: str, corruption: str
) -> None:
    table = funding_repository.PolymarketFundingOperationRow.__table__
    selected_dialect = (
        sqlite.dialect() if dialect_name == "sqlite" else postgresql.dialect()
    )

    class MetadataInspector:
        bind = type("Bind", (), {"dialect": selected_dialect})()

        def get_columns(self, _table_name):
            columns = [
                {
                    "name": column.name,
                    "type": column.type,
                    "nullable": column.nullable,
                }
                for column in table.columns
            ]
            if corruption == "column_type":
                columns[0]["type"] = Integer()
            if corruption == "column_nullability":
                columns[1]["nullable"] = not columns[1]["nullable"]
            return columns

        def get_pk_constraint(self, _table_name):
            return {
                "constrained_columns": [
                    column.name for column in table.primary_key.columns
                ]
            }

        def get_unique_constraints(self, _table_name):
            constraints = [
                {
                    "name": constraint.name,
                    "constrained_columns": [
                        column.name for column in constraint.columns
                    ],
                }
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
                and constraint.name is not None
            ]
            if corruption == "unique":
                target = next(
                    constraint
                    for constraint in constraints
                    if constraint["name"] == "uq_pm_funding_risk_assessment"
                )
                target["constrained_columns"] = ["operation_id"]
            return constraints

        def get_check_constraints(self, _table_name):
            constraints = [
                {
                    "name": constraint.name,
                    "sqltext": str(constraint.sqltext),
                }
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
                and constraint.name is not None
            ]
            if corruption == "check":
                target = next(
                    constraint
                    for constraint in constraints
                    if constraint["name"] == "ck_pm_funding_risk_score"
                )
                target["sqltext"] = "1 = 1"
            return constraints

        def get_foreign_keys(self, _table_name):
            constraints = [
                {
                    "name": constraint.name,
                    "constrained_columns": [
                        element.parent.name for element in constraint.elements
                    ],
                    "referred_table": constraint.elements[0].column.table.name,
                    "referred_columns": [
                        element.column.name for element in constraint.elements
                    ],
                    "options": {"ondelete": constraint.ondelete},
                }
                for constraint in table.constraints
                if isinstance(constraint, ForeignKeyConstraint)
                and constraint.name is not None
            ]
            if corruption == "foreign_key":
                constraints[0]["referred_columns"][0] = "deposit_id"
            return constraints

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository._validate_table_signature(MetadataInspector(), table)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("status", "retrying_transfer"),
        ("venue_wallet_address", "0x" + "A" * 40),
        ("request_hash", "0x" + "A" * 64),
        ("amount_usdc", "1.0"),
        ("amount_usdc", "2.000000"),
        ("amount_atomic", str(2**256)),
        ("venue_buying_power_before_atomic", "00"),
        ("risk_level", "unknown"),
        ("risk_score", 101),
        ("risk_action", "execute"),
        ("revision", -1),
        ("created_at", "2026-08-19T12:00:00+00:00"),
    ],
)
def test_sqlite_direct_dml_rejects_invalid_operation_values(
    tmp_path, field: str, invalid_value: object
) -> None:
    repository = _seeded_repository(tmp_path / "bridge.sqlite3")
    values = _operation().model_dump()
    values[field] = invalid_value

    with pytest.raises((IntegrityError, StatementError)):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                values,
            )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("operation_id", "bad id"),
        ("agent_id", "agent$bad"),
        ("resource", "polymarket funding with spaces"),
        ("failure_reason_code", "bad-reason"),
        ("created_at", "2026-02-31T12:00:00.000000Z"),
    ],
)
def test_sqlite_direct_dml_rejects_invalid_grammar_and_time(
    tmp_path, field: str, invalid_value: object
) -> None:
    repository = _seeded_repository(tmp_path / f"bad-{field}.sqlite3")
    values = _operation().model_dump()
    values[field] = invalid_value

    with pytest.raises((IntegrityError, StatementError)):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                values,
            )


def test_sqlite_raw_driver_insert_rejects_non_epoch_timestamp(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "raw-invalid-time.sqlite3")
    values = _operation().model_dump()
    timestamp_type = funding_repository.UTCDateTimeMicros()
    values["created_at"] = "2026-02-31T12:00:00.000000Z"
    values["updated_at"] = timestamp_type.process_bind_param(NOW, None)
    columns = tuple(values)
    statement = (
        "INSERT INTO polymarket_funding_operations ("
        + ", ".join(columns)
        + ") VALUES ("
        + ", ".join(f":{column}" for column in columns)
        + ")"
    )

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.exec_driver_sql(statement, values)


def test_operation_target_fk_rejects_token_provenance_drift(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "target-token-drift.sqlite3")
    values = _operation().model_dump()
    values["destination_token_address"] = "0x" + "5" * 40

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                values,
            )


def test_sqlite_update_guard_rejects_raw_immutable_terminal_revision_and_transition(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "raw-update-guard.sqlite3")
    current, _ = repository.create_funding_operation(_operation())

    invalid_updates = (
        {"bridge_address": "0x" + "5" * 40, "revision": 1},
        {"status": "submitted", "revision": 1},
        {"status": "confirmed", "confirmed_at": NOW, "revision": 2},
    )
    for changes in invalid_updates:
        with pytest.raises(IntegrityError):
            with repository.engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.update()
                    .where(
                        funding_repository.PolymarketFundingOperationRow.operation_id
                        == current.operation_id
                    )
                    .values(**changes)
                )

    failed = _replacement(
        current,
        status="failed",
        failure_reason_code="PRE_BROADCAST_FAILURE",
    )
    failed = repository.compare_and_set_funding_operation(
        expected_revision=current.revision,
        expected_status=current.status,
        replacement=failed,
    )
    assert failed is not None
    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(updated_at=NOW + timedelta(minutes=1), revision=2)
            )

    recovery, _ = repository.create_funding_operation(
        _operation(
            operation_id="pm_funding_operation_raw_recovery",
            idempotency_key="pm_funding_idempotency_raw_recovery",
        )
    )
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
    ):
        recovery = _advance(repository, recovery, status)
    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == recovery.operation_id
                )
                .values(
                    status="transaction_prepared",
                    revision=recovery.revision + 1,
                    updated_at=recovery.updated_at + timedelta(seconds=1),
                )
            )


def test_database_read_validation_errors_are_fixed_and_redacted(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "read-error.sqlite3")
    marker = "raw-secret-read-marker"

    def invalid_converter(_row):
        raise ValueError(marker)

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database read failed",
    ) as captured:
        repository._read_one(
            funding_repository.select(
                funding_repository.BridgeDepositTargetRow
            ).limit(1),
            invalid_converter,
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert marker not in str(captured.value)


def test_postgres_guard_ddl_enforces_the_same_transition_and_grammar_contract() -> None:
    statements: list[str] = []

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def exec_driver_sql(self, statement: str) -> None:
            statements.append(statement)

    funding_repository._install_operation_update_guard(FakeConnection())
    ddl = "\n".join(statements).lower()
    assert len(statements) == 4
    for fragment in (
        funding_repository._OPERATION_INSERT_GUARD_NAME,
        funding_repository._OPERATION_UPDATE_GUARD_NAME,
        "clink-operation-guard-v4-update-sha256",
        "is distinct from",
        "old.status in ('finalized', 'failed', 'released')",
        "old.status in ('settlement_submitting', 'settlement_unknown', 'submitted')",
        "new.core_replacement_forbidden = true",
        "core_prebroadcast_released",
        "old.core_state = 'payment_submitted'",
        "new.revision <> old.revision + 1",
        "new.operation_id !~",
        "new.resource !~",
        "new.failure_reason_code !~",
        "action_unknown",
        "policy_unknown",
        "settlement_unknown",
    ):
        assert fragment.lower() in ddl
    assert "transaction_prepared" not in funding_repository._ALLOWED_OPERATION_TRANSITIONS[
        "settlement_submitting"
    ]


def test_postgres_same_name_noop_guard_functions_fail_signature_check() -> None:
    class FakeMappings:
        def all(self):
            return [
                {
                    "trigger_name": funding_repository._OPERATION_INSERT_GUARD_NAME,
                    "function_name": funding_repository._OPERATION_INSERT_GUARD_FUNCTION,
                    "function_definition": "BEGIN RETURN NEW; END",
                },
                {
                    "trigger_name": funding_repository._OPERATION_UPDATE_GUARD_NAME,
                    "function_name": funding_repository._OPERATION_UPDATE_GUARD_FUNCTION,
                    "function_definition": "BEGIN RETURN NEW; END",
                },
            ]

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def scalar(self, _statement, _parameters=None):
            return 2

        def execute(self, _statement, _parameters=None):
            return FakeResult()

    assert funding_repository._operation_update_guard_exists(FakeConnection()) is False


def test_postgres_disabled_canonical_guard_fails_closed() -> None:
    definitions = funding_repository._postgres_operation_guard_definitions()

    class FakeMappings:
        def all(self):
            return [
                {
                    "trigger_name": trigger_name,
                    "trigger_type": definition["trigger_type"],
                    "trigger_enabled": (
                        "D"
                        if trigger_name
                        == funding_repository._OPERATION_UPDATE_GUARD_NAME
                        else "O"
                    ),
                    "function_name": definition["function_name"],
                    "function_definition": definition["function_body"],
                }
                for trigger_name, definition in definitions.items()
            ]

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def execute(self, _statement, _parameters=None):
            return FakeResult()

    assert funding_repository._operation_update_guard_exists(FakeConnection()) is False


def test_postgres_canonical_guard_functions_pass_signature_check() -> None:
    definitions = funding_repository._postgres_operation_guard_definitions()

    class FakeMappings:
        def all(self):
            return [
                {
                    "trigger_name": trigger_name,
                    "trigger_type": definition["trigger_type"],
                    "trigger_enabled": "O",
                    "function_name": definition["function_name"],
                    "function_definition": definition["function_body"],
                }
                for trigger_name, definition in definitions.items()
            ]

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def execute(self, _statement, _parameters=None):
            return FakeResult()

    assert funding_repository._operation_update_guard_exists(FakeConnection()) is True


def test_postgres_check_fingerprint_quotes_the_explicit_schema_and_table() -> None:
    statements: list[str] = []

    class FakeResult:
        def scalar_one(self):
            return [{"Plan": {"Output": ["(length(user_id) > 0)"]}}]

    class FakeConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, statement: str):
            statements.append(statement)
            return FakeResult()

    inspector = type("Inspector", (), {"bind": FakeConnection()})()

    fingerprint = funding_repository._postgres_check_fingerprint(
        inspector,
        "polymarket_funding_operations",
        "length(user_id) > 0",
        schema_name="app-schema",
    )

    assert fingerprint == "(length(user_id) > 0)"
    assert "FROM \"app-schema\".polymarket_funding_operations LIMIT 0" in statements[0]


@pytest.mark.parametrize(
    "expression",
    (
        "clink_evil_immutable(user_id)",
        "public.length(user_id) > 0",
        "length(user_id) > 0; SELECT true",
        "length(user_id) > 0 -- bypass",
        "length(user_id) > 0 /* bypass */",
        "EXISTS (SELECT 1)",
    ),
)
def test_postgres_check_fingerprint_rejects_unsafe_catalog_sql_before_explain(
    expression: str,
) -> None:
    explain_calls: list[str] = []

    class TrapConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, statement: str):
            explain_calls.append(statement)
            raise AssertionError("unsafe catalog SQL reached EXPLAIN")

    inspector = type("Inspector", (), {"bind": TrapConnection()})()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ) as captured:
        funding_repository._postgres_check_fingerprint(
            inspector,
            "polymarket_funding_operations",
            expression,
            schema_name="app_schema",
        )

    assert explain_calls == []
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_postgres_check_fingerprint_rejects_oversized_expression_before_explain() -> None:
    explain_calls: list[str] = []

    class TrapConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, statement: str):
            explain_calls.append(statement)
            raise AssertionError("oversized catalog SQL reached EXPLAIN")

    inspector = type("Inspector", (), {"bind": TrapConnection()})()
    expression = ("true AND " * 16_385) + "true"

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ):
        funding_repository._postgres_check_fingerprint(
            inspector,
            "polymarket_funding_operations",
            expression,
            schema_name="app_schema",
        )

    assert len(expression) > 131_072
    assert explain_calls == []


@pytest.mark.parametrize("plan_kind", ("oversized", "too_deep"))
def test_postgres_check_fingerprint_rejects_unbounded_explain_plan(
    plan_kind: str,
) -> None:
    if plan_kind == "oversized":
        plan = [{"Plan": {"Output": ["x" * 262_145]}}]
    else:
        nested: dict[str, object] = {}
        cursor = nested
        for _ in range(17):
            child: dict[str, object] = {}
            cursor["Nested"] = child
            cursor = child
        plan = [{"Plan": {"Output": ["length(user_id) > 0"], "Nested": nested}}]

    class FakeResult:
        def scalar_one(self):
            return plan

    class FakeConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, _statement: str):
            return FakeResult()

    inspector = type("Inspector", (), {"bind": FakeConnection()})()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ) as captured:
        funding_repository._postgres_check_fingerprint(
            inspector,
            "polymarket_funding_operations",
            "length(user_id) > 0",
            schema_name="app_schema",
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_postgres_check_fingerprint_redacts_unexpected_explain_failure() -> None:
    marker = "secret-postgres-fingerprint-marker"

    class FailingConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, _statement: str):
            raise RuntimeError(marker)

    inspector = type("Inspector", (), {"bind": FailingConnection()})()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is incomplete",
    ) as captured:
        funding_repository._postgres_check_fingerprint(
            inspector,
            "polymarket_funding_operations",
            "length(user_id) > 0",
            schema_name="app_schema",
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert marker not in str(captured.value)


def test_postgres_migration_takes_transaction_lock_before_any_ddl(monkeypatch) -> None:
    events: list[str] = []

    class FakeTransaction:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    class FakeConnection:
        def begin(self):
            events.append("begin")
            return FakeTransaction()

        def execute(self, statement, _parameters=None):
            rendered = str(statement)
            if rendered.startswith("SET LOCAL search_path"):
                events.append("search_path")
            elif rendered.startswith("SET LOCAL lock_timeout"):
                events.append("lock_timeout")
            elif rendered.startswith("SET LOCAL statement_timeout"):
                events.append("statement_timeout")
            elif "pg_advisory_xact_lock" in rendered:
                events.append("lock")
            elif "polymarket_bridge_schema_version" in rendered:
                events.append("metadata")

        def close(self) -> None:
            events.append("close")

    class FakeEngine:
        dialect = type(
            "Dialect",
            (),
            {"name": "postgresql", "default_schema_name": "app_schema"},
        )()

        def connect(self):
            return FakeConnection()

    class FakeInspector:
        def __init__(self) -> None:
            self.calls = 0

        def get_table_names(self, *, schema=None):
            events.append(f"catalog:{schema}")
            self.calls += 1
            if self.calls == 1:
                return []
            return [
                "polymarket_bridge_schema_version",
                *sorted(funding_repository._MANAGED_TABLES),
            ]

    inspector = FakeInspector()
    monkeypatch.setattr(funding_repository, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(
        funding_repository.Base.metadata,
        "create_all",
        lambda _connection: events.append("ddl"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_validate_schema_signature",
        lambda _connection, version, schema_name=None: events.append("signature"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_install_operation_update_guard",
        lambda _connection, schema_name=None, version=None: events.append("guard_ddl"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_active_target_conflict_exists",
        lambda _connection: False,
    )
    repository = object.__new__(funding_repository.SqlAlchemyBridgeRepository)
    repository.engine = FakeEngine()

    repository._migrate()

    assert events[:6] == [
        "begin",
        "search_path",
        "lock_timeout",
        "statement_timeout",
        "lock",
        "catalog:app_schema",
    ]
    assert (
        events.index("catalog:app_schema")
        < events.index("ddl")
        < events.index("guard_ddl")
        < events.index("signature")
        < events.index("metadata")
    )
    assert events[-2:] == ["commit", "close"]


def test_postgres_future_version_stops_before_fingerprint_or_ddl(monkeypatch) -> None:
    events: list[str] = []

    class FakeTransaction:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    class FakeConnection:
        def begin(self):
            events.append("begin")
            return FakeTransaction()

        def execute(self, statement, _parameters=None):
            rendered = str(statement)
            if rendered.startswith("SET LOCAL search_path"):
                events.append("search_path")
            elif rendered.startswith("SET LOCAL lock_timeout"):
                events.append("lock_timeout")
            elif rendered.startswith("SET LOCAL statement_timeout"):
                events.append("statement_timeout")
            elif "pg_advisory_xact_lock" in rendered:
                events.append("lock")
            else:
                raise AssertionError(f"unexpected SQL before future gate: {rendered}")

        def scalar(self, _statement):
            events.append("version")
            return funding_repository.BRIDGE_SCHEMA_VERSION + 1

        def exec_driver_sql(self, _statement: str):
            events.append("explain")
            raise AssertionError("future schema reached fingerprint")

        def close(self) -> None:
            events.append("close")

    class FakeEngine:
        dialect = type(
            "Dialect",
            (),
            {"name": "postgresql", "default_schema_name": "app_schema"},
        )()

        def connect(self):
            return FakeConnection()

    class FakeInspector:
        def get_table_names(self, *, schema=None):
            events.append(f"catalog:{schema}")
            return [
                "polymarket_bridge_schema_version",
                *sorted(funding_repository._MANAGED_TABLES),
            ]

    monkeypatch.setattr(
        funding_repository,
        "inspect",
        lambda _connection: FakeInspector(),
    )
    monkeypatch.setattr(
        funding_repository.Base.metadata,
        "create_all",
        lambda _connection: events.append("ddl"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_validate_schema_signature",
        lambda _connection, version, schema_name=None: events.append("fingerprint"),
    )
    repository = object.__new__(funding_repository.SqlAlchemyBridgeRepository)
    repository.engine = FakeEngine()

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="bridge database schema is newer than this binary",
    ):
        repository._migrate()

    assert events == [
        "begin",
        "search_path",
        "lock_timeout",
        "statement_timeout",
        "lock",
        "catalog:app_schema",
        "version",
        "rollback",
        "close",
    ]


def test_postgres_v1_to_v2_migration_locks_before_add_table(monkeypatch) -> None:
    events: list[str] = []

    class FakeTransaction:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    class FakeConnection:
        def begin(self):
            return FakeTransaction()

        def execute(self, statement, _parameters=None):
            rendered = str(statement)
            if rendered.startswith("SET LOCAL search_path"):
                events.append("search_path")
            elif rendered.startswith("SET LOCAL lock_timeout"):
                events.append("lock_timeout")
            elif rendered.startswith("SET LOCAL statement_timeout"):
                events.append("statement_timeout")
            elif "pg_advisory_xact_lock" in rendered:
                events.append("lock")
            elif rendered.lower().startswith("update"):
                events.append("version_update")

        def scalar(self, _statement):
            return 1

        def close(self) -> None:
            pass

    class FakeEngine:
        dialect = type(
            "Dialect",
            (),
            {"name": "postgresql", "default_schema_name": "app_schema"},
        )()

        def connect(self):
            return FakeConnection()

    class FakeInspector:
        def __init__(self) -> None:
            self.calls = 0

        def get_table_names(self, *, schema=None):
            assert schema == "app_schema"
            self.calls += 1
            tables = {
                "polymarket_bridge_schema_version",
                *funding_repository._V1_MANAGED_TABLES,
            }
            if self.calls > 1:
                tables.add("polymarket_funding_operations")
            return sorted(tables)

    inspector = FakeInspector()
    monkeypatch.setattr(funding_repository, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(
        funding_repository.PolymarketFundingOperationRow.__table__,
        "create",
        lambda _connection, checkfirst=False: events.append("operation_ddl"),
    )
    target_scope_index = next(
        index
        for index in funding_repository.BridgeDepositTargetRow.__table__.indexes
        if index.name == funding_repository._TARGET_OPERATION_SCOPE_INDEX_NAME
    )
    monkeypatch.setattr(
        target_scope_index,
        "create",
        lambda _connection, checkfirst=False: events.append("target_index_ddl"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_validate_table_signature",
        lambda _inspector, _table, schema_name=None: None,
    )
    monkeypatch.setattr(
        funding_repository,
        "_validate_schema_signature",
        lambda _connection, version, schema_name=None: None,
    )
    monkeypatch.setattr(
        funding_repository,
        "_install_operation_update_guard",
        lambda _connection, schema_name=None, version=None: events.append("guard_ddl"),
    )
    monkeypatch.setattr(
        funding_repository,
        "_active_target_conflict_exists",
        lambda _connection: False,
    )
    repository = object.__new__(funding_repository.SqlAlchemyBridgeRepository)
    repository.engine = FakeEngine()

    repository._migrate()

    assert events == [
        "search_path",
        "lock_timeout",
        "statement_timeout",
        "lock",
        "target_index_ddl",
        "operation_ddl",
        "guard_ddl",
        "version_update",
        "commit",
    ]


def test_postgres_operation_repository_live_contract_when_configured() -> None:
    postgres_url = os.getenv("TEST_PREDICTION_MARKETS_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_PREDICTION_MARKETS_POSTGRES_URL is not configured")

    schema = f"clink_funding_operation_{uuid4().hex}"

    def scoped_url(name: str) -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={name}"})
            .render_as_string(hide_password=False)
        )

    admin_engine = create_engine(postgres_url)
    repositories = []
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        repositories = [
            funding_repository.PostgresBridgeRepository(scoped_url(schema)),
            funding_repository.PostgresBridgeRepository(scoped_url(schema)),
        ]
        repositories[0].save_deposit_target(_target())

        barrier = Barrier(2)

        def create(repository):
            barrier.wait()
            return repository.create_funding_operation(_operation())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, repositories))
        assert sorted(created for _stored, created in results) == [False, True]

        current = results[0][0]
        replacement = _replacement(
            current,
            status="confirmed",
            confirmed_at=NOW + timedelta(seconds=1),
        )
        barrier = Barrier(2)

        def transition(repository):
            barrier.wait()
            return repository.compare_and_set_funding_operation(
                expected_revision=0,
                expected_status="created",
                replacement=replacement,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            transitions = list(pool.map(transition, repositories))
        assert sum(result is not None for result in transitions) == 1
        current = repositories[0].get_funding_operation(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            operation_id=OPERATION_ID,
        )
        assert current is not None
        # Check immutable scope while this row is still active, so the
        # terminal-row guard cannot mask the intended rejection.
        with pytest.raises(IntegrityError, match="funding operation update guard"):
            with repositories[0].engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.update()
                    .where(
                        funding_repository.PolymarketFundingOperationRow.operation_id
                        == current.operation_id
                    )
                    .values(
                        bridge_address="0x" + "5" * 40,
                        revision=current.revision + 1,
                        updated_at=current.updated_at + timedelta(seconds=1),
                    )
                )
        current = _terminalize(repositories[0], current, "failed")

        # Keep an uncertain broadcast active under a separate target. It
        # must not make the later invalid-row/terminal checks pass merely
        # because a second operation for the original target is forbidden.
        broadcast_binding = "pm_binding_broadcast_pg"
        repositories[0].save_deposit_target(
            _target(deposit_id="pm_deposit_broadcast_pg", binding_id=broadcast_binding)
        )
        broadcast, _ = repositories[0].create_funding_operation(
            _operation(
                operation_id="pm_funding_operation_broadcast_pg",
                idempotency_key="pm_funding_idempotency_broadcast_pg",
                binding_id=broadcast_binding,
                resource=f"polymarket:funding:{broadcast_binding}",
            )
        )
        for status in (
            "confirmed",
            "action_creating",
            "action_created",
            "policy_evaluating",
            "policy_approved",
            "reserved",
            "settlement_submitting",
            "settlement_unknown",
        ):
            broadcast = _advance(repositories[0], broadcast, status)
        with pytest.raises(IntegrityError):
            with repositories[0].engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.update()
                    .where(
                        funding_repository.PolymarketFundingOperationRow.operation_id
                        == broadcast.operation_id
                    )
                    .values(
                        status="released",
                        core_state="released",
                        failure_reason_code="PROOFLESS_BROADCAST_FAILURE",
                        revision=broadcast.revision + 1,
                        updated_at=broadcast.updated_at + timedelta(seconds=1),
                    )
                )
        broadcast_payment_submitted = _replacement(
            broadcast,
            status="settlement_unknown",
            core_state="payment_submitted",
            core_tx_hash=TX_HASH,
        )
        broadcast = repositories[0].compare_and_set_funding_operation(
            expected_revision=broadcast.revision,
            expected_status=broadcast.status,
            replacement=broadcast_payment_submitted,
        )
        assert broadcast is not None
        for invalid_core_state, invalid_core_tx_hash in (
            ("spending_reserved", None),
            ("settled", TX_HASH),
        ):
            with pytest.raises(IntegrityError):
                with repositories[0].engine.begin() as connection:
                    connection.execute(
                        funding_repository.PolymarketFundingOperationRow.__table__.update()
                        .where(
                            funding_repository.PolymarketFundingOperationRow.operation_id
                            == broadcast.operation_id
                        )
                        .values(
                            core_state=invalid_core_state,
                            core_tx_hash=invalid_core_tx_hash,
                            revision=broadcast.revision + 1,
                            updated_at=broadcast.updated_at
                            + timedelta(seconds=1),
                        )
                    )

        bad_values = _operation(
            operation_id="pm_funding_operation_bad_pg",
            idempotency_key="pm_funding_idempotency_bad_pg",
        ).model_dump()
        bad_values["status"] = "retrying_transfer"
        with pytest.raises(IntegrityError):
            with repositories[0].engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                    bad_values,
                )

        for index, invalid_updates in enumerate(
            (
                {"venue_wallet_address": "0x" + "A" * 40},
                {"amount_usdc": "2.000000"},
                {"amount_atomic": str(2**256)},
                {"operation_id": "bad operation id"},
                {"resource": "polymarket funding with spaces"},
            ),
            start=1,
        ):
            values = _operation(
                operation_id=f"pm_funding_operation_bad_pg_{index}",
                idempotency_key=f"pm_funding_idempotency_bad_pg_{index}",
            ).model_dump()
            values.update(invalid_updates)
            with pytest.raises(IntegrityError):
                with repositories[0].engine.begin() as connection:
                    connection.execute(
                        funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                        values,
                    )

        invalid_time = _operation(
            operation_id="pm_funding_operation_bad_pg_time",
            idempotency_key="pm_funding_idempotency_bad_pg_time",
        ).model_dump()
        invalid_time["created_at"] = "2026-02-31T12:00:00.000000Z"
        with pytest.raises((SQLAlchemyError, ValueError)):
            with repositories[0].engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.insert(),
                    invalid_time,
                )

        terminal, _ = repositories[0].create_funding_operation(
            _operation(
                operation_id="pm_funding_operation_terminal_pg",
                idempotency_key="pm_funding_idempotency_terminal_pg",
            )
        )
        terminal = repositories[0].compare_and_set_funding_operation(
            expected_revision=terminal.revision,
            expected_status=terminal.status,
            replacement=_replacement(
                terminal,
                status="failed",
                failure_reason_code="PRE_BROADCAST_FAILURE",
            ),
        )
        assert terminal is not None
        with pytest.raises(IntegrityError):
            with repositories[0].engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.update()
                    .where(
                        funding_repository.PolymarketFundingOperationRow.operation_id
                        == terminal.operation_id
                    )
                    .values(
                        revision=terminal.revision + 1,
                        updated_at=terminal.updated_at + timedelta(seconds=1),
                    )
                )

        with repositories[0].engine.connect() as connection:
            schema_version_before_disable = connection.scalar(
                text("SELECT version FROM polymarket_bridge_schema_version")
            )
            guard_source_before_disable = connection.scalar(
                text(
                    "SELECT p.prosrc FROM pg_trigger AS t "
                    "JOIN pg_proc AS p ON p.oid = t.tgfoid "
                    "WHERE t.tgname = :trigger_name "
                    "AND t.tgrelid = "
                    "to_regclass('polymarket_funding_operations')"
                ),
                {
                    "trigger_name": (
                        funding_repository._OPERATION_UPDATE_GUARD_NAME
                    )
                },
            )
        with repositories[0].engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations DISABLE TRIGGER "
                f"{funding_repository._OPERATION_UPDATE_GUARD_NAME}"
            )
        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="bridge database schema is incomplete",
        ):
            funding_repository.PostgresBridgeRepository(scoped_url(schema))
        with repositories[0].engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version FROM polymarket_bridge_schema_version")
            ) == schema_version_before_disable
            disabled_guard = connection.execute(
                text(
                    "SELECT t.tgenabled, p.prosrc FROM pg_trigger AS t "
                    "JOIN pg_proc AS p ON p.oid = t.tgfoid "
                    "WHERE t.tgname = :trigger_name "
                    "AND t.tgrelid = "
                    "to_regclass('polymarket_funding_operations')"
                ),
                {
                    "trigger_name": (
                        funding_repository._OPERATION_UPDATE_GUARD_NAME
                    )
                },
            ).one()
            assert disabled_guard.tgenabled == "D"
            assert disabled_guard.prosrc == guard_source_before_disable
        with repositories[0].engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations ENABLE TRIGGER "
                f"{funding_repository._OPERATION_UPDATE_GUARD_NAME}"
            )
        with repositories[0].engine.connect() as connection:
            assert funding_repository._operation_update_guard_exists(connection)

        with repositories[0].engine.begin() as connection:
            connection.exec_driver_sql(
                f"""
                CREATE OR REPLACE FUNCTION
                    {funding_repository._OPERATION_UPDATE_GUARD_FUNCTION}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  RETURN NEW;
                END;
                $$
                """
            )
        with repositories[0].engine.connect() as connection:
            assert (
                funding_repository._operation_update_guard_exists(connection)
                is False
            )
        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="bridge database schema is incomplete",
        ):
            funding_repository.PostgresBridgeRepository(scoped_url(schema))
    finally:
        for repository in repositories:
            repository.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_same_name_noop_check_fails_live_when_configured() -> None:
    postgres_url = os.getenv("TEST_PREDICTION_MARKETS_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_PREDICTION_MARKETS_POSTGRES_URL is not configured")

    schema = f"clink_funding_noop_check_{uuid4().hex}"

    def scoped_url(name: str) -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={name}"})
            .render_as_string(hide_password=False)
        )

    admin_engine = create_engine(postgres_url)
    repository = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        repository = funding_repository.PostgresBridgeRepository(scoped_url(schema))
        with repository.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations "
                "DROP CONSTRAINT ck_pm_funding_risk_score"
            )
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations "
                "ADD CONSTRAINT ck_pm_funding_risk_score CHECK (1 = 1)"
            )

        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="bridge database schema is incomplete",
        ):
            funding_repository.PostgresBridgeRepository(scoped_url(schema))
    finally:
        if repository is not None:
            repository.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_allowed_name_overload_is_rejected_without_planner_execution() -> None:
    postgres_url = os.getenv("TEST_PREDICTION_MARKETS_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_PREDICTION_MARKETS_POSTGRES_URL is not configured")

    schema = f"clink_funding_shadow_{uuid4().hex}"

    def scoped_url(name: str) -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={name}"})
            .render_as_string(hide_password=False)
        )

    admin_engine = create_engine(postgres_url)
    repository = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        repository = funding_repository.PostgresBridgeRepository(scoped_url(schema))
        with repository.engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SEQUENCE "{schema}".shadow_calls')
            connection.exec_driver_sql(
                f"""
                CREATE FUNCTION "{schema}".length(integer)
                RETURNS integer LANGUAGE plpgsql IMMUTABLE AS $$
                BEGIN
                  PERFORM pg_catalog.nextval(
                    '"{schema}".shadow_calls'::pg_catalog.regclass
                  );
                  PERFORM pg_catalog.pg_sleep(30);
                  RETURN 1;
                END;
                $$
                """
            )
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations "
                "DROP CONSTRAINT ck_pm_funding_risk_score"
            )
            connection.exec_driver_sql(
                "ALTER TABLE polymarket_funding_operations "
                "ADD CONSTRAINT ck_pm_funding_risk_score "
                "CHECK (length(1) > 0) NOT VALID"
            )
            before = connection.exec_driver_sql(
                f'SELECT last_value, is_called FROM "{schema}".shadow_calls'
            ).one()

        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="bridge database schema is incomplete",
        ):
            funding_repository.PostgresBridgeRepository(scoped_url(schema))

        with admin_engine.connect() as connection:
            after = connection.exec_driver_sql(
                f'SELECT last_value, is_called FROM "{schema}".shadow_calls'
            ).one()
        assert after == before
    finally:
        if repository is not None:
            repository.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_v1_migration_and_malformed_signature_when_configured() -> None:
    postgres_url = os.getenv("TEST_PREDICTION_MARKETS_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_PREDICTION_MARKETS_POSTGRES_URL is not configured")

    v1_schema = f"clink_funding_v1_{uuid4().hex}"
    malformed_schema = f"clink_funding_bad_{uuid4().hex}"

    def scoped_url(name: str) -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={name}"})
            .render_as_string(hide_password=False)
        )

    admin_engine = create_engine(postgres_url)
    v1_engine = None
    malformed_engine = None
    migrated_repository = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{v1_schema}"'))
            connection.execute(text(f'CREATE SCHEMA "{malformed_schema}"'))

        v1_engine = create_engine(scoped_url(v1_schema))
        with v1_engine.begin() as connection:
            for table in (
                funding_repository.BridgeSchemaVersionRow.__table__,
                funding_repository.BridgeDepositTargetRow.__table__,
                funding_repository.BridgeDepositClaimRow.__table__,
                funding_repository.BridgeObservationRow.__table__,
            ):
                table.create(connection)
            connection.execute(
                funding_repository.BridgeSchemaVersionRow.__table__.insert().values(
                    singleton=1, version=1
                )
            )
            connection.execute(
                funding_repository.BridgeDepositTargetRow.__table__.insert().values(
                    deposit_id="pm_deposit_pg_v1",
                    user_id=USER_ID,
                    binding_id=BINDING_ID,
                    venue_wallet_address=VENUE_WALLET,
                    bridge_address=BRIDGE_ADDRESS,
                    source_network="eip155:137",
                    source_token_address=SOURCE_TOKEN,
                    destination_network="eip155:137",
                    destination_token_address=DESTINATION_TOKEN,
                    status="ready",
                    created_at=NOW,
                )
            )
        migrated_repository = funding_repository.PostgresBridgeRepository(
            scoped_url(v1_schema)
        )
        assert migrated_repository.find_deposit_target_for_binding(
            user_id=USER_ID, binding_id=BINDING_ID
        ) is not None
        with migrated_repository.engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version FROM polymarket_bridge_schema_version")
            ) == funding_repository.BRIDGE_SCHEMA_VERSION
            assert connection.scalar(
                text("SELECT count(*) FROM polymarket_bridge_deposit_targets")
            ) == 1

        malformed_engine = create_engine(scoped_url(malformed_schema))
        with malformed_engine.begin() as connection:
            for table in (
                funding_repository.BridgeSchemaVersionRow.__table__,
                funding_repository.BridgeDepositTargetRow.__table__,
                funding_repository.BridgeDepositClaimRow.__table__,
                funding_repository.BridgeObservationRow.__table__,
            ):
                table.create(connection)
            connection.execute(
                funding_repository.BridgeSchemaVersionRow.__table__.insert().values(
                    singleton=1, version=1
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE polymarket_bridge_deposit_targets "
                    "DROP COLUMN source_token_address CASCADE"
                )
            )
        with pytest.raises(
            funding_repository.BridgeRepositoryError,
            match="bridge database schema is incomplete",
        ):
            funding_repository.PostgresBridgeRepository(
                scoped_url(malformed_schema)
            )
        with malformed_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version FROM polymarket_bridge_schema_version")
            ) == 1
            assert "polymarket_funding_operations" not in set(
                sa_inspect(connection).get_table_names()
            )
    finally:
        if migrated_repository is not None:
            migrated_repository.engine.dispose()
        if v1_engine is not None:
            v1_engine.dispose()
        if malformed_engine is not None:
            malformed_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{v1_schema}" CASCADE'))
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{malformed_schema}" CASCADE')
            )
        admin_engine.dispose()


def _chain_confirmed_operation(repository):
    current, _ = repository.create_funding_operation(
        _operation(
            operation_id="pm_funding_operation_bridge_failure",
            idempotency_key="pm_funding_idempotency_bridge_failure",
        )
    )
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
        "chain_confirmed",
    ):
        current = _advance(repository, current, status)
    return current


def _venue_side_failed(current, **updates: object):
    values: dict[str, object] = {
        "status": "failed",
        "bridge_observation_id": "pm_observation_bridge_failed",
        "bridge_status": "FAILED",
        "failure_reason_code": "POLYMARKET_BRIDGE_FAILED",
    }
    values.update(updates)
    return _replacement(current, **values)


def test_venue_side_failure_has_one_exact_disjoint_model_proof_shape(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "venue-failure-model.sqlite3")
    chain_confirmed = _chain_confirmed_operation(repository)

    failed = type(chain_confirmed).model_validate(
        _venue_side_failed(chain_confirmed).model_dump()
    )

    assert failed.status == "failed"
    assert failed.core_state == "settled"
    assert failed.core_replacement_forbidden is False
    assert failed.core_failure_evidence_kind is None
    assert failed.bridge_status == "FAILED"
    assert failed.venue_buying_power_after_atomic is None

    invalid_updates = (
        {"core_state": "spending_reserved"},
        {"core_replacement_forbidden": True},
        {"core_failure_evidence_kind": "failed_receipt"},
        {"bridge_observation_id": None},
        {"bridge_status": "COMPLETED"},
        {"failure_reason_code": "SOME_OTHER_FAILURE"},
        {"venue_buying_power_after_atomic": "1"},
        {"finalized_at": chain_confirmed.updated_at + timedelta(seconds=2)},
    )
    for updates in invalid_updates:
        invalid = failed.model_dump()
        invalid.update(updates)
        with pytest.raises(ValidationError):
            type(failed).model_validate(invalid)


def test_chain_confirmed_can_cas_to_terminal_venue_side_failure(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "venue-failure-cas.sqlite3")
    chain_confirmed = _chain_confirmed_operation(repository)
    failed = _venue_side_failed(chain_confirmed)

    stored = repository.compare_and_set_funding_operation(
        expected_revision=chain_confirmed.revision,
        expected_status="chain_confirmed",
        replacement=failed,
    )

    assert stored == failed
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is terminal",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=failed.revision,
            expected_status="failed",
            replacement=_replacement(failed, status="failed"),
        )


def test_raw_guard_allows_only_post_settlement_venue_side_failure(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "venue-failure-raw.sqlite3")
    chain_confirmed = _chain_confirmed_operation(repository)

    with repository.engine.begin() as connection:
        connection.execute(
            funding_repository.PolymarketFundingOperationRow.__table__.update()
            .where(
                funding_repository.PolymarketFundingOperationRow.operation_id
                == chain_confirmed.operation_id
            )
            .values(
                status="failed",
                bridge_observation_id="pm_observation_bridge_failed",
                bridge_status="FAILED",
                failure_reason_code="POLYMARKET_BRIDGE_FAILED",
                revision=chain_confirmed.revision + 1,
                updated_at=chain_confirmed.updated_at + timedelta(seconds=1),
            )
        )
    stored = repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=chain_confirmed.operation_id,
    )
    assert stored is not None
    assert stored.status == "failed"
    assert stored.bridge_status == "FAILED"

    for index, invalid_changes in enumerate(
        (
            {"bridge_observation_id": None},
            {"bridge_status": "COMPLETED"},
            {"failure_reason_code": "SOME_OTHER_FAILURE"},
            {"venue_buying_power_after_atomic": "1"},
        ),
        start=1,
    ):
        repository = _seeded_repository(
            tmp_path / f"venue-failure-invalid-{index}.sqlite3"
        )
        current, _ = repository.create_funding_operation(
            _operation(
                operation_id=f"pm_funding_operation_bridge_failure_raw_{index}",
                idempotency_key=f"pm_funding_idempotency_bridge_failure_raw_{index}",
            )
        )
        for status in (
            "confirmed",
            "action_creating",
            "action_created",
            "policy_evaluating",
            "policy_approved",
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
            "submitted",
            "chain_confirmed",
        ):
            current = _advance(repository, current, status)
        values = {
            "status": "failed",
            "bridge_observation_id": f"pm_observation_bridge_failed_raw_{index}",
            "bridge_status": "FAILED",
            "failure_reason_code": "POLYMARKET_BRIDGE_FAILED",
            "revision": current.revision + 1,
            "updated_at": current.updated_at + timedelta(seconds=1),
        }
        values.update(invalid_changes)
        with pytest.raises(IntegrityError):
            with repository.engine.begin() as connection:
                connection.execute(
                    funding_repository.PolymarketFundingOperationRow.__table__.update()
                    .where(
                        funding_repository.PolymarketFundingOperationRow.operation_id
                        == current.operation_id
                    )
                    .values(**values)
                )


def test_fabricated_bridge_failure_cannot_exit_a_broadcast_ambiguous_state(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "venue-failure-wrong-origin.sqlite3")
    current, _ = repository.create_funding_operation(
        _operation(
            operation_id="pm_funding_operation_bridge_failure_wrong_origin",
            idempotency_key="pm_funding_idempotency_bridge_failure_wrong_origin",
        )
    )
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "settlement_submitting",
    ):
        current = _advance(repository, current, status)

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    status="failed",
                    core_tx_hash=TX_HASH,
                    core_state="settled",
                    bridge_observation_id="pm_observation_fabricated_bridge_failed",
                    bridge_status="FAILED",
                    failure_reason_code="POLYMARKET_BRIDGE_FAILED",
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )


class _CoordinatorCoreFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.mutation_calls: list[str] = []
        self.create_action_error: RuntimeError | None = None
        self.policy_error: RuntimeError | None = None
        self.policy_approved = True
        self.settle_error: RuntimeError | None = None
        self.settle_state = "payment_submitted"
        self.reservation_state = "payment_submitted"
        self.reconcile_state = "payment_submitted"
        self.release_error: RuntimeError | None = None

    def funding_readiness(self):
        self.calls.append(("funding_readiness", None))
        return {
            "status": "ready",
            "live_funding_enabled": True,
            "native_facilitator_ready": True,
            "settlement_rail": "clink_native_facilitator",
            "spender_address": SPENDER_ADDRESS,
            "supported_assets": {"eip155:137": SOURCE_TOKEN},
        }

    def account_readiness(self, user_id: str):
        self.calls.append(("account_readiness", user_id))
        return {
            "user_id": user_id,
            "wallet_bound": True,
            "wallet_address": "0x" + "3" * 40,
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_active": True,
            "active_spending_mandate": {
                "spending_grant_id": "spending_grant_1",
                "agent_id": "hermes",
                "limits_usdc": {
                    "per_transaction": "5",
                    "rolling_hour": "10",
                    "daily": "10",
                    "total": "25",
                },
                "remaining_usdc": {
                    "rolling_hour": "10",
                    "daily": "10",
                    "total": "25",
                },
                "product_scopes": ["prediction_markets"],
                "venue_scopes": ["polymarket"],
                "merchant_scopes": [],
                "merchant_trust_scopes": ["clink_verified"],
                "network_scopes": ["eip155:137"],
                "asset_scopes": [SOURCE_TOKEN],
                "notification_mode": "silent_under_limits",
                "expires_at": "2026-09-19T12:00:00Z",
            },
            "chain_allowances": {"eip155:137": True},
            "ready": False,
        }

    def resolve_authorization(self, **kwargs):
        self.calls.append(("resolve_authorization", kwargs))
        return {
            "ready": True,
            "authorization_rail": "native_allowance",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
            "asset_allowance_id": "asset_allowance_1",
            "required_amount_atomic": int(kwargs["amount_atomic"]),
            "observed_allowance_atomic": 25_000_000,
            "opc_installation_id": kwargs.get("opc_installation_id"),
            "next_action": "create_action_and_evaluate_policy",
        }

    def create_action(self, context):
        self.mutation_calls.append("create_action")
        self.calls.append(("create_action", context))
        if self.create_action_error is not None:
            raise self.create_action_error
        return {"action_id": "core_action_1", "state": "created"}

    def evaluate_policy(self, context, **kwargs):
        self.mutation_calls.append("evaluate_policy")
        self.calls.append(("evaluate_policy", (context, kwargs)))
        if self.policy_error is not None:
            raise self.policy_error
        return {
            "policy_decision_id": "core_policy_1",
            "approved": self.policy_approved,
            "decision": "approved" if self.policy_approved else "blocked",
            "reason_code": "ALLOW" if self.policy_approved else "POLICY_BLOCKED",
            "required_action": None,
            "risk_level": kwargs["risk_level"],
            "risk_score": kwargs["risk_score"],
            "risk_action": kwargs["risk_action"],
            "risk_assessment": {
                "provider": "misttrack",
                "provider_endpoint": "v2/risk_score",
                "subject": context.destination,
                "network": "eip155:137",
                "asset": "USDC",
                "coin": "USDC-Polygon",
                "score": 7,
                "risk_level": "low",
                "indicators": [],
                "risk_details": [],
                "hacking_event": None,
                "decision": "allow",
                "decision_reasons": ["score:7"],
                "mode": "enforce",
                "enforced": True,
                "mapping_version": "misttrack-policy-v1",
                "hold_score": 31,
                "deny_score": 71,
                "assessed_at": "2026-08-19T11:59:30Z",
                "expires_at": "2026-08-19T12:04:30Z",
                "cache_hit": False,
                "response_sha256": "a" * 64,
            },
        }

    def update_action_policy_approved(self, context, **kwargs):
        self.mutation_calls.append("update_action_policy_approved")
        self.calls.append(("update_action_policy_approved", (context, kwargs)))
        return {
            "action_id": kwargs["action_id"],
            "state": "policy_approved",
            "policy_decision_id": kwargs["policy_decision_id"],
        }

    def audit_policy_evaluated(self, context, **kwargs):
        self.mutation_calls.append("audit_policy_evaluated")
        self.calls.append(("audit_policy_evaluated", (context, kwargs)))
        return {
            "event_id": "core_audit_1",
            "event_type": "prediction_market_funding_policy_evaluated",
            "source_service": "clink_prediction_markets",
        }

    def reserve(self, context, **kwargs):
        self.mutation_calls.append("reserve")
        self.calls.append(("reserve", (context, kwargs)))
        return {
            "reservation_id": "core_reservation_1",
            "state": "spending_reserved",
            "single_submission": True,
            "replacement_forbidden": False,
        }

    def settle(self, reservation_id: str, *, payment_authorization):
        self.mutation_calls.append("settle")
        self.calls.append(("settle", (reservation_id, payment_authorization)))
        if self.settle_error is not None:
            raise self.settle_error
        if self.settle_state == "definite_failure":
            return self._definite_failure_payload(reservation_id, "spending_reserved")
        return self._reservation_payload(reservation_id, self.settle_state)

    def _reservation_payload(self, reservation_id: str, state: str):
        result = {
            "reservation_id": reservation_id,
            "state": state,
            "single_submission": True,
            "replacement_forbidden": False,
        }
        if state in {"payment_submitted", "settled", "finalized"}:
            result["tx_hash"] = TX_HASH
        return result

    def _definite_failure_payload(self, reservation_id: str, state: str):
        return {
            "reservation_id": reservation_id,
            "state": state,
            "tx_hash": TX_HASH,
            "single_submission": True,
            "replacement_forbidden": True,
            "failed_submission_evidence": [
                {
                    "kind": "failed_receipt",
                    "reason_code": "onchain_revert",
                    "tx_hash": TX_HASH,
                }
            ],
        }

    def reservation(self, reservation_id: str):
        self.calls.append(("reservation", reservation_id))
        if self.reservation_state == "definite_failure":
            return self._definite_failure_payload(reservation_id, "spending_reserved")
        if self.reservation_state == "released_failure":
            return self._definite_failure_payload(reservation_id, "released")
        return self._reservation_payload(reservation_id, self.reservation_state)

    def reconcile(self, reservation_id: str):
        self.mutation_calls.append("reconcile")
        self.calls.append(("reconcile", reservation_id))
        if self.reconcile_state == "definite_failure":
            return self._definite_failure_payload(reservation_id, "spending_reserved")
        return self._reservation_payload(reservation_id, self.reconcile_state)

    def finalize(self, reservation_id: str, **kwargs):
        self.mutation_calls.append("finalize")
        self.calls.append(("finalize", (reservation_id, kwargs)))
        return {
            "reservation_id": reservation_id,
            "state": "finalized",
            "tx_hash": TX_HASH,
            "single_submission": True,
            "replacement_forbidden": False,
        }

    def release(self, reservation_id: str, **kwargs):
        self.mutation_calls.append("release")
        self.calls.append(("release", (reservation_id, kwargs)))
        if self.release_error is not None:
            raise self.release_error
        return self._definite_failure_payload(reservation_id, "released")


class _PrebroadcastCoordinatorCoreFake(_CoordinatorCoreFake):
    def __init__(self, risk_state: str, *, settle_loses_response: bool = False) -> None:
        super().__init__()
        self.risk_state = risk_state
        self.settle_loses_response = settle_loses_response

    def _prebroadcast_payload(self, reservation_id: str):
        blocked = self.risk_state == "blocked"
        return {
            "reservation_id": reservation_id,
            "state": "payment_submitted",
            "tx_hash": TX_HASH,
            "single_submission": True,
            "replacement_forbidden": False,
            "risk_prebroadcast_state": self.risk_state,
            "risk_prebroadcast_blocked": blocked,
            "risk_prebroadcast_blocked_at": (
                "2026-08-19T12:00:00Z" if blocked else None
            ),
            "reconciliation_status": (
                "manual_review_required" if blocked else "pending"
            ),
            "next_action": "operator_reconcile" if blocked else "reconcile_payment",
            "manual_review_reason": (
                "live funding risk assessment failed immediately before submission"
                if blocked
                else None
            ),
            "manual_review_required_at": (
                "2026-08-19T12:00:00Z" if blocked else None
            ),
        }

    def settle(self, reservation_id: str, *, payment_authorization):
        self.mutation_calls.append("settle")
        self.calls.append(("settle", (reservation_id, payment_authorization)))
        if self.settle_loses_response:
            raise RuntimeError("redacted Core settle response loss")
        return self._prebroadcast_payload(reservation_id)

    def reservation(self, reservation_id: str):
        self.calls.append(("reservation", reservation_id))
        return self._prebroadcast_payload(reservation_id)

    def reconcile(self, reservation_id: str):
        raise AssertionError("prebroadcast wait/block must not reconcile")

    def release(self, reservation_id: str, **kwargs):
        raise AssertionError("prebroadcast wait/block must not release")


class _RetryableReservedReleaseCoreFake(_CoordinatorCoreFake):
    """Core keeps a no-transaction reservation retryable until it is released."""

    @staticmethod
    def _retryable_payload(reservation_id: str) -> dict[str, object]:
        return {
            "reservation_id": reservation_id,
            "state": "spending_reserved",
            "reconciliation_status": "retryable",
            "next_action": "retry_settlement",
            "receipt_id": None,
            "tx_hash": None,
            "single_submission": True,
            "replacement_forbidden": False,
        }

    def reservation(self, reservation_id: str):
        self.calls.append(("reservation", reservation_id))
        return self._retryable_payload(reservation_id)

    def reconcile(self, reservation_id: str):
        self.mutation_calls.append("reconcile")
        self.calls.append(("reconcile", reservation_id))
        return self._retryable_payload(reservation_id)

    def release(self, reservation_id: str, **kwargs):
        self.mutation_calls.append("release")
        self.calls.append(("release", (reservation_id, kwargs)))
        return {
            "reservation_id": reservation_id,
            "state": "released",
            "reconciliation_status": "released",
            "next_action": "terminal",
            "release_reason": "prediction_market_prebroadcast_retry",
            "receipt_id": None,
            "tx_hash": None,
            "single_submission": True,
            "replacement_forbidden": False,
        }


class _VenueAccountFake:
    def __init__(self) -> None:
        self.binding_id = BINDING_ID
        self.venue_wallet_address = VENUE_WALLET
        self.buying_power_atomic = "0"
        self.calls: list[tuple[str, object]] = []

    def resolve_active_account(self, *, user_id: str):
        from services.funding_adapter_service.coordinator import VenueAccount

        self.calls.append(("resolve_active_account", user_id))
        return VenueAccount(
            user_id=user_id,
            binding_id=self.binding_id,
            venue_wallet_address=self.venue_wallet_address,
        )

    def get_buying_power_atomic(
        self, *, user_id: str, binding_id: str, venue_wallet_address: str
    ) -> str:
        self.calls.append(
            (
                "get_buying_power_atomic",
                (user_id, binding_id, venue_wallet_address),
            )
        )
        return self.buying_power_atomic


class _NoNetworkBridgeClient:
    def __init__(self) -> None:
        self.status_payload = None
        self.calls: list[tuple[str, object]] = []

    def post(self, _path, _payload):
        raise AssertionError("prepare must reuse the seeded Bridge target")

    def get(self, path):
        self.calls.append(("get", path))
        if self.status_payload is None:
            raise AssertionError("Bridge status was not configured")
        return self.status_payload


def _coordinator_config(tmp_path, **updates):
    from shared.config import AppConfig

    values = {
        "polymarket_bridge_database_path": str(tmp_path / "coordinator.sqlite3"),
        "prediction_markets_internal_api_token": "prediction-token",
        "clink_core_internal_api_token": "core-token",
        "live_mode": True,
        "require_user_confirmation": True,
    }
    values.update(updates)
    return AppConfig(**values)


def _coordinator_fixture(
    tmp_path, *, core=None, venue=None, risk=None, config=None
):
    from services.funding_adapter_service.coordinator import (
        PolymarketFundingCoordinator,
    )
    from services.funding_adapter_service.service import (
        PolymarketFundingAdapterService,
    )

    selected_config = config or _coordinator_config(tmp_path)
    repository = funding_repository.SQLiteBridgeRepository(
        selected_config.polymarket_bridge_database_path
    )
    repository.save_deposit_target(_target())
    bridge_client = _NoNetworkBridgeClient()
    bridge = PolymarketFundingAdapterService(
        selected_config,
        bridge_client=bridge_client,
        repository=repository,
        clock=lambda: NOW,
    )
    selected_core = core or _CoordinatorCoreFake()
    selected_venue = venue or _VenueAccountFake()
    selected_risk = risk or _RiskAssessmentFake()
    coordinator = PolymarketFundingCoordinator(
        config=selected_config,
        funding_adapter=bridge,
        core_gateway=selected_core,
        venue_accounts=selected_venue,
        risk_assessments=selected_risk,
        clock=lambda: NOW,
    )
    return coordinator, repository, selected_core, selected_venue


def _prepare_request(**updates):
    request_type = getattr(
        funding_schemas, "CreatePolymarketFundingOperationRequest"
    )
    values = {
        "user_id": USER_ID,
        "amount_usdc": "1.000000",
        "idempotency_key": "pm_coordinator_idem_1",
        "resource": "polymarket:funding:active",
    }
    values.update(updates)
    return request_type.model_validate(values)


def test_funding_http_requests_are_strict_subject_only_and_not_operation_models() -> None:
    request = _prepare_request()
    assert request.amount_usdc == "1.000000"
    assert request.model_dump().keys() == {
        "user_id",
        "amount_usdc",
        "idempotency_key",
        "resource",
        "opc_installation_id",
    }
    for invalid in (
        {"amount_usdc": 1.0},
        {"amount_usdc": "0.000000"},
        {"binding_id": BINDING_ID},
        {"venue_wallet_address": VENUE_WALLET},
        {"agent_id": "caller-selected-agent"},
    ):
        values = request.model_dump()
        values.update(invalid)
        with pytest.raises(ValidationError):
            type(request).model_validate(values)


@pytest.mark.parametrize(
    ("adapter_error", "expected_status", "expected_message"),
    [
        (
            "transport",
            503,
            "Bridge service is temporarily unavailable",
        ),
        (
            "context",
            409,
            "Bridge target context conflict",
        ),
        (
            "adapter",
            502,
            "Bridge target could not be created",
        ),
        (
            "value",
            502,
            "Bridge target could not be created",
        ),
    ],
)
def test_prepare_maps_bridge_target_failures_to_safe_retryable_statuses(
    tmp_path, adapter_error, expected_status, expected_message
) -> None:
    from services.funding_adapter_service.service import (
        BridgeAdapterError,
        BridgeTransportError,
    )

    coordinator, _repository, core, _venue = _coordinator_fixture(tmp_path)
    marker = "bridge-secret-marker"
    errors = {
        "transport": BridgeTransportError(marker),
        "context": BridgeAdapterError("bridge binding context conflict"),
        "adapter": BridgeAdapterError(marker),
        "value": ValueError(marker),
    }

    def fail(_request):
        raise errors[adapter_error]

    coordinator.funding_adapter.create_deposit_address = fail

    with pytest.raises(funding_coordinator.FundingCoordinatorError) as captured:
        coordinator.prepare(_prepare_request())

    assert captured.value.status_code == expected_status
    assert str(captured.value) == expected_message
    assert marker not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert core.mutation_calls == []


def test_prepare_derives_scope_and_persists_exact_operation_without_money_mutation(
    tmp_path,
) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)

    operation = coordinator.prepare(_prepare_request())

    assert operation.status == "created"
    assert operation.user_id == USER_ID
    assert operation.agent_id == "hermes"
    assert operation.binding_id == BINDING_ID
    assert operation.venue_wallet_address == VENUE_WALLET
    assert operation.bridge_address == BRIDGE_ADDRESS
    assert operation.amount_usdc == "1.000000"
    assert operation.amount_atomic == "1000000"
    assert operation.source_token_address == SOURCE_TOKEN
    assert operation.destination_token_address == DESTINATION_TOKEN
    assert operation.wallet_identity_id == "wallet_identity_1"
    assert operation.spending_grant_id == "spending_grant_1"
    assert operation.asset_allowance_id == "asset_allowance_1"
    assert operation.spender_address == SPENDER_ADDRESS
    assert operation.venue_buying_power_before_atomic == "0"
    assert operation.risk_level == "low"
    assert operation.risk_score == 7
    assert operation.risk_action == "approve"
    assert operation.request_hash.startswith("0x")
    assert operation.quote_hash.startswith("0x")
    assert core.mutation_calls == []
    assert venue.calls == [
        ("resolve_active_account", USER_ID),
        (
            "get_buying_power_atomic",
            (USER_ID, BINDING_ID, VENUE_WALLET),
        ),
    ]
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=operation.operation_id,
    ) == operation


def test_legacy_prepare_hash_inputs_do_not_add_a_null_opc_scope(
    tmp_path, monkeypatch
) -> None:
    coordinator, _repository, _core, _venue = _coordinator_fixture(tmp_path)
    captured: list[tuple[str, dict[str, object]]] = []
    canonical_hash = funding_coordinator._canonical_hash

    def capture_hash(label: str, value: dict[str, object]) -> str:
        captured.append((label, dict(value)))
        return canonical_hash(label, value)

    monkeypatch.setattr(funding_coordinator, "_canonical_hash", capture_hash)

    operation = coordinator.prepare(_prepare_request())

    assert operation.opc_installation_id is None
    assert [label for label, _value in captured] == ["request", "quote"]
    assert all("opc_installation_id" not in value for _label, value in captured)


def test_prepare_idempotency_replays_exact_request_and_rejects_all_drift(
    tmp_path,
) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)
    original = coordinator.prepare(_prepare_request())

    replay = coordinator.prepare(_prepare_request())

    assert replay == original
    assert core.mutation_calls == []

    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    with pytest.raises(FundingCoordinatorError, match="funding operation conflict"):
        coordinator.prepare(_prepare_request(amount_usdc="2.000000"))
    with pytest.raises(FundingCoordinatorError, match="funding operation conflict"):
        coordinator.prepare(_prepare_request(resource="polymarket:funding:changed"))

    venue.binding_id = "pm_binding_changed"
    venue.venue_wallet_address = "0x" + "9" * 40
    repository.save_deposit_target(
        _target(
            deposit_id="pm_deposit_changed_binding",
            binding_id=venue.binding_id,
            venue_wallet_address=venue.venue_wallet_address,
        )
    )
    with pytest.raises(FundingCoordinatorError, match="funding operation conflict"):
        coordinator.prepare(_prepare_request())


def test_prepare_persists_opc_installation_and_rejects_cross_installation_replay(
    tmp_path,
) -> None:
    coordinator, repository, core, _venue = _coordinator_fixture(tmp_path)
    request = _prepare_request(opc_installation_id=OPC_INSTALLATION_ID)

    original = coordinator.prepare(request)
    replay = coordinator.prepare(request)

    assert replay == original
    assert original.opc_installation_id == OPC_INSTALLATION_ID
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=original.operation_id,
    ).opc_installation_id == OPC_INSTALLATION_ID
    authorization = next(
        payload for name, payload in core.calls if name == "resolve_authorization"
    )
    assert authorization["opc_installation_id"] == OPC_INSTALLATION_ID

    for mismatched in (None, OTHER_OPC_INSTALLATION_ID):
        with pytest.raises(
            funding_coordinator.FundingCoordinatorError,
            match="funding operation conflict",
        ):
            coordinator.prepare(
                _prepare_request(opc_installation_id=mismatched)
            )


def test_confirm_and_advance_reject_cross_installation_before_core_mutation(
    tmp_path,
) -> None:
    coordinator, _repository, core, _venue = _coordinator_fixture(tmp_path)
    operation = coordinator.prepare(
        _prepare_request(opc_installation_id=OPC_INSTALLATION_ID)
    )
    core.calls.clear()
    core.mutation_calls.clear()

    with pytest.raises(
        funding_coordinator.FundingCoordinatorError,
        match="funding operation conflict",
    ):
        coordinator.confirm(
            operation.operation_id,
            _confirm_request(opc_installation_id=OTHER_OPC_INSTALLATION_ID),
        )
    with pytest.raises(
        funding_coordinator.FundingCoordinatorError,
        match="funding operation conflict",
    ):
        coordinator.advance(
            user_id=USER_ID,
            operation_id=operation.operation_id,
            opc_installation_id=None,
        )

    assert core.mutation_calls == []


def test_prepare_exact_replay_uses_persisted_operation_not_changed_external_state(
    tmp_path,
) -> None:
    coordinator, _repository, core, venue = _coordinator_fixture(tmp_path)
    original = coordinator.prepare(_prepare_request())
    core.calls.clear()
    venue.buying_power_atomic = "9999999"

    def unavailable_readiness():
        raise RuntimeError("external readiness changed")

    core.funding_readiness = unavailable_readiness

    replay = coordinator.prepare(_prepare_request())

    assert replay == original
    assert core.calls == []
    assert venue.calls[-1] == ("resolve_active_account", USER_ID)


def test_prepare_fails_closed_for_invalid_core_or_unavailable_scoped_venue_reader(
    tmp_path,
) -> None:
    from services.funding_adapter_service.coordinator import (
        FundingCoordinatorError,
        UnavailableVenueAccountGateway,
    )

    core = _CoordinatorCoreFake()
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path / "bad-core", core=core
    )
    original_account_readiness = core.account_readiness

    def wrong_agent(user_id: str):
        result = original_account_readiness(user_id)
        result["active_spending_mandate"]["agent_id"] = "other-agent"
        return result

    core.account_readiness = wrong_agent
    with pytest.raises(FundingCoordinatorError, match="Core account is not ready"):
        coordinator.prepare(_prepare_request())
    assert core.mutation_calls == []

    unavailable, _repository, unavailable_core, _venue = _coordinator_fixture(
        tmp_path / "unavailable",
        venue=UnavailableVenueAccountGateway(),
    )
    with pytest.raises(
        FundingCoordinatorError, match="venue account service is unavailable"
    ) as captured:
        unavailable.prepare(_prepare_request())
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert unavailable_core.calls == []


def _confirm_request(**updates):
    request_type = getattr(
        funding_schemas, "ConfirmPolymarketFundingOperationRequest"
    )
    values = {"user_id": USER_ID, "confirmed": True}
    values.update(updates)
    return request_type.model_validate(values)


def _bridge_payload(status: str, *, amount_atomic: str = "1000000"):
    return {
        "transactions": [
            {
                "fromChainId": "137",
                "fromTokenAddress": SOURCE_TOKEN,
                "fromAmountBaseUnit": amount_atomic,
                "toChainId": "137",
                "toTokenAddress": DESTINATION_TOKEN,
                "status": status,
                "txHash": TX_HASH,
                "createdTimeMs": 1_787_140_800_000,
            }
        ],
        "nextCursor": None,
    }


def test_confirmation_request_is_strict_true_and_live_gates_precede_core_mutation(
    tmp_path,
) -> None:
    request = _confirm_request()
    for invalid in (
        {"confirmed": False},
        {"binding_id": BINDING_ID},
        {"operation_id": OPERATION_ID},
        {"agent_id": "caller-selected-agent"},
    ):
        values = request.model_dump()
        values.update(invalid)
        with pytest.raises(ValidationError):
            type(request).model_validate(values)

    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    for index, config_updates in enumerate(
        (
            {"live_mode": False},
            {"require_user_confirmation": False},
        ),
        start=1,
    ):
        config = _coordinator_config(tmp_path / str(index), **config_updates)
        coordinator, repository, core, _venue = _coordinator_fixture(
            tmp_path / str(index), config=config
        )
        operation = coordinator.prepare(_prepare_request())
        with pytest.raises(
            FundingCoordinatorError, match="live funding confirmation is unavailable"
        ):
            coordinator.confirm(operation.operation_id, request)
        stored = repository.get_funding_operation(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            operation_id=operation.operation_id,
        )
        assert stored is not None
        assert stored.status == "created"
        assert core.mutation_calls == []


def test_advance_rechecks_live_gates_after_a_confirmed_operation_is_reloaded(
    tmp_path,
) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)
    created = coordinator.prepare(_prepare_request())
    confirmed = created.model_copy(
        update={
            "status": "confirmed",
            "confirmed_at": NOW,
            "updated_at": NOW,
            "revision": created.revision + 1,
        }
    )
    assert repository.compare_and_set_funding_operation(
        expected_revision=created.revision,
        expected_status="created",
        replacement=confirmed,
    ) == confirmed

    from services.funding_adapter_service.coordinator import (
        FundingCoordinatorError,
        PolymarketFundingCoordinator,
    )

    disabled = PolymarketFundingCoordinator(
        config=_coordinator_config(tmp_path, live_mode=False),
        funding_adapter=coordinator.funding_adapter,
        core_gateway=core,
        venue_accounts=venue,
        clock=lambda: NOW,
    )

    with pytest.raises(
        FundingCoordinatorError, match="live funding confirmation is unavailable"
    ):
        disabled.advance(user_id=USER_ID, operation_id=created.operation_id)
    assert core.mutation_calls == []


def test_confirm_runs_core_controls_in_order_and_submits_once(tmp_path) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)
    operation = coordinator.prepare(_prepare_request())

    submitted = coordinator.confirm(operation.operation_id, _confirm_request())

    assert submitted.status == "submitted"
    assert submitted.core_state == "payment_submitted"
    assert submitted.core_tx_hash == TX_HASH
    assert core.mutation_calls == [
        "create_action",
        "evaluate_policy",
        "update_action_policy_approved",
        "audit_policy_evaluated",
        "reserve",
        "settle",
    ]
    settle_call = next(value for name, value in core.calls if name == "settle")
    assert settle_call == (
        "core_reservation_1",
        {
            "kind": "prediction_market_bridge_transfer",
            "operation_id": operation.operation_id,
            "reservation_id": "core_reservation_1",
            "binding_id": BINDING_ID,
            "bridge_address": BRIDGE_ADDRESS,
            "source_token": SOURCE_TOKEN,
            "amount_atomic": "1000000",
        },
    )
    replay = coordinator.confirm(operation.operation_id, _confirm_request())
    assert replay.status in {"submitted", "chain_confirmed"}
    assert core.mutation_calls.count("settle") == 1
    stored = repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=operation.operation_id,
    )
    assert stored == replay


def test_blocked_prebroadcast_response_enters_terminal_manual_review(tmp_path) -> None:
    core = _PrebroadcastCoordinatorCoreFake("blocked", settle_loses_response=True)
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    reviewed = coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    )
    mutations_at_review = list(core.mutation_calls)
    calls_at_review = list(core.calls)

    assert unknown.status == "settlement_unknown"
    assert reviewed.status == "manual_review"
    assert reviewed.reservation_id == "core_reservation_1"
    assert reviewed.core_state == "payment_submitted"
    assert reviewed.core_tx_hash == TX_HASH
    assert reviewed.failure_reason_code == "CORE_RISK_PREBROADCAST_BLOCKED"
    assert core.mutation_calls.count("settle") == 1
    assert "reconcile" not in core.mutation_calls
    assert "release" not in core.mutation_calls

    assert coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    ) == reviewed
    assert core.mutation_calls == mutations_at_review
    assert core.calls == calls_at_review


def test_pending_prebroadcast_response_waits_without_reconcile_or_retry(tmp_path) -> None:
    core = _PrebroadcastCoordinatorCoreFake("pending")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    waiting = coordinator.confirm(operation.operation_id, _confirm_request())
    mutations_after_settle = list(core.mutation_calls)
    recovered = coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    )

    assert waiting.status == "settlement_unknown"
    assert waiting.reservation_id == "core_reservation_1"
    assert waiting.core_state == "payment_submitted"
    assert waiting.core_tx_hash == TX_HASH
    assert recovered == waiting
    assert core.mutation_calls == mutations_after_settle
    assert core.mutation_calls.count("settle") == 1


def test_ready_prebroadcast_response_preserves_existing_submitted_path(tmp_path) -> None:
    core = _PrebroadcastCoordinatorCoreFake("ready")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    submitted = coordinator.confirm(operation.operation_id, _confirm_request())

    assert submitted.status == "submitted"
    assert submitted.core_state == "payment_submitted"
    assert submitted.core_tx_hash == TX_HASH
    assert core.mutation_calls.count("settle") == 1


def test_action_response_loss_is_persisted_unknown_and_never_retried(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.create_action_error = RuntimeError("secret action response marker")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    replay = coordinator.advance(user_id=USER_ID, operation_id=operation.operation_id)

    assert unknown.status == "action_unknown"
    assert replay == unknown
    assert core.mutation_calls == ["create_action"]
    assert "secret action response marker" not in repr(unknown)


def test_policy_response_loss_is_persisted_unknown_and_never_retried(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.policy_error = RuntimeError("secret policy response marker")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    replay = coordinator.advance(user_id=USER_ID, operation_id=operation.operation_id)

    assert unknown.status == "policy_unknown"
    assert replay == unknown
    assert core.mutation_calls == ["create_action", "evaluate_policy"]


def test_policy_block_is_terminal_before_reservation_or_settlement(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.policy_approved = False
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    failed = coordinator.confirm(operation.operation_id, _confirm_request())

    assert failed.status == "failed"
    assert failed.failure_reason_code == "POLICY_BLOCKED"
    assert core.mutation_calls == ["create_action", "evaluate_policy"]


def test_settlement_ambiguity_uses_only_get_and_reconcile_and_never_settles_again(
    tmp_path,
) -> None:
    core = _CoordinatorCoreFake()
    core.settle_error = RuntimeError("secret settlement response marker")
    core.reservation_state = "spending_reserved"
    core.reconcile_state = "spending_reserved"
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    recovered = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )
    recovered_again = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )

    assert unknown.status == "settlement_unknown"
    assert recovered.status == "settlement_unknown"
    assert recovered_again.status == "settlement_unknown"
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("reconcile") == 2
    assert sum(name == "reservation" for name, _value in core.calls) >= 2


def test_retryable_no_transaction_reservation_is_released_once(
    tmp_path,
) -> None:
    core = _RetryableReservedReleaseCoreFake()
    core.settle_error = RuntimeError("Core settle response unavailable")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    released = coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    )

    assert unknown.status == "settlement_unknown"
    assert released.status == "released"
    assert released.core_state == "released"
    assert released.core_tx_hash is None
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("reconcile") == 1
    assert core.mutation_calls.count("release") == 1
    assert core.mutation_calls[-2:] == ["reconcile", "release"]


def test_retryable_no_transaction_recovery_does_not_release_local_tx_evidence(
    tmp_path,
) -> None:
    core = _RetryableReservedReleaseCoreFake()
    core.settle_error = RuntimeError("Core settle response unavailable")
    coordinator, repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    with_local_tx = _replacement(
        unknown,
        status="settlement_unknown",
        core_state="payment_submitted",
        core_tx_hash=TX_HASH,
    )
    stamped = repository.compare_and_set_funding_operation(
        expected_revision=unknown.revision,
        expected_status="settlement_unknown",
        replacement=with_local_tx,
    )
    assert stamped is not None

    try:
        recovered = coordinator.advance(
            user_id=USER_ID,
            operation_id=operation.operation_id,
        )
    except funding_coordinator.FundingCoordinatorError:
        recovered = repository.get_funding_operation(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            operation_id=operation.operation_id,
        )

    assert recovered is not None
    assert recovered.status == "settlement_unknown"
    assert recovered.core_tx_hash == TX_HASH
    assert core.mutation_calls.count("release") == 0


def test_definite_core_failure_is_read_before_exact_release(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "definite_failure"
    core.reservation_state = "definite_failure"
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    released = coordinator.confirm(operation.operation_id, _confirm_request())

    assert released.status == "released"
    assert released.core_state == "released"
    assert released.core_tx_hash == TX_HASH
    assert released.core_replacement_forbidden is True
    assert released.core_failure_evidence_kind == "failed_receipt"
    assert released.failure_reason_code == "ONCHAIN_REVERT"
    call_names = [name for name, _value in core.calls]
    assert call_names.index("settle") < call_names.index("reservation")
    assert call_names.index("reservation") < call_names.index("release")


def test_bridge_and_buying_power_proofs_are_scoped_before_finalization(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "settled"
    core.reservation_state = "settled"
    coordinator, _repository, _core, venue = _coordinator_fixture(
        tmp_path, core=core
    )
    bridge_client = coordinator.funding_adapter.bridge_client
    bridge_client.status_payload = _bridge_payload("PROCESSING")
    operation = coordinator.prepare(_prepare_request())

    pending = coordinator.confirm(operation.operation_id, _confirm_request())

    assert pending.status == "bridge_pending"
    assert pending.bridge_status == "PROCESSING"
    assert core.mutation_calls.count("settle") == 1

    bridge_client.status_payload = _bridge_payload("COMPLETED")
    unchanged = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )
    assert unchanged.status == "bridge_pending"
    assert unchanged.bridge_status == "COMPLETED"
    assert unchanged.venue_buying_power_after_atomic == "0"
    assert "finalize" not in core.mutation_calls

    venue.buying_power_atomic = "1000000"
    credited = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )
    assert credited.status == "venue_credited"
    finalized = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )
    assert finalized.status == "finalized"
    assert finalized.core_state == "finalized"
    assert finalized.finalized_at is not None
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("finalize") == 1
    assert all(
        call[1] == (USER_ID, BINDING_ID, VENUE_WALLET)
        for call in venue.calls
        if call[0] == "get_buying_power_atomic"
    )


def test_core_settlement_is_one_action_and_venue_sync_is_a_separate_step(
    tmp_path,
) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "settled"
    core.reservation_state = "settled"

    original_reservation_payload = core._reservation_payload

    def settled_receipt(reservation_id: str, state: str):
        result = original_reservation_payload(reservation_id, state)
        if state == "settled":
            result.update(
                receipt_id="fund_receipt_pm_1",
                receipt={"receipt_id": "fund_receipt_pm_1", "tx_hash": TX_HASH},
            )
        return result

    core._reservation_payload = settled_receipt
    coordinator, _repository, _core, venue = _coordinator_fixture(
        tmp_path, core=core
    )
    bridge_client = coordinator.funding_adapter.bridge_client
    bridge_client.status_payload = _bridge_payload("PROCESSING")
    operation = coordinator.prepare(_prepare_request())
    venue.calls.clear()

    pending = coordinator.confirm(operation.operation_id, _confirm_request())

    assert pending.status == "bridge_pending"
    assert pending.core_state == "settled"
    assert pending.core_tx_hash == TX_HASH
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("reserve") == 1
    assert [
        name for name, _ in venue.calls if name == "get_buying_power_atomic"
    ] == []
    assert all(name not in {"hosted_execute", "relayer_submit"} for name, _ in core.calls)
    assert all(name == "get" for name, _ in bridge_client.calls)

    bridge_client.status_payload = _bridge_payload("COMPLETED")
    venue.buying_power_atomic = "1000000"
    credited = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )
    finalized = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )

    assert credited.status == "venue_credited"
    assert finalized.status == "finalized"
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("finalize") == 1
    assert sum(name == "get_buying_power_atomic" for name, _ in venue.calls) == 1


@pytest.mark.parametrize("drift_source", ("reservation", "finalize"))
def test_finalization_canonical_transaction_drift_enters_manual_review(
    tmp_path, drift_source: str
) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "settled"
    core.reservation_state = "settled"
    coordinator, _repository, _core, venue = _coordinator_fixture(
        tmp_path, core=core
    )
    coordinator.funding_adapter.bridge_client.status_payload = _bridge_payload(
        "COMPLETED"
    )
    operation = coordinator.prepare(_prepare_request())
    venue.buying_power_atomic = "1000000"
    credited = coordinator.confirm(operation.operation_id, _confirm_request())
    assert credited.status == "venue_credited"

    drifted_hash = "0x" + "d" * 64
    if drift_source == "reservation":
        def drifted_reservation(reservation_id: str):
            result = core._reservation_payload(reservation_id, "settled")
            result["tx_hash"] = drifted_hash
            core.calls.append(("reservation", reservation_id))
            return result

        core.reservation = drifted_reservation
    else:
        original_finalize = core.finalize

        def drifted_finalize(reservation_id: str, **kwargs):
            result = original_finalize(reservation_id, **kwargs)
            result["tx_hash"] = drifted_hash
            return result

        core.finalize = drifted_finalize

    mutation_counts_before = {
        name: core.mutation_calls.count(name)
        for name in ("settle", "release", "finalize")
    }
    reviewed = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )

    assert reviewed.status == "manual_review"
    assert reviewed.core_tx_hash == TX_HASH
    assert reviewed.failure_reason_code == "CORE_TX_HASH_DRIFT"
    assert core.mutation_calls.count("settle") == mutation_counts_before["settle"]
    assert core.mutation_calls.count("release") == mutation_counts_before["release"]
    assert core.mutation_calls.count("finalize") == (
        mutation_counts_before["finalize"] + (drift_source == "finalize")
    )
    mutations_at_review = list(core.mutation_calls)
    assert coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    ) == reviewed
    assert core.mutation_calls == mutations_at_review


def test_bridge_failed_after_core_settlement_is_terminal_without_core_release(
    tmp_path,
) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "settled"
    core.reservation_state = "settled"
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    coordinator.funding_adapter.bridge_client.status_payload = _bridge_payload(
        "FAILED"
    )
    operation = coordinator.prepare(_prepare_request())

    failed = coordinator.confirm(operation.operation_id, _confirm_request())

    assert failed.status == "failed"
    assert failed.core_state == "settled"
    assert failed.bridge_status == "FAILED"
    assert failed.failure_reason_code == "POLYMARKET_BRIDGE_FAILED"
    assert failed.core_replacement_forbidden is False
    assert "release" not in core.mutation_calls


def test_get_confirm_and_advance_rederive_subject_scope_and_reject_cross_user(
    tmp_path,
) -> None:
    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    coordinator, _repository, core, _venue = _coordinator_fixture(tmp_path)
    operation = coordinator.prepare(_prepare_request())

    assert coordinator.get(user_id=USER_ID, operation_id=operation.operation_id) == operation
    for action in (
        lambda: coordinator.get(
            user_id="telegram_user_2", operation_id=operation.operation_id
        ),
        lambda: coordinator.advance(
            user_id="telegram_user_2", operation_id=operation.operation_id
        ),
        lambda: coordinator.confirm(
            operation.operation_id,
            _confirm_request(user_id="telegram_user_2"),
        ),
    ):
        with pytest.raises(
            FundingCoordinatorError, match="funding operation is unavailable"
        ):
            action()
    assert core.mutation_calls == []


def test_internal_funding_routes_are_bearer_first_subject_only_and_safe(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from services.funding_adapter_service.app import create_app

    coordinator, _repository, _core, _venue = _coordinator_fixture(tmp_path)
    app = create_app(
        config=coordinator.config,
        service=coordinator.funding_adapter,
        coordinator=coordinator,
    )
    token = {"Authorization": "Bearer prediction-token"}
    marker = "raw-private-key-input-marker"

    with TestClient(app) as client:
        unauthenticated = client.post(
            "/polymarket/funding-operations",
            content=b'{"amount_usdc":"' + marker.encode() + b'"',
            headers={"Content-Type": "application/json"},
        )
        invalid = client.post(
            "/polymarket/funding-operations",
            json={
                **_prepare_request().model_dump(),
                "binding_id": BINDING_ID,
                "private_key": marker,
            },
            headers=token,
        )
        created = client.post(
            "/polymarket/funding-operations",
            json=_prepare_request().model_dump(),
            headers=token,
        )

        assert unauthenticated.status_code == 401
        assert unauthenticated.json() == {"detail": "invalid internal bearer token"}
        assert invalid.status_code == 422
        assert invalid.json() == {"detail": "request is invalid"}
        assert marker not in invalid.text
        assert created.status_code == 201
        operation_id = created.json()["operation_id"]
        assert created.json().keys() == {
            "operation_id",
            "user_id",
            "binding_id",
            "venue_wallet_address",
            "bridge_address",
            "status",
            "amount_usdc",
            "resource",
            "action_id",
            "policy_decision_id",
            "audit_event_id",
            "reservation_id",
            "core_tx_hash",
            "core_state",
            "bridge_status",
            "venue_buying_power_before_atomic",
            "venue_buying_power_after_atomic",
            "failure_reason_code",
            "confirmed_at",
            "finalized_at",
            "created_at",
            "updated_at",
            "revision",
            "next_action",
        }
        assert created.json()["user_id"] == USER_ID
        assert created.json()["binding_id"] == BINDING_ID
        assert created.json()["venue_wallet_address"] == VENUE_WALLET
        assert created.json()["bridge_address"] == BRIDGE_ADDRESS
        assert created.json()["venue_buying_power_before_atomic"] == "0"
        assert created.json()["venue_buying_power_after_atomic"] is None
        assert "opc_installation_id" not in created.json()
        assert "hermes" not in created.text.lower()
        assert "private" not in created.text.lower()
        assert "raw" not in created.text.lower()

        fetched = client.get(
            f"/polymarket/funding-operations/{operation_id}",
            params={"user_id": USER_ID},
            headers=token,
        )
        history = client.get(
            f"/polymarket/funding-history/{operation_id}",
            params={"user_id": USER_ID},
            headers=token,
        )
        confirmed = client.post(
            f"/polymarket/funding-operations/{operation_id}/confirm",
            json=_confirm_request().model_dump(),
            headers=token,
        )
        advanced = client.post(
            f"/polymarket/funding-operations/{operation_id}/advance",
            json={"user_id": USER_ID},
            headers=token,
        )

        assert fetched.status_code == 200
        assert fetched.json()["status"] == "created"
        assert "opc_installation_id" not in fetched.json()
        assert history.status_code == 200
        assert "opc_installation_id" not in history.json()
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "submitted"
        assert "opc_installation_id" not in confirmed.json()
        assert advanced.status_code == 200
        assert advanced.json()["operation_id"] == operation_id
        assert "opc_installation_id" not in advanced.json()
        assert "hermes" not in confirmed.text.lower()


def test_opc_funding_http_responses_echo_exact_installation_scope(
    tmp_path,
) -> None:
    from fastapi.testclient import TestClient

    from services.funding_adapter_service.app import create_app

    coordinator, _repository, _core, _venue = _coordinator_fixture(tmp_path)
    app = create_app(
        config=coordinator.config,
        service=coordinator.funding_adapter,
        coordinator=coordinator,
    )
    token = {"Authorization": "Bearer prediction-token"}
    request = _prepare_request(opc_installation_id=OPC_INSTALLATION_ID)

    with TestClient(app) as client:
        created = client.post(
            "/polymarket/funding-operations",
            json=request.model_dump(),
            headers=token,
        )
        operation_id = created.json()["operation_id"]
        fetched = client.get(
            f"/polymarket/funding-operations/{operation_id}",
            params={"user_id": USER_ID},
            headers=token,
        )
        history = client.get(
            f"/polymarket/funding-history/{operation_id}",
            params={"user_id": USER_ID},
            headers=token,
        )
        confirmed = client.post(
            f"/polymarket/funding-operations/{operation_id}/confirm",
            json=_confirm_request(
                opc_installation_id=OPC_INSTALLATION_ID
            ).model_dump(),
            headers=token,
        )
        advanced = client.post(
            f"/polymarket/funding-operations/{operation_id}/advance",
            json={
                "user_id": USER_ID,
                "opc_installation_id": OPC_INSTALLATION_ID,
            },
            headers=token,
        )

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert history.status_code == 200
    assert confirmed.status_code == 200
    assert advanced.status_code == 200
    for response in (created, fetched, history, confirmed, advanced):
        assert response.json()["opc_installation_id"] == OPC_INSTALLATION_ID


def test_default_app_assembles_production_funding_coordinator(
    tmp_path,
) -> None:
    from fastapi.testclient import TestClient

    from services.funding_adapter_service.app import create_app

    config = _coordinator_config(
        tmp_path,
        account_binding_file=str(tmp_path / "bindings.jsonl"),
        credential_store_file=str(tmp_path / "credentials.jsonl"),
        credential_store_dev_secret="default-app-test-secret",
    )
    coordinator, _repository, core, _venue = _coordinator_fixture(
        tmp_path, config=config
    )
    app = create_app(
        config=coordinator.config,
        service=coordinator.funding_adapter,
    )
    with TestClient(app) as client:
        health = client.get("/healthz")
        unavailable = client.post(
            "/polymarket/funding-operations",
            json=_prepare_request().model_dump(),
            headers={"Authorization": "Bearer prediction-token"},
        )

    assert health.status_code == 200
    assert health.json()["funding_coordinator"] == "assembled"
    assert health.json()["risk_assessment"] == "delegated_to_core"
    assert health.json()["risk_authority"] == "core_policy"
    assert unavailable.status_code == 409
    assert unavailable.json() == {"detail": "venue account is unavailable"}
    assert core.mutation_calls == []


def test_funding_route_scope_errors_are_fixed_and_do_not_echo_path_or_query(
    tmp_path,
) -> None:
    from fastapi.testclient import TestClient

    from services.funding_adapter_service.app import create_app

    coordinator, _repository, _core, _venue = _coordinator_fixture(tmp_path)
    app = create_app(
        config=coordinator.config,
        service=coordinator.funding_adapter,
        coordinator=coordinator,
    )
    marker = "private-key-path-marker"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/polymarket/funding-operations/{marker}",
            params={"user_id": "bad user scope"},
            headers={"Authorization": "Bearer prediction-token"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "funding operation is unavailable"}
    assert marker not in response.text


def test_two_coordinators_have_one_non_idempotent_action_and_settlement_winner(
    tmp_path,
) -> None:
    from services.funding_adapter_service.coordinator import (
        PolymarketFundingCoordinator,
    )
    from services.funding_adapter_service.service import (
        PolymarketFundingAdapterService,
    )

    class BlockingCore(_CoordinatorCoreFake):
        def __init__(self) -> None:
            super().__init__()
            self.action_entered = Event()
            self.allow_action = Event()

        def create_action(self, context):
            self.action_entered.set()
            assert self.allow_action.wait(timeout=5)
            return super().create_action(context)

    config = _coordinator_config(tmp_path)
    core = BlockingCore()
    venue = _VenueAccountFake()
    first, repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue, config=config
    )
    second_repository = funding_repository.SQLiteBridgeRepository(
        config.polymarket_bridge_database_path
    )
    second_bridge = PolymarketFundingAdapterService(
        config,
        bridge_client=_NoNetworkBridgeClient(),
        repository=second_repository,
        clock=lambda: NOW,
    )
    second = PolymarketFundingCoordinator(
        config=config,
        funding_adapter=second_bridge,
        core_gateway=core,
        venue_accounts=venue,
        clock=lambda: NOW,
    )
    operation = first.prepare(_prepare_request())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.confirm, operation.operation_id, _confirm_request()
        )
        assert core.action_entered.wait(timeout=5)
        second_result = pool.submit(
            second.confirm, operation.operation_id, _confirm_request()
        )
        concurrent = second_result.result(timeout=5)
        core.allow_action.set()
        completed = first_result.result(timeout=5)

    assert concurrent.status == "action_creating"
    assert completed.status == "submitted"
    assert core.mutation_calls.count("create_action") == 1
    assert core.mutation_calls.count("evaluate_policy") == 1
    assert core.mutation_calls.count("settle") == 1
    stored = repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=operation.operation_id,
    )
    assert stored == completed
    assert stored.reservation_id == "core_reservation_1"


def test_two_coordinators_have_one_reservation_post_sequence_winner(tmp_path) -> None:
    class BlockingCore(_CoordinatorCoreFake):
        def __init__(self) -> None:
            super().__init__()
            self.update_entered = Event()
            self.allow_first_update = Event()
            self.update_lock = Lock()
            self.update_count = 0

        def update_action_policy_approved(self, context, **kwargs):
            with self.update_lock:
                self.update_count += 1
                is_first = self.update_count == 1
            if is_first:
                self.update_entered.set()
                assert self.allow_first_update.wait(timeout=5)
            return super().update_action_policy_approved(context, **kwargs)

    config = _coordinator_config(tmp_path)
    core = BlockingCore()
    venue = _VenueAccountFake()
    first, repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue, config=config
    )
    second, _second_repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue, config=config
    )
    current = first.prepare(_prepare_request())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
    ):
        current = _advance(repository, current, status)
    core.calls.clear()
    core.mutation_calls.clear()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.advance, user_id=USER_ID, operation_id=current.operation_id
        )
        assert core.update_entered.wait(timeout=5)
        second_result = pool.submit(
            second.advance, user_id=USER_ID, operation_id=current.operation_id
        )
        concurrent = second_result.result(timeout=5)
        core.allow_first_update.set()
        completed = first_result.result(timeout=5)

    assert concurrent.status == "reservation_creating"
    assert completed.status == "submitted"
    assert core.mutation_calls.count("update_action_policy_approved") == 1
    assert core.mutation_calls.count("audit_policy_evaluated") == 1
    assert core.mutation_calls.count("reserve") == 1


def test_two_coordinators_have_one_finalize_post_winner(tmp_path) -> None:
    class BlockingCore(_CoordinatorCoreFake):
        def __init__(self) -> None:
            super().__init__()
            self.finalize_entered = Event()
            self.allow_first_finalize = Event()
            self.finalize_lock = Lock()
            self.finalize_count = 0

        def finalize(self, reservation_id: str, **kwargs):
            with self.finalize_lock:
                self.finalize_count += 1
                is_first = self.finalize_count == 1
            if is_first:
                self.finalize_entered.set()
                assert self.allow_first_finalize.wait(timeout=5)
            return super().finalize(reservation_id, **kwargs)

    config = _coordinator_config(tmp_path)
    core = BlockingCore()
    core.settle_state = "settled"
    core.reservation_state = "settled"
    venue = _VenueAccountFake()
    first, repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue, config=config
    )
    first.funding_adapter.bridge_client.status_payload = _bridge_payload("COMPLETED")
    second, _second_repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue, config=config
    )
    operation = first.prepare(_prepare_request())
    venue.buying_power_atomic = "1000000"
    credited = first.confirm(operation.operation_id, _confirm_request())
    assert credited.status == "venue_credited"
    core.calls.clear()
    core.mutation_calls.clear()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.advance, user_id=USER_ID, operation_id=credited.operation_id
        )
        assert core.finalize_entered.wait(timeout=5)
        second_result = pool.submit(
            second.advance, user_id=USER_ID, operation_id=credited.operation_id
        )
        concurrent = second_result.result(timeout=5)
        core.allow_first_finalize.set()
        completed = first_result.result(timeout=5)

    assert concurrent.status == "finalizing"
    assert completed.status == "finalized"
    assert core.mutation_calls.count("finalize") == 1


def test_prepare_redacts_malformed_external_values_without_exception_chains(
    tmp_path,
) -> None:
    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    marker = "private-key-core-readiness-marker"
    core = _CoordinatorCoreFake()

    def malformed_readiness():
        result = _CoordinatorCoreFake().funding_readiness()
        result["spender_address"] = marker
        return result

    core.funding_readiness = malformed_readiness
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )

    with pytest.raises(FundingCoordinatorError, match="Core funding is not ready") as captured:
        coordinator.prepare(_prepare_request())
    assert marker not in str(captured.value)
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert core.mutation_calls == []


def test_prepare_uses_the_hosted_polygon_executor_without_a_new_product_rail(
    tmp_path,
) -> None:
    core = _CoordinatorCoreFake()

    def hosted_readiness():
        core.calls.append(("funding_readiness", None))
        return {
            "status": "ready",
            "live_funding_enabled": True,
            "native_facilitator_ready": False,
            "hosted_facilitator_enabled": True,
            "hosted_facilitator_ready": True,
            "settlement_rail": "clink_hosted_executor",
            "automatic_payment_rail": "clink_hosted_executor",
            "spender_address": None,
            "spender_addresses": {"eip155:137": SPENDER_ADDRESS},
            "supported_assets": {"eip155:137": SOURCE_TOKEN},
        }

    core.funding_readiness = hosted_readiness
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )

    operation = coordinator.prepare(_prepare_request())

    assert operation.spender_address == SPENDER_ADDRESS
    authorization_call = next(
        payload for name, payload in core.calls if name == "resolve_authorization"
    )
    assert authorization_call["spender_address"] == SPENDER_ADDRESS
    assert "executor_contract" not in authorization_call
    assert "tenant_id" not in authorization_call
    assert "node_id" not in authorization_call


@pytest.mark.parametrize(
    "field,value",
    [
        ("hosted_facilitator_enabled", False),
        ("hosted_facilitator_ready", False),
        ("automatic_payment_rail", "clink_payer_proxy"),
    ],
)
def test_prepare_rejects_inconsistent_hosted_readiness(
    tmp_path,
    field,
    value,
) -> None:
    core = _CoordinatorCoreFake()

    def hosted_readiness():
        result = {
            "status": "ready",
            "live_funding_enabled": True,
            "native_facilitator_ready": False,
            "hosted_facilitator_enabled": True,
            "hosted_facilitator_ready": True,
            "settlement_rail": "clink_hosted_executor",
            "automatic_payment_rail": "clink_hosted_executor",
            "spender_address": None,
            "spender_addresses": {"eip155:137": SPENDER_ADDRESS},
            "supported_assets": {"eip155:137": SOURCE_TOKEN},
        }
        result[field] = value
        return result

    core.funding_readiness = hosted_readiness
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )

    with pytest.raises(
        funding_coordinator.FundingCoordinatorError,
        match="Core funding is not ready",
    ):
        coordinator.prepare(_prepare_request())
    assert core.mutation_calls == []


def test_release_response_loss_recovers_by_reading_before_retry_and_never_resettles(
    tmp_path,
) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "definite_failure"
    core.reservation_state = "definite_failure"
    core.release_error = RuntimeError("secret release response marker")
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())

    unknown = coordinator.confirm(operation.operation_id, _confirm_request())
    core.release_error = None
    released = coordinator.advance(
        user_id=USER_ID, operation_id=operation.operation_id
    )

    assert unknown.status == "settlement_unknown"
    assert released.status == "released"
    assert core.mutation_calls.count("settle") == 1
    assert core.mutation_calls.count("release") == 2
    call_names = [name for name, _value in core.calls]
    first_release = call_names.index("release")
    second_release = call_names.index("release", first_release + 1)
    reservation_indexes = [
        index for index, name in enumerate(call_names) if name == "reservation"
    ]
    assert any(index < first_release for index in reservation_indexes)
    assert any(first_release < index < second_release for index in reservation_indexes)


@pytest.mark.parametrize(
    "inflight_status",
    ("action_creating", "policy_evaluating"),
)
def test_reloaded_inflight_non_idempotent_post_requires_explicit_manual_recovery(
    tmp_path, inflight_status: str
) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)
    current = coordinator.prepare(_prepare_request())
    current = _advance(repository, current, "confirmed")
    current = _advance(repository, current, "action_creating")
    if inflight_status == "policy_evaluating":
        current = _advance(repository, current, "action_created")
        current = _advance(repository, current, "policy_evaluating")
    core.calls.clear()
    core.mutation_calls.clear()
    restarted, _restart_repository, _restart_core, _restart_venue = (
        _coordinator_fixture(
            tmp_path,
            core=core,
            venue=venue,
            config=coordinator.config,
        )
    )

    reloaded = restarted.advance(
        user_id=USER_ID,
        operation_id=current.operation_id,
    )

    assert reloaded == current
    assert restarted.view(reloaded).next_action == "manual_reconcile_inflight"
    assert core.calls == []
    assert core.mutation_calls == []

    recovered = restarted.recover_ambiguous(
        user_id=USER_ID,
        operation_id=current.operation_id,
    )

    assert recovered.status == "manual_review"
    assert restarted.view(recovered).next_action == "manual_review"
    assert restarted.advance(
        user_id=USER_ID,
        operation_id=current.operation_id,
    ) == recovered
    assert core.calls == []
    assert core.mutation_calls == []


@pytest.mark.parametrize(
    "inflight_status",
    ("reservation_creating", "finalizing"),
)
def test_reloaded_reservation_or_finalize_post_requires_explicit_manual_recovery(
    tmp_path, inflight_status: str
) -> None:
    coordinator, repository, core, venue = _coordinator_fixture(tmp_path)
    current = coordinator.prepare(_prepare_request())
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
    ):
        current = _advance(repository, current, status)
    if inflight_status == "reservation_creating":
        current = _advance(repository, current, "reservation_creating")
    else:
        for status in (
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
            "submitted",
            "chain_confirmed",
            "bridge_pending",
        ):
            current = _advance(repository, current, status)
        current = _advance(
            repository,
            current,
            "venue_credited",
            bridge_observation_id="pm_observation_finalize_recovery",
            bridge_status="COMPLETED",
            venue_buying_power_after_atomic="1000000",
        )
        current = _advance(repository, current, "finalizing")
    core.calls.clear()
    core.mutation_calls.clear()
    restarted, _restart_repository, _restart_core, _restart_venue = (
        _coordinator_fixture(
            tmp_path,
            core=core,
            venue=venue,
            config=coordinator.config,
        )
    )

    reloaded = restarted.advance(
        user_id=USER_ID,
        operation_id=current.operation_id,
    )

    assert reloaded == current
    assert restarted.view(reloaded).next_action == "manual_reconcile_inflight"
    assert core.calls == []
    assert core.mutation_calls == []

    reviewed = restarted.recover_ambiguous(
        user_id=USER_ID,
        operation_id=current.operation_id,
    )

    assert reviewed.status == "manual_review"
    assert reviewed.failure_reason_code is None
    assert core.calls == []
    assert core.mutation_calls == []


def test_repository_recovery_lookup_is_exact_and_self_scoped(tmp_path) -> None:
    repository = _seeded_repository(tmp_path / "recovery-lookup.sqlite3")
    operation, _created = repository.create_funding_operation(_operation())
    lookup = getattr(repository, "get_funding_operation_for_recovery", None)

    assert callable(lookup)
    assert lookup(user_id=USER_ID, operation_id=OPERATION_ID) == operation
    assert lookup(user_id="telegram_user_2", operation_id=OPERATION_ID) is None
    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation recovery lookup is invalid",
    ):
        lookup(user_id="bad user", operation_id=OPERATION_ID)


@pytest.mark.parametrize(
    "inflight_status",
    (
        "action_creating",
        "policy_evaluating",
        "reservation_creating",
        "finalizing",
    ),
)
def test_explicit_recovery_uses_only_the_internal_repository_lookup(
    tmp_path, inflight_status: str
) -> None:
    class UnavailableVenue:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def resolve_active_account(self, *, user_id: str):
            self.calls.append(("resolve_active_account", user_id))
            raise RuntimeError("venue must not be consulted for recovery")

        def get_buying_power_atomic(self, **kwargs):
            self.calls.append(("get_buying_power_atomic", kwargs))
            raise RuntimeError("venue must not be consulted for recovery")

    coordinator, repository, core, _venue = _coordinator_fixture(tmp_path)
    current = coordinator.prepare(_prepare_request())
    current = _advance(repository, current, "confirmed")
    current = _advance(repository, current, "action_creating")
    if inflight_status != "action_creating":
        current = _advance(repository, current, "action_created")
        current = _advance(repository, current, "policy_evaluating")
    if inflight_status in {"reservation_creating", "finalizing"}:
        current = _advance(repository, current, "policy_approved")
        current = _advance(repository, current, "reservation_creating")
    if inflight_status == "finalizing":
        for status in (
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
            "submitted",
            "chain_confirmed",
            "bridge_pending",
        ):
            current = _advance(repository, current, status)
        current = _advance(
            repository,
            current,
            "venue_credited",
            bridge_observation_id="pm_observation_repository_recovery",
            bridge_status="COMPLETED",
            venue_buying_power_after_atomic="1000000",
        )
        current = _advance(repository, current, "finalizing")
    trap = UnavailableVenue()
    coordinator.venue_accounts = trap
    risk = coordinator.risk_assessments
    bridge = coordinator.funding_adapter.bridge_client
    core.calls.clear()
    core.mutation_calls.clear()
    risk.calls.clear()
    bridge.calls.clear()

    reviewed = coordinator.recover_ambiguous(
        user_id=USER_ID,
        operation_id=current.operation_id,
    )

    assert reviewed.status == "manual_review"
    assert reviewed.binding_id == current.binding_id
    assert reviewed.bridge_address == current.bridge_address
    assert reviewed.source_token_address == current.source_token_address
    assert trap.calls == []
    assert risk.calls == []
    assert core.calls == []
    assert core.mutation_calls == []
    assert bridge.calls == []


def test_explicit_recovery_rejects_invalid_cross_user_and_non_inflight_without_venue(
    tmp_path,
) -> None:
    class UnavailableVenue:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def resolve_active_account(self, *, user_id: str):
            self.calls.append(user_id)
            raise RuntimeError("venue must not be consulted for recovery")

    coordinator, _repository, _core, _venue = _coordinator_fixture(tmp_path)
    operation = coordinator.prepare(_prepare_request())
    trap = UnavailableVenue()
    coordinator.venue_accounts = trap

    for user_id, error in (
        ("bad user", "funding operation is unavailable"),
        ("telegram_user_2", "funding operation is unavailable"),
        (USER_ID, "funding operation is not an ambiguous external attempt"),
    ):
        with pytest.raises(
            funding_coordinator.FundingCoordinatorError,
            match=error,
        ):
            coordinator.recover_ambiguous(
                user_id=user_id,
                operation_id=operation.operation_id,
            )

    assert trap.calls == []


def test_explicit_recovery_redacts_repository_failures(
    tmp_path, monkeypatch
) -> None:
    marker = "private-recovery-database-marker"
    coordinator, repository, _core, _venue = _coordinator_fixture(tmp_path)
    operation = coordinator.prepare(_prepare_request())

    def fail_lookup(**_kwargs):
        raise funding_repository.BridgeRepositoryError(marker)

    monkeypatch.setattr(
        repository,
        "get_funding_operation_for_recovery",
        fail_lookup,
        raising=False,
    )
    with pytest.raises(
        funding_coordinator.FundingCoordinatorError,
        match="funding operation recovery lookup failed",
    ) as captured:
        coordinator.recover_ambiguous(
            user_id=USER_ID,
            operation_id=operation.operation_id,
        )

    assert marker not in str(captured.value)
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("observed_state", ("payment_submitted", "settled"))
def test_submitted_canonical_transaction_hash_drift_enters_manual_review(
    tmp_path, observed_state: str
) -> None:
    core = _CoordinatorCoreFake()
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core
    )
    operation = coordinator.prepare(_prepare_request())
    submitted = coordinator.confirm(operation.operation_id, _confirm_request())
    assert submitted.status == "submitted"

    drifted_hash = "0x" + "d" * 64

    def drifted_reservation(reservation_id: str):
        result = core._reservation_payload(reservation_id, observed_state)
        result["tx_hash"] = drifted_hash
        core.calls.append(("reservation", reservation_id))
        return result

    core.reservation = drifted_reservation
    core.reconcile = lambda _reservation_id: pytest.fail(
        "canonical hash drift must not reconcile"
    )

    reviewed = coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    )

    assert reviewed.status == "manual_review"
    assert reviewed.core_tx_hash == TX_HASH
    assert reviewed.failure_reason_code == "CORE_TX_HASH_DRIFT"
    assert "finalize" not in core.mutation_calls
    assert "release" not in core.mutation_calls
    mutations_at_review = list(core.mutation_calls)
    assert coordinator.advance(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    ) == reviewed
    assert core.mutation_calls == mutations_at_review
    assert core.mutation_calls.count("settle") == 1


def test_other_small_venue_credit_cannot_finalize_this_operation(tmp_path) -> None:
    core = _CoordinatorCoreFake()
    core.settle_state = "settled"
    core.reservation_state = "settled"
    venue = _VenueAccountFake()
    venue.buying_power_atomic = "1000000"
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, core=core, venue=venue
    )
    coordinator.funding_adapter.bridge_client.status_payload = _bridge_payload(
        "COMPLETED"
    )
    operation = coordinator.prepare(_prepare_request())
    venue.buying_power_atomic = "1500000"

    pending = coordinator.confirm(operation.operation_id, _confirm_request())

    assert pending.status == "bridge_pending"
    assert pending.venue_buying_power_after_atomic == "1500000"
    assert "finalize" not in core.mutation_calls


def test_default_app_health_reports_assembled_funding_and_risk(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from services.funding_adapter_service.app import create_app

    config = _coordinator_config(
        tmp_path,
        account_binding_file=str(tmp_path / "bindings.jsonl"),
        credential_store_file=str(tmp_path / "credentials.jsonl"),
        credential_store_dev_secret="default-health-test-secret",
    )
    coordinator, _repository, _core, _venue = _coordinator_fixture(
        tmp_path, config=config
    )
    app = create_app(
        config=coordinator.config,
        service=coordinator.funding_adapter,
    )

    with TestClient(app) as client:
        health = client.get("/healthz")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["funding_coordinator"] == "assembled"
    assert health.json()["risk_assessment"] == "delegated_to_core"
    assert health.json()["risk_authority"] == "core_policy"


class _RiskAssessmentFake:
    available = True

    def __init__(self, **result_updates: object) -> None:
        self.result_updates = result_updates
        self.calls: list[dict[str, object]] = []

    def assess(self, **kwargs):
        self.calls.append(kwargs)
        values: dict[str, object] = {
            "assessment_id": "risk_assessment_1",
            "subject_id": kwargs["user_id"],
            "bridge_address": kwargs["bridge_address"],
            "amount_atomic": kwargs["amount_atomic"],
            "resource": kwargs["resource"],
            "risk_level": "low",
            "risk_score": 7,
            "risk_action": "approve",
            "assessed_at": NOW,
        }
        values.update(self.result_updates)
        assessment_type = getattr(
            funding_schemas, "PolymarketFundingRiskAssessment"
        )
        return assessment_type.model_validate(values)


def _coordinator_with_risk(base, core, venue, risk, *, clock=lambda: NOW):
    from services.funding_adapter_service.coordinator import (
        PolymarketFundingCoordinator,
    )

    return PolymarketFundingCoordinator(
        config=base.config,
        funding_adapter=base.funding_adapter,
        core_gateway=core,
        venue_accounts=venue,
        risk_assessments=risk,
        clock=clock,
    )


def test_prepare_requires_an_available_server_derived_risk_assessment(tmp_path) -> None:
    from services.funding_adapter_service.coordinator import (
        FundingCoordinatorError,
        PolymarketFundingCoordinator,
    )

    base, repository, core, venue = _coordinator_fixture(tmp_path)
    coordinator = PolymarketFundingCoordinator(
        config=base.config,
        funding_adapter=base.funding_adapter,
        core_gateway=core,
        venue_accounts=venue,
        clock=lambda: NOW,
    )
    core.calls.clear()

    with pytest.raises(
        FundingCoordinatorError, match="funding risk assessment is unavailable"
    ) as captured:
        coordinator.prepare(_prepare_request())

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert core.calls == []
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        idempotency_key="pm_coordinator_idem_1",
    ) is None


@pytest.mark.parametrize(
    "assessment_drift",
    (
        {"subject_id": "telegram_user_2"},
        {"bridge_address": "0x" + "9" * 40},
        {"amount_atomic": "999999"},
        {"resource": "polymarket:funding:other"},
    ),
)
def test_prepare_rejects_unbound_risk_assessment_before_core_or_operation(
    tmp_path, assessment_drift: dict[str, object]
) -> None:
    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    base, repository, core, venue = _coordinator_fixture(tmp_path)
    core.calls.clear()
    risk = _RiskAssessmentFake(**assessment_drift)
    coordinator = _coordinator_with_risk(base, core, venue, risk)

    with pytest.raises(
        FundingCoordinatorError, match="funding risk assessment is unavailable"
    ):
        coordinator.prepare(_prepare_request())

    assert len(risk.calls) == 1
    assert core.calls == []
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        idempotency_key="pm_coordinator_idem_1",
    ) is None


def test_prepare_persists_exact_bound_risk_assessment_result(tmp_path) -> None:
    base, repository, core, venue = _coordinator_fixture(tmp_path)
    core.calls.clear()
    risk = _RiskAssessmentFake()
    coordinator = _coordinator_with_risk(base, core, venue, risk)

    operation = coordinator.prepare(_prepare_request())

    assert risk.calls == [
        {
            "operation_id": operation.operation_id,
            "user_id": USER_ID,
            "bridge_address": BRIDGE_ADDRESS,
            "amount_atomic": "1000000",
            "resource": "polymarket:funding:active",
        }
    ]
    assert operation.risk_assessment_id == "risk_assessment_1"
    assert operation.risk_level == "low"
    assert operation.risk_score == 7
    assert operation.risk_action == "approve"
    assert operation.risk_assessed_at == NOW
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=operation.operation_id,
    ) == operation


def test_core_delegated_risk_id_is_unique_per_operation_and_replay_is_exact(
    tmp_path,
) -> None:
    from services.funding_adapter_service.production_gateways import (
        CoreDelegatedRiskAssessmentGateway,
    )

    base, repository, core, venue = _coordinator_fixture(tmp_path)
    core.calls.clear()
    coordinator = _coordinator_with_risk(
        base,
        core,
        venue,
        CoreDelegatedRiskAssessmentGateway(clock=lambda: NOW),
    )
    first_request = _prepare_request(idempotency_key="pm_same_context_1")
    second_request = _prepare_request(idempotency_key="pm_same_context_2")

    first = coordinator.prepare(first_request)
    first = _terminalize(repository, first, "failed")
    second = coordinator.prepare(second_request)
    replay = coordinator.prepare(first_request)

    assert first.operation_id != second.operation_id
    assert first.risk_assessment_id != second.risk_assessment_id
    assert replay == first
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=first.operation_id,
    ) == first
    assert repository.get_funding_operation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        operation_id=second.operation_id,
    ) == second


def test_prepare_accepts_risk_assessed_during_a_slow_gateway_call(tmp_path) -> None:
    class AdvancingClock:
        def __init__(self) -> None:
            self.current = NOW

        def __call__(self):
            return self.current

    class AdvancingRisk(_RiskAssessmentFake):
        def __init__(self, clock) -> None:
            super().__init__()
            self.clock = clock

        def assess(self, **kwargs):
            self.clock.current = NOW + timedelta(seconds=60)
            self.result_updates["assessed_at"] = NOW + timedelta(seconds=55)
            return super().assess(**kwargs)

    base, _repository, core, venue = _coordinator_fixture(tmp_path)
    core.calls.clear()
    clock = AdvancingClock()
    risk = AdvancingRisk(clock)
    coordinator = _coordinator_with_risk(
        base, core, venue, risk, clock=clock
    )

    operation = coordinator.prepare(_prepare_request())

    assert operation.created_at == NOW + timedelta(seconds=60)
    assert operation.risk_assessed_at == NOW + timedelta(seconds=55)


@pytest.mark.parametrize(
    "assessed_at",
    (
        NOW - timedelta(minutes=5, microseconds=1),
        NOW + timedelta(seconds=30, microseconds=1),
    ),
)
def test_prepare_rejects_stale_or_implausibly_future_risk_before_core_or_operation(
    tmp_path, assessed_at: datetime
) -> None:
    from services.funding_adapter_service.coordinator import FundingCoordinatorError

    base, repository, core, venue = _coordinator_fixture(tmp_path)
    core.calls.clear()
    risk = _RiskAssessmentFake(assessed_at=assessed_at)
    coordinator = _coordinator_with_risk(base, core, venue, risk)

    with pytest.raises(
        FundingCoordinatorError, match="funding risk assessment is unavailable"
    ):
        coordinator.prepare(_prepare_request())

    assert core.calls == []
    assert repository.get_funding_operation_by_idempotency(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        idempotency_key="pm_coordinator_idem_1",
    ) is None


def test_prepare_accepts_risk_within_fixed_clock_skew(tmp_path) -> None:
    base, _repository, core, venue = _coordinator_fixture(tmp_path)
    risk = _RiskAssessmentFake(assessed_at=NOW + timedelta(seconds=30))
    coordinator = _coordinator_with_risk(base, core, venue, risk)

    operation = coordinator.prepare(_prepare_request())

    assert operation.risk_assessed_at == NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    "caller_field",
    ("risk_level", "risk_score", "risk_action", "risk_assessed_at"),
)
def test_prepare_request_rejects_caller_supplied_risk_fields(caller_field: str) -> None:
    with pytest.raises(ValidationError):
        _prepare_request(**{caller_field: "caller-controlled"})


@pytest.mark.parametrize(
    ("buying_power_before", "buying_power_after"),
    (
        ("0", "999999"),
        (str(2**256 - 500_001), UINT256_MAX_ATOMIC),
    ),
)
def test_model_and_repository_require_the_full_operation_credit_delta(
    tmp_path, buying_power_before: str, buying_power_after: str
) -> None:
    repository = _seeded_repository(tmp_path / "credit-delta.sqlite3")
    current, _ = repository.create_funding_operation(
        _operation(venue_buying_power_before_atomic=buying_power_before)
    )
    for status in (
        "confirmed",
        "action_creating",
        "action_created",
        "policy_evaluating",
        "policy_approved",
        "reserved",
        "transaction_prepared",
        "settlement_submitting",
        "submitted",
        "chain_confirmed",
        "bridge_pending",
    ):
        current = _advance(repository, current, status)

    insufficient = _replacement(
        current,
        status="venue_credited",
        bridge_observation_id="pm_observation_insufficient_credit",
        bridge_status="COMPLETED",
        venue_buying_power_after_atomic=buying_power_after,
    )

    with pytest.raises(
        funding_repository.BridgeRepositoryError,
        match="funding operation is invalid",
    ):
        repository.compare_and_set_funding_operation(
            expected_revision=current.revision,
            expected_status=current.status,
            replacement=insufficient,
        )


def test_sqlite_raw_guard_rejects_credit_smaller_than_operation_amount(
    tmp_path,
) -> None:
    repository = _seeded_repository(tmp_path / "credit-raw.sqlite3")
    current = _chain_confirmed_operation(repository)
    current = _advance(repository, current, "bridge_pending")

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                funding_repository.PolymarketFundingOperationRow.__table__.update()
                .where(
                    funding_repository.PolymarketFundingOperationRow.operation_id
                    == current.operation_id
                )
                .values(
                    status="venue_credited",
                    bridge_observation_id="pm_observation_insufficient_raw",
                    bridge_status="COMPLETED",
                    venue_buying_power_after_atomic="999999",
                    revision=current.revision + 1,
                    updated_at=current.updated_at + timedelta(seconds=1),
                )
            )


def test_sqlite_and_postgres_credit_checks_use_the_same_exact_amount_expression() -> None:
    expression = funding_repository._OPERATION_CREDIT_INCREASE_SQL
    normalized_expression = " ".join(expression.lower().split())

    assert "amount_atomic" in normalized_expression
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        ddl = str(
            CreateTable(
                funding_repository.PolymarketFundingOperationRow.__table__
            ).compile(dialect=dialect)
        )
        normalized_ddl = " ".join(ddl.lower().split()).replace("%%", "%")
        assert normalized_expression in normalized_ddl
