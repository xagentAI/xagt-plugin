from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from services.account_service.authorization import (
    AuthorizationForm,
    allowance_advice,
    authorization_terms,
)
from services.account_service.schemas import SpendingGrant, WalletIdentity


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TOKEN = "0x" + "1" * 40
OTHER_TOKEN = "0x" + "2" * 40


def identity(**updates: object) -> WalletIdentity:
    values: dict[str, object] = {
        "wallet_identity_id": "wallet_identity_1",
        "user_id": "user_1",
        "wallet_address": "0x" + "a" * 40,
        "status": "active",
        "proof_hash": "0xproof",
        "verified_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return WalletIdentity(**values)


def form(**updates: object) -> AuthorizationForm:
    values: dict[str, object] = {
        "wallet_identity_id": "wallet_identity_1",
        "network": "eip155:137",
        "total_usdc": Decimal("100"),
        "hourly_usdc": Decimal("10"),
    }
    values.update(updates)
    return AuthorizationForm(**values)


def grant(**updates: object) -> SpendingGrant:
    values: dict[str, object] = {
        "spending_grant_id": "spending_grant_1",
        "wallet_identity_id": "wallet_identity_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "status": "active",
        "max_amount_usdc": Decimal("100"),
        "per_transaction_limit_usdc": Decimal("3"),
        "hourly_limit_usdc": Decimal("3"),
        "daily_limit_usdc": Decimal("50"),
        "used_amount_usdc": Decimal("40"),
        "reserved_amount_usdc": Decimal("5"),
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": [],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:137"],
        "asset_scopes": [TOKEN],
        "starts_at": NOW - timedelta(days=10),
        "expires_at": NOW + timedelta(days=20),
        "created_at": NOW - timedelta(days=10),
        "updated_at": NOW,
    }
    values.update(updates)
    return SpendingGrant(**values)


def test_new_form_builds_marketplace_only_terms_with_utc_expiry() -> None:
    result = authorization_terms(
        form(total_usdc=Decimal("100"), hourly_usdc=Decimal("10"), duration_days=30),
        identity=identity(),
        current=None,
        token_address=TOKEN.upper(),
        at=NOW,
    )

    assert result["action"] == "sign"
    terms = result["terms"]
    assert terms == {
        "wallet_identity_id": "wallet_identity_1",
        "agent_id": "hermes",
        "max_amount_usdc": "100",
        "per_transaction_limit_usdc": "10",
        "hourly_limit_usdc": "10",
        "daily_limit_usdc": "100",
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": [],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:137"],
        "asset_scopes": [TOKEN],
        "starts_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
    }
    assert "user_id" not in terms
    assert "session_id" not in terms
    assert "signed_message" not in terms
    assert "signature" not in terms
    assert "opc_installation" not in terms


