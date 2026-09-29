from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$")
_OPC_INSTALLATION_PATTERN = re.compile(r"^opc_[0-9a-f]{40}$")
_EVM_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-f]{40}$")
_TX_HASH_PATTERN = re.compile(r"^0x[0-9a-f]{64}$")
_ATOMIC_AMOUNT_PATTERN = re.compile(r"^[1-9][0-9]{0,77}$")
_UINT256_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,77})$")
_USDC_AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{6}$")
_RESOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
UINT256_MAX_ATOMIC = str(2**256 - 1)
POLYMARKET_BRIDGE_FAILURE_REASON = "POLYMARKET_BRIDGE_FAILED"
RISK_ASSESSMENT_MAX_AGE = timedelta(minutes=5)
RISK_ASSESSMENT_CLOCK_SKEW = timedelta(seconds=30)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )


class _StrictHttpModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _canonical_id(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _canonical_opc_installation_id(value: str) -> str:
    normalized = str(value).strip()
    if not _OPC_INSTALLATION_PATTERN.fullmatch(normalized):
        raise ValueError("opc_installation_id is invalid")
    return normalized


def _canonical_address(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if not _EVM_ADDRESS_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a canonical EVM address")
    if normalized == "0x" + "0" * 40:
        raise ValueError(f"{field_name} must not be the zero address")
    return normalized


def _canonical_transaction_hash(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if not _TX_HASH_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a canonical transaction hash")
    return normalized


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _strict_canonical_address(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _EVM_ADDRESS_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase canonical EVM address")
    if normalized == "0x" + "0" * 40:
        raise ValueError(f"{field_name} must not be the zero address")
    return normalized


def _strict_canonical_hash(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _TX_HASH_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase canonical hash")
    return normalized


def _covers_full_operation_credit(
    *, before_atomic: str, amount_atomic: str, after_atomic: str
) -> bool:
    required = int(before_atomic) + int(amount_atomic)
    return required <= int(UINT256_MAX_ATOMIC) and int(after_atomic) >= required


FundingOperationStatus = Literal[
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
]

FUNDING_OPERATION_STATUSES = frozenset(get_args(FundingOperationStatus))
_FUNDING_OPERATION_NEXT_ACTIONS = {
    "created": "confirm",
    "confirmed": "processing",
    "action_creating": "manual_reconcile_inflight",
    "action_unknown": "manual_review",
    "action_created": "processing",
    "policy_evaluating": "manual_reconcile_inflight",
    "policy_unknown": "manual_review",
    "policy_approved": "processing",
    "reservation_creating": "manual_reconcile_inflight",
    "reserved": "processing",
    "transaction_prepared": "processing",
    "settlement_submitting": "check_core_status",
    "settlement_unknown": "check_core_status",
    "submitted": "check_core_status",
    "chain_confirmed": "check_bridge_status",
    "bridge_pending": "check_bridge_status",
    "venue_credited": "finalize",
    "finalizing": "manual_reconcile_inflight",
    "finalized": "complete",
    "failed": "terminal",
    "released": "terminal",
    "manual_review": "manual_review",
}
FUNDING_OPERATION_PENDING_STATUSES = frozenset(
    FUNDING_OPERATION_STATUSES - {"created", "finalized", "failed", "released"}
)

if set(_FUNDING_OPERATION_NEXT_ACTIONS) != FUNDING_OPERATION_STATUSES:
    raise RuntimeError("funding operation status/action contract is incomplete")


def funding_operation_next_action(status: str) -> str:
    """Return the single user-facing next action for a runtime status."""
    try:
        return _FUNDING_OPERATION_NEXT_ACTIONS[status]
    except KeyError:
        raise ValueError(f"unknown funding operation status: {status}") from None


CoreFundingState = Literal[
    "spending_reserved",
    "payment_submitted",
    "settled",
    "finalized",
    "released",
]
BridgeFundingStatus = Literal[
    "DEPOSIT_DETECTED",
    "PROCESSING",
    "ORIGIN_TX_CONFIRMED",
    "SUBMITTED",
    "COMPLETED",
    "FAILED",
]


class PolymarketFundingRiskAssessment(_StrictFrozenModel):
    """Trusted server-side risk result bound to one exact funding context."""

    assessment_id: str
    subject_id: str
    bridge_address: str
    amount_atomic: str
    resource: str
    risk_level: Literal["low", "medium", "high", "critical"]
    risk_score: int = Field(ge=0, le=100)
    risk_action: Literal[
        "approve",
        "hold",
        "block",
        "blocked",
        "reject",
        "deny",
        "manual_review",
        "review",
    ]
    assessed_at: datetime

    @field_validator("assessment_id", "subject_id")
    @classmethod
    def validate_assessment_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("bridge_address")
    @classmethod
    def validate_assessment_bridge_address(cls, value: str) -> str:
        return _strict_canonical_address(value, field_name="bridge_address")

    @field_validator("amount_atomic")
    @classmethod
    def validate_assessment_amount_atomic(cls, value: str) -> str:
        if (
            not _ATOMIC_AMOUNT_PATTERN.fullmatch(value)
            or len(value) == len(UINT256_MAX_ATOMIC)
            and value > UINT256_MAX_ATOMIC
        ):
            raise ValueError("amount_atomic must be a positive uint256 integer string")
        return value

    @field_validator("resource")
    @classmethod
    def validate_assessment_resource(cls, value: str) -> str:
        if not _RESOURCE_PATTERN.fullmatch(value):
            raise ValueError("resource is invalid")
        return value

    @field_validator("assessed_at")
    @classmethod
    def validate_assessed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="assessed_at")


class PolymarketFundingOperation(_StrictFrozenModel):
    """Durable repository state; not an HTTP request DTO."""

    operation_id: str
    user_id: str
    agent_id: str
    idempotency_key: str
    opc_installation_id: str | None = None
    binding_id: str
    venue_wallet_address: str
    bridge_address: str
    source_network: Literal["eip155:137"]
    source_token_address: str
    destination_network: Literal["eip155:137"]
    destination_token_address: str
    amount_usdc: str
    amount_atomic: str
    resource: str
    request_hash: str
    quote_hash: str
    wallet_identity_id: str
    spending_grant_id: str
    asset_allowance_id: str
    spender_address: str
    venue_buying_power_before_atomic: str
    risk_assessment_id: str
    risk_level: Literal["low", "medium", "high", "critical"]
    risk_score: int = Field(ge=0, le=100)
    risk_action: Literal[
        "approve",
        "hold",
        "block",
        "blocked",
        "reject",
        "deny",
        "manual_review",
        "review",
    ]
    risk_assessed_at: datetime
    status: FundingOperationStatus
    action_id: str | None = None
    policy_decision_id: str | None = None
    audit_event_id: str | None = None
    reservation_id: str | None = None
    core_tx_hash: str | None = None
    core_state: CoreFundingState | None = None
    core_replacement_forbidden: bool = False
    core_failure_evidence_kind: Literal[
        "definite_rpc_rejection", "failed_receipt"
    ] | None = None
    bridge_observation_id: str | None = None
    bridge_status: BridgeFundingStatus | None = None
    venue_buying_power_after_atomic: str | None = None
    failure_reason_code: str | None = None
    confirmed_at: datetime | None = None
    finalized_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=0)

    @field_validator(
        "operation_id",
        "user_id",
        "agent_id",
        "idempotency_key",
        "binding_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "risk_assessment_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator(
        "action_id",
        "policy_decision_id",
        "audit_event_id",
        "reservation_id",
        "core_state",
        "bridge_observation_id",
    )
    @classmethod
    def validate_optional_ids(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("opc_installation_id")
    @classmethod
    def validate_opc_installation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_opc_installation_id(value)

    @field_validator(
        "venue_wallet_address",
        "bridge_address",
        "source_token_address",
        "destination_token_address",
        "spender_address",
    )
    @classmethod
    def validate_operation_addresses(cls, value: str, info) -> str:
        return _strict_canonical_address(value, field_name=info.field_name)

    @field_validator("request_hash", "quote_hash")
    @classmethod
    def validate_operation_hashes(cls, value: str, info) -> str:
        return _strict_canonical_hash(value, field_name=info.field_name)

    @field_validator("core_tx_hash")
    @classmethod
    def validate_optional_transaction_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strict_canonical_hash(value, field_name="core_tx_hash")

    @field_validator("amount_usdc")
    @classmethod
    def validate_amount_usdc(cls, value: str) -> str:
        if not _USDC_AMOUNT_PATTERN.fullmatch(value):
            raise ValueError("amount_usdc must be a canonical six-decimal USDC string")
        return value

    @field_validator("amount_atomic")
    @classmethod
    def validate_operation_amount_atomic(cls, value: str) -> str:
        if (
            not _ATOMIC_AMOUNT_PATTERN.fullmatch(value)
            or len(value) == len(UINT256_MAX_ATOMIC)
            and value > UINT256_MAX_ATOMIC
        ):
            raise ValueError("amount_atomic must be a positive uint256 integer string")
        return value

    @field_validator(
        "venue_buying_power_before_atomic",
        "venue_buying_power_after_atomic",
    )
    @classmethod
    def validate_buying_power_atomic(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        if (
            not _UINT256_PATTERN.fullmatch(value)
            or len(value) == len(UINT256_MAX_ATOMIC)
            and value > UINT256_MAX_ATOMIC
        ):
            raise ValueError(f"{info.field_name} must be a uint256 integer string")
        return value

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        if not _RESOURCE_PATTERN.fullmatch(value):
            raise ValueError("resource is invalid")
        return value

    @field_validator("failure_reason_code")
    @classmethod
    def validate_failure_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _REASON_PATTERN.fullmatch(value):
            raise ValueError("failure_reason_code is invalid")
        return value

    @field_validator(
        "confirmed_at",
        "finalized_at",
        "risk_assessed_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def validate_operation_timestamps(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_exact_amount_and_time_order(self) -> PolymarketFundingOperation:
        whole, fraction = self.amount_usdc.split(".", 1)
        if str(int(whole) * 1_000_000 + int(fraction)) != self.amount_atomic:
            raise ValueError("amount_usdc and amount_atomic must identify the same value")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if not (
            self.created_at - RISK_ASSESSMENT_MAX_AGE
            <= self.risk_assessed_at
            <= self.created_at + RISK_ASSESSMENT_CLOCK_SKEW
        ):
            raise ValueError("risk_assessed_at is outside the trusted freshness window")
        for field_name in ("confirmed_at", "finalized_at"):
            timestamp = getattr(self, field_name)
            if timestamp is not None and timestamp < self.created_at:
                raise ValueError(f"{field_name} must not precede created_at")
        if (
            self.confirmed_at is not None
            and self.finalized_at is not None
            and self.finalized_at < self.confirmed_at
        ):
            raise ValueError("finalized_at must not precede confirmed_at")

        allowed_core_states = {
            "spending_reserved",
            "payment_submitted",
            "settled",
            "finalized",
            "released",
        }
        if self.core_state is not None and self.core_state not in allowed_core_states:
            raise ValueError("core_state is invalid")
        if self.core_replacement_forbidden != (
            self.core_failure_evidence_kind is not None
        ):
            raise ValueError("Core failure proof is incomplete")
        if self.core_replacement_forbidden and (
            self.core_tx_hash is None
            or self.failure_reason_code is None
            or self.core_state not in {"spending_reserved", "released"}
        ):
            raise ValueError("Core failure proof is incomplete")
        if self.failure_reason_code is not None and self.status not in {
            "failed",
            "released",
            "manual_review",
        }:
            raise ValueError("failure_reason_code is invalid for status")
        if self.finalized_at is not None and self.status != "finalized":
            raise ValueError("finalized_at is invalid for status")

        bridge_values = (
            self.bridge_observation_id,
            self.bridge_status,
            self.venue_buying_power_after_atomic,
        )
        if any(value is not None for value in bridge_values):
            if self.status not in {
                "bridge_pending",
                "venue_credited",
                "finalizing",
                "finalized",
                "failed",
                "manual_review",
            }:
                raise ValueError("Bridge proof is invalid for status")
            if (self.bridge_observation_id is None) != (self.bridge_status is None):
                raise ValueError("Bridge observation proof is incomplete")

        def require(*field_names: str) -> None:
            if any(getattr(self, field_name) is None for field_name in field_names):
                raise ValueError(f"{self.status} funding proof is incomplete")

        if self.status == "created":
            created_checkpoints = (
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
                "core_tx_hash",
                "core_state",
                "bridge_observation_id",
                "bridge_status",
                "venue_buying_power_after_atomic",
                "failure_reason_code",
                "confirmed_at",
                "finalized_at",
            )
            if self.core_replacement_forbidden or any(
                getattr(self, field_name) is not None
                for field_name in created_checkpoints
            ):
                raise ValueError("created funding operation has checkpoints")
        elif self.status in {"confirmed", "action_creating", "action_unknown"}:
            require("confirmed_at")
            if self.action_id is not None:
                raise ValueError("action checkpoint is invalid for status")
        elif self.status in {
            "action_created",
            "policy_evaluating",
            "policy_unknown",
        }:
            require("confirmed_at", "action_id")
            if self.policy_decision_id is not None:
                raise ValueError("policy checkpoint is invalid for status")
        elif self.status in {"policy_approved", "reservation_creating"}:
            require("confirmed_at", "action_id", "policy_decision_id")
            if self.reservation_id is not None:
                raise ValueError("reservation checkpoint is invalid for status")
        elif self.status in {
            "reserved",
            "transaction_prepared",
            "settlement_submitting",
        }:
            require(
                "confirmed_at",
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
            )
            if self.core_state != "spending_reserved" or self.core_tx_hash is not None:
                raise ValueError(f"{self.status} Core proof is invalid")
        elif self.status == "settlement_unknown":
            require(
                "confirmed_at",
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
            )
            if (
                self.core_state not in {None, "spending_reserved", "payment_submitted"}
                or self.core_state in {None, "spending_reserved"}
                and self.core_tx_hash is not None
                or self.core_state == "payment_submitted"
                and self.core_tx_hash is None
            ):
                raise ValueError("settlement_unknown Core proof is invalid")
        elif self.status == "submitted":
            require(
                "confirmed_at",
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
                "core_tx_hash",
            )
            if self.core_state != "payment_submitted":
                raise ValueError("submitted Core proof is invalid")
        elif self.status in {"chain_confirmed", "bridge_pending"}:
            require(
                "confirmed_at",
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
                "core_tx_hash",
            )
            if self.core_state != "settled":
                raise ValueError(f"{self.status} Core proof is invalid")
        elif self.status in {"venue_credited", "finalizing", "finalized"}:
            require(
                "confirmed_at",
                "action_id",
                "policy_decision_id",
                "audit_event_id",
                "reservation_id",
                "core_tx_hash",
                "bridge_observation_id",
                "bridge_status",
                "venue_buying_power_after_atomic",
            )
            expected_core_state = (
                "finalized" if self.status == "finalized" else "settled"
            )
            if self.core_state != expected_core_state:
                raise ValueError(f"{self.status} Core proof is invalid")
            if self.bridge_status != "COMPLETED" or not _covers_full_operation_credit(
                before_atomic=self.venue_buying_power_before_atomic,
                amount_atomic=self.amount_atomic,
                after_atomic=self.venue_buying_power_after_atomic,
            ):
                raise ValueError(f"{self.status} venue credit proof is invalid")
            if self.status == "finalized":
                require("finalized_at")
        elif self.status in {"failed", "released"}:
            require("failure_reason_code")
            venue_side_failure = (
                self.status == "failed" and self.bridge_status == "FAILED"
            )
            if venue_side_failure:
                if (
                    self.failure_reason_code != POLYMARKET_BRIDGE_FAILURE_REASON
                    or self.core_tx_hash is None
                    or self.core_state != "settled"
                    or self.core_replacement_forbidden
                    or self.core_failure_evidence_kind is not None
                    or self.bridge_observation_id is None
                    or self.venue_buying_power_after_atomic is not None
                    or self.finalized_at is not None
                ):
                    raise ValueError("venue-side failure proof is incomplete")
            elif self.core_tx_hash is None:
                if self.core_replacement_forbidden:
                    raise ValueError("pre-broadcast failure proof is invalid")
            elif not self.core_replacement_forbidden:
                raise ValueError("post-broadcast failure proof is incomplete")
            if self.status == "released" and self.reservation_id is not None:
                if self.core_state != "released":
                    raise ValueError("released Core proof is invalid")
        return self


class CreatePolymarketFundingOperationRequest(_StrictHttpModel):
    """Subject-only internal request; ownership is derived server-side."""

    user_id: str
    amount_usdc: str
    idempotency_key: str
    resource: str
    opc_installation_id: str | None = None

    @field_validator("user_id", "idempotency_key")
    @classmethod
    def validate_request_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("amount_usdc")
    @classmethod
    def validate_request_amount(cls, value: str) -> str:
        if (
            not _USDC_AMOUNT_PATTERN.fullmatch(value)
            or value == "0.000000"
        ):
            raise ValueError(
                "amount_usdc must be a positive canonical six-decimal USDC string"
            )
        whole, fraction = value.split(".", 1)
        atomic = str(int(whole) * 1_000_000 + int(fraction))
        if (
            len(atomic) > len(UINT256_MAX_ATOMIC)
            or len(atomic) == len(UINT256_MAX_ATOMIC)
            and atomic > UINT256_MAX_ATOMIC
        ):
            raise ValueError("amount_usdc exceeds uint256")
        return value

    @field_validator("resource")
    @classmethod
    def validate_request_resource(cls, value: str) -> str:
        if not _RESOURCE_PATTERN.fullmatch(value):
            raise ValueError("resource is invalid")
        return value

    @field_validator("opc_installation_id")
    @classmethod
    def validate_request_opc_installation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_opc_installation_id(value)


class ConfirmPolymarketFundingOperationRequest(_StrictHttpModel):
    user_id: str
    confirmed: Literal[True]
    opc_installation_id: str | None = None

    @field_validator("user_id")
    @classmethod
    def validate_confirmation_user_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="user_id")

    @field_validator("opc_installation_id")
    @classmethod
    def validate_confirmation_opc_installation_id(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        return _canonical_opc_installation_id(value)


class AdvancePolymarketFundingOperationRequest(_StrictHttpModel):
    user_id: str
    opc_installation_id: str | None = None

    @field_validator("user_id")
    @classmethod
    def validate_advance_user_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="user_id")

    @field_validator("opc_installation_id")
    @classmethod
    def validate_advance_opc_installation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_opc_installation_id(value)


class PolymarketFundingOperationView(_StrictFrozenModel):
    operation_id: str
    user_id: str
    opc_installation_id: str | None = None
    binding_id: str
    venue_wallet_address: str
    bridge_address: str
    status: FundingOperationStatus
    amount_usdc: str
    resource: str
    action_id: str | None = None
    policy_decision_id: str | None = None
    audit_event_id: str | None = None
    reservation_id: str | None = None
    core_tx_hash: str | None = None
    core_state: CoreFundingState | None = None
    bridge_status: BridgeFundingStatus | None = None
    venue_buying_power_before_atomic: str
    venue_buying_power_after_atomic: str | None = None
    failure_reason_code: str | None = None
    confirmed_at: datetime | None = None
    finalized_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=0)
    next_action: str

    @field_validator(
        "operation_id",
        "user_id",
        "binding_id",
        "action_id",
        "policy_decision_id",
        "audit_event_id",
        "reservation_id",
        "core_state",
    )
    @classmethod
    def validate_view_ids(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("opc_installation_id")
    @classmethod
    def validate_view_opc_installation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_opc_installation_id(value)

    @field_validator("venue_wallet_address", "bridge_address")
    @classmethod
    def validate_view_addresses(cls, value: str, info) -> str:
        return _strict_canonical_address(value, field_name=info.field_name)

    @field_validator(
        "venue_buying_power_before_atomic",
        "venue_buying_power_after_atomic",
    )
    @classmethod
    def validate_view_buying_power(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        if (
            not _UINT256_PATTERN.fullmatch(value)
            or len(value) == len(UINT256_MAX_ATOMIC)
            and value > UINT256_MAX_ATOMIC
        ):
            raise ValueError(f"{info.field_name} must be a uint256 integer string")
        return value

    @field_validator("amount_usdc")
    @classmethod
    def validate_view_amount(cls, value: str) -> str:
        if not _USDC_AMOUNT_PATTERN.fullmatch(value) or value == "0.000000":
            raise ValueError("amount_usdc is invalid")
        return value

    @field_validator("resource")
    @classmethod
    def validate_view_resource(cls, value: str) -> str:
        if not _RESOURCE_PATTERN.fullmatch(value):
            raise ValueError("resource is invalid")
        return value

    @field_validator("core_tx_hash")
    @classmethod
    def validate_view_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strict_canonical_hash(value, field_name="core_tx_hash")

    @field_validator("failure_reason_code")
    @classmethod
    def validate_view_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _REASON_PATTERN.fullmatch(value):
            raise ValueError("failure_reason_code is invalid")
        return value

    @field_validator("confirmed_at", "finalized_at", "created_at", "updated_at")
    @classmethod
    def validate_view_time(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, field_name=info.field_name)

    @field_validator("next_action")
    @classmethod
    def validate_next_action(cls, value: str) -> str:
        return _canonical_id(value, field_name="next_action")


class CreatePolymarketBridgeDepositRequest(_StrictModel):
    user_id: str
    binding_id: str
    venue_wallet_address: str

    @field_validator("user_id", "binding_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("venue_wallet_address")
    @classmethod
    def validate_venue_wallet(cls, value: str) -> str:
        return _canonical_address(value, field_name="venue_wallet_address")


class PolymarketBridgeDeposit(_StrictModel):
    deposit_id: str
    user_id: str
    binding_id: str
    venue_wallet_address: str
    bridge_address: str
    source_network: Literal["eip155:137"]
    source_token_address: str
    destination_network: Literal["eip155:137"]
    destination_token_address: str
    status: Literal["ready"]
    created_at: datetime

    @field_validator("deposit_id", "user_id", "binding_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator(
        "venue_wallet_address",
        "bridge_address",
        "source_token_address",
        "destination_token_address",
    )
    @classmethod
    def validate_addresses(cls, value: str, info) -> str:
        return _canonical_address(value, field_name=info.field_name)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="created_at")


class PolymarketBridgeStatus(_StrictModel):
    observation_id: str
    user_id: str
    binding_id: str
    venue_wallet_address: str
    bridge_address: str
    source_network: Literal["eip155:137"]
    source_token_address: str
    destination_network: Literal["eip155:137"]
    destination_token_address: str
    status: Literal[
        "DEPOSIT_DETECTED",
        "PROCESSING",
        "ORIGIN_TX_CONFIRMED",
        "SUBMITTED",
        "COMPLETED",
        "FAILED",
    ]
    tx_hash: str | None = None
    amount_atomic: str
    checked_at: datetime
    bridge_created_time_ms: int | None = Field(default=None, ge=0)

    @field_validator("observation_id", "user_id", "binding_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator(
        "venue_wallet_address",
        "bridge_address",
        "source_token_address",
        "destination_token_address",
    )
    @classmethod
    def validate_addresses(cls, value: str, info) -> str:
        return _canonical_address(value, field_name=info.field_name)

    @field_validator("tx_hash")
    @classmethod
    def validate_tx_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_transaction_hash(value, field_name="tx_hash")

    @field_validator("amount_atomic")
    @classmethod
    def validate_amount_atomic(cls, value: str) -> str:
        normalized = str(value).strip()
        if (
            not _ATOMIC_AMOUNT_PATTERN.fullmatch(normalized)
            or len(normalized) == len(UINT256_MAX_ATOMIC)
            and normalized > UINT256_MAX_ATOMIC
        ):
            raise ValueError("amount_atomic must be a uint256 base-unit integer")
        return normalized

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="checked_at")

    @property
    def amount_usdc(self) -> str:
        padded = self.amount_atomic.zfill(7)
        whole, fraction = padded[:-6], padded[-6:].rstrip("0")
        return whole if not fraction else f"{whole}.{fraction}"


# These read-only legacy types remain importable until Task 4 removes the old MCP
# surface. The V2 funding adapter does not call or expose a Bridge quote route.
class CreatePolymarketBridgeQuoteRequest(_StrictModel):
    user_id: str
    from_amount_usdc: str
    recipient_address: str | None = None


class PolymarketBridgeQuote(_StrictModel):
    quote_id: str
    user_id: str
    from_amount_usdc: str
    from_amount_atomic: str
    recipient_address: str | None = None
    bridge_quote_id: str | None = None
    expected_pusd_amount_usdc: str | None = None
    status: str
    reason: str | None = None
    next_action: str
    created_at: str
