from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select

from scripts.legacy_reauthorization_report import build_reauthorization_report
from services.account_service.repository import (
    AccountRepository,
    SpendingGrantRow,
    WalletIdentityRow,
)
from services.account_service.schemas import SpendingGrant, WalletIdentity
from services.funding_service.schemas import SpendingAuthorization


NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def legacy_authorization(
    authorization_id: str, user_id: str, product: str = "prediction_markets"
) -> dict:
    marketplace = product == "marketplace"
    return SpendingAuthorization(
        spending_authorization_id=authorization_id,
        user_id=user_id,
        agent_id="hermes",
        wallet_address="0x" + "11" * 20,
        max_amount_usdc="10",
        per_order_limit_usdc="5",
        used_amount_usdc="0",
        remaining_amount_usdc="10",
        venue="clink_marketplace" if marketplace else "polymarket",
        chain="eip155:8453" if marketplace else "eip155:137",
        token="USDC",
        spender_address="0x" + "22" * 20,
        purpose="marketplace" if marketplace else "prediction_market_spending_cap",
        status="active",
        expires_at="2099-01-01T00:00:00Z",
        created_at="2026-07-01T00:00:00Z",
    ).model_dump(mode="json")


def test_legacy_records_are_labeled_and_report_never_synthesizes_grants(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_1",
            user_id="already_reauthorized",
            wallet_address="0x" + "33" * 20,
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
            user_id="already_reauthorized",
            agent_id="hermes",
            status="active",
            max_amount_usdc=Decimal("10"),
            per_transaction_limit_usdc=Decimal("5"),
            daily_limit_usdc=Decimal("10"),
            product_scopes=["prediction_markets"],
            network_scopes=["eip155:137"],
            asset_scopes=["0x" + "44" * 20],
            starts_at=NOW,
            expires_at=NOW.replace(year=2027),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    records = tmp_path / "funding.jsonl"
    rows = [
        legacy_authorization("legacy_1", "needs_reauthorization"),
        legacy_authorization("legacy_2", "needs_reauthorization"),
        legacy_authorization("legacy_3", "already_reauthorized"),
    ]
    records.write_text(
        "".join(
            json.dumps(
                {
                    "record_type": "spending_authorization",
                    "record_id": row["spending_authorization_id"],
                    "payload": row,
                }
            )
            + "\n"
            for row in rows
        )
    )
    records_before = records.read_bytes()
    tables_before = set(inspect(repository.engine).get_table_names())
    with repository.sessions() as session:
        identities_before = len(session.scalars(select(WalletIdentityRow)).all())
        grants_before = len(session.scalars(select(SpendingGrantRow)).all())

    report = build_reauthorization_report(
        database_url=database_url,
        funding_records_path=records,
        now=NOW,
    )

    legacy = SpendingAuthorization(**rows[0])
    assert legacy.legacy is True
    with pytest.raises(ValidationError, match="frozen"):
        legacy.status = "revoked"
    assert report == {
        "generated_at": "2026-07-15T12:00:00Z",
        "legacy": True,
        "users_requiring_reauthorization": [
            {
                "user_id": "needs_reauthorization",
                "legacy_spending_authorization_ids": ["legacy_1", "legacy_2"],
                "products": ["prediction_markets"],
                "reason": "legacy_authorization_not_promoted",
            }
        ],
        "user_count": 1,
    }
    assert records.read_bytes() == records_before
    assert set(inspect(repository.engine).get_table_names()) == tables_before
    with repository.sessions() as session:
        assert len(session.scalars(select(WalletIdentityRow)).all()) == identities_before
        assert len(session.scalars(select(SpendingGrantRow)).all()) == grants_before


@pytest.mark.parametrize(
    ("covered_product", "uncovered_product", "uncovered_id"),
    [
        ("prediction_markets", "marketplace", "legacy_marketplace"),
        ("marketplace", "prediction_markets", "legacy_prediction"),
    ],
)
def test_report_lists_only_products_not_covered_by_active_grants(
    tmp_path, covered_product, uncovered_product, uncovered_id
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    repository = AccountRepository(database_url)
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_product_scope",
            user_id="partial_user",
            wallet_address="0x" + "55" * 20,
            status="active",
            proof_hash="0xproof",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.save_spending_grant(
        SpendingGrant(
            spending_grant_id="grant_product_scope",
            wallet_identity_id="wallet_product_scope",
            user_id="partial_user",
            agent_id="hermes",
            status="active",
            max_amount_usdc=Decimal("10"),
            per_transaction_limit_usdc=Decimal("5"),
            daily_limit_usdc=Decimal("10"),
            product_scopes=[covered_product],
            network_scopes=["eip155:137", "eip155:8453"],
            asset_scopes=["0x" + "66" * 20],
            starts_at=NOW,
            expires_at=NOW.replace(year=2027),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    records = tmp_path / "funding.jsonl"
    rows = [
        legacy_authorization("legacy_prediction", "partial_user", "prediction_markets"),
        legacy_authorization("legacy_marketplace", "partial_user", "marketplace"),
    ]
    records.write_text(
        "".join(
            json.dumps(
                {
                    "record_type": "spending_authorization",
                    "record_id": row["spending_authorization_id"],
                    "payload": row,
                }
            )
            + "\n"
            for row in rows
        )
    )

    report = build_reauthorization_report(
        database_url=database_url, funding_records_path=records, now=NOW
    )

    assert report["users_requiring_reauthorization"] == [
        {
            "user_id": "partial_user",
            "legacy_spending_authorization_ids": [uncovered_id],
            "products": [uncovered_product],
            "reason": "legacy_authorization_not_promoted",
        }
    ]
