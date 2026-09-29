from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from shared.config import AppConfig
from shared.models import Provider, ServiceOffering


ROOT = Path(__file__).resolve().parents[1]
MERCHANT_WALLET = "0x" + "1" * 40
ADMIN_WALLET = "0x" + "2" * 40


class HealthyCore:
    def health(self):
        return {
            "status": "ok",
            "services": {
                "action": "ok",
                "policy": "ok",
                "audit": "ok",
                "funding": "ok",
            },
        }


def session(repository, wallet, token):
    repository.create_merchant_session(
        sha256(token.encode()).hexdigest(),
        wallet,
        datetime.now(UTC) + timedelta(hours=1),
    )


def provider_with_offering(repository, *, wallet=MERCHANT_WALLET):
    provider = Provider(
        name="Signal Forge",
        domain="signal-forge.example",
        source="clink_manifest",
        status="active",
    )
    repository.upsert_provider(provider, wallet_address=wallet)
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="clink_manifest",
        source_id="POST https://signal-forge.example/risk",
        name="Wallet risk signal",
        endpoint="https://signal-forge.example/risk",
        method="POST",
        status="verified",
    )
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    return provider, offering


def make_client(tmp_path, *, admin_disabled=False):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'console.sqlite3'}"
    repository = MarketplaceRepository(database_url)
    config = replace(
        AppConfig.from_env(),
        database_url=database_url,
        redis_url="",
        admin_wallets=(ADMIN_WALLET,),
        admin_disabled=admin_disabled,
        core_internal_api_token="core-secret-must-not-reach-browser",
        siwe_allowed_domains=("marketplace.example",),
    )
    client = TestClient(
        create_marketplace_app(
            config,
            repository,
            IdentityService(repository),
            core=HealthyCore(),
        )
    )
    return client, repository, config


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def manifest_payload():
    return {
        "provider": {
            "name": "Pending Signal Forge",
            "domain": "pending-signal.example",
            "source": "clink_manifest",
        },
        "offerings": [{
            "name": "Pending risk signal",
            "endpoint": "https://pending-signal.example/risk",
            "method": "POST",
            "payment_options": [],
        }],
    }


def test_console_pages_use_external_assets_and_cover_operator_workflows(tmp_path):
    client, _, _ = make_client(tmp_path)

    merchant = client.get("/merchant")
    admin = client.get("/admin")
    merchant_css = client.get("/assets/console.css")
    merchant_js = client.get("/assets/merchant.js")
    admin_js = client.get("/assets/admin.js")

    assert merchant.status_code == admin.status_code == 200
    for page in (merchant, admin):
        assert "default-src 'self'" in page.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
    assert merchant_css.status_code == merchant_js.status_code == admin_js.status_code == 200
    assert '<link rel="stylesheet" href="/assets/console.css">' in merchant.text
    assert '<script src="/assets/merchant.js" defer></script>' in merchant.text
    assert '<script src="/assets/admin.js" defer></script>' in admin.text
    assert "<style>" not in merchant.text + admin.text
    assert "sessionStorage" in merchant_js.text
    assert "sessionStorage" in admin_js.text
    assert "localStorage" not in merchant_js.text + admin_js.text
    assert "privateKey" not in merchant_js.text + admin_js.text
    for expected in (
        "window.ethereum",
        "eth_requestAccounts",
        "eth_signTypedData_v4",
        "renderManifests",
        "Continue Manifest",
        "/merchant/candidates",
        "/claim-draft",
        "/merchant/manifests",
        "/claim-challenge",
        "/submit-claim",
        "/verify-domain",
        "/verify",
        "/disable",
    ):
        assert expected in merchant_js.text
    for expected in (
        "window.ethereum",
        "/admin/status",
        "/admin/providers",
        "/admin/registries/sync",
        "/suspend",
        "/restore",
    ):
        assert expected in admin_js.text
    assert "<!doctype html>" not in (ROOT / "services" / "marketplace_app.py").read_text(
        encoding="utf-8"
    ).lower()


