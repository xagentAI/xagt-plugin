from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


USDCAmount = Annotated[Decimal, Field(max_digits=38, decimal_places=6)]
EVM_ADDRESS_PATTERN = re.compile(r"^0[xX]([0-9a-fA-F]{40})$")
EVM_TX_HASH_PATTERN = re.compile(r"^0[xX]([0-9a-fA-F]{64})$")
MAX_UINT256 = 2**256 - 1


def canonicalize_evm_address(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("EVM address must be a string")
    match = EVM_ADDRESS_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("EVM address must be 0x followed by 40 hex characters")
    return "0x" + match.group(1).lower()


def reject_control_characters(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("message fields must be strings")
    if any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        raise ValueError("message fields must not contain control characters")
    return value


def canonicalize_transaction_hash(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("transaction hash must be a string")
    match = EVM_TX_HASH_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("transaction hash must be 0x followed by 64 hex characters")
    return "0x" + match.group(1).lower()


def normalize_scope_list(value: list[str], *, field_name: str) -> list[str]:
    normalized = []
    for scope in value:
        reject_control_characters(scope)
        scope = scope.strip().lower()
        if not scope:
            raise ValueError(f"{field_name} scopes must not contain empty values")
        normalized.append(scope)
    return sorted(set(normalized))


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class WalletIdentity(BaseModel):
    wallet_identity_id: str
    user_id: str
    chain_family: Literal["eip155"] = "eip155"
    wallet_address: str
    status: Literal["pending", "active", "suspended", "revoked"]
    proof_scheme: Literal["eip191"] = "eip191"
    proof_hash: str
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _canonical_wallet_address = field_validator("wallet_address")(canonicalize_evm_address)
    _utc_timestamps = field_validator("verified_at", "created_at", "updated_at")(
        lambda value: _utc_timestamp(value) if value is not None else None
    )


class AccountSession(BaseModel):
    account_session_id: str
    user_id: str
    wallet_address: str
    nonce: str
    domain: str
    purpose: Literal[
        "clink_wallet_identity",
        "clink_spending_grant",
        "agentonomy_opc_installation",
    ]
    wallet_identity_id: str | None = None
    created_by_public_account_session_id: str | None = None
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    expires_at: datetime
    consumed_at: datetime | None = None
    created_at: datetime

    _canonical_wallet_address = field_validator("wallet_address")(canonicalize_evm_address)
    _safe_message_fields = field_validator("user_id", "domain")(reject_control_characters)
    _utc_timestamps = field_validator("expires_at", "consumed_at", "created_at")(
        lambda value: _utc_timestamp(value) if value is not None else None
    )


class PublicAccountSession(BaseModel):
    public_account_session_id: str
    token_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    browser_session_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    csrf_token_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    user_id: str
    purpose: Literal["clink_account_console"] = "clink_account_console"
    status: Literal["active", "revoked", "expired"] = "active"
    expires_at: datetime
    exchanged_at: datetime | None = None
    authenticated_wallet_identity_id: str | None = None
    authenticated_at: datetime | None = None
    last_accessed_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _safe_user_id = field_validator("user_id")(reject_control_characters)
    _utc_timestamps = field_validator(
        "expires_at",
        "exchanged_at",
        "authenticated_at",
        "last_accessed_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )(lambda value: _utc_timestamp(value) if value is not None else None)


class SpendingGrant(BaseModel):
    spending_grant_id: str
    wallet_identity_id: str
    user_id: str
    agent_id: str
    status: Literal["pending", "active", "paused", "exhausted", "expired", "revoked"]
    status_reason: str | None = None
    max_amount_usdc: USDCAmount
    per_transaction_limit_usdc: USDCAmount
    hourly_limit_usdc: USDCAmount | None = None
    daily_limit_usdc: USDCAmount
    used_amount_usdc: USDCAmount = Decimal("0")
    reserved_amount_usdc: USDCAmount = Decimal("0")
    product_scopes: list[str]
    venue_scopes: list[str] = Field(default_factory=list)
    merchant_scopes: list[str] = Field(default_factory=list)
    merchant_trust_scopes: list[
        Literal["clink_verified", "registry_verified"]
    ] = Field(default_factory=lambda: ["clink_verified"])
    notification_mode: Literal["silent_under_limits", "notify_all"] = "notify_all"
    network_scopes: list[str]
    asset_scopes: list[str]
    starts_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    _utc_timestamps = field_validator(
        "starts_at", "expires_at", "created_at", "updated_at"
    )(_utc_timestamp)

    @field_validator("product_scopes")
    @classmethod
    def product_scopes_are_explicit(cls, value: list[str]) -> list[str]:
        if not value or any(not scope or scope == "all" for scope in value):
            raise ValueError("product scopes must be explicit and non-empty")
        return normalize_scope_list(value, field_name="product")

    @field_validator("venue_scopes", "merchant_scopes", "network_scopes")
    @classmethod
    def normalize_named_scopes(cls, value: list[str], info) -> list[str]:
        return normalize_scope_list(value, field_name=info.field_name.removesuffix("_scopes"))

    @field_validator("merchant_trust_scopes")
    @classmethod
    def normalize_merchant_trust_scopes(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one merchant trust scope is required")
        return sorted(set(value))

    @field_validator("asset_scopes")
    @classmethod
    def canonical_asset_scopes(cls, value: list[str]) -> list[str]:
        return sorted({canonicalize_evm_address(scope) for scope in value})

    @model_validator(mode="after")
    def valid_policy(self) -> "SpendingGrant":
        _validate_grant_policy(self)
        return self


class OpcInstallationAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pairing_id: str
    installation_id: str
    public_jwk: dict[str, str]
    public_jwk_thumbprint: str
    label: str
    scope: Literal["payments"] = "payments"
    consent_expires_at: datetime

    _safe_identifiers = field_validator(
        "pairing_id", "installation_id", "public_jwk_thumbprint", "label"
    )(reject_control_characters)
    _utc_expiry = field_validator("consent_expires_at")(_utc_timestamp)

    @model_validator(mode="after")
    def valid_installation(self) -> "OpcInstallationAuthorization":
        if not self.pairing_id or len(self.pairing_id) > 96:
            raise ValueError("OPC pairing id is invalid")
        if not re.fullmatch(r"opc_[0-9a-f]{40}", self.installation_id):
            raise ValueError("OPC installation id is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", self.public_jwk_thumbprint):
            raise ValueError("OPC public key thumbprint is invalid")
        if not 1 <= len(self.label) <= 80:
            raise ValueError("OPC installation label is invalid")
        if (
            set(self.public_jwk) != {"kty", "crv", "x", "y"}
            or self.public_jwk.get("kty") != "EC"
            or self.public_jwk.get("crv") != "P-256"
        ):
            raise ValueError("OPC public key is invalid")
        return self


class SpendingGrantRequest(BaseModel):
    user_id: str
    wallet_identity_id: str
    agent_id: str
    max_amount_usdc: USDCAmount
    per_transaction_limit_usdc: USDCAmount
    hourly_limit_usdc: USDCAmount | None = None
    daily_limit_usdc: USDCAmount
    product_scopes: list[str]
    venue_scopes: list[str] = Field(default_factory=list)
    merchant_scopes: list[str] = Field(default_factory=list)
    merchant_trust_scopes: list[
        Literal["clink_verified", "registry_verified"]
    ] = Field(default_factory=lambda: ["clink_verified"])
    notification_mode: Literal["silent_under_limits", "notify_all"] = "notify_all"
    network_scopes: list[str]
    asset_scopes: list[str]
    starts_at: datetime
    expires_at: datetime
    amends_spending_grant_id: str | None = None
    opc_installation: OpcInstallationAuthorization | None = None
    created_by_public_account_session_id: str | None = None
    session_id: str | None = None
    signed_message: str | None = None
    signature: str | None = None

    _safe_identifiers = field_validator("user_id", "wallet_identity_id", "agent_id")(
        reject_control_characters
    )
    _utc_timestamps = field_validator("starts_at", "expires_at")(_utc_timestamp)

    @field_validator("product_scopes")
    @classmethod
    def normalize_products(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one product scope is required")
        return normalize_scope_list(value, field_name="product")

    @field_validator("amends_spending_grant_id")
    @classmethod
    def safe_amendment_target(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 96:
            raise ValueError("spending grant amendment target is too long")
        return reject_control_characters(value)

    @field_validator("venue_scopes", "merchant_scopes")
    @classmethod
    def normalize_optional_scopes(cls, value: list[str], info) -> list[str]:
        return normalize_scope_list(value, field_name=info.field_name.removesuffix("_scopes"))

    @field_validator("merchant_trust_scopes")
    @classmethod
    def normalize_merchant_trust_scopes(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one merchant trust scope is required")
        return sorted(set(value))

    @field_validator("network_scopes")
    @classmethod
    def normalize_networks(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one network scope is required")
        return normalize_scope_list(value, field_name="network")

    @field_validator("asset_scopes")
    @classmethod
    def normalize_assets(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one asset scope is required")
        return sorted({canonicalize_evm_address(scope) for scope in value})

    @model_validator(mode="after")
    def valid_policy(self) -> "SpendingGrantRequest":
        _validate_grant_policy(self)
        if self.opc_installation is not None:
            if self.agent_id != "hermes":
                raise ValueError("OPC installation requires the Hermes grant")
            if self.amends_spending_grant_id is not None:
                raise ValueError("OPC installation cannot be added by grant amendment")
            if self.created_by_public_account_session_id is None:
                raise ValueError("OPC installation requires an account session")
            if self.opc_installation.consent_expires_at > self.expires_at:
                raise ValueError("OPC consent cannot outlive the spending grant")
        return self

    def terms_payload(self) -> dict[str, Any]:
        payload = self.model_dump(
            mode="json",
            exclude={
                "session_id",
                "signed_message",
                "signature",
                "created_by_public_account_session_id",
            },
        )
        if self.amends_spending_grant_id is None:
            payload.pop("amends_spending_grant_id")
        if self.opc_installation is None:
            payload.pop("opc_installation")
        return payload


class AssetAllowance(BaseModel):
    asset_allowance_id: str
    wallet_identity_id: str
    network: str
    token_address: str
    token_symbol: str
    token_decimals: int
    spender_address: str
    approved_amount_atomic: int = Field(ge=0, le=MAX_UINT256)
    observed_allowance_atomic: int = Field(ge=0, le=MAX_UINT256)
    allowance_tx_hash: str | None = None
    status: Literal["pending", "active", "insufficient", "revoked", "stale"]
    confirmed_block: int | None = Field(default=None, ge=0)
    last_chain_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _canonical_addresses = field_validator("token_address", "spender_address")(
        canonicalize_evm_address
    )
    _utc_timestamps = field_validator(
        "last_chain_check_at", "created_at", "updated_at"
    )(lambda value: _utc_timestamp(value) if value is not None else None)

    _canonical_tx_hash = field_validator("allowance_tx_hash")(
        lambda value: canonicalize_transaction_hash(value) if value is not None else None
    )

    @field_serializer(
        "approved_amount_atomic", "observed_allowance_atomic", when_used="json"
    )
    def serialize_atomic_amount(self, value: int) -> str:
        return str(value)


class AuthorizationResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    agent_id: str
    opc_installation_id: str | None = None
    authorization_rail: Literal[
        "native_allowance", "clink_payer_proxy", "external_x402"
    ] = (
        "native_allowance"
    )
    product: str
    venue: str | None = None
    merchant: str | None = None
    merchant_trust_tier: Literal["clink_verified", "registry_verified"] | None = None
    network: str
    token_address: str | None = None
    asset: str | None = None
    spender_address: str | None = None
    amount_usdc: USDCAmount
    destination: str
    resource: str

    _safe_identifiers = field_validator(
        "user_id", "agent_id", "product", "venue", "merchant", "network", "asset", "resource"
    )(lambda value: reject_control_characters(value) if value is not None else None)
    _canonical_destination = field_validator("destination")(canonicalize_evm_address)
    _canonical_spender = field_validator("spender_address")(
        lambda value: canonicalize_evm_address(value) if value is not None else None
    )
    _canonical_token = field_validator("token_address")(
        lambda value: canonicalize_evm_address(value) if value is not None else None
    )

    @field_validator("opc_installation_id")
    @classmethod
    def validate_opc_installation_id(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"opc_[0-9a-f]{40}", value) is None:
            raise ValueError("opc_installation_id is invalid")
        return value

    @field_validator("product", "venue", "merchant", "network", "asset")
    @classmethod
    def normalize_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("authorization scope must not be empty")
        return normalized

    @model_validator(mode="after")
    def valid_resolution_request(self) -> "AuthorizationResolutionRequest":
        if self.amount_usdc <= 0:
            raise ValueError("amount_usdc must be positive")
        if self.token_address is None and self.asset is None:
            raise ValueError("token_address or asset is required")
        if self.token_address is not None and self.asset is not None:
            try:
                asset_address = canonicalize_evm_address(self.asset)
            except ValueError:
                asset_address = None
            if asset_address is not None and asset_address != self.token_address:
                raise ValueError("token_address and asset do not match")
        if (
            self.authorization_rail in {"native_allowance", "clink_payer_proxy"}
            and self.spender_address is None
        ):
            raise ValueError("allowance-backed resolution requires spender_address")
        if self.authorization_rail == "external_x402" and self.token_address is None:
            raise ValueError("external x402 resolution requires token_address")
        if self.authorization_rail == "external_x402" and self.spender_address is not None:
            raise ValueError("external x402 resolution must not use spender_address")
        return self


class AuthorizationResolutionResult(BaseModel):
    ready: bool
    opc_installation_id: str | None = None
    authorization_rail: Literal[
        "native_allowance", "clink_payer_proxy", "external_x402"
    ] | None = None
    reason_code: str | None = None
    wallet_identity_id: str | None = None
    spending_grant_id: str | None = None
    asset_allowance_id: str | None = None
    remaining_amount_usdc: USDCAmount | None = None
    remaining_daily_amount_usdc: USDCAmount | None = None
    remaining_hourly_amount_usdc: USDCAmount | None = None
    notification_mode: Literal["silent_under_limits", "notify_all"] | None = None
    user_interaction_required: bool | None = None
    interaction_reason_code: str | None = None
    required_amount_atomic: int | None = Field(default=None, ge=0, le=MAX_UINT256)
    observed_allowance_atomic: int | None = Field(default=None, ge=0, le=MAX_UINT256)
    next_action: str


def _validate_grant_policy(value: SpendingGrant | SpendingGrantRequest) -> None:
    if value.hourly_limit_usdc is None:
        value.hourly_limit_usdc = value.daily_limit_usdc
    if any(
        amount <= 0
        for amount in (
            value.max_amount_usdc,
            value.per_transaction_limit_usdc,
            value.hourly_limit_usdc,
            value.daily_limit_usdc,
        )
    ):
        raise ValueError("grant amounts must be positive")
    if value.per_transaction_limit_usdc > value.max_amount_usdc:
        raise ValueError("per-transaction limit exceeds total grant")
    if value.per_transaction_limit_usdc > value.hourly_limit_usdc:
        raise ValueError("per-transaction limit exceeds hourly limit")
    if value.hourly_limit_usdc > value.daily_limit_usdc:
        raise ValueError("hourly limit exceeds daily limit")
    if value.daily_limit_usdc > value.max_amount_usdc:
        raise ValueError("daily limit exceeds total grant")
    if value.starts_at >= value.expires_at:
        raise ValueError("starts_at must be before expires_at")
