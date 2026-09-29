from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from shared.config import AppConfig
from shared.manifest import ManifestClaim
from shared.models import ClinkServiceManifest, Provider
from storage.tables import ChallengeRow, ManifestRow, MerchantSessionRow, OfferingRow, ProviderRow


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"


@pytest.fixture
def signed_siwe():
    return Account.create()


def build_app(database_url, *, allowed_domains=None):
    config = replace(
        AppConfig.from_env(),
        database_url=database_url,
        **({"siwe_allowed_domains": allowed_domains} if allowed_domains is not None else {}),
    )
    repository = MarketplaceRepository(database_url)
    return TestClient(create_marketplace_app(config, repository, IdentityService(repository)))


def issue_siwe_challenge(app, account, domain="marketplace.clink.local"):
    return app.post(
        "/auth/siwe/challenge",
        json={"address": account.address, "domain": domain},
    ).json()


def signed_siwe_payload(account, challenge, *, message=None, address=None):
    signed_message = challenge["message"] if message is None else message
    signature = Account.sign_message(
        encode_defunct(text=signed_message), account.key
    ).signature.hex()
    return {
        "address": account.address if address is None else address,
        "nonce": challenge["nonce"],
        "message": signed_message,
        "signature": signature,
    }


def verify_siwe(app, account):
    challenge = issue_siwe_challenge(app, account)
    response = app.post(
        "/auth/siwe/verify",
        json=signed_siwe_payload(account, challenge),
    )
    assert response.status_code == 200
    return response.json()


def manifest_payload():
    return {
        "provider": {"name": "Risk Co", "domain": "risk.example", "source": "merchant"},
        "offerings": [{
            "name": "Wallet risk",
            "endpoint": "https://risk.example/check",
            "method": "POST",
            "payment_options": [{
                "scheme": "exact",
                "network": "eip155:137",
                "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                "amount_atomic": "10000",
                "pay_to": "0x" + "1" * 40,
            }],
        }],
    }


def submit_manifest(app, token):
    response = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=manifest_payload(),
    )
    assert response.status_code == 200
    return response.json()["manifest_id"]


def submit_wallet_claim(app, token, account, manifest_id):
    headers = {"Authorization": f"Bearer {token}"}
    challenge_response = app.post(
        f"/merchant/manifests/{manifest_id}/claim-challenge",
        headers=headers,
    )
    assert challenge_response.status_code == 200
    claim = ManifestClaim.model_validate(challenge_response.json()["claim"])
    signature = Account.sign_message(
        encode_typed_data(full_message=claim.typed_data()), account.key
    ).signature.hex()
    return app.post(
        f"/merchant/manifests/{manifest_id}/submit-claim",
        headers=headers,
        json={
            "claim": claim.model_dump(mode="json"),
            "signature": signature,
            "wallet_address": account.address,
        },
    )


def test_siwe_session_survives_app_recreation(database_url, signed_siwe):
    first = build_app(database_url)
    token = verify_siwe(first, signed_siwe)["access_token"]

    second = build_app(database_url)
    response = second.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=manifest_payload(),
    )

    assert response.status_code == 200


def test_siwe_challenge_persists_exact_expected_message(database_url, signed_siwe):
    challenge = issue_siwe_challenge(build_app(database_url), signed_siwe)
    repository = MarketplaceRepository(database_url)

    with repository.sessions() as session:
        row = session.get(ChallengeRow, challenge["nonce"])

    assert row.subject == signed_siwe.address.lower()
    assert row.payload == {
        "address": signed_siwe.address.lower(),
        "domain": "marketplace.clink.local",
        "nonce": challenge["nonce"],
        "message": challenge["message"],
    }


def test_siwe_rejects_tampered_challenge_message(database_url, signed_siwe):
    app = build_app(database_url)
    challenge = issue_siwe_challenge(app, signed_siwe)
    payload = signed_siwe_payload(
        signed_siwe,
        challenge,
        message=challenge["message"] + "\nTampered",
    )

    response = app.post("/auth/siwe/verify", json=payload)

    assert response.status_code == 401


