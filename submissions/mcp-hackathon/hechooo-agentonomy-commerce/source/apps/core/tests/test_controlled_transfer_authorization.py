from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import ValidationError

from services.account_service.authorization import AuthorizationForm, authorization_terms
from services.account_service.opc_console import OPC_SETUP_HTML, OPC_SETUP_JS
from services.account_service.opc_service import OpcInstallationRow
from services.account_service.repository import AccountRepository
from services.account_service.schemas import (
    AuthorizationResolutionRequest,
    SpendingGrant,
    SpendingGrantRequest,
    WalletIdentity,
)
from services.account_service.service import AccountService


NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
TOKEN = "0x" + "1" * 40
TRANSFER_DESTINATION = "0x" + "3" * 40


def identity(**updates: object) -> WalletIdentity:
    values: dict[str, object] = {
        "wallet_identity_id": "wallet_identity_transfer",
        "user_id": "transfer-user",
        "wallet_address": "0x" + "a" * 40,
        "status": "active",
        "proof_hash": "0xproof",
        "verified_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return WalletIdentity(**values)


def current_grant(**updates: object) -> SpendingGrant:
    values: dict[str, object] = {
        "spending_grant_id": "spending_grant_transfer",
        "wallet_identity_id": "wallet_identity_transfer",
        "user_id": "transfer-user",
        "agent_id": "hermes",
        "status": "active",
        "max_amount_usdc": Decimal("100"),
        "per_transaction_limit_usdc": Decimal("10"),
        "hourly_limit_usdc": Decimal("25"),
        "daily_limit_usdc": Decimal("75"),
        "used_amount_usdc": Decimal("20"),
        "reserved_amount_usdc": Decimal("5"),
        "product_scopes": ["marketplace", "prediction_markets"],
        "venue_scopes": ["clink_marketplace", "legacy_venue", "polymarket"],
        "merchant_scopes": ["merchant-a"],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:8453"],
        "asset_scopes": [TOKEN],
        "starts_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=10),
        "created_at": NOW - timedelta(days=1),
        "updated_at": NOW,
    }
    values.update(updates)
    return SpendingGrant(**values)


def form(**updates: object) -> AuthorizationForm:
    values: dict[str, object] = {
        "wallet_identity_id": "wallet_identity_transfer",
        "network": "eip155:8453",
        "total_usdc": Decimal("100"),
        "hourly_usdc": Decimal("25"),
    }
    values.update(updates)
    return AuthorizationForm(**values)


def grant_request(identity_item: WalletIdentity, **updates: object) -> SpendingGrantRequest:
    values: dict[str, object] = {
        "user_id": identity_item.user_id,
        "wallet_identity_id": identity_item.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": Decimal("100"),
        "per_transaction_limit_usdc": Decimal("10"),
        "hourly_limit_usdc": Decimal("25"),
        "daily_limit_usdc": Decimal("75"),
        "product_scopes": ["marketplace", "prediction_markets"],
        "venue_scopes": ["clink_marketplace", "polymarket"],
        "merchant_scopes": ["merchant-a"],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:8453"],
        "asset_scopes": [TOKEN],
        "starts_at": NOW,
        "expires_at": NOW + timedelta(days=10),
    }
    values.update(updates)
    return SpendingGrantRequest(**values)


@pytest.mark.parametrize(
    ("products", "expected_products", "expected_venues"),
    [
        (None, ["marketplace"], ["clink_marketplace"]),
        (["marketplace"], ["marketplace"], ["clink_marketplace"]),
        (["transfers"], ["transfers"], ["clink_transfers"]),
        (
            ["transfers", "marketplace"],
            ["marketplace", "transfers"],
            ["clink_marketplace", "clink_transfers"],
        ),
    ],
)
def test_new_form_product_selection_is_explicit_and_paired(
    products: list[str] | None,
    expected_products: list[str],
    expected_venues: list[str],
) -> None:
    selected = form(duration_days=7, **({"products": products} if products is not None else {}))
    result = authorization_terms(
        selected,
        identity=identity(),
        current=None,
        token_address=TOKEN,
        at=NOW,
    )

    assert result["terms"]["product_scopes"] == expected_products
    assert result["terms"]["venue_scopes"] == expected_venues


@pytest.mark.parametrize("products", [[], ["prediction_markets"], ["transfers", "unknown"]])
def test_form_rejects_empty_or_unreviewed_product_selection(products: list[str]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        form(products=products)


@pytest.mark.parametrize(
    ("product_scopes", "venue_scopes"),
    [
        (["transfers"], ["clink_marketplace"]),
        (["marketplace"], ["clink_transfers"]),
    ],
)
def test_signed_grant_requires_transfer_product_and_venue_pair(
    product_scopes: list[str], venue_scopes: list[str]
) -> None:
    repository = AccountRepository("sqlite+pysqlite:///:memory:")
    owner = identity()
    repository.save_wallet_identity(owner)
    service = AccountService(repository, domain="account.example", clock=lambda: NOW)

    with pytest.raises(ValueError, match="clink_transfers"):
        service.create_spending_grant_challenge(
            grant_request(
                owner,
                product_scopes=product_scopes,
                venue_scopes=venue_scopes,
            )
        )


def test_existing_selection_changes_only_reviewed_products_and_venues() -> None:
    result = authorization_terms(
        form(
            spending_grant_id="spending_grant_transfer",
            products=["transfers"],
            duration_days=None,
        ),
        identity=identity(),
        current=current_grant(),
        token_address=TOKEN,
        at=NOW,
    )

    assert result["action"] == "sign"
    assert result["terms"]["product_scopes"] == ["prediction_markets", "transfers"]
    assert result["terms"]["venue_scopes"] == ["clink_transfers", "legacy_venue", "polymarket"]
    assert result["terms"]["merchant_scopes"] == ["merchant-a"]
    assert result["terms"]["network_scopes"] == ["eip155:8453"]
    assert result["terms"]["starts_at"] == current_grant().starts_at.isoformat().replace("+00:00", "Z")
    assert result["terms"]["expires_at"] == current_grant().expires_at.isoformat().replace("+00:00", "Z")


def test_existing_omitted_selection_preserves_all_scopes() -> None:
    current = current_grant()
    result = authorization_terms(
        form(spending_grant_id=current.spending_grant_id, duration_days=None),
        identity=identity(),
        current=current,
        token_address=TOKEN,
        at=NOW,
    )

    assert result["action"] == "none"
    assert result["terms"]["product_scopes"] == current.product_scopes
    assert result["terms"]["venue_scopes"] == current.venue_scopes


def test_existing_selection_rejects_wildcard_venue_scope() -> None:
    current = current_grant(
        product_scopes=["marketplace", "prediction_markets"],
        venue_scopes=[],
    )

    with pytest.raises(ValueError, match="wildcard venue"):
        authorization_terms(
            form(
                spending_grant_id=current.spending_grant_id,
                products=["transfers"],
                duration_days=None,
            ),
            identity=identity(),
            current=current,
            token_address=TOKEN,
            at=NOW,
        )


def _signed(service: AccountService, account, request: SpendingGrantRequest):
    challenge = service.create_spending_grant_challenge(request)
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), account.key
    ).signature.hex()
    return request.model_copy(
        update={
            "session_id": challenge.session_id,
            "signed_message": challenge.message_to_sign,
            "signature": signature,
        }
    ), challenge


