from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi.testclient import TestClient

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from shared.config import AppConfig


def test_admin_disabled_denies_allowlisted_merchant_session(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'admin-disabled.sqlite3'}"
    repository = MarketplaceRepository(database_url)
    wallet = "0x" + "1" * 40
    token = "allowlisted-admin-session"
    repository.create_merchant_session(
        sha256(token.encode()).hexdigest(),
        wallet,
        datetime.now(UTC) + timedelta(hours=1),
    )
    config = replace(
        AppConfig.from_env(),
        database_url=database_url,
        admin_wallets=(wallet,),
        admin_disabled=True,
    )
    client = TestClient(
        create_marketplace_app(config, repository, IdentityService(repository)),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/admin/providers/provider_missing/suspend",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin operations are disabled"
    console = client.get("/admin")
    assert console.status_code == 403
    assert console.json()["detail"] == "admin operations are disabled"