def test_siwe_rejects_message_without_challenge_nonce(database_url, signed_siwe):
    app = build_app(database_url)
    challenge = issue_siwe_challenge(app, signed_siwe)
    payload = signed_siwe_payload(
        signed_siwe,
        challenge,
        message="Historical personal_sign login approval",
    )

    response = app.post("/auth/siwe/verify", json=payload)

    assert response.status_code == 401


@pytest.mark.parametrize("field", ["domain", "address"])
def test_siwe_rejects_domain_or_address_mismatch(database_url, signed_siwe, field):
    app = build_app(database_url)
    challenge = issue_siwe_challenge(app, signed_siwe)
    if field == "domain":
        message = challenge["message"].replace(
            "marketplace.clink.local", "evil.example"
        )
    else:
        message = challenge["message"].replace(
            signed_siwe.address, Account.create().address
        )
    payload = signed_siwe_payload(signed_siwe, challenge, message=message)

    response = app.post("/auth/siwe/verify", json=payload)

    assert response.status_code == 401


def test_siwe_verify_rechecks_allowed_domain(database_url, signed_siwe):
    challenge = issue_siwe_challenge(build_app(database_url), signed_siwe)
    verifier = build_app(database_url, allowed_domains=("other.example",))

    response = verifier.post(
        "/auth/siwe/verify",
        json=signed_siwe_payload(signed_siwe, challenge),
    )

    assert response.status_code == 401


