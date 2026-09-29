from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from services.account_service.repository import (
    AccountRepository,
    SpendingGrantDailyUsageRow,
)
from services.account_service.schemas import (
    AssetAllowance,
    AuthorizationResolutionRequest,
    SpendingGrant,
    WalletIdentity,
)
from services.account_service.service import AccountService


NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
TOKEN = "0x" + "1" * 40
BASE_TOKEN = "0x" + "4" * 40
SPENDER = "0x" + "2" * 40
DESTINATION = "0x" + "3" * 40


def identity(**updates) -> WalletIdentity:
    values = {
        "wallet_identity_id": "wallet_identity_b",
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


def grant(**updates) -> SpendingGrant:
    values = {
        "spending_grant_id": "spending_grant_b",
        "wallet_identity_id": "wallet_identity_b",
        "user_id": "user_1",
        "agent_id": "hermes",
        "status": "active",
        "max_amount_usdc": Decimal("10"),
        "per_transaction_limit_usdc": Decimal("4"),
        "hourly_limit_usdc": Decimal("4"),
        "daily_limit_usdc": Decimal("5"),
        "used_amount_usdc": Decimal("1"),
        "reserved_amount_usdc": Decimal("1"),
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": ["merchant_1"],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:137"],
        "asset_scopes": [TOKEN],
        "starts_at": datetime(2026, 7, 1, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 1, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SpendingGrant(**values)


def allowance(**updates) -> AssetAllowance:
    values = {
        "asset_allowance_id": "asset_allowance_b",
        "wallet_identity_id": "wallet_identity_b",
        "network": "eip155:137",
        "token_address": TOKEN,
        "token_symbol": "USDC",
        "token_decimals": 6,
        "spender_address": SPENDER,
        "approved_amount_atomic": 10_000_000,
        "observed_allowance_atomic": 10_000_000,
        "status": "active",
        "confirmed_block": 10,
        "last_chain_check_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return AssetAllowance(**values)


def request(**updates) -> AuthorizationResolutionRequest:
    values = {
        "user_id": "user_1",
        "agent_id": "hermes",
        "product": "marketplace",
        "venue": "clink_marketplace",
        "merchant": "merchant_1",
        "merchant_trust_tier": "registry_verified",
        "network": "eip155:137",
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "amount_usdc": Decimal("2"),
        "destination": DESTINATION,
        "resource": "https://merchant.example/api",
    }
    values.update(updates)
    return AuthorizationResolutionRequest(**values)


def network_configs():
    return {
        "eip155:137": {
            "chain_id": 137,
            "required_confirmations": 3,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": TOKEN,
        },
        "eip155:8453": {
            "chain_id": 8453,
            "required_confirmations": 2,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": BASE_TOKEN,
        },
    }


@pytest.fixture
def context(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs=network_configs(),
    )
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    repository.save_asset_allowance(allowance())
    return repository, service


def test_resolution_is_readiness_not_approval(context):
    _, service = context

    result = service.resolve_authorization(request())

    assert result.ready is True
    assert not hasattr(result, "approved")
    assert result.wallet_identity_id == "wallet_identity_b"
    assert result.spending_grant_id == "spending_grant_b"
    assert result.asset_allowance_id == "asset_allowance_b"
    assert result.remaining_amount_usdc == Decimal("8")
    assert result.remaining_daily_amount_usdc == Decimal("5")
    assert result.remaining_hourly_amount_usdc == Decimal("4")
    assert result.notification_mode == "silent_under_limits"
    assert result.user_interaction_required is False
    assert result.required_amount_atomic == 2_000_000
    assert result.observed_allowance_atomic == 10_000_000
    assert result.next_action == "create_action_and_evaluate_policy"


def test_external_x402_resolution_uses_grant_without_asset_allowance(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'external.sqlite3'}")
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(grant())
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs=network_configs(),
    )

    result = service.resolve_authorization(
        request(
            authorization_rail="external_x402",
            spender_address=None,
        )
    )

    assert result.ready is True
    assert result.wallet_identity_id == "wallet_identity_b"
    assert result.spending_grant_id == "spending_grant_b"
    assert result.asset_allowance_id is None
    assert result.required_amount_atomic is None
    assert result.observed_allowance_atomic is None
    assert result.user_interaction_required is True
    assert result.interaction_reason_code == "EXTERNAL_X402_SIGNATURE_REQUIRED"


def test_resolution_rejects_untrusted_merchant_tier(context):
    repository, service = context
    repository.save_spending_grant(
        grant(merchant_trust_scopes=["clink_verified"])
    )

    result = service.resolve_authorization(request())

    assert result.ready is False
    assert result.reason_code == "MERCHANT_TRUST_SCOPE_MISMATCH"


def test_marketplace_resolution_rejects_missing_merchant_trust_tier(context):
    _, service = context

    result = service.resolve_authorization(request(merchant_trust_tier=None))

    assert result.ready is False
    assert result.reason_code == "MERCHANT_TRUST_SCOPE_MISMATCH"


def test_prediction_markets_resolution_allows_missing_merchant_trust_tier(context):
    repository, service = context
    repository.save_spending_grant(
        grant(
            product_scopes=["prediction_markets"],
            venue_scopes=["polymarket"],
        )
    )

    result = service.resolve_authorization(
        request(
            product="prediction_markets",
            venue="polymarket",
            merchant_trust_tier=None,
        )
    )

    assert result.ready is True
    assert result.spending_grant_id == "spending_grant_b"


def test_external_x402_resolution_rejects_symbol_only_input():
    with pytest.raises(
        ValidationError, match="external x402 resolution requires token_address"
    ):
        request(
            authorization_rail="external_x402",
            token_address=None,
            asset="USDC",
            spender_address=None,
        )


def test_external_x402_resolution_matches_network_and_token_as_one_scope(tmp_path):
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'network-token.sqlite3'}"
    )
    repository.save_wallet_identity(identity())
    repository.save_spending_grant(
        grant(
            network_scopes=["eip155:137", "eip155:8453"],
            asset_scopes=[TOKEN, BASE_TOKEN],
        )
    )
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs=network_configs(),
    )

    cross_network = service.resolve_authorization(
        request(
            authorization_rail="external_x402",
            network="eip155:8453",
            token_address=TOKEN,
            spender_address=None,
        )
    )
    wrong_polygon_token = service.resolve_authorization(
        request(
            authorization_rail="external_x402",
            token_address="0x" + "9" * 40,
            spender_address=None,
        )
    )
    canonical_base = service.resolve_authorization(
        request(
            authorization_rail="external_x402",
            network="eip155:8453",
            token_address=BASE_TOKEN,
            spender_address=None,
        )
    )

    assert cross_network.ready is False
    assert cross_network.reason_code == "ASSET_SCOPE_MISMATCH"
    assert wrong_polygon_token.ready is False
    assert wrong_polygon_token.reason_code == "ASSET_SCOPE_MISMATCH"
    assert canonical_base.ready is True