def test_same_grant_transfer_amendment_preserves_accounting_and_rejects_stale_scope(
    tmp_path,
) -> None:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'transfer.db'}")
    account = Account.create()
    owner = identity(wallet_address=account.address)
    repository.save_wallet_identity(owner)
    service = AccountService(repository, domain="account.example", clock=lambda: NOW)

    initial_signed, _ = _signed(
        service,
        account,
        grant_request(
            owner,
            product_scopes=["marketplace", "prediction_markets", "transfers"],
            venue_scopes=["clink_marketplace", "clink_transfers", "polymarket"],
        ),
    )
    initial = service.create_spending_grant(initial_signed)
    stale_signed, stale_challenge = _signed(
        service,
        account,
        grant_request(
            owner,
            amends_spending_grant_id=initial.spending_grant_id,
            product_scopes=["marketplace", "prediction_markets", "transfers"],
            venue_scopes=["clink_marketplace", "clink_transfers", "polymarket"],
        ),
    )
    assert "Base Authority Hash:" in stale_challenge.message_to_sign

    removal_signed, _ = _signed(
        service,
        account,
        grant_request(
            owner,
            amends_spending_grant_id=initial.spending_grant_id,
            product_scopes=["marketplace", "prediction_markets"],
            venue_scopes=["clink_marketplace", "polymarket"],
        ),
    )
    removed = service.create_spending_grant(removal_signed)
    assert removed.product_scopes == ["marketplace", "prediction_markets"]
    assert removed.used_amount_usdc == initial.used_amount_usdc
    assert removed.reserved_amount_usdc == initial.reserved_amount_usdc

    with pytest.raises(ValueError, match="authority"):
        service.create_spending_grant(stale_signed)