def test_invalid_siwe_signature_does_not_consume_challenge(database_url, signed_siwe):
    app = build_app(database_url)
    challenge = issue_siwe_challenge(app, signed_siwe)
    invalid = signed_siwe_payload(Account.create(), challenge, address=signed_siwe.address)

    rejected = app.post("/auth/siwe/verify", json=invalid)
    accepted = app.post(
        "/auth/siwe/verify",
        json=signed_siwe_payload(signed_siwe, challenge),
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_siwe_challenge_is_single_use(database_url, signed_siwe):
    app = build_app(database_url)
    challenge = issue_siwe_challenge(app, signed_siwe)
    payload = signed_siwe_payload(signed_siwe, challenge)

    accepted = app.post("/auth/siwe/verify", json=payload)
    replay = app.post("/auth/siwe/verify", json=payload)

    assert accepted.status_code == 200
    assert replay.status_code == 401


def test_siwe_verify_rejects_expired_challenge(database_url, signed_siwe):
    repository = MarketplaceRepository(database_url)
    identity = IdentityService(repository)
    challenge = identity.siwe_challenge(
        subject=signed_siwe.address,
        domain="marketplace.clink.local",
        ttl=-1,
    )
    app = TestClient(
        create_marketplace_app(AppConfig.from_env(), repository, identity)
    )

    response = app.post(
        "/auth/siwe/verify",
        json=signed_siwe_payload(signed_siwe, challenge),
    )

    assert response.status_code == 401


def test_manifest_claim_survives_app_recreation(database_url, signed_siwe):
    first = build_app(database_url)
    token = verify_siwe(first, signed_siwe)["access_token"]
    manifest_id = submit_manifest(first, token)

    second = build_app(database_url)
    response = second.post(
        f"/merchant/manifests/{manifest_id}/claim-challenge",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    claim = ManifestClaim.model_validate(response.json()["claim"])
    signature = Account.sign_message(encode_typed_data(full_message=claim.typed_data()), signed_siwe.key).signature.hex()
    payload = {"claim": claim.model_dump(mode="json"), "signature": signature, "wallet_address": signed_siwe.address}

    third = build_app(database_url)
    accepted = third.post(
        f"/merchant/manifests/{manifest_id}/submit-claim",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    replay = build_app(database_url).post(
        f"/merchant/manifests/{manifest_id}/submit-claim",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert accepted.status_code == 200
    assert replay.status_code == 401


def test_manifest_submit_and_wallet_claim_do_not_own_provider(database_url, signed_siwe):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    repository = MarketplaceRepository(database_url)

    with repository.sessions() as session:
        manifest = session.get(ManifestRow, manifest_id)
        assert session.get(ProviderRow, manifest.provider_id) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None

    claimed = submit_wallet_claim(app, token, signed_siwe, manifest_id)

    assert claimed.status_code == 200
    with repository.sessions() as session:
        manifest = session.get(ManifestRow, manifest_id)
        assert manifest.status == "wallet_verified"
        assert session.get(ProviderRow, manifest.provider_id) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None


def test_manifest_submit_rejects_noncanonical_provider_id(database_url, signed_siwe):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    payload = manifest_payload()
    payload["provider"]["provider_id"] = "provider_attacker_controlled"

    response = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "provider_id does not match normalized domain"
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        assert session.scalar(select(ManifestRow.manifest_id)) is None
        assert session.scalar(select(ProviderRow.provider_id)) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None


def test_manifest_submit_strips_server_managed_offering_metadata(
    database_url, signed_siwe
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    payload = manifest_payload()
    payload["offerings"][0]["metadata"] = {
        "merchant_note": "keep me",
        "bazaar_targets": [
            {
                "name": "Nansen",
                "category": "data",
                "relationship": "first_party",
            }
        ],
        "bazaar_info": {"input": {"type": "forged"}},
        "quality": {"l30DaysTotalCalls": 999999},
        "trust_tier": "registry_verified",
        "verification_source": "external_registry",
        "last_verified_at": "2099-01-01T00:00:00Z",
        "x402_version": 2,
    }

    response = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        manifest = session.get(ManifestRow, response.json()["manifest_id"])
        assert manifest.payload["offerings"][0]["metadata"] == {
            "merchant_note": "keep me"
        }


def test_domain_verification_requires_wallet_verified_manifest(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        provider_id = session.get(ManifestRow, manifest_id).provider_id
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )

    response = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    with repository.sessions() as session:
        assert session.get(ProviderRow, provider_id) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None


def test_failed_domain_proof_does_not_own_provider(database_url, signed_siwe, monkeypatch):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    assert submit_wallet_claim(app, token, signed_siwe, manifest_id).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        provider_id = session.get(ManifestRow, manifest_id).provider_id

    def reject_proof(_self, **_payload):
        raise ValueError("domain proof rejected")

    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify", reject_proof
    )
    response = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    with repository.sessions() as session:
        assert session.get(ProviderRow, provider_id) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None


def test_successful_domain_proof_is_the_only_provider_ownership_path(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    assert submit_wallet_claim(app, token, signed_siwe, manifest_id).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        provider_id = session.get(ManifestRow, manifest_id).provider_id
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )

    response = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    with repository.sessions() as session:
        provider = session.get(ProviderRow, provider_id)
        assert provider.wallet_address == signed_siwe.address.lower()
        assert provider.status == "domain_verified"


def test_domain_proof_rejects_existing_provider_with_mismatched_trusted_domain(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    assert submit_wallet_claim(app, token, signed_siwe, manifest_id).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        provider_id = session.get(ManifestRow, manifest_id).provider_id
    repository.upsert_provider(
        Provider(
            provider_id=provider_id,
            name="Trusted legacy provider",
            domain="trusted.example",
            source="legacy",
            metadata={"trusted": True},
        )
    )
    with repository.sessions() as session:
        existing = session.get(ProviderRow, provider_id)
        before = {
            "domain": existing.domain,
            "wallet_address": existing.wallet_address,
            "status": existing.status,
            "payload": existing.payload,
            "domain_failures": existing.domain_failures,
            "last_domain_verified_at": existing.last_domain_verified_at,
            "updated_at": existing.updated_at,
        }
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )

    response = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    with repository.sessions() as session:
        existing = session.get(ProviderRow, provider_id)
        assert {
            "domain": existing.domain,
            "wallet_address": existing.wallet_address,
            "status": existing.status,
            "payload": existing.payload,
            "domain_failures": existing.domain_failures,
            "last_domain_verified_at": existing.last_domain_verified_at,
            "updated_at": existing.updated_at,
        } == before
        assert session.scalar(select(OfferingRow.offering_id)) is None


def test_domain_proof_accepts_normalized_trusted_domain_without_overwriting_it(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, token)
    assert submit_wallet_claim(app, token, signed_siwe, manifest_id).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        provider_id = session.get(ManifestRow, manifest_id).provider_id
    repository.upsert_provider(
        Provider(
            provider_id=provider_id,
            name="Trusted legacy provider",
            domain="Risk.Example.",
            source="legacy",
        )
    )
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )

    response = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    with repository.sessions() as session:
        provider = session.get(ProviderRow, provider_id)
        assert provider.domain == "risk.example."
        assert provider.wallet_address == signed_siwe.address.lower()
        assert provider.status == "domain_verified"


def test_two_wallets_compete_only_at_successful_domain_proof(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    first_account = signed_siwe
    second_account = Account.create()
    first_token = verify_siwe(app, first_account)["access_token"]
    second_token = verify_siwe(app, second_account)["access_token"]
    first_payload = manifest_payload()
    second_payload = manifest_payload()

    first_submit = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {first_token}"},
        json=first_payload,
    )
    second_submit = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {second_token}"},
        json=second_payload,
    )
    assert first_submit.status_code == second_submit.status_code == 200
    assert submit_wallet_claim(
        app, first_token, first_account, first_submit.json()["manifest_id"]
    ).status_code == 200
    assert submit_wallet_claim(
        app, second_token, second_account, second_submit.json()["manifest_id"]
    ).status_code == 200
    assert first_submit.json()["manifest_id"] != second_submit.json()["manifest_id"]
    assert first_submit.json()["manifest_hash"] == second_submit.json()["manifest_hash"]
    provider_id = first_submit.json()["provider_id"]
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        assert session.get(ProviderRow, provider_id) is None
        assert session.scalar(select(OfferingRow.offering_id)) is None
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )

    winner = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    loser = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    blocked_payload = manifest_payload()
    blocked_payload["offerings"][0]["description"] = "Post-ownership replacement"
    blocked_manifest = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {first_token}"},
        json=blocked_payload,
    )

    assert winner.status_code == 200
    assert loser.status_code == 409
    assert blocked_manifest.status_code == 200
    with repository.sessions() as session:
        provider = session.get(ProviderRow, provider_id)
        assert provider.wallet_address == second_account.address.lower()
        assert provider.status == "domain_verified"
        offering = session.scalar(select(OfferingRow).where(OfferingRow.provider_id == provider_id))
        assert offering.payload["description"] == manifest_payload()["offerings"][0].get("description", "")


