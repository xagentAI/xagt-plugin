from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreparePolymarketDepositWalletRequest(BaseModel):
    user_id: str
    owner_wallet: str
    mode: str = "derive"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolymarketDepositWalletState(BaseModel):
    user_id: str
    owner_wallet: str
    deposit_wallet: str | None = None
    status: str
    reason: str | None = None
    next_action: str
    can_use_x402: bool = False
    transaction_id: str | None = None
    relayer_state: str | None = None
    created_at: str
    updated_at: str
    raw_response: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolymarketDepositWalletReadiness(BaseModel):
    service: str = "prediction_markets_deposit_wallet_service"
    user_id: str
    owner_wallet: str | None = None
    deposit_wallet: str | None = None
    status: str
    ready: bool = False
    can_use_x402: bool = False
    missing: list[str] = Field(default_factory=list)
    reason: str | None = None
    next_action: str
    relayer_url_configured: bool = False
    builder_credentials_configured: bool = False
    state: PolymarketDepositWalletState | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
