from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator


_EVM_ADDRESS_PATTERN = re.compile(r"^0[xX]([0-9a-fA-F]{40})$")
_ZERO_ADDRESS = "0x" + "0" * 40


def canonicalize_optional_evm_address(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    match = _EVM_ADDRESS_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(
            f"{field_name} must be 0x followed by 40 hex characters"
        )
    normalized = "0x" + match.group(1).lower()
    if normalized == _ZERO_ADDRESS:
        raise ValueError(f"{field_name} must not be the zero address")
    return normalized


def _canonical_evm_address_field(
    value: object,
    info: ValidationInfo,
) -> str | None:
    return canonicalize_optional_evm_address(
        value,
        field_name=info.field_name,
    )


class CreatePolymarketBindingSessionRequest(BaseModel):
    user_id: str
    agent_id: str = "hermes"
    wallet_address: str | None = None
    polymarket_deposit_wallet: str | None = None
    expires_in_minutes: int = 30
    return_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _canonical_addresses = field_validator(
        "wallet_address",
        "polymarket_deposit_wallet",
        mode="before",
    )(_canonical_evm_address_field)


class CompletePolymarketBindingSessionRequest(BaseModel):
    wallet_address: str
    signature: str
    signed_message: str
    polymarket_deposit_wallet: str | None = None
    clob_auth_signature: str | None = None
    clob_auth_timestamp: str | None = None
    clob_auth_nonce: int = 0
    polymarket_signature_type: str = "auto"
    metadata: dict[str, Any] = Field(default_factory=dict)

    _canonical_addresses = field_validator(
        "wallet_address",
        "polymarket_deposit_wallet",
        mode="before",
    )(_canonical_evm_address_field)


class RevokePolymarketBindingSessionRequest(BaseModel):
    wallet_address: str
    signature: str
    signed_message: str
    reason: str = "user_requested_unbind"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolymarketBindingSession(BaseModel):
    session_id: str
    user_id: str
    agent_id: str
    venue: str = "polymarket"
    wallet_address: str | None = None
    polymarket_deposit_wallet: str | None = None
    message_to_sign: str
    signing_url: str
    status: str
    reason: str | None = None
    next_action: str
    expires_at: str
    created_at: str
    completed_at: str | None = None
    binding_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _canonical_addresses = field_validator(
        "wallet_address",
        "polymarket_deposit_wallet",
        mode="before",
    )(_canonical_evm_address_field)


class PolymarketAccountBinding(BaseModel):
    binding_id: str
    session_id: str
    user_id: str
    agent_id: str
    venue: str = "polymarket"
    wallet_address: str
    polymarket_deposit_wallet: str | None = None
    funder_address: str | None = None
    account_mode: str | None = None
    signature_scheme: str = "eip191_personal_sign"
    polymarket_signature_type: str = "0"
    has_api_credentials: bool = False
    api_key_fingerprint: str | None = None
    status: str
    reason: str | None = None
    next_action: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    _canonical_addresses = field_validator(
        "wallet_address",
        "polymarket_deposit_wallet",
        "funder_address",
        mode="before",
    )(_canonical_evm_address_field)