def test_manifest_retry_cannot_downgrade_verified_provider_or_offering(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    first = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=manifest_payload(),
    )
    assert first.status_code == 200
    assert submit_wallet_claim(
        app, token, signed_siwe, first.json()["manifest_id"]
    ).status_code == 200
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )
    verified_domain = app.post(
        f"/merchant/providers/{first.json()['provider_id']}/verify-domain",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verified_domain.status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions.begin() as session:
        manifest = session.get(ManifestRow, first.json()["manifest_id"])
        provider = session.get(ProviderRow, manifest.provider_id)
        provider.status = "active"
        provider.payload = {**provider.payload, "status": "active"}
        offering = session.scalar(
            select(OfferingRow).where(OfferingRow.provider_id == provider.provider_id)
        )
        offering.status = "verified"
        offering.payload = {**offering.payload, "status": "verified"}

    retried = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=manifest_payload(),
    )

    assert retried.status_code == 200
    assert retried.json()["manifest_id"] == first.json()["manifest_id"]
    with repository.sessions() as session:
        provider = session.get(ProviderRow, first.json()["provider_id"])
        offering = session.scalar(
            select(OfferingRow).where(OfferingRow.provider_id == provider.provider_id)
        )
        assert provider.status == "active"
        assert offering.status == "verified"


