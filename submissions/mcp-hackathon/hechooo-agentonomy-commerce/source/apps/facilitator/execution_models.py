"""Immutable Hosted execution values and the durable execution state machine."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


BASE_CHAIN = "eip155:8453"
BASE_CHAIN_ID = 8453
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
POLYGON_CHAIN = "eip155:137"
POLYGON_CHAIN_ID = 137
POLYGON_USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BASE_SEPOLIA_CHAIN = "eip155:84532"
BASE_SEPOLIA_CHAIN_ID = 84532
BASE_SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
POLYGON_AMOY_CHAIN = "eip155:80002"
POLYGON_AMOY_CHAIN_ID = 80002
POLYGON_AMOY_USDC = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"
MAX_UINT256 = 2**256 - 1

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_AMOUNT = re.compile(r"^[1-9][0-9]*$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


class ExecutionState(StrEnum):
    REQUESTED = "requested"
    PREFLIGHT_APPROVED = "preflight_approved"
    SIGNING = "signing"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    SUBMISSION_UNKNOWN = "submission_unknown"
    SUBMISSION_REJECTED = "submission_rejected"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    REVERTED = "reverted"
    EXPIRED = "expired"
    RELEASED = "released"
    REORG_REVIEW = "reorg_review"


_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.REQUESTED: frozenset(
        {ExecutionState.PREFLIGHT_APPROVED, ExecutionState.EXPIRED, ExecutionState.RELEASED}
    ),
    ExecutionState.PREFLIGHT_APPROVED: frozenset(
        {ExecutionState.SIGNING, ExecutionState.EXPIRED, ExecutionState.RELEASED}
    ),
    ExecutionState.SIGNING: frozenset(
        {ExecutionState.SIGNED, ExecutionState.EXPIRED, ExecutionState.RELEASED}
    ),
    ExecutionState.SIGNED: frozenset(
        {
            ExecutionState.SUBMITTED,
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.SUBMISSION_REJECTED,
        }
    ),
    ExecutionState.SUBMISSION_REJECTED: frozenset(
        {
            ExecutionState.SUBMITTED,
            ExecutionState.SUBMISSION_UNKNOWN,
        }
    ),
    ExecutionState.SUBMITTED: frozenset(
        {
            ExecutionState.SUBMISSION_UNKNOWN,
            ExecutionState.CONFIRMED,
            ExecutionState.REVERTED,
        }
    ),
    ExecutionState.SUBMISSION_UNKNOWN: frozenset(
        {ExecutionState.CONFIRMED, ExecutionState.REVERTED}
    ),
    ExecutionState.CONFIRMED: frozenset({ExecutionState.FINALIZED}),
    ExecutionState.FINALIZED: frozenset({ExecutionState.REORG_REVIEW}),
    ExecutionState.REVERTED: frozenset(),
    ExecutionState.EXPIRED: frozenset(),
    ExecutionState.RELEASED: frozenset(),
    ExecutionState.REORG_REVIEW: frozenset(),
}


def allowed_transitions(state: ExecutionState | str) -> frozenset[ExecutionState]:
    try:
        return _TRANSITIONS[ExecutionState(state)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("execution state is invalid") from exc


def _identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _address(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _ADDRESS.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value.lower()


def _hash(value: object, *, field_name: str) -> str:
    if isinstance(value, bytes):
        if len(value) != 32:
            raise ValueError(f"{field_name} is invalid")
        return "0x" + value.hex()
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value.lower()


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} is invalid")
    return value


class ExecutionIntent(BaseModel):
    """Core-bound execution scope supplied before signing or broadcasting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    node_id: str
    wallet_binding_id: str
    capability_id: str
    reservation_id: str
    purchase_id: str
    request_id: str
    request_hash: str
    idempotency_key: str
    chain: str
    owner: str
    payee: str
    token: str
    amount_atomic: str
    executor: str
    signer_epoch: int
    owner_nonce: int
    deadline: int
    capability_hash: str
    reservation_hash: str
    execution_scope_hash: str
    execution_digest: str
    relayer_address: str

    @field_validator(
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "capability_id",
        "reservation_id",
        "purchase_id",
        "request_id",
        "idempotency_key",
    )
    @classmethod
    def validate_identifiers(cls, value: object, info) -> str:
        return _identifier(value, field_name=info.field_name)

    @field_validator("owner", "payee", "token", "executor", "relayer_address")
    @classmethod
    def validate_addresses(cls, value: object, info) -> str:
        return _address(value, field_name=info.field_name)

    @field_validator(
        "capability_hash",
        "reservation_hash",
        "execution_scope_hash",
        "execution_digest",
        "request_hash",
    )
    @classmethod
    def validate_hashes(cls, value: object, info) -> str:
        return _hash(value, field_name=info.field_name)

    @field_validator("amount_atomic", mode="before")
    @classmethod
    def validate_atomic_amount(cls, value: object) -> str:
        if not isinstance(value, str) or _AMOUNT.fullmatch(value) is None:
            raise ValueError("amount_atomic is invalid")
        if int(value) > MAX_UINT256:
            raise ValueError("amount_atomic exceeds uint256")
        return value

    @field_validator("signer_epoch", "deadline")
    @classmethod
    def validate_positive_fields(cls, value: object, info) -> int:
        return _positive_int(value, field_name=info.field_name)

    @field_validator("owner_nonce")
    @classmethod
    def validate_owner_nonce(cls, value: object) -> int:
        if type(value) is not int or value < 0 or value > MAX_UINT256:
            raise ValueError("owner_nonce is invalid")
        return value

    @model_validator(mode="after")
    def validate_fixed_chain_scope(self) -> "ExecutionIntent":
        profile = HOSTED_CHAIN_PROFILES.get(self.chain)
        if profile is None:
            raise ValueError("chain is not an approved Hosted network")
        if self.token != profile.token:
            raise ValueError("token is not canonical USDC for chain")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"signature", "raw_transaction"},
        )

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    @property
    def canonical_hash(self) -> str:
        return "0x" + hashlib.sha256(self.canonical_bytes()).hexdigest()