def test_same_grant_scope_revision_rejects_aba_replay_after_add_then_remove(
    tmp_path,
) -> None:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'aba.db'}")
    account = Account.create()
    owner = identity(wallet_address=account.address)
    repository.save_wallet_identity(owner)
    service = AccountService(repository, domain="account.example", clock=lambda: NOW)

    initial_signed, _ = _signed(
        service,
        account,
        grant_request(
            owner,
            product_scopes=["marketplace"],
            venue_scopes=["clink_marketplace"],
        ),
    )
    initial = service.create_spending_grant(initial_signed)
    add_signed, add_challenge = _signed(
        service,
        account,
        grant_request(
            owner,
            amends_spending_grant_id=initial.spending_grant_id,
            product_scopes=["marketplace", "transfers"],
            venue_scopes=["clink_marketplace", "clink_transfers"],
        ),
    )
    assert "Base Authority Revision:" in add_challenge.message_to_sign

    replacement_signed, _ = _signed(
        service,
        account,
        grant_request(
            owner,
            amends_spending_grant_id=initial.spending_grant_id,
            product_scopes=["marketplace", "transfers"],
            venue_scopes=["clink_marketplace", "clink_transfers"],
        ),
    )
    service.create_spending_grant(replacement_signed)
    remove_signed, _ = _signed(
        service,
        account,
        grant_request(
            owner,
            amends_spending_grant_id=initial.spending_grant_id,
            product_scopes=["marketplace"],
            venue_scopes=["clink_marketplace"],
        ),
    )
    service.create_spending_grant(remove_signed)

    # The authority hash is back to its original value, but the durable
    # amendment revision proves that this signed add challenge predates the
    # intervening add/remove sequence.
    with pytest.raises(ValueError, match="authority"):
        service.create_spending_grant(add_signed)


def test_accounting_only_advance_does_not_invalidate_amendment_cas(tmp_path) -> None:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'accounting.db'}")
    account = Account.create()
    owner = identity(wallet_address=account.address)
    repository.save_wallet_identity(owner)
    service = AccountService(repository, domain="account.example", clock=lambda: NOW)
    initial_signed, _ = _signed(service, account, grant_request(owner))
    initial = service.create_spending_grant(initial_signed)

    amendment = grant_request(
        owner,
        amends_spending_grant_id=initial.spending_grant_id,
        max_amount_usdc=Decimal("120"),
        daily_limit_usdc=Decimal("90"),
    )
    signed, _ = _signed(service, account, amendment)
    repository.save_spending_grant(
        initial.model_copy(
            update={"used_amount_usdc": Decimal("30"), "reserved_amount_usdc": Decimal("7")}
        )
    )

    amended = service.create_spending_grant(signed)
    assert amended.max_amount_usdc == Decimal("120")
    assert amended.used_amount_usdc == Decimal("30")
    assert amended.reserved_amount_usdc == Decimal("7")


