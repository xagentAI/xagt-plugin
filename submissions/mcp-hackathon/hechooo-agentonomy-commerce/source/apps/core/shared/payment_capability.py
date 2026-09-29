from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from services.account_service.schemas import SpendingGrant, canonicalize_evm_address
from services.policy_service.schemas import PolicyDecision
from shared.hosted_facilitator_protocol import canonical_json_bytes, sha256_identifier


PAYMENT_CAPABILITY_VERSION = "clink-payment-capability-v1"
MAX_PAYMENT_CAPABILITY_LIFETIME_SECONDS = 60
VERIFICATION_ONLY_RISK_ABSENCE_MARKER = (
    "clink-risk-evidence-absent:verification-only:live-funding-disabled:v1"
)

_CANONICAL_ATOMIC_AMOUNT = re.compile(r"^[1-9][0-9]*$")
_LOWERCASE_BYTES32 = re.compile(r"^0x[0-9a-f]{64}$")
_MAX_IDENTIFIER_LENGTH = 256
_USDC_DECIMAL_PLACES = 6


def _validate_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{field_name} must be a non-empty bounded string")
    if any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _validate_bytes32(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _LOWERCASE_BYTES32.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 0x plus 64 lower-case hex characters")
    return value


def _canonical_atomic_amount(value: object) -> str:
    if not isinstance(value, str) or _CANONICAL_ATOMIC_AMOUNT.fullmatch(value) is None:
        raise ValueError("amount_atomic must be a positive canonical atomic integer string")
    return value


def _canonical_hash(value: object) -> str:
    return sha256_identifier(canonical_json_bytes(value))


def _canonical_usdc_amount(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("USDC grant amount must be a positive finite Decimal")
    whole, separator, fractional = format(value, "f").partition(".")
    if len(fractional) > _USDC_DECIMAL_PLACES:
        if any(digit != "0" for digit in fractional[_USDC_DECIMAL_PLACES:]):
            raise ValueError("USDC grant amount exceeds six decimal places")
        fractional = fractional[:_USDC_DECIMAL_PLACES]
    return f"{whole}.{fractional.ljust(_USDC_DECIMAL_PLACES, '0')}"


class PaymentCapabilityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_version: Literal["clink-payment-capability-v1"] = (
        PAYMENT_CAPABILITY_VERSION
    )
    capability_id: str
    user_id: str
    agent_id: str
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    wallet_identity_id: str
    wallet_address: str
    spending_grant_id: str
    spending_grant_hash: str
    asset_allowance_id: str
    action_id: str
    policy_decision_id: str
    policy_snapshot_hash: str
    risk_evidence_hash: str
    reservation_id: str
    reservation_hash: str
    purchase_id: str
    merchant_id: str
    product: str
    venue: str
    quote_hash: str
    payment_challenge_hash: str
    network: Literal["eip155:137", "eip155:8453", "eip155:80002"]
    asset_contract: str
    amount_atomic: str
    pay_to: str
    executor_contract: str
    execution_scope_hash: str
    confirmation_mode: Literal["policy_approved", "user_approved"]
    revocation_id: str
    issued_at: int
    expires_at: int

    _canonical_addresses = field_validator(
        "wallet_address", "asset_contract", "pay_to", "executor_contract"
    )(canonicalize_evm_address)

    @field_validator(
        "capability_id",
        "user_id",
        "agent_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "action_id",
        "policy_decision_id",
        "reservation_id",
        "purchase_id",
        "merchant_id",
        "product",
        "venue",
        mode="before",
    )
    @classmethod
    def valid_identifier(cls, value: object, info) -> str:
        return _validate_identifier(value, field_name=info.field_name)

    @field_validator(
        "spending_grant_hash",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "reservation_hash",
        "quote_hash",
        "payment_challenge_hash",
        "execution_scope_hash",
        "revocation_id",
        mode="before",
    )
    @classmethod
    def valid_hash(cls, value: object, info) -> str:
        return _validate_bytes32(value, field_name=info.field_name)

    _valid_amount = field_validator("amount_atomic", mode="before")(
        _canonical_atomic_amount
    )

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def strict_timestamp(cls, value: object, info) -> int:
        if type(value) is not int:
            raise ValueError(f"{info.field_name} must be an integer timestamp")
        return value

    @model_validator(mode="after")
    def valid_scope_and_lifetime(self) -> "PaymentCapabilityV1":
        if self.issued_at <= 0 or self.expires_at <= self.issued_at:
            raise ValueError("capability timestamps must be positive and ordered")
        if self.expires_at - self.issued_at > MAX_PAYMENT_CAPABILITY_LIFETIME_SECONDS:
            raise ValueError("capability lifetime exceeds 60 seconds")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @property
    def capability_hash(self) -> str:
        return sha256_identifier(self.canonical_bytes())


_SPENDING_GRANT_TERM_FIELDS = {
    "wallet_identity_id",
    "user_id",
    "agent_id",
    "max_amount_usdc",
    "per_transaction_limit_usdc",
    "hourly_limit_usdc",
    "daily_limit_usdc",
    "product_scopes",
    "venue_scopes",
    "merchant_scopes",
    "merchant_trust_scopes",
    "notification_mode",
    "network_scopes",
    "asset_scopes",
    "starts_at",
    "expires_at",
}
_SPENDING_GRANT_USDC_FIELDS = (
    "max_amount_usdc",
    "per_transaction_limit_usdc",
    "hourly_limit_usdc",
    "daily_limit_usdc",
)


def spending_grant_terms_hash(grant: SpendingGrant) -> str:
    if not isinstance(grant, SpendingGrant):
        raise TypeError("grant must be a SpendingGrant")
    projection = grant.model_dump(
        mode="json",
        include=_SPENDING_GRANT_TERM_FIELDS,
    )
    for field_name in _SPENDING_GRANT_USDC_FIELDS:
        projection[field_name] = _canonical_usdc_amount(getattr(grant, field_name))
    return _canonical_hash(projection)


def policy_decision_snapshot_hash(decision: PolicyDecision) -> str:
    if not isinstance(decision, PolicyDecision):
        raise TypeError("decision must be a PolicyDecision")
    return _canonical_hash(decision.model_dump(mode="json"))


def risk_evidence_hash(risk_assessment: Mapping[str, Any] | None) -> str:
    if risk_assessment is None:
        return _canonical_hash(VERIFICATION_ONLY_RISK_ABSENCE_MARKER)
    if not isinstance(risk_assessment, Mapping):
        raise TypeError("risk_assessment must be a mapping or None")
    return _canonical_hash(dict(risk_assessment))


class _ReservationScope(BaseModel):
    """Core-owned immutable projection linked from the on-chain execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reservation_id: str
    purchase_id: str
    user_id: str
    agent_id: str
    wallet_identity_id: str
    spending_grant_id: str
    asset_allowance_id: str
    action_id: str
    policy_decision_id: str
    merchant_id: str
    product: str
    venue: str
    quote_hash: str
    network: Literal["eip155:137", "eip155:8453", "eip155:80002"]
    asset_contract: str
    amount_atomic: str
    pay_to: str
    authorization_rail: Literal["native_allowance", "clink_payer_proxy"]

    _canonical_addresses = field_validator("asset_contract", "pay_to")(
        canonicalize_evm_address
    )
    _valid_amount = field_validator("amount_atomic", mode="before")(
        _canonical_atomic_amount
    )

    @field_validator(
        "reservation_id",
        "purchase_id",
        "user_id",
        "agent_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "action_id",
        "policy_decision_id",
        "merchant_id",
        "product",
        "venue",
        mode="before",
    )
    @classmethod
    def valid_identifier(cls, value: object, info) -> str:
        return _validate_identifier(value, field_name=info.field_name)

    @field_validator("quote_hash", mode="before")
    @classmethod
    def valid_hash(cls, value: object, info) -> str:
        return _validate_bytes32(value, field_name=info.field_name)


def reservation_scope_hash(
    *,
    reservation_id: str,
    purchase_id: str,
    user_id: str,
    agent_id: str,
    wallet_identity_id: str,
    spending_grant_id: str,
    asset_allowance_id: str,
    action_id: str,
    policy_decision_id: str,
    merchant_id: str,
    product: str,
    venue: str,
    quote_hash: str,
    network: str,
    asset_contract: str,
    amount_atomic: str,
    pay_to: str,
    authorization_rail: str,
) -> str:
    """Hash the exact immutable Core reservation facts used by Hosted."""

    reservation = _ReservationScope(
        reservation_id=reservation_id,
        purchase_id=purchase_id,
        user_id=user_id,
        agent_id=agent_id,
        wallet_identity_id=wallet_identity_id,
        spending_grant_id=spending_grant_id,
        asset_allowance_id=asset_allowance_id,
        action_id=action_id,
        policy_decision_id=policy_decision_id,
        merchant_id=merchant_id,
        product=product,
        venue=venue,
        quote_hash=quote_hash,
        network=network,
        asset_contract=asset_contract,
        amount_atomic=amount_atomic,
        pay_to=pay_to,
        authorization_rail=authorization_rail,
    )
    return _canonical_hash(reservation.model_dump(mode="json"))


class _ExecutionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    network: Literal["eip155:137", "eip155:8453", "eip155:80002"]
    asset_contract: str
    wallet_address: str
    executor_contract: str
    pay_to: str
    amount_atomic: str
    purchase_id: str
    reservation_id: str
    quote_hash: str

    _canonical_addresses = field_validator(
        "asset_contract", "wallet_address", "executor_contract", "pay_to"
    )(canonicalize_evm_address)
    _valid_amount = field_validator("amount_atomic", mode="before")(
        _canonical_atomic_amount
    )

    @field_validator("purchase_id", "reservation_id", mode="before")
    @classmethod
    def valid_identifier(cls, value: object, info) -> str:
        return _validate_identifier(value, field_name=info.field_name)

    @field_validator("quote_hash", mode="before")
    @classmethod
    def valid_hash(cls, value: object, info) -> str:
        return _validate_bytes32(value, field_name=info.field_name)


def execution_scope_hash(
    *,
    network: str,
    asset_contract: str,
    wallet_address: str,
    executor_contract: str,
    pay_to: str,
    amount_atomic: str,
    purchase_id: str,
    reservation_id: str,
    quote_hash: str,
) -> str:
    scope = _ExecutionScope(
        network=network,
        asset_contract=asset_contract,
        wallet_address=wallet_address,
        executor_contract=executor_contract,
        pay_to=pay_to,
        amount_atomic=amount_atomic,
        purchase_id=purchase_id,
        reservation_id=reservation_id,
        quote_hash=quote_hash,
    )
    return _canonical_hash(scope.model_dump(mode="json"))


class _RevocationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    wallet_identity_id: str
    spending_grant_id: str
    asset_allowance_id: str
    wallet_binding_id: str

    @field_validator(
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "wallet_binding_id",
        mode="before",
    )
    @classmethod
    def valid_identifier(cls, value: object, info) -> str:
        return _validate_identifier(value, field_name=info.field_name)


def revocation_projection_id(
    *,
    wallet_identity_id: str,
    spending_grant_id: str,
    asset_allowance_id: str,
    wallet_binding_id: str,
) -> str:
    projection = _RevocationProjection(
        wallet_identity_id=wallet_identity_id,
        spending_grant_id=spending_grant_id,
        asset_allowance_id=asset_allowance_id,
        wallet_binding_id=wallet_binding_id,
    )
    return _canonical_hash(projection.model_dump(mode="json"))