def test_resolution_selection_is_deterministic_by_immutable_ids(context):
    repository, service = context
    repository.save_spending_grant(
        grant(
            spending_grant_id="spending_grant_a",
            created_at=NOW.replace(day=16),
            updated_at=NOW.replace(day=16),
        )
    )
    result = service.resolve_authorization(request())

    assert result.spending_grant_id == "spending_grant_a"
    assert result.asset_allowance_id == "asset_allowance_b"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda repo: repo.save_wallet_identity(identity(status="suspended")), "WALLET_IDENTITY_REQUIRED"),
        (lambda repo: repo.save_spending_grant(grant(status="paused")), "SPENDING_GRANT_REQUIRED"),
        (lambda repo: repo.save_asset_allowance(allowance(status="stale")), "ASSET_ALLOWANCE_REQUIRED"),
    ],
)
def test_resolution_requires_active_identity_grant_and_allowance(context, mutate, expected):
    repository, service = context
    mutate(repository)

    result = service.resolve_authorization(request())

    assert result.ready is False
    assert result.reason_code == expected


@pytest.mark.parametrize(
    ("grant_update", "request_update", "expected"),
    [
        ({"product_scopes": ["prediction_markets"]}, {}, "PRODUCT_SCOPE_MISMATCH"),
        ({"venue_scopes": ["polymarket"]}, {}, "VENUE_SCOPE_MISMATCH"),
        ({"merchant_scopes": ["merchant_2"]}, {}, "MERCHANT_SCOPE_MISMATCH"),
        ({"network_scopes": ["eip155:8453"]}, {}, "NETWORK_SCOPE_MISMATCH"),
        ({"asset_scopes": ["0x" + "9" * 40]}, {}, "ASSET_SCOPE_MISMATCH"),
        ({}, {"amount_usdc": Decimal("4.5")}, "PER_TRANSACTION_LIMIT_EXCEEDED"),
        (
            {"used_amount_usdc": Decimal("9"), "reserved_amount_usdc": Decimal("0")},
            {"amount_usdc": Decimal("2")},
            "BUDGET_EXCEEDED",
        ),
    ],
)
def test_resolution_reports_exact_scope_and_budget_reason(
    context, grant_update, request_update, expected
):
    repository, service = context
    repository.save_spending_grant(grant(**grant_update))

    result = service.resolve_authorization(request(**request_update))

    assert result.ready is False
    assert result.reason_code == expected


def test_resolution_enforces_utc_daily_usage(context):
    repository, service = context
    with repository.sessions.begin() as session:
        session.add(
            SpendingGrantDailyUsageRow(
                spending_grant_daily_usage_id="daily_1",
                spending_grant_id="spending_grant_b",
                usage_date=date(2026, 7, 15),
                used_amount_usdc=Decimal("3"),
                reserved_amount_usdc=Decimal("1"),
                created_at=NOW,
                updated_at=NOW,
            )
        )

    result = service.resolve_authorization(request())

    assert result.ready is False
    assert result.reason_code == "DAILY_LIMIT_EXCEEDED"


def test_resolution_rejects_partial_active_allowance_below_exact_requested_amount(context):
    repository, service = context
    repository.save_asset_allowance(allowance(observed_allowance_atomic=1_999_999))

    result = service.resolve_authorization(request())

    assert repository.asset_allowance("asset_allowance_b").status == "active"
    assert result.ready is False
    assert result.reason_code == "ASSET_ALLOWANCE_REQUIRED"


def test_symbol_asset_still_reports_grant_asset_scope_mismatch(context):
    repository, service = context
    repository.save_spending_grant(grant(asset_scopes=["0x" + "9" * 40]))

    result = service.resolve_authorization(
        request(token_address=None, asset="USDC")
    )

    assert result.ready is False
    assert result.reason_code == "ASSET_SCOPE_MISMATCH"


def test_resolution_rejects_legacy_grant_id_input():
    with pytest.raises(Exception):
        AuthorizationResolutionRequest(
            **request().model_dump(), spending_authorization_id="legacy_auth"
        )
