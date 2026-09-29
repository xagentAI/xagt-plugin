"""Pure planning helpers for the embedded Core authorization form.

The helpers in this module deliberately do not access repositories, wallets, or
chain clients.  They turn the small browser form into the existing signed grant
request shape and describe the allowance that the browser may need to show.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from .schemas import (
    MAX_UINT256,
    SpendingGrant,
    SpendingGrantRequest,
    USDCAmount,
    WalletIdentity,
    canonicalize_evm_address,
    reject_control_characters,
    normalize_scope_list,
)


_USDC_AMOUNT_ADAPTER = TypeAdapter(USDCAmount)

REVIEWED_PRODUCT_SCOPES = frozenset({"marketplace", "transfers"})
REVIEWED_VENUE_BY_PRODUCT = {
    "marketplace": "clink_marketplace",
    "transfers": "clink_transfers",
}
REVIEWED_VENUE_SCOPES = frozenset(REVIEWED_VENUE_BY_PRODUCT.values())
GRANT_AUTHORITY_FIELDS = (
    "spending_grant_id",
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
)


def _non_empty_safe_identifier(value: str, *, field_name: str) -> str:
    value = reject_control_characters(value)
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class AuthorizationForm(BaseModel):
    """The only user-controlled fields accepted by the embedded form."""

    model_config = ConfigDict(extra="forbid")

    wallet_identity_id: str = Field(min_length=1, max_length=96, strict=True)
    network: str = Field(min_length=1, max_length=64, strict=True)
    total_usdc: USDCAmount
    hourly_usdc: USDCAmount
    duration_days: int | None = Field(default=None, ge=1, le=365, strict=True)
    spending_grant_id: str | None = Field(
        default=None, min_length=1, max_length=96, strict=True
    )
    # ``None`` deliberately preserves the old form contract: new grants are
    # Marketplace-only and existing grants retain their exact scopes.  An
    # explicit list is the only way this small form may alter product scope.
    products: list[str] | None = None

    _safe_identifiers = field_validator(
        "wallet_identity_id", "network", "spending_grant_id"
    )(
        lambda value, info: (
            _non_empty_safe_identifier(value, field_name=info.field_name)
            if value is not None
            else None
        )
    )

    @field_validator("total_usdc", "hourly_usdc", mode="before")
    @classmethod
    def require_decimal_string_amounts(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)) or isinstance(value, bool):
            raise ValueError("USDC amounts must be decimal strings or Decimal values")
        return value

    @field_validator("total_usdc", "hourly_usdc")
    @classmethod
    def positive_finite_amounts(cls, value: Decimal) -> Decimal:
        _validate_usdc_amount(value, field_name="USDC amount", positive=True)
        return value

    @field_validator("products")
    @classmethod
    def normalize_products(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = normalize_scope_list(value, field_name="product")
        if not normalized:
            raise ValueError("product selection must not be empty")
        unsupported = set(normalized) - REVIEWED_PRODUCT_SCOPES
        if unsupported:
            raise ValueError(
                f"unsupported product selection: {sorted(unsupported)[0]}"
            )
        return normalized


def _validate_usdc_amount(
    value: object,
    *,
    field_name: str,
    positive: bool,
) -> Decimal:
    """Validate a monetary input without converting through binary float."""

    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name} must be a Decimal or integer")
    if isinstance(value, int):
        value = Decimal(value)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field_name} must be {qualifier}")
    try:
        return _USDC_AMOUNT_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ValueError(
            f"{field_name} must be a finite USDC amount with at most 38 digits "
            "and 6 decimal places"
        ) from exc


def _utc_time(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _public_terms(request: SpendingGrantRequest) -> dict[str, Any]:
    """Return only terms safe to hand to the browser for a signature."""

    terms = request.terms_payload()
    for private_field in (
        "user_id",
        "session_id",
        "signed_message",
        "signature",
        "opc_installation",
        "created_by_public_account_session_id",
    ):
        terms.pop(private_field, None)
    return terms


def reviewed_scope_selection(
    current_product_scopes: list[str],
    current_venue_scopes: list[str],
    selected_products: list[str],
) -> tuple[list[str], list[str]]:
    """Apply only the two reviewed product/venue toggles to an old grant."""

    selected = set(selected_products)
    if not selected or not selected.issubset(REVIEWED_PRODUCT_SCOPES):
        raise ValueError("product selection must include only reviewed products")
    if current_product_scopes and not current_venue_scopes:
        raise ValueError("cannot amend a wildcard venue scope")
    products = (
        set(current_product_scopes) - REVIEWED_PRODUCT_SCOPES
    ) | selected
    venues = set(current_venue_scopes) - REVIEWED_VENUE_SCOPES
    venues.update(REVIEWED_VENUE_BY_PRODUCT[product] for product in selected)
    return sorted(products), sorted(venues)


def reviewed_scope_amendment_is_valid(
    current_product_scopes: list[str],
    current_venue_scopes: list[str],
    proposed_product_scopes: list[str],
    proposed_venue_scopes: list[str],
) -> bool:
    """Check that an amendment changes only reviewed product/venue pairs."""

    current_products = set(current_product_scopes)
    current_venues = set(current_venue_scopes)
    proposed_products = set(proposed_product_scopes)
    proposed_venues = set(proposed_venue_scopes)
    if proposed_products == current_products and proposed_venues == current_venues:
        return True
    if not proposed_products:
        return False
    if (
        proposed_products - REVIEWED_PRODUCT_SCOPES
        != current_products - REVIEWED_PRODUCT_SCOPES
    ):
        return False
    if (
        proposed_venues - REVIEWED_VENUE_SCOPES
        != current_venues - REVIEWED_VENUE_SCOPES
    ):
        return False
    expected_venues = set(current_venues) - REVIEWED_VENUE_SCOPES
    expected_venues.update(
        REVIEWED_VENUE_BY_PRODUCT[product]
        for product in proposed_products & REVIEWED_PRODUCT_SCOPES
    )
    return proposed_venues == expected_venues


def grant_authorization_hash(grant: SpendingGrant) -> str:
    """Hash signed authority while intentionally excluding accounting state."""

    if not isinstance(grant, SpendingGrant):
        raise TypeError("grant must be a SpendingGrant")
    # Keep this import local: hosted_facilitator_protocol imports account
    # schemas during package initialization, and a module-level import here
    # would create an account_service <-> hosted protocol cycle.
    from shared.hosted_facilitator_protocol import canonical_json_bytes

    terms = grant.model_dump(mode="json", include=set(GRANT_AUTHORITY_FIELDS))
    return hashlib.sha256(canonical_json_bytes(terms)).hexdigest()


def authorization_terms(
    form: AuthorizationForm,
    *,
    identity: WalletIdentity,
    current: SpendingGrant | None,
    token_address: str,
    at: datetime,
) -> dict[str, Any]:
    """Plan a new marketplace grant or a bounded amendment to an active one."""

    if not isinstance(form, AuthorizationForm):
        raise TypeError("form must be an AuthorizationForm")
    if not isinstance(identity, WalletIdentity):
        raise TypeError("identity must be a WalletIdentity")

    now = _utc_time(at, field_name="server time")
    if identity.status != "active":
        raise ValueError("wallet identity is not active")
    if identity.wallet_identity_id != form.wallet_identity_id:
        raise ValueError("wallet identity does not match form")

    # Validate the selected token even when the existing grant's immutable asset
    # scope will be retained for an amendment.
    selected_token = canonicalize_evm_address(token_address)
    has_grant_id = form.spending_grant_id is not None
    if (current is None) != (not has_grant_id):
        raise ValueError("form grant id and current grant must agree")

    if current is None:
        if form.duration_days is None:
            raise ValueError("duration_days is required for a new grant")
        max_amount = form.total_usdc
        hourly_limit = form.hourly_usdc
        per_transaction = form.hourly_usdc
        daily_limit = form.total_usdc
        selected_products = (
            ["marketplace"] if form.products is None else form.products
        )
        product_scopes, venue_scopes = reviewed_scope_selection([], [], selected_products)
        merchant_scopes: list[str] = []
        merchant_trust_scopes = ["clink_verified", "registry_verified"]
        notification_mode = "silent_under_limits"
        network_scopes = [form.network]
        asset_scopes = [selected_token]
        starts_at = now
        expires_at = now + timedelta(days=form.duration_days)
        amendment_id = None
        action = "sign"
    else:
        if form.duration_days is not None:
            raise ValueError("duration_days must be omitted for a current grant")
        if current.status != "active":
            raise ValueError("only an active grant can be amended")
        if current.spending_grant_id != form.spending_grant_id:
            raise ValueError("current grant does not match form")
        if current.wallet_identity_id != identity.wallet_identity_id:
            raise ValueError("current grant identity does not match form")
        if current.user_id != identity.user_id:
            raise ValueError("current grant user does not match identity")
        if current.agent_id != "hermes":
            raise ValueError("only the Hermes grant can be amended")
        if not (current.starts_at <= now < current.expires_at):
            raise ValueError("current grant is not active at the server time")
        if form.network not in current.network_scopes:
            raise ValueError("form network is outside the current grant scope")
        if selected_token not in current.asset_scopes:
            raise ValueError("form token is outside the current grant scope")

        used = _validate_usdc_amount(
            current.used_amount_usdc,
            field_name="used amount",
            positive=False,
        )
        reserved = _validate_usdc_amount(
            current.reserved_amount_usdc,
            field_name="reserved amount",
            positive=False,
        )
        with localcontext() as context:
            context.prec = 80
            below_committed = form.total_usdc < used + reserved
        if below_committed:
            raise ValueError("total cannot be below used plus reserved amount")

        old_hourly = current.hourly_limit_usdc
        if old_hourly is None:
            old_hourly = current.daily_limit_usdc
        max_amount = form.total_usdc
        daily_limit = min(current.daily_limit_usdc, form.total_usdc)
        hourly_limit = form.hourly_usdc
        per_transaction = min(
            current.per_transaction_limit_usdc, form.hourly_usdc
        )
        if form.hourly_usdc > daily_limit:
            raise ValueError("hourly limit exceeds resulting daily limit")

        # Scope and dates are signed grant facts.  An amendment may change the
        # two budget inputs plus the explicitly reviewed product/venue pair;
        # all dates and other restrictions remain byte-for-byte from the grant.
        if form.products is None:
            product_scopes = list(current.product_scopes)
            venue_scopes = list(current.venue_scopes)
        else:
            product_scopes, venue_scopes = reviewed_scope_selection(
                current.product_scopes,
                current.venue_scopes,
                form.products,
            )
        merchant_scopes = list(current.merchant_scopes)
        merchant_trust_scopes = list(current.merchant_trust_scopes)
        notification_mode = current.notification_mode
        network_scopes = list(current.network_scopes)
        asset_scopes = list(current.asset_scopes)
        starts_at = current.starts_at
        expires_at = current.expires_at
        amendment_id = current.spending_grant_id
        action = (
            "sign"
            if (
                max_amount != current.max_amount_usdc
                or hourly_limit != old_hourly
                or product_scopes != current.product_scopes
                or venue_scopes != current.venue_scopes
            )
            else "none"
        )

    request = SpendingGrantRequest(
        user_id=identity.user_id,
        wallet_identity_id=identity.wallet_identity_id,
        agent_id="hermes",
        max_amount_usdc=max_amount,
        per_transaction_limit_usdc=per_transaction,
        hourly_limit_usdc=hourly_limit,
        daily_limit_usdc=daily_limit,
        product_scopes=product_scopes,
        venue_scopes=venue_scopes,
        merchant_scopes=merchant_scopes,
        merchant_trust_scopes=merchant_trust_scopes,
        notification_mode=notification_mode,
        network_scopes=network_scopes,
        asset_scopes=asset_scopes,
        starts_at=starts_at,
        expires_at=expires_at,
        amends_spending_grant_id=amendment_id,
    )
    return {"action": action, "terms": _public_terms(request)}


def _format_usdc(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _atomic_usdc(value: Decimal) -> int:
    whole, separator, fractional = format(value, "f").partition(".")
    if len(fractional) > 6:
        raise ValueError("USDC amount cannot be represented in atomic units")
    if not separator:
        fractional = ""
    atomic = int(whole) * 1_000_000 + int(fractional.ljust(6, "0") or "0")
    if not 0 <= atomic <= MAX_UINT256:
        raise ValueError("USDC amount exceeds uint256 atomic range")
    return atomic


def allowance_advice(
    *,
    total: Decimal,
    used: Decimal,
    per_transaction: Decimal,
    observed_atomic: int | None,
) -> dict[str, str | bool | None]:
    """Describe the finite allowance target for the remaining grant budget."""

    total_amount = _validate_usdc_amount(total, field_name="total amount", positive=False)
    used_amount = _validate_usdc_amount(used, field_name="used amount", positive=False)
    per_amount = _validate_usdc_amount(
        per_transaction, field_name="per-transaction amount", positive=True
    )
    if used_amount > total_amount:
        raise ValueError("used amount cannot exceed total amount")

    if observed_atomic is not None:
        if isinstance(observed_atomic, bool) or not isinstance(observed_atomic, int):
            raise ValueError("observed allowance must be an integer atomic amount")
        if not 0 <= observed_atomic <= MAX_UINT256:
            raise ValueError("observed allowance atomic amount is outside uint256")

    with localcontext() as context:
        context.prec = 80
        target = total_amount - used_amount
        required = min(per_amount, target)
    target_atomic = _atomic_usdc(target)

    if target == 0:
        status = "exhausted"
    elif observed_atomic is None:
        status = "unknown"
    elif observed_atomic >= _atomic_usdc(required):
        status = "sufficient"
    else:
        status = "insufficient"

    return {
        "status": status,
        "required_usdc": _format_usdc(required),
        "target_usdc": _format_usdc(target),
        "target_atomic": str(target_atomic),
        "observed_atomic": (
            str(observed_atomic) if observed_atomic is not None else None
        ),
        "exceeds_budget": (
            observed_atomic > target_atomic if observed_atomic is not None else None
        ),
    }


__all__ = [
    "AuthorizationForm",
    "GRANT_AUTHORITY_FIELDS",
    "REVIEWED_PRODUCT_SCOPES",
    "REVIEWED_VENUE_BY_PRODUCT",
    "REVIEWED_VENUE_SCOPES",
    "allowance_advice",
    "authorization_terms",
    "grant_authorization_hash",
    "reviewed_scope_amendment_is_valid",
    "reviewed_scope_selection",
]
