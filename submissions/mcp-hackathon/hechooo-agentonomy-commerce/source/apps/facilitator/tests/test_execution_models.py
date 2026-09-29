from __future__ import annotations

import pytest

from execution_models import (
    BASE_CHAIN,
    BASE_USDC,
    ExecutionIntent,
    ExecutionState,
    HostedExecution,
    MAX_UINT256,
    allowed_transitions,
)


NOW = 2_000_000_000
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
RELAYER = "0x" + "44" * 20


def intent(**updates: object) -> ExecutionIntent:
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "binding_1",
        "capability_id": "capability_1",
        "reservation_id": "reservation_1",
        "purchase_id": "purchase_1",
        "request_id": "request_1",
        "request_hash": "0x" + "99" * 32,
        "idempotency_key": "idempotency_1",
        "chain": BASE_CHAIN,
        "owner": OWNER,
        "payee": PAYEE,
        "token": BASE_USDC,
        "amount_atomic": "1000000",
        "executor": EXECUTOR,
        "signer_epoch": 1,
        "owner_nonce": 7,
        "deadline": NOW + 60,
        "capability_hash": "0x" + "55" * 32,
        "reservation_hash": "0x" + "66" * 32,
        "execution_scope_hash": "0x" + "77" * 32,
        "execution_digest": "0x" + "88" * 32,
        "relayer_address": RELAYER,
    }
    values.update(updates)
    return ExecutionIntent(**values)


def test_execution_intent_canonicalizes_addresses_and_hashes() -> None:
    value = intent(
        owner=OWNER.upper().replace("X", "x"),
        token=BASE_USDC.upper().replace("X", "x"),
        capability_hash="0x" + "AA" * 32,
    )

    assert value.owner == OWNER
    assert value.token == BASE_USDC
    assert value.capability_hash == "0x" + "aa" * 32
    assert value.amount_atomic == "1000000"


@pytest.mark.parametrize("amount", ["0", "01", "1.0", "-1", 1.0])
def test_execution_intent_rejects_noncanonical_atomic_amount(amount: object) -> None:
    with pytest.raises(ValueError, match="amount_atomic"):
        intent(amount_atomic=amount)


def test_execution_intent_rejects_non_base_scope_and_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="chain"):
        intent(chain="eip155:1")
    with pytest.raises(ValueError, match="token"):
        intent(token="0x" + "99" * 20)
    with pytest.raises(ValueError, match="deadline"):
        intent(deadline=0)
    with pytest.raises(ValueError, match="signer_epoch"):
        intent(signer_epoch=0)


def test_execution_intent_rejects_sensitive_material_fields() -> None:
    with pytest.raises(ValueError, match="signature|extra"):
        intent(signature=b"x" * 65)
    with pytest.raises(ValueError, match="raw_transaction|extra"):
        intent(raw_transaction=b"x")


def test_execution_sensitive_material_is_not_in_repr() -> None:
    value = HostedExecution(
        **intent().model_dump(),
        signature=bytes.fromhex("aa" * 65),
        raw_transaction=bytes.fromhex("bb" * 80),
        execution_id="execution_1",
        status=ExecutionState.SIGNED,
        relayer_nonce=0,
        created_at=NOW,
        updated_at=NOW,
    )

    representation = repr(value)
    assert "aa" * 10 not in representation
    assert "bb" * 10 not in representation
    assert value.status is ExecutionState.SIGNED
    assert "signature" not in value.canonical_payload()
    assert "raw_transaction" not in value.canonical_payload()


def test_owner_nonce_accepts_full_uint256_as_external_integer() -> None:
    value = intent(owner_nonce=MAX_UINT256)
    assert value.owner_nonce == MAX_UINT256


def test_execution_state_machine_is_explicit_and_terminal() -> None:
    assert ExecutionState.SIGNING in allowed_transitions(
        ExecutionState.PREFLIGHT_APPROVED
    )
    assert ExecutionState.SIGNED in allowed_transitions(ExecutionState.SIGNING)
    assert ExecutionState.SIGNED not in allowed_transitions(
        ExecutionState.SUBMISSION_UNKNOWN
    )
    assert ExecutionState.SUBMISSION_REJECTED in allowed_transitions(
        ExecutionState.SIGNED
    )
    assert ExecutionState.SUBMISSION_UNKNOWN in allowed_transitions(
        ExecutionState.SUBMISSION_REJECTED
    )
    assert ExecutionState.RELEASED not in allowed_transitions(
        ExecutionState.SUBMISSION_REJECTED
    )
    assert allowed_transitions(ExecutionState.REORG_REVIEW) == frozenset()
