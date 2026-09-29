from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from shared.commerce import PurchasePreview
from shared.config import AppConfig


def test_preview_lookup_requires_internal_identity_and_returns_owner(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'preview.sqlite3'}"
    repo = MarketplaceRepository(url)
    config = replace(AppConfig.from_env(), database_url=url, redis_url="", internal_api_token="node-only")
    app = create_marketplace_app(config, repo, IdentityService(repo))
    now = datetime.now(UTC)
    preview = PurchasePreview(
        preview_id="preview_owned", offering_id="offering_a", user_id="c_alice",
        quote_hash="quote", input_hash="input", payment={}, execution_mode="clink_allowance",
        created_at=now, expires_at=now + timedelta(minutes=5),
    )
    repo.save_preview(preview)
    with TestClient(app) as client:
        path = "/purchases/previews/preview_owned"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer runtime-token"}).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer node-only"})
        assert response.status_code == 200
        assert response.json()["user_id"] == "c_alice"
        assert response.json()["preview_id"] == "preview_owned"
        assert client.get("/purchases/previews/missing", headers={"Authorization": "Bearer node-only"}).status_code == 404
