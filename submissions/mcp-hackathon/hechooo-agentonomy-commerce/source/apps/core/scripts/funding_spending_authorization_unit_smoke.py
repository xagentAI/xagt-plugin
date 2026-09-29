from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.funding_service.schemas import (  # noqa: E402
    CreateSpendingAuthorizationRequest,
    SpendFromSpendingAuthorizationRequest,
    SpendingAuthorization,
)
from services.funding_service.service import FundingService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


READ_ONLY_ERROR = "legacy spending authorizations are read-only"


def assert_read_only(operation) -> None:
    try:
        operation()
    except ValueError as exc:
        assert str(exc) == READ_ONLY_ERROR
    else:
        raise AssertionError("legacy mutation unexpectedly succeeded")


def main() -> None:
    with TemporaryDirectory(prefix="clink-legacy-read-only-") as temporary_dir:
        root = Path(temporary_dir)
        storage_file = root / "funding.jsonl"
        authorization = SpendingAuthorization(
            spending_authorization_id="legacy_smoke_authorization",
            user_id="spending-user",
            agent_id="hermes_agent",
            wallet_address="0x" + "11" * 20,
            max_amount_usdc="5",
            per_order_limit_usdc="1",
            used_amount_usdc="0",
            remaining_amount_usdc="5",
            venue="polymarket",
            chain="eip155:137",
            token="USDC",
            spender_address="0x" + "22" * 20,
            purpose="prediction_market_spending_cap",
            status="active",
            expires_at="2099-01-01T00:00:00Z",
            created_at="2026-07-01T00:00:00Z",
        )
        storage_file.write_text(
            json.dumps(
                {
                    "record_type": "spending_authorization",
                    "record_id": authorization.spending_authorization_id,
                    "payload": authorization.model_dump(mode="json"),
                }
            )
            + "\n"
        )
        service = FundingService(
            config=AppConfig(
                funding_database_url=f"sqlite+pysqlite:///{root / 'core.sqlite3'}"
            ),
            storage_file=storage_file,
        )

        assert_read_only(
            lambda: service.create_spending_authorization(
                CreateSpendingAuthorizationRequest(
                    user_id="spending-user",
                    agent_id="hermes_agent",
                    wallet_address="0x" + "11" * 20,
                    max_amount_usdc="5",
                    per_order_limit_usdc="1",
                    spender_address="0x" + "22" * 20,
                )
            )
        )
        assert_read_only(
            lambda: service.spend_from_spending_authorization(
                SpendFromSpendingAuthorizationRequest(
                    spending_authorization_id=authorization.spending_authorization_id,
                    amount_usdc="1",
                    destination="0x" + "33" * 20,
                )
            )
        )
        assert_read_only(
            lambda: service.revoke_spending_authorization(
                authorization.spending_authorization_id
            )
        )
        status = service.get_funding_status(user_id="spending-user")
        assert status.spending_authorizations == [authorization]

    print(json.dumps({"status": "ok", "legacy": True, "read_only": True}))


if __name__ == "__main__":
    main()