def test_merchant_provider_list_and_status_are_session_scoped(tmp_path):
    client, repository, _ = make_client(tmp_path)
    provider, offering = provider_with_offering(repository)
    merchant_token = "merchant-session"
    other_token = "other-session"
    session(repository, MERCHANT_WALLET, merchant_token)
    session(repository, "0x" + "3" * 40, other_token)

    assert client.get("/merchant/providers").status_code == 401
    listed = client.get("/merchant/providers", headers=bearer(merchant_token))
    status = client.get(
        f"/merchant/providers/{provider.provider_id}/status",
        headers=bearer(merchant_token),
    )
    hidden = client.get(
        f"/merchant/providers/{provider.provider_id}/status",
        headers=bearer(other_token),
    )

    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["providers"][0]["provider"]["provider_id"] == provider.provider_id
    assert status.status_code == 200
    assert status.json()["provider"]["status"] == "active"
    assert status.json()["offerings"][0]["offering_id"] == offering.offering_id
    assert status.json()["offerings"][0]["status"] == "verified"
    assert hidden.status_code == 404


def test_merchant_can_resume_own_pending_manifests_without_signature_exposure(tmp_path):
    client, repository, _ = make_client(tmp_path)
    merchant_token = "merchant-session"
    other_token = "other-session"
    session(repository, MERCHANT_WALLET, merchant_token)
    session(repository, "0x" + "3" * 40, other_token)
    created = client.post(
        "/merchant/manifests",
        headers=bearer(merchant_token),
        json=manifest_payload(),
    )

    assert created.status_code == 200
    assert client.get("/merchant/manifests").status_code == 401
    listed = client.get("/merchant/manifests", headers=bearer(merchant_token))
    hidden = client.get("/merchant/manifests", headers=bearer(other_token))

    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    item = listed.json()["manifests"][0]
    assert item["manifest_id"] == created.json()["manifest_id"]
    assert item["status"] == "submitted"
    assert item["domain"] == "pending-signal.example"
    assert "signature" not in item
    assert "payload" not in item
    assert hidden.status_code == 200
    assert hidden.json() == {"count": 0, "manifests": []}


def test_admin_read_apis_reuse_admin_session_and_do_not_expose_secrets(tmp_path):
    client, repository, config = make_client(tmp_path)
    provider, _ = provider_with_offering(repository)
    merchant_token = "merchant-session"
    admin_token = "admin-session"
    session(repository, MERCHANT_WALLET, merchant_token)
    session(repository, ADMIN_WALLET, admin_token)

    assert client.get("/admin/status").status_code == 401
    assert client.get("/admin/status", headers=bearer(merchant_token)).status_code == 403
    status = client.get("/admin/status", headers=bearer(admin_token))
    providers = client.get("/admin/providers", headers=bearer(admin_token))

    assert status.status_code == 200
    assert {"worker", "registries", "core", "metrics"} <= set(status.json())
    assert providers.status_code == 200
    assert providers.json()["count"] == 1
    assert providers.json()["providers"][0]["provider"]["provider_id"] == provider.provider_id
    browser_payload = json.dumps([status.json(), providers.json()])
    assert config.core_internal_api_token not in browser_payload
    assert str(repository.engine.url) not in browser_payload


def test_auth_config_exposes_only_domains_needed_for_browser_siwe(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.get("/auth/siwe/config")

    assert response.status_code == 200
    assert response.json() == {"allowed_domains": ["marketplace.example"]}


def test_admin_disabled_blocks_new_console_and_api_routes(tmp_path):
    client, repository, _ = make_client(tmp_path, admin_disabled=True)
    admin_token = "admin-session"
    session(repository, ADMIN_WALLET, admin_token)

    for method, path in (
        ("get", "/admin"),
        ("get", "/admin/status"),
        ("get", "/admin/providers"),
        ("post", "/admin/registries/sync"),
    ):
        response = getattr(client, method)(path, headers=bearer(admin_token))
        assert response.status_code == 403
        assert response.json()["detail"] == "admin operations are disabled"