@pytest.mark.parametrize(
    "updates",
    [
        {"duration_days": 0},
        {"duration_days": 366},
        {"total_usdc": Decimal("1.0000001")},
        {"total_usdc": Decimal("NaN")},
        {"total_usdc": Decimal("Infinity")},
        {"hourly_usdc": Decimal("0")},
    ],
)
def test_form_rejects_malformed_amounts_or_duration(updates: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        form(**updates)


@pytest.mark.parametrize("value", [100, 1.25, True, False])
def test_form_rejects_non_decimal_string_amounts(value: object) -> None:
    with pytest.raises((ValidationError, ValueError)):
        form(total_usdc=value)


def test_form_forbids_untrusted_policy_fields() -> None:
    with pytest.raises(ValidationError):
        form(user_id="attacker", product_scopes=["prediction_markets"])


@pytest.mark.parametrize(
    "identity_updates, form_updates",
    [
        ({"status": "suspended"}, {}),
        ({"wallet_identity_id": "wallet_identity_2"}, {}),
    ],
)
def test_new_terms_require_active_selected_identity(
    identity_updates: dict[str, object], form_updates: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        authorization_terms(
            form(**form_updates),
            identity=identity(**identity_updates),
            current=None,
            token_address=TOKEN,
            at=NOW,
        )


def test_amendment_retains_scope_and_dates_clamps_old_limits_and_keeps_id() -> None:
    current = grant()
    result = authorization_terms(
        form(
            spending_grant_id=current.spending_grant_id,
            total_usdc=Decimal("120"),
            hourly_usdc=Decimal("10"),
            duration_days=None,
            network="eip155:137",
        ),
        identity=identity(),
        current=current,
        token_address=TOKEN,
        at=NOW,
    )

    assert result["action"] == "sign"
    assert result["terms"]["amends_spending_grant_id"] == current.spending_grant_id
    assert result["terms"]["max_amount_usdc"] == "120"
    assert result["terms"]["per_transaction_limit_usdc"] == "3"
    assert result["terms"]["hourly_limit_usdc"] == "10"
    assert result["terms"]["daily_limit_usdc"] == "50"
    assert result["terms"]["product_scopes"] == current.product_scopes
    assert result["terms"]["venue_scopes"] == current.venue_scopes
    assert result["terms"]["network_scopes"] == current.network_scopes
    assert result["terms"]["asset_scopes"] == current.asset_scopes
    assert result["terms"]["starts_at"] == current.starts_at.isoformat().replace("+00:00", "Z")
    assert result["terms"]["expires_at"] == current.expires_at.isoformat().replace("+00:00", "Z")


def test_unchanged_amendment_is_a_noop() -> None:
    current = grant(max_amount_usdc=Decimal("120"), daily_limit_usdc=Decimal("50"))
    result = authorization_terms(
        form(
            spending_grant_id=current.spending_grant_id,
            total_usdc=current.max_amount_usdc,
            hourly_usdc=current.hourly_limit_usdc,
            duration_days=None,
        ),
        identity=identity(),
        current=current,
        token_address=TOKEN,
        at=NOW,
    )

    assert result["action"] == "none"


def test_amendment_rejects_duration_and_budget_below_used_or_reserved() -> None:
    current = grant()
    with pytest.raises(ValueError, match="duration"):
        authorization_terms(
            form(spending_grant_id=current.spending_grant_id, duration_days=1),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )
    with pytest.raises(ValueError, match="used|reserved"):
        authorization_terms(
            form(
                spending_grant_id=current.spending_grant_id,
                total_usdc=Decimal("44"),
                hourly_usdc=Decimal("10"),
                duration_days=None,
            ),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )


def test_amendment_rejects_hour_above_resulting_daily_limit() -> None:
    current = grant(daily_limit_usdc=Decimal("5"), hourly_limit_usdc=Decimal("5"))
    with pytest.raises(ValueError, match="hourly|daily"):
        authorization_terms(
            form(
                spending_grant_id=current.spending_grant_id,
                total_usdc=Decimal("100"),
                hourly_usdc=Decimal("10"),
                duration_days=None,
            ),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )


@pytest.mark.parametrize("at", [datetime(2026, 9, 10, 12, 0), None])
def test_new_terms_require_timezone_aware_server_time(at: datetime | None) -> None:
    with pytest.raises((ValueError, TypeError)):
        authorization_terms(
            form(duration_days=1),
            identity=identity(),
            current=None,
            token_address=TOKEN,
            at=at,  # type: ignore[arg-type]
        )


def test_existing_grant_requires_matching_current_and_form_id() -> None:
    current = grant()
    with pytest.raises(ValueError):
        authorization_terms(
            form(),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )
    with pytest.raises(ValueError):
        authorization_terms(
            form(spending_grant_id="spending_grant_other"),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )
    with pytest.raises(ValueError):
        authorization_terms(
            form(spending_grant_id=current.spending_grant_id),
            identity=identity(),
            current=None,
            token_address=TOKEN,
            at=NOW,
        )


@pytest.mark.parametrize(
    "grant_updates, form_updates, token",
    [
        ({}, {"network": "eip155:8453"}, TOKEN),
        ({}, {}, OTHER_TOKEN),
        ({"agent_id": "other-agent"}, {}, TOKEN),
    ],
)
def test_existing_form_binds_current_network_asset_and_agent(
    grant_updates: dict[str, object],
    form_updates: dict[str, object],
    token: str,
) -> None:
    current = grant(**grant_updates)
    with pytest.raises(ValueError):
        authorization_terms(
            form(
                spending_grant_id=current.spending_grant_id,
                duration_days=None,
                **form_updates,
            ),
            identity=identity(),
            current=current,
            token_address=token,
            at=NOW,
        )


@pytest.mark.parametrize("status", ["paused", "revoked", "expired", "exhausted", "pending"])
def test_existing_form_only_amends_active_grants(status: str) -> None:
    with pytest.raises(ValueError, match="active"):
        authorization_terms(
            form(spending_grant_id="spending_grant_1", duration_days=None),
            identity=identity(),
            current=grant(status=status),
            token_address=TOKEN,
            at=NOW,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "total": Decimal("100"),
                "used": Decimal("-1"),
                "per_transaction": Decimal("10"),
                "observed_atomic": 0,
            },
            "used",
        ),
        (
            {
                "total": Decimal("100"),
                "used": Decimal("101"),
                "per_transaction": Decimal("10"),
                "observed_atomic": 0,
            },
            "used",
        ),
        (
            {
                "total": Decimal("1.0000001"),
                "used": Decimal("0"),
                "per_transaction": Decimal("1"),
                "observed_atomic": 0,
            },
            "decimal",
        ),
        (
            {
                "total": Decimal("100"),
                "used": Decimal("0"),
                "per_transaction": Decimal("10"),
                "observed_atomic": True,
            },
            "atomic",
        ),
        (
            {
                "total": Decimal("100"),
                "used": Decimal("0"),
                "per_transaction": Decimal("10"),
                "observed_atomic": 2**256,
            },
            "atomic",
        ),
    ],
)
def test_allowance_advice_rejects_invalid_inputs(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        allowance_advice(**kwargs)  # type: ignore[arg-type]


def test_allowance_advice_uses_unspent_budget_and_reports_sufficiency() -> None:
    result = allowance_advice(
        total=Decimal("100"),
        used=Decimal("40"),
        per_transaction=Decimal("10"),
        observed_atomic=60_000_000,
    )

    assert result == {
        "status": "sufficient",
        "required_usdc": "10",
        "target_usdc": "60",
        "target_atomic": "60000000",
        "observed_atomic": "60000000",
        "exceeds_budget": False,
    }


def test_allowance_advice_distinguishes_unknown_insufficient_and_excess() -> None:
    unknown = allowance_advice(
        total=Decimal("100"),
        used=Decimal("40"),
        per_transaction=Decimal("10"),
        observed_atomic=None,
    )
    insufficient = allowance_advice(
        total=Decimal("100"),
        used=Decimal("40"),
        per_transaction=Decimal("10"),
        observed_atomic=9_999_999,
    )
    excessive = allowance_advice(
        total=Decimal("100"),
        used=Decimal("40"),
        per_transaction=Decimal("10"),
        observed_atomic=2**256 - 1,
    )

    assert unknown["status"] == "unknown"
    assert unknown["observed_atomic"] is None
    assert unknown["exceeds_budget"] is None
    assert insufficient["status"] == "insufficient"
    assert insufficient["exceeds_budget"] is False
    assert excessive["status"] == "sufficient"
    assert excessive["exceeds_budget"] is True


def test_allowance_advice_exhausted_budget_is_not_unknown_and_cannot_approve() -> None:
    result = allowance_advice(
        total=Decimal("100"),
        used=Decimal("100"),
        per_transaction=Decimal("10"),
        observed_atomic=None,
    )

    assert result == {
        "status": "exhausted",
        "required_usdc": "0",
        "target_usdc": "0",
        "target_atomic": "0",
        "observed_atomic": None,
        "exceeds_budget": None,
    }


def test_allowance_advice_formats_decimal_amounts_without_float_or_scientific_notation() -> None:
    result = allowance_advice(
        total=Decimal("100.500000"),
        used=Decimal("0.500000"),
        per_transaction=Decimal("0.100000"),
        observed_atomic=100_000,
    )

    assert result["required_usdc"] == "0.1"
    assert result["target_usdc"] == "100"
    assert result["target_atomic"] == "100000000"


@pytest.mark.parametrize("amount", [Decimal("1e72"), Decimal("1e100")])
def test_allowance_advice_rejects_amounts_beyond_usdc_precision_and_uint256(
    amount: Decimal,
) -> None:
    with pytest.raises(ValueError):
        allowance_advice(
            total=amount,
            used=Decimal("0"),
            per_transaction=Decimal("1"),
            observed_atomic=None,
        )


def test_allowance_advice_accepts_maximum_legal_38_digit_usdc_amount() -> None:
    maximum = Decimal("9" * 32 + ".999999")
    result = allowance_advice(
        total=maximum,
        used=Decimal("0"),
        per_transaction=Decimal("1"),
        observed_atomic=None,
    )

    assert result["status"] == "unknown"
    assert result["target_usdc"] == "9" * 32 + ".999999"
    assert result["target_atomic"] == ("9" * 32) + "999999"