class HostedExecution(ExecutionIntent):
    """Durable execution projection returned by the repository."""

    signature: bytes | None = Field(default=None, repr=False)
    raw_transaction: bytes | None = Field(default=None, repr=False)
    execution_id: str
    status: ExecutionState = ExecutionState.PREFLIGHT_APPROVED
    relayer_nonce: int
    signing_claim_generation: int = 0
    signing_claim_expires_at: int | None = None
    broadcast_attempts: int = 0
    unsigned_transaction_hash: str | None = None
    raw_transaction_hash: str | None = None
    broadcasted_at: int | None = None
    receipt_status: int | None = None
    receipt_block_number: int | None = None
    receipt_block_hash: str | None = None
    confirmations: int = 0
    safe_block_number: int | None = None
    safe_block_hash: str | None = None
    watcher_version: str | None = None
    finality_boundary: str | None = None
    reorg_state: str = "none"
    reorg_evidence: dict[str, Any] | None = None
    submission_failure_code: str | None = None
    release_evidence: dict[str, Any] | None = None
    confirmed_at: int | None = None
    finalized_at: int | None = None
    reverted_at: int | None = None
    released_at: int | None = None
    expired_at: int | None = None
    reorg_reviewed_at: int | None = None
    created_at: int
    updated_at: int

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: object) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, bytes) or len(value) != 65:
            raise ValueError("signature is invalid")
        return bytes(value)

    @field_validator("raw_transaction")
    @classmethod
    def validate_raw_transaction(cls, value: object) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, bytes) or not value:
            raise ValueError("raw_transaction is invalid")
        return bytes(value)

    @field_validator("execution_id")
    @classmethod
    def validate_execution_id(cls, value: object) -> str:
        return _identifier(value, field_name="execution_id")

    @field_validator("relayer_nonce")
    @classmethod
    def validate_relayer_nonce(cls, value: object) -> int:
        if type(value) is not int or value < 0 or value > MAX_UINT256:
            raise ValueError("relayer_nonce is invalid")
        return value

    @field_validator("signing_claim_generation")
    @classmethod
    def validate_signing_claim_generation(cls, value: object) -> int:
        if type(value) is not int or value < 0:
            raise ValueError("signing_claim_generation is invalid")
        return value

    @field_validator("signing_claim_expires_at")
    @classmethod
    def validate_signing_claim_expiry(cls, value: object) -> int | None:
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("signing_claim_expires_at is invalid")
        return value

    @field_validator("broadcast_attempts", "confirmations")
    @classmethod
    def validate_counters(cls, value: object, info) -> int:
        if type(value) is not int or value < 0:
            raise ValueError(f"{info.field_name} is invalid")
        return value

    @field_validator(
        "unsigned_transaction_hash",
        "raw_transaction_hash",
        "receipt_block_hash",
        "safe_block_hash",
    )
    @classmethod
    def validate_optional_hashes(cls, value: object, info) -> str | None:
        if value is None:
            return None
        return _hash(value, field_name=info.field_name)

    @field_validator("receipt_status")
    @classmethod
    def validate_receipt_status(cls, value: object) -> int | None:
        if value is not None and value not in {0, 1}:
            raise ValueError("receipt_status is invalid")
        return value

    @field_validator("finality_boundary")
    @classmethod
    def validate_finality_boundary(cls, value: object) -> str | None:
        if value is not None and value not in {"safe", "finalized"}:
            raise ValueError("finality_boundary is invalid")
        return value

    @field_validator("submission_failure_code")
    @classmethod
    def validate_submission_failure_code(cls, value: object) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) is None
        ):
            raise ValueError("submission_failure_code is invalid")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamps(cls, value: object, info) -> int:
        return _positive_int(value, field_name=info.field_name)

    @field_validator(
        "confirmed_at",
        "finalized_at",
        "reverted_at",
        "released_at",
        "expired_at",
        "reorg_reviewed_at",
    )
    @classmethod
    def validate_optional_timestamps(cls, value: object, info) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_chain_finality(self) -> "HostedExecution":
        profile = HOSTED_CHAIN_PROFILES.get(self.chain)
        if profile is None:
            raise ValueError("chain is not an approved Hosted network")
        if self.finality_boundary is not None and self.finality_boundary != profile.finality_boundary:
            raise ValueError("finality_boundary does not match chain")
        if self.status in {
            ExecutionState.CONFIRMED,
            ExecutionState.FINALIZED,
            ExecutionState.REVERTED,
            ExecutionState.REORG_REVIEW,
        } and self.finality_boundary != profile.finality_boundary:
            raise ValueError("terminal execution requires the chain finality boundary")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ExecutionState.REVERTED,
            ExecutionState.EXPIRED,
            ExecutionState.RELEASED,
            ExecutionState.REORG_REVIEW,
        }
