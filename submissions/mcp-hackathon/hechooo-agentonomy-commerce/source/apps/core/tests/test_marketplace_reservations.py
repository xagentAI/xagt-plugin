from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    ReleaseSpendingReservationRequest,
)
from services.funding_service.service import FundingService, ReservationProvenance
from shared.config import AppConfig


NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
PROVENANCE = ReservationProvenance(
    action=SimpleNamespace(user_id="u", agent_id="a"),
    authorization_path="unified_grant",
    product="marketplace",
    unified_references={
        "product": "marketplace",
        "wallet_identity_id": "wallet_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
    },
)


def request(purchase="purchase_1", key="key_1", amount="3"):
    return CreateSpendingReservationRequest(
        purchase_id=purchase,
        idempotency_key=key,
        wallet_identity_id="wallet_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1",
        product="marketplace",
        action_id="action_1" + purchase,
        policy_decision_id="policy_1" + purchase,
        merchant_id="merchant",
        quote_hash="0x" + "a" * 64,
        amount_usdc=amount,
        amount_atomic=str(int(Decimal(amount) * 1_000_000)),
        network="eip155:137",
        asset="USDC",
        merchant_trust_tier="clink_verified",
        destination="0x" + "3" * 40,
        resource="https://merchant.example/api",
        venue="clink_marketplace",
    )


def service_with_unified_grant(root: Path) -> FundingService:
    database_url = f"sqlite+pysqlite:///{root / 'ledger.db'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_1",
            user_id="u",
            wallet_address="0x" + "4" * 40,
            status="active",
            proof_hash="0xproof",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_spending_grant(
        SpendingGrant(
            spending_grant_id="grant_1",
            wallet_identity_id="wallet_1",
            user_id="u",
            agent_id="a",
            status="active",
            max_amount_usdc=Decimal("10"),
            per_transaction_limit_usdc=Decimal("5"),
            daily_limit_usdc=Decimal("10"),
            product_scopes=["marketplace"],
            venue_scopes=["clink_marketplace"],
            merchant_scopes=["merchant"],
            network_scopes=["eip155:137"],
            asset_scopes=[TOKEN],
            starts_at=datetime(2026, 7, 1, tzinfo=UTC),
            expires_at=datetime(2026, 8, 1, tzinfo=UTC),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_asset_allowance(
        AssetAllowance(
            asset_allowance_id="allowance_1",
            wallet_identity_id="wallet_1",
            network="eip155:137",
            token_address=TOKEN,
            token_symbol="USDC",
            token_decimals=6,
            spender_address="0x" + "2" * 40,
            approved_amount_atomic=10_000_000,
            observed_allowance_atomic=10_000_000,
            status="active",
            confirmed_block=1,
            last_chain_check_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    service = FundingService(
        config=AppConfig(funding_database_url=database_url),
        storage_file=root / "records.jsonl",
    )
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    return service


def reserve(service: FundingService, reservation_request):
    with patch.object(
        service, "_verify_marketplace_provenance", return_value=PROVENANCE
    ):
        return service.reserve_spending(reservation_request)


def test_reservation_is_idempotent_and_holds_budget_atomically():
    with TemporaryDirectory() as directory:
        service = service_with_unified_grant(Path(directory))
        first = reserve(service, request())
        assert reserve(service, request()) == first
        reserve(service, request("purchase_2", "key_2", "5"))
        with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
            reserve(service, request("purchase_3", "key_3", "3"))


def test_submitted_reservation_cannot_be_released():
    with TemporaryDirectory() as directory:
        service = service_with_unified_grant(Path(directory))
        row = reserve(service, request())
        with service.ledger.transaction() as tx:
            submitted = {**row, "state": "payment_submitted"}
            tx.put(
                "reservation",
                row["reservation_id"],
                submitted,
                purchase_id=row["purchase_id"],
                idempotency_key=row["idempotency_key"],
                action_id=row["action_id"],
                policy_decision_id=row["policy_decision_id"],
                reservation_id=row["reservation_id"],
            )

        with pytest.raises(ValueError, match="cannot be released"):
            service.release_reservation(
                row["reservation_id"],
                ReleaseSpendingReservationRequest(reason="retry"),
            )