def test_new_proof_does_not_overwrite_active_provider_or_verified_offering(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    token = verify_siwe(app, signed_siwe)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    first_id = submit_manifest(app, token)
    assert submit_wallet_claim(app, token, signed_siwe, first_id).status_code == 200
    provider_id = ClinkServiceManifest.model_validate(manifest_payload()).provider.provider_id
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )
    assert app.post(
        f"/merchant/providers/{provider_id}/verify-domain", headers=headers
    ).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions.begin() as session:
        provider = session.get(ProviderRow, provider_id)
        provider.status = "active"
        provider.payload = {**provider.payload, "name": "Trusted Provider", "status": "active"}
        offering = session.scalar(
            select(OfferingRow).where(OfferingRow.provider_id == provider_id)
        )
        offering.status = "verified"
        offering.payload = {**offering.payload, "name": "Trusted Offering", "status": "verified"}

    replacement = manifest_payload()
    replacement["provider"]["name"] = "Untrusted Replacement"
    replacement["offerings"][0]["name"] = "Untrusted Offering"
    second = app.post("/merchant/manifests", headers=headers, json=replacement)
    assert second.status_code == 200
    assert submit_wallet_claim(
        app, token, signed_siwe, second.json()["manifest_id"]
    ).status_code == 200
    reproved = app.post(
        f"/merchant/providers/{provider_id}/verify-domain", headers=headers
    )

    assert reproved.status_code == 200
    with repository.sessions() as session:
        provider = session.get(ProviderRow, provider_id)
        offering = session.scalar(
            select(OfferingRow).where(OfferingRow.provider_id == provider_id)
        )
        assert provider.status == "active"
        assert provider.payload["name"] == "Trusted Provider"
        assert offering.status == "verified"
        assert offering.payload["name"] == "Trusted Offering"