def test_transfer_resolution_requires_no_merchant_trust_and_preserves_allowlist(tmp_path) -> None:
    # Importing OpcInstallationRow above registers the table used by the
    # existing atomic grant invalidation path.  Use a file-backed DB so the
    # repository's independent sessions share the same schema.
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'resolution.db'}")
    owner = identity()
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        current_grant(
            product_scopes=["transfers"],
            venue_scopes=["clink_transfers"],
            merchant_scopes=[],
        )
    )
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs={
            "eip155:8453": {
                "chain_id": 8453,
                "required_confirmations": 2,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": TOKEN,
            }
        },
    )
    request = AuthorizationResolutionRequest(
        user_id=owner.user_id,
        agent_id="hermes",
        product="transfers",
        venue="clink_transfers",
        merchant=None,
        merchant_trust_tier=None,
        network="eip155:8453",
        token_address=TOKEN,
        authorization_rail="external_x402",
        amount_usdc=Decimal("2"),
        destination=TRANSFER_DESTINATION,
        resource="transfer://direct",
    )

    result = service.resolve_authorization(request)

    assert result.ready is True
    assert result.spending_grant_id == "spending_grant_transfer"


def test_transfer_resolution_rejects_merchant_trust_labels(tmp_path) -> None:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'trust.db'}")
    owner = identity()
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        current_grant(
            product_scopes=["transfers"],
            venue_scopes=["clink_transfers"],
            merchant_scopes=[],
        )
    )
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs={
            "eip155:8453": {
                "chain_id": 8453,
                "required_confirmations": 2,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": TOKEN,
            }
        },
    )

    request = AuthorizationResolutionRequest(
        user_id=owner.user_id,
        agent_id="hermes",
        product="transfers",
        venue="clink_transfers",
        merchant=None,
        merchant_trust_tier="clink_verified",
        network="eip155:8453",
        token_address=TOKEN,
        authorization_rail="external_x402",
        amount_usdc=Decimal("2"),
        destination=TRANSFER_DESTINATION,
        resource="transfer://direct",
    )

    result = service.resolve_authorization(request)

    assert result.ready is False
    assert result.reason_code == "MERCHANT_TRUST_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    ("product", "venue"),
    [("transfers", "clink_marketplace"), ("marketplace", "clink_transfers")],
)
def test_reviewed_products_require_their_paired_venue(
    tmp_path, product: str, venue: str
) -> None:
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'venue.db'}")
    owner = identity()
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        current_grant(
            product_scopes=["marketplace", "transfers"],
            venue_scopes=["clink_marketplace", "clink_transfers"],
            merchant_scopes=[],
        )
    )
    service = AccountService(
        repository,
        domain="account.example",
        clock=lambda: NOW,
        network_configs={
            "eip155:8453": {
                "chain_id": 8453,
                "required_confirmations": 2,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "token_address": TOKEN,
            }
        },
    )
    request = AuthorizationResolutionRequest(
        user_id=owner.user_id,
        agent_id="hermes",
        product=product,
        venue=venue,
        merchant="merchant-a" if product == "marketplace" else None,
        merchant_trust_tier="clink_verified" if product == "marketplace" else None,
        network="eip155:8453",
        token_address=TOKEN,
        authorization_rail="external_x402",
        amount_usdc=Decimal("2"),
        destination=TRANSFER_DESTINATION,
        resource="transfer://direct" if product == "transfers" else "https://merchant.example/api",
    )

    result = service.resolve_authorization(request)

    assert result.ready is False
    assert result.reason_code == "VENUE_SCOPE_MISMATCH"


def test_opc_setup_exposes_unchecked_transfer_choice_and_exact_scope_guards() -> None:
    assert 'id="opc-setup-marketplace"' in OPC_SETUP_HTML
    assert 'id="opc-setup-transfers"' in OPC_SETUP_HTML
    assert "Direct-address transfers" in OPC_SETUP_HTML
    assert "clink_transfers" in OPC_SETUP_JS
    assert "products" in OPC_SETUP_JS
    assert "opc-setup-transfers" in OPC_SETUP_JS


def test_opc_setup_new_summary_uses_selected_products() -> None:
    assert 'opcSetupSelectedProducts({required: false}).join(", ") || "No product selected"' in OPC_SETUP_JS
