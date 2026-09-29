from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, Field


def eligible_payment_options(payment_options, *, network=None, max_price_usd=None):
    cap = None
    if max_price_usd is not None:
        try:
            cap = Decimal(str(max_price_usd))
        except Exception as exc:
            raise ValueError("max_price_usd must be numeric") from exc
        if cap < 0:
            raise ValueError("max_price_usd must not be negative")
    return [
        option
        for option in payment_options
        if (not network or option.network == network)
        and (cap is None or option.price_usd is not None and option.price_usd <= cap)
    ]


def purchase_execution_mode(*, trust_tier, provider_id, native_provider_ids):
    if trust_tier == "clink_verified" and provider_id in native_provider_ids:
        return "clink_allowance"
    return "external_x402_signature"


def payment_capability(execution_mode, *, authorization=None):
    if execution_mode == "external_x402_signature":
        return {
            "rail": execution_mode,
            "mandate_compatible": False,
            "auto_pay_compatible": False,
            "requires_purchase_signature": True,
            "reason_code": "MERCHANT_SCOPED_EIP3009_SIGNATURE_REQUIRED",
        }
    ready = bool(authorization and authorization.get("ready"))
    return {
        "rail": execution_mode,
        "mandate_compatible": True,
        "auto_pay_compatible": ready,
        "requires_purchase_signature": False,
        "reason_code": (
            None
            if ready
            else (authorization or {}).get("reason_code")
            or "CORE_AUTHORIZATION_CHECK_REQUIRED"
        ),
    }

class Quote(BaseModel):
    offering_id: str; provider_id: str; name: str; endpoint: str
    payment: dict[str, Any]; reputation: dict[str, Any]; sla: dict[str, Any] = Field(default_factory=dict)
    trust_tier: Literal["registry_verified", "clink_verified"]
    verification_source: str
    execution_mode: Literal[
        "clink_allowance", "clink_payer_proxy", "external_x402_signature"
    ]
    payment_capability: dict[str, Any]

class PurchasePreview(BaseModel):
    preview_id: str; offering_id: str; user_id: str; quote_hash: str; input_hash: str
    payment: dict[str, Any]; execution_mode: Literal[
        "clink_allowance", "clink_payer_proxy", "external_x402_signature"
    ]
    opc_installation_id: str | None = Field(
        default=None,
        pattern=r"^opc_[0-9a-f]{40}$",
    )
    payment_capability: dict[str, Any] = Field(default_factory=dict)
    state: Literal["preview_created"] = "preview_created"; expires_at: datetime; created_at: datetime

class Purchase(BaseModel):
    purchase_id: str; preview_id: str; offering_id: str; user_id: str
    state: Literal["preview_created", "policy_approved", "confirmation_required", "spending_reserved", "signing_required", "payment_submitted", "delivered", "paid_but_undelivered", "failed"]
    execution_mode: str; input_hash: str; output_hash: str | None = None
    reservation_id: str | None = None; action_id: str | None = None; policy_decision_id: str | None = None
    receipt_id: str | None = None; audit_event_ids: list[str] = Field(default_factory=list)
    reason_code: str | None = None; metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime; updated_at: datetime
