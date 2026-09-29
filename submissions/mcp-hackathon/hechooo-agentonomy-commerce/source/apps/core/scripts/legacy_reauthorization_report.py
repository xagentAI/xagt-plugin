from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, select

from services.account_service.repository import SpendingGrantRow
from services.funding_service.schemas import SpendingAuthorization
from shared.config import AppConfig


def _latest_legacy_authorizations(path: Path) -> list[SpendingAuthorization]:
    latest: dict[str, dict] = {}
    if not path.exists():
        return []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("record_type") != "spending_authorization":
                continue
            latest[record["record_id"]] = record["payload"]
    return [
        SpendingAuthorization.model_validate(payload)
        for payload in latest.values()
    ]


def _legacy_product(authorization: SpendingAuthorization) -> str:
    values = f"{authorization.purpose} {authorization.venue}".lower()
    if "prediction" in values or "polymarket" in values:
        return "prediction_markets"
    if "marketplace" in values:
        return "marketplace"
    return authorization.venue.strip().lower()


def build_reauthorization_report(
    *, database_url: str, funding_records_path: Path, now: datetime
) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("report timestamp must be timezone-aware")
    now = now.astimezone(UTC)
    engine = create_engine(database_url)
    try:
        if "spending_grants" not in inspect(engine).get_table_names():
            raise RuntimeError("Core schema is behind; run migrations before reporting")
        with engine.connect() as connection:
            covered_products_by_user: dict[str, set[str]] = defaultdict(set)
            for user_id, product_scopes in connection.execute(
                    select(
                        SpendingGrantRow.user_id,
                        SpendingGrantRow.product_scopes,
                    ).where(
                        SpendingGrantRow.status.in_(("active", "pending")),
                        SpendingGrantRow.starts_at <= now,
                        SpendingGrantRow.expires_at > now,
                    )
                ):
                covered_products_by_user[user_id].update(product_scopes or [])
    finally:
        engine.dispose()

    by_user: dict[str, list[SpendingAuthorization]] = defaultdict(list)
    for authorization in _latest_legacy_authorizations(funding_records_path):
        expires_at = datetime.fromisoformat(
            authorization.expires_at.replace("Z", "+00:00")
        )
        if (
            authorization.legacy
            and authorization.status == "active"
            and expires_at > now
            and _legacy_product(authorization)
            not in covered_products_by_user[authorization.user_id]
        ):
            by_user[authorization.user_id].append(authorization)

    users = []
    for user_id, authorizations in sorted(by_user.items()):
        users.append(
            {
                "user_id": user_id,
                "legacy_spending_authorization_ids": sorted(
                    item.spending_authorization_id for item in authorizations
                ),
                "products": sorted({_legacy_product(item) for item in authorizations}),
                "reason": "legacy_authorization_not_promoted",
            }
        )
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "legacy": True,
        "users_requiring_reauthorization": users,
        "user_count": len(users),
    }


def main() -> None:
    config = AppConfig.from_env()
    report = build_reauthorization_report(
        database_url=config.funding_database_url,
        funding_records_path=Path(config.funding_session_file),
        now=datetime.now(UTC),
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