def test_non_owner_cannot_verify_or_disable_provider_offering(
    database_url, signed_siwe, monkeypatch
):
    app = build_app(database_url)
    owner_token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, owner_token)
    assert submit_wallet_claim(app, owner_token, signed_siwe, manifest_id).status_code == 200
    repository = MarketplaceRepository(database_url)
    with repository.sessions() as session:
        manifest = session.get(ManifestRow, manifest_id)
        provider_id = manifest.provider_id
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )
    owned = app.post(
        f"/merchant/providers/{provider_id}/verify-domain",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owned.status_code == 200
    with repository.sessions() as session:
        offering_id = session.scalar(
            select(OfferingRow.offering_id).where(OfferingRow.provider_id == provider_id)
        )
    other_token = verify_siwe(app, Account.create())["access_token"]
    monkeypatch.setattr(
        "services.provider_verification.EndpointVerifier.verify",
        lambda _self, _offering: SimpleNamespace(
            verified=True, to_dict=lambda: {"verified": True}
        ),
    )

    verify_response = app.post(
        f"/merchant/offerings/{offering_id}/verify",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    disable_response = app.post(
        f"/merchant/offerings/{offering_id}/disable",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert verify_response.status_code == 403
    assert disable_response.status_code == 403
    with repository.sessions() as session:
        assert session.get(ProviderRow, provider_id).status == "domain_verified"
        assert session.get(OfferingRow, offering_id).status == "submitted"


def test_other_wallet_cannot_access_manifest_but_can_prepare_own_unowned_draft(database_url, signed_siwe):
    app = build_app(database_url)
    owner_token = verify_siwe(app, signed_siwe)["access_token"]
    manifest_id = submit_manifest(app, owner_token)
    owner_challenge = app.post(
        f"/merchant/manifests/{manifest_id}/claim-challenge",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["claim"]
    other_token = verify_siwe(app, Account.create())["access_token"]

    challenge = app.post(
        f"/merchant/manifests/{manifest_id}/claim-challenge",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    claim = app.post(
        f"/merchant/manifests/{manifest_id}/submit-claim",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"claim": owner_challenge, "signature": "0x00", "wallet_address": "0x" + "2" * 40},
    )
    replacement_payload = manifest_payload()
    replacement_payload["offerings"][0]["name"] = "Other wallet risk"
    replacement = app.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {other_token}"},
        json=replacement_payload,
    )

    assert challenge.status_code == 404
    assert claim.status_code == 404
    assert replacement.status_code == 200
    assert replacement.json()["manifest_id"] != manifest_id


def test_session_storage_contains_only_token_hash(database_url, signed_siwe):
    token = verify_siwe(build_app(database_url), signed_siwe)["access_token"]
    repository = MarketplaceRepository(database_url)

    with repository.sessions() as session:
        stored_hashes = session.scalars(select(MerchantSessionRow.token_hash)).all()

    assert stored_hashes == [sha256(token.encode()).hexdigest()]
    assert token not in stored_hashes


def test_identity_service_requires_repository():
    with pytest.raises(TypeError):
        IdentityService()


def test_challenge_rejects_wrong_purpose_or_subject(database_url):
    identity = IdentityService(MarketplaceRepository(database_url))
    challenge = identity.challenge(subject="0x" + "1" * 40, purpose="siwe")

    assert identity.repository.consume_challenge(challenge["nonce"], "manifest_claim", challenge["subject"]) is False
    assert identity.repository.consume_challenge(challenge["nonce"], "siwe", "0x" + "2" * 40) is False
    assert identity.repository.consume_challenge(challenge["nonce"], "siwe", challenge["subject"]) is True


def test_challenge_rejects_expiry_and_replay(database_url):
    identity = IdentityService(MarketplaceRepository(database_url))
    expired = identity.challenge(subject="0x" + "1" * 40, purpose="siwe", ttl=-1)
    replayable = identity.challenge(subject="0x" + "1" * 40, purpose="siwe")

    assert identity.repository.consume_challenge(expired["nonce"], "siwe", expired["subject"]) is False
    assert identity.repository.consume_challenge(replayable["nonce"], "siwe", replayable["subject"]) is True
    assert identity.repository.consume_challenge(replayable["nonce"], "siwe", replayable["subject"]) is False


def test_migration_upgrades_existing_0001_sqlite(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing-0001.sqlite3'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE providers (provider_id VARCHAR(64) PRIMARY KEY, wallet_address VARCHAR(42))"))
        connection.execute(text("CREATE TABLE manifests (manifest_id VARCHAR(64) PRIMARY KEY, provider_id VARCHAR(64))"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO providers (provider_id, wallet_address) VALUES ('provider_1', '0x1111111111111111111111111111111111111111')"))
        connection.execute(text("INSERT INTO manifests (manifest_id, provider_id) VALUES ('manifest_1', 'provider_1')"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260712_0001')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "20260713_0002")

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(manifests)")}
        assert "owner_wallet_address" in columns
        owner = connection.execute(text("SELECT owner_wallet_address FROM manifests WHERE manifest_id = 'manifest_1'"))

    assert owner.scalar_one() == "0x1111111111111111111111111111111111111111"


def test_migration_replays_partial_nullable_owner_backfill(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'partial-owner.sqlite3'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE providers (provider_id VARCHAR(64) PRIMARY KEY, wallet_address VARCHAR(42))"))
        connection.execute(text("CREATE TABLE manifests (manifest_id VARCHAR(64) PRIMARY KEY, provider_id VARCHAR(64), owner_wallet_address VARCHAR(42))"))
        connection.execute(text("CREATE INDEX ix_manifests_owner_wallet_address ON manifests (owner_wallet_address)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO providers (provider_id, wallet_address) VALUES ('provider_1', '0x1111111111111111111111111111111111111111')"))
        connection.execute(text("INSERT INTO manifests (manifest_id, provider_id, owner_wallet_address) VALUES ('manifest_1', 'provider_1', NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260712_0001')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")),
        "20260713_0002",
    )

    with engine.connect() as connection:
        column = next(row for row in connection.exec_driver_sql("PRAGMA table_info(manifests)") if row[1] == "owner_wallet_address")
        owner = connection.execute(text("SELECT owner_wallet_address FROM manifests WHERE manifest_id = 'manifest_1'"))

    assert column[3] == 1
    assert owner.scalar_one() == "0x1111111111111111111111111111111111111111"


def test_registry_cursor_lease_migration_recovers_missing_cursor_table_without_marker(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'registry-cursor-downgrade.sqlite3'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("CREATE TABLE registry_cursor_lease_migration_state (unrelated BOOLEAN NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260713_0002')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    with engine.connect() as connection:
        upgraded_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(registry_cursors)")}
        indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(registry_cursors)")}

    assert upgraded_columns == {"registry_id", "cursor", "etag", "status", "last_error", "sync_owner_token", "sync_lease_until", "updated_at"}
    assert "ix_registry_cursors_sync_lease_until" in indexes

    command.downgrade(config, "20260713_0002")

    with engine.connect() as connection:
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "registry_cursors" in tables
    assert "registry_cursor_lease_migration_state" in tables
    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(registry_cursors)")}
    assert columns == {"registry_id", "cursor", "etag", "status", "last_error", "updated_at"}


def test_migration_rejects_partial_owner_without_provider_wallet(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'partial-owner-missing.sqlite3'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE providers (provider_id VARCHAR(64) PRIMARY KEY, wallet_address VARCHAR(42))"))
        connection.execute(text("CREATE TABLE manifests (manifest_id VARCHAR(64) PRIMARY KEY, provider_id VARCHAR(64), owner_wallet_address VARCHAR(42))"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO manifests (manifest_id, provider_id, owner_wallet_address) VALUES ('manifest_1', 'missing_provider', NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260712_0001')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    with pytest.raises(RuntimeError, match="provider wallet owner"):
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")


def test_pending_manifest_migration_removes_provider_fk_and_scopes_hash_to_owner(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pending-manifest.sqlite3'}"
    engine = create_engine(database_url)
    provider_id = Provider.build_id("legacy", "risk.example")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(text("CREATE TABLE providers (provider_id VARCHAR(64) PRIMARY KEY, domain VARCHAR(255) NOT NULL)"))
        connection.execute(text("""
            CREATE TABLE manifests (
                manifest_id VARCHAR(64) PRIMARY KEY,
                provider_id VARCHAR(64) NOT NULL REFERENCES providers(provider_id) ON DELETE CASCADE,
                owner_wallet_address VARCHAR(42) NOT NULL,
                manifest_hash VARCHAR(66) NOT NULL UNIQUE,
                payload JSON NOT NULL,
                signature TEXT,
                signer VARCHAR(42),
                status VARCHAR(32) NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("CREATE INDEX ix_manifests_provider_id ON manifests (provider_id)"))
        connection.execute(text("CREATE INDEX ix_manifests_owner_wallet_address ON manifests (owner_wallet_address)"))
        connection.execute(text("CREATE INDEX ix_manifests_status ON manifests (status)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO providers (provider_id, domain) VALUES (:provider_id, 'Risk.Example.')"),
            {"provider_id": provider_id},
        )
        connection.execute(text("""
            INSERT INTO manifests (
                manifest_id, provider_id, owner_wallet_address, manifest_hash,
                payload, status, updated_at
            ) VALUES (
                'manifest_1', :provider_id, '0x1111111111111111111111111111111111111111',
                '0xhash', '{}', 'submitted', '2026-07-13 00:00:00'
            )
        """), {"provider_id": provider_id})
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260713_0003')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(manifests)").all()
        unique_indexes = [
            row for row in connection.exec_driver_sql("PRAGMA index_list(manifests)").all()
            if row[2]
        ]
        unique_columns = {
            tuple(
                item[2]
                for item in connection.exec_driver_sql(
                    f"PRAGMA index_info('{row[1]}')"
                ).all()
            )
            for row in unique_indexes
        }
        connection.execute(text("""
            INSERT INTO manifests (
                manifest_id, provider_id, owner_wallet_address, manifest_hash,
                payload, status, updated_at
            ) VALUES (
                'manifest_2', 'missing_provider', '0x2222222222222222222222222222222222222222',
                '0xhash', '{}', 'submitted', '2026-07-13 00:00:00'
            )
        """))
        with pytest.raises(IntegrityError):
            connection.execute(text("""
                INSERT INTO manifests (
                    manifest_id, provider_id, owner_wallet_address, manifest_hash,
                    payload, status, updated_at
                ) VALUES (
                    'manifest_3', 'missing_provider', '0x2222222222222222222222222222222222222222',
                    '0xhash', '{}', 'submitted', '2026-07-13 00:00:00'
                )
            """))

    assert foreign_keys == []
    assert ("owner_wallet_address", "manifest_hash") in unique_columns
    assert ("manifest_hash",) not in unique_columns


def test_pending_manifest_migration_rejects_noncanonical_provider_before_schema_change(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'noncanonical-provider.sqlite3'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(text("""
            CREATE TABLE providers (
                provider_id VARCHAR(64) PRIMARY KEY,
                domain VARCHAR(255) NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE manifests (
                manifest_id VARCHAR(64) PRIMARY KEY,
                provider_id VARCHAR(64) NOT NULL REFERENCES providers(provider_id) ON DELETE CASCADE,
                owner_wallet_address VARCHAR(42) NOT NULL,
                manifest_hash VARCHAR(66) NOT NULL UNIQUE,
                payload JSON NOT NULL,
                signature TEXT,
                signer VARCHAR(42),
                status VARCHAR(32) NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("""
            INSERT INTO providers (provider_id, domain)
            VALUES ('provider_attacker', 'victim.example')
        """))
        connection.execute(text("""
            INSERT INTO manifests (
                manifest_id, provider_id, owner_wallet_address, manifest_hash,
                payload, status, updated_at
            ) VALUES (
                'manifest_1', 'provider_attacker',
                '0x1111111111111111111111111111111111111111',
                '0xhash', '{}', 'submitted', '2026-07-13 00:00:00'
            )
        """))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260713_0003')"))

    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.raises(RuntimeError, match=r"count=1.*provider_attacker"):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(manifests)").all()
        unique_indexes = [
            row for row in connection.exec_driver_sql("PRAGMA index_list(manifests)").all()
            if row[2]
        ]
        unique_columns = {
            tuple(
                item[2]
                for item in connection.exec_driver_sql(
                    f"PRAGMA index_info('{row[1]}')"
                ).all()
            )
            for row in unique_indexes
        }

    assert version == "20260713_0003"
    assert any(row[2] == "providers" for row in foreign_keys)
    assert ("manifest_hash",) in unique_columns
    assert ("owner_wallet_address", "manifest_hash") not in unique_columns


def test_pending_manifest_migration_downgrade_restores_legacy_constraints(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pending-manifest-downgrade.sqlite3'}"
    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO providers (provider_id, domain, status, payload, domain_failures, updated_at) VALUES ('provider_1', 'risk.example', 'discovered', '{}', 0, '2026-07-13 00:00:00')"))
        connection.execute(text("""
            INSERT INTO manifests (
                manifest_id, provider_id, owner_wallet_address, manifest_hash,
                payload, status, updated_at
            ) VALUES (
                'manifest_1', 'provider_1', '0x1111111111111111111111111111111111111111',
                '0xhash', '{}', 'submitted', '2026-07-13 00:00:00'
            )
        """))

    command.downgrade(config, "20260713_0003")
    engine.dispose()
    engine = create_engine(database_url)

    with engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(manifests)").all()
        unique_indexes = [
            row for row in connection.exec_driver_sql("PRAGMA index_list(manifests)").all()
            if row[2]
        ]
        unique_columns = {
            tuple(
                item[2]
                for item in connection.exec_driver_sql(
                    f"PRAGMA index_info('{row[1]}')"
                ).all()
            )
            for row in unique_indexes
        }

    assert any(row[2] == "providers" for row in foreign_keys)
    assert ("manifest_hash",) in unique_columns
    assert ("owner_wallet_address", "manifest_hash") not in unique_columns
