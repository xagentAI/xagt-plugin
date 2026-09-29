from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from services.marketplace_worker import _verify_offerings
from services.purchase_service import PurchaseService
from shared.config import AppConfig
from shared.models import PaymentOption, Provider, ServiceOffering


def repository(tmp_path) -> MarketplaceRepository:
    return MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'verification-races.sqlite3'}"
    )


def active_service(repo: MarketplaceRepository):
    wallet = "0x" + "a" * 40
    provider = Provider(
        name="Race-safe provider",
        domain="race-safe.example",
        source="merchant",
        status="active",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id="POST https://race-safe.example/v1/check",
        name="Race-safe offering",
        endpoint="https://race-safe.example/v1/check",
        method="POST",
        status="verified",
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset="0x" + "1" * 40,
                amount_atomic="10000",
                pay_to="0x" + "2" * 40,
            )
        ],
    )
    repo.upsert_provider(provider, wallet_address=wallet)
    repo.upsert_offering(offering, verified_at=datetime.now(UTC))
    return wallet, provider, offering


class BlockingVerifier:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def verify(self, _offering):
        self.entered.set()
        assert self.release.wait(timeout=5), "test did not release verifier"
        return SimpleNamespace(
            verified=True,
            to_dict=lambda: {"verified": True},
        )


def merchant_client(repo, wallet, verifier):
    token = "merchant-race-token"
    repo.create_merchant_session(
        sha256(token.encode()).hexdigest(),
        wallet,
        datetime.now(UTC) + timedelta(hours=1),
    )
    config = replace(
        AppConfig.from_env(),
        database_url=str(repo.engine.url),
        redis_url="",
    )
    app = create_marketplace_app(
        config,
        repo,
        IdentityService(repo),
        endpoint_verifier=verifier,
    )
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_inflight_manual_verify_cannot_resurrect_merchant_disabled_offering(tmp_path):
    repo = repository(tmp_path)
    wallet, _provider, offering = active_service(repo)
    verifier = BlockingVerifier()
    client, headers = merchant_client(repo, wallet, verifier)
    response = {}

    thread = Thread(
        target=lambda: response.setdefault(
            "verify",
            client.post(
                f"/merchant/offerings/{offering.offering_id}/verify",
                headers=headers,
            ),
        )
    )
    thread.start()
    assert verifier.entered.wait(timeout=5)

    disabled = client.post(
        f"/merchant/offerings/{offering.offering_id}/disable",
        headers=headers,
    )
    verifier.release.set()
    thread.join(timeout=5)

    assert disabled.status_code == 200
    assert response["verify"].status_code == 409
    assert response["verify"].json()["detail"] == "offering verification result was not applied"
    assert repo.get_offering(offering.offering_id).status == "disabled"
    assert repo.search("Race-safe") == []
    with pytest.raises(ValueError, match="active provider"):
        PurchaseService(repo, core=object()).create_preview(
            user_id="user-1",
            offering_id=offering.offering_id,
            service_input={"subject": "0x" + "3" * 40},
        )


def test_inflight_worker_verify_cannot_override_admin_suspension(tmp_path):
    repo = repository(tmp_path)
    _wallet, provider, offering = active_service(repo)
    purchases = PurchaseService(repo, core=object())
    preview = purchases.create_preview(
        user_id="user-1",
        offering_id=offering.offering_id,
        service_input={"subject": "0x" + "3" * 40},
    )
    verifier = BlockingVerifier()
    result = {}
    thread = Thread(
        target=lambda: result.setdefault(
            "worker",
            _verify_offerings(repo, verifier, interval_seconds=900),
        )
    )
    thread.start()
    assert verifier.entered.wait(timeout=5)

    assert repo.suspend_provider(provider.provider_id)
    verifier.release.set()
    thread.join(timeout=5)

    assert result["worker"] == {"checked": 1, "applied": 0, "not_applied": 1}
    assert repo.get_provider(provider.provider_id).status == "suspended"
    assert repo.get_offering(offering.offering_id).status == "stale"
    assert repo.search("Race-safe") == []
    assert repo.active_offering(offering.offering_id) is None
    with pytest.raises(ValueError, match="active provider"):
        purchases.create_preview(
            user_id="user-1",
            offering_id=offering.offering_id,
            service_input={"subject": "0x" + "3" * 40},
        )
    with pytest.raises(ValueError, match="active provider"):
        purchases.execute(preview.preview_id)
