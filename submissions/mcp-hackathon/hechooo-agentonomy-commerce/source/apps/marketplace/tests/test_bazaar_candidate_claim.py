from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from adapters.cdp_bazaar import CdpBazaarAdapter
from services.identity_service import IdentityService
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from shared.config import AppConfig
from shared.manifest import ManifestClaim
from storage.tables import ManifestRow, OfferingRow, ProviderRow, ProvenanceRow


OWNER_WALLET = "0x" + "1" * 40
OTHER_WALLET = "0x" + "2" * 40


@pytest.fixture
def repository(tmp_path):
    return MarketplaceRepository(f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}")


@pytest.fixture
def client(repository):
    return TestClient(
        create_marketplace_app(AppConfig.from_env(), repository, IdentityService(repository)),
        raise_server_exceptions=False,
    )


def merchant_headers(repository, wallet=OWNER_WALLET):
    token = f"merchant-{wallet}"
    repository.create_merchant_session(
        sha256(token.encode()).hexdigest(),
        wallet,
        datetime.now(UTC) + timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def store_candidate(
    repository,
    *,
    index=1,
    name="Wallet Risk",
    pay_to=OWNER_WALLET,
    network="eip155:137",
    status="discovered",
    registry_id="cdp_bazaar",
    owner_wallet=None,
):
    resource = {
        "resource": f"https://risk-{index}.example.com/v1/check",
        "serviceName": name,
        "description": "Screen a wallet before payment",
        "tags": ["risk", "wallet"],
        "accepts": [{
            "scheme": "exact",
            "network": network,
            "asset": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
            "amount": "5000",
            "payTo": pay_to,
        }],
        "extensions": {"bazaar": {"info": {"input": {"method": "POST"}}}},
    }
    provider, offering = CdpBazaarAdapter().normalize_resource(resource)
    repository.upsert_provider(provider, owner_wallet)
    repository.upsert_offering(offering.model_copy(update={"status": status}))
    repository.add_provenance(
        offering.offering_id,
        registry_id,
        offering.source_id,
        offering.model_dump(mode="json"),
    )
    return provider, offering


def test_candidate_list_requires_merchant_session(client):
    response = client.get("/merchant/candidates")

    assert response.status_code == 401
    assert response.json()["detail"] == "merchant SIWE session required"


def test_candidate_list_returns_only_uncontrolled_discovered_bazaar_rows(
    client, repository
):
    _, candidate = store_candidate(repository, index=1)
    store_candidate(repository, index=2, owner_wallet=OTHER_WALLET)
    store_candidate(repository, index=3, status="verified")
    store_candidate(repository, index=4, registry_id="clink_peer")

    response = client.get(
        "/merchant/candidates", headers=merchant_headers(repository)
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert [item["offering"]["offering_id"] for item in response.json()["candidates"]] == [
        candidate.offering_id
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"domain": "risk-2.example.com"},
        {"pay_to": OTHER_WALLET.upper()},
        {"query": "wallet premium"},
    ],
)
def test_candidate_list_supports_domain_pay_to_and_query_filters(
    client, repository, params
):
    store_candidate(repository, index=1, name="Basic Screening")
    _, expected = store_candidate(
        repository,
        index=2,
        name="Premium Wallet Risk",
        pay_to=OTHER_WALLET,
    )

    response = client.get(
        "/merchant/candidates",
        params=params,
        headers=merchant_headers(repository),
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["candidates"][0]["offering"]["offering_id"] == expected.offering_id


def test_candidate_list_honors_limit(client, repository):
    for index in range(1, 4):
        store_candidate(repository, index=index)

    response = client.get(
        "/merchant/candidates",
        params={"limit": 2},
        headers=merchant_headers(repository),
    )

    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert len(response.json()["candidates"]) == 2


def test_candidate_scan_uses_bounded_batches_without_losing_post_filter_matches(
    client, repository
):
    candidates = []
    for index in range(1, 56):
        _, candidate = store_candidate(repository, index=index, name="Decoy")
        candidates.append(candidate)
    target = max(candidates, key=lambda item: item.offering_id)
    with repository.sessions.begin() as session:
        provenance = session.scalar(
            select(ProvenanceRow).where(
                ProvenanceRow.offering_id == target.offering_id,
                ProvenanceRow.registry_id == "cdp_bazaar",
            )
        )
        provenance.payload = {**provenance.payload, "name": "Target Needle"}
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if "offering_provenance" in statement and "providers" in statement:
            statements.append(statement.upper())

    event.listen(repository.engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(
            "/merchant/candidates",
            params={"query": "target needle", "limit": 1},
            headers=merchant_headers(repository),
        )
    finally:
        event.remove(repository.engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["candidates"][0]["offering"]["name"] == "Target Needle"
    assert len(statements) == 1
    assert all("LIMIT" in statement for statement in statements)
    assert all(" OVER (" not in statement for statement in statements)


def test_candidate_scan_has_explicit_budget_for_unmatched_post_filters(
    client, repository
):
    for index in range(1, 151):
        store_candidate(repository, index=index, name="Decoy")
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if "offering_provenance" in statement and "providers" in statement:
            statements.append(statement.upper())

    event.listen(repository.engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(
            "/merchant/candidates",
            params={"pay_to": OTHER_WALLET, "limit": 1},
            headers=merchant_headers(repository),
        )
    finally:
        event.remove(repository.engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json() == {"count": 0, "candidates": []}
    assert len(statements) == 4
    assert all(" OVER (" not in statement for statement in statements)


def test_candidate_domain_filter_is_pushed_into_database_query(client, repository):
    store_candidate(repository, index=1)
    store_candidate(repository, index=2)
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if "offering_provenance" in statement and "providers" in statement:
            statements.append(statement.upper())

    event.listen(repository.engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(
            "/merchant/candidates",
            params={"domain": "risk-2.example.com", "limit": 1},
            headers=merchant_headers(repository),
        )
    finally:
        event.remove(repository.engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert len(statements) == 1
    assert "PROVIDERS.DOMAIN =" in statements[0]
    assert " OVER (" not in statements[0]


def test_candidate_query_filter_is_pushed_into_database_query(client, repository):
    store_candidate(repository, index=1, name="Basic Screening")
    store_candidate(repository, index=2, name="Target Needle")
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if "offering_provenance" in statement and "providers" in statement:
            statements.append(statement.upper())

    event.listen(repository.engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(
            "/merchant/candidates",
            params={"query": "target needle", "limit": 1},
            headers=merchant_headers(repository),
        )
    finally:
        event.remove(repository.engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json()["candidates"][0]["offering"]["name"] == "Target Needle"
    assert len(statements) == 1
    assert "JSON_EXTRACT" in statements[0]
    assert "LIKE" in statements[0]


def test_candidate_list_does_not_trust_imported_status_fields(client, repository):
    provider, candidate = store_candidate(repository)
    with repository.sessions.begin() as session:
        provider_row = session.get(ProviderRow, provider.provider_id)
        offering_row = session.get(OfferingRow, candidate.offering_id)
        provider_row.payload = {
            **provider_row.payload,
            "status": "active",
            "verified_wallets": [OTHER_WALLET],
        }
        offering_row.payload = {**offering_row.payload, "status": "verified"}

    response = client.get(
        "/merchant/candidates", headers=merchant_headers(repository)
    )

    assert response.status_code == 200
    item = response.json()["candidates"][0]
    assert item["provider"]["status"] == "discovered"
    assert item["provider"]["verified_wallets"] == []
    assert item["offering"]["status"] == "discovered"


def test_candidate_uses_latest_bazaar_provenance_and_provider_row_domain(
    client, repository
):
    provider, candidate = store_candidate(repository)
    for endpoint in ("older.example.com", "newest.example.com"):
        repository.add_provenance(
            candidate.offering_id,
            "cdp_bazaar",
            f"POST https://{endpoint}/check",
            candidate.model_dump(mode="json") | {
                "endpoint": f"https://{endpoint}/check",
                "source": "merchant",
                "status": "verified",
                "offering_id": "forged_offering",
                "provider_id": "forged_provider",
            },
        )
    with repository.sessions.begin() as session:
        rows = session.scalars(
            select(ProvenanceRow)
            .where(
                ProvenanceRow.offering_id == candidate.offering_id,
                ProvenanceRow.registry_id == "cdp_bazaar",
            )
            .order_by(ProvenanceRow.provenance_id)
        ).all()
        tied_at = datetime(2026, 1, 1, tzinfo=UTC)
        for row in rows:
            row.updated_at = tied_at
        offering_row = session.get(OfferingRow, candidate.offering_id)
        offering_row.payload = {
            **offering_row.payload,
            "endpoint": "https://shared-row.example.com/check",
        }
        provider_row = session.get(ProviderRow, provider.provider_id)
        provider_row.payload = {
            **provider_row.payload,
            "domain": "forged.example.com",
        }

    response = client.get(
        "/merchant/candidates", headers=merchant_headers(repository)
    )

    assert response.status_code == 200
    item = response.json()["candidates"][0]
    assert item["provider"]["provider_id"] == provider.provider_id
    assert item["provider"]["domain"] == "risk-1.example.com"
    assert item["offering"]["offering_id"] == candidate.offering_id
    assert item["offering"]["provider_id"] == provider.provider_id
    assert item["offering"]["endpoint"] == "https://newest.example.com/check"
    assert item["offering"]["source"] == "cdp_bazaar"
    assert item["offering"]["status"] == "discovered"


def test_candidate_and_draft_strip_untrusted_metadata_and_payment_extras(
    client, repository
):
    provider, candidate = store_candidate(repository)
    with repository.sessions.begin() as session:
        provenance = session.scalar(
            select(ProvenanceRow).where(
                ProvenanceRow.offering_id == candidate.offering_id,
                ProvenanceRow.registry_id == "cdp_bazaar",
            )
        )
        payment = {
            **provenance.payload["payment_options"][0],
            "metadata": {"extra": {"secret": "upstream"}},
            "vendor_payment_blob": {"nested": True},
        }
        provenance.payload = {
            **provenance.payload,
            "metadata": {
                "bazaar_info": {"secret": "upstream"},
                "quality": {"score": 100},
                "vendor_blob": {"nested": True},
            },
            "payment_options": [payment],
            "vendor_offering_blob": {"nested": True},
        }
        provider_row = session.get(ProviderRow, provider.provider_id)
        provider_row.payload = {
            **provider_row.payload,
            "metadata": {"vendor": {"nested": True}},
            "vendor_provider_blob": {"nested": True},
        }
    headers = merchant_headers(repository)

    listed = client.get("/merchant/candidates", headers=headers)
    draft = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=headers,
    )

    assert listed.status_code == draft.status_code == 200
    listed_item = listed.json()["candidates"][0]
    listed_payment = listed_item["offering"]["payment_options"][0]
    assert listed_item["provider"]["metadata"] == {}
    assert "vendor_provider_blob" not in listed_item["provider"]
    assert listed_item["offering"]["metadata"] == {}
    assert "vendor_offering_blob" not in listed_item["offering"]
    assert listed_payment["metadata"] == {}
    assert "vendor_payment_blob" not in listed_payment
    manifest = draft.json()["manifest"]
    assert manifest["provider"]["metadata"] == {}
    assert manifest["offerings"][0]["metadata"] == {
        "claim_source": "cdp_bazaar",
        "claimed_offering_id": candidate.offering_id,
    }
    assert manifest["offerings"][0]["payment_options"][0]["metadata"] == {}


def test_pay_to_filter_is_case_sensitive_for_non_evm_networks(client, repository):
    recipient = "SoLanaBase58RecipientAbC123"
    store_candidate(
        repository,
        pay_to=recipient,
        network="solana:mainnet",
    )
    headers = merchant_headers(repository)

    wrong_case = client.get(
        "/merchant/candidates",
        params={"pay_to": recipient.lower()},
        headers=headers,
    )
    exact_case = client.get(
        "/merchant/candidates",
        params={"pay_to": recipient},
        headers=headers,
    )

    assert wrong_case.json() == {"count": 0, "candidates": []}
    assert exact_case.json()["count"] == 1


def test_merchant_can_create_prefilled_manifest_from_bazaar_candidate(
    client, repository
):
    provider, candidate = store_candidate(repository)

    response = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=merchant_headers(repository),
    )

    assert response.status_code == 200
    manifest = response.json()["manifest"]
    assert manifest["provider"] == {
        **provider.model_dump(mode="json"),
        "source": "clink_manifest",
        "status": "discovered",
        "verified_wallets": [],
        "metadata": {},
    }
    draft = manifest["offerings"][0]
    assert draft["endpoint"] == candidate.endpoint
    assert draft["method"] == candidate.method
    assert len(draft["payment_options"]) == 1
    assert draft["payment_options"][0] == {
        **candidate.payment_options[0].model_dump(mode="json"),
        "metadata": {},
    }
    assert draft["metadata"] == {
        "claim_source": "cdp_bazaar",
        "claimed_offering_id": candidate.offering_id,
    }
    assert repository.get_provider(provider.provider_id).status == "discovered"
    assert repository.get_offering(candidate.offering_id).status == "discovered"


def test_claim_draft_is_read_only_and_safe_to_retry(client, repository):
    provider, candidate = store_candidate(repository)
    headers = merchant_headers(repository)

    first = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft", headers=headers
    )
    second = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft", headers=headers
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert repository.stats()["providers"] == 1
    assert repository.stats()["offerings"] == 1
    with repository.sessions() as session:
        assert session.get(ProviderRow, provider.provider_id).wallet_address is None
    listed = client.get("/merchant/candidates", headers=headers)
    assert listed.json()["count"] == 1
    other_wallet = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=merchant_headers(repository, OTHER_WALLET),
    )
    assert other_wallet.status_code == 200


def test_claim_rejects_provider_owned_by_another_wallet(client, repository):
    _, candidate = store_candidate(repository, owner_wallet=OWNER_WALLET)

    response = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=merchant_headers(repository, OTHER_WALLET),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "provider ownership conflict"


def test_claim_allows_provider_already_owned_by_same_wallet(client, repository):
    _, candidate = store_candidate(repository, owner_wallet=OWNER_WALLET)

    response = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=merchant_headers(repository, OWNER_WALLET),
    )

    assert response.status_code == 200


def test_claim_draft_does_not_bypass_manifest_claim_or_verification(client, repository):
    provider, candidate = store_candidate(repository)
    headers = merchant_headers(repository)
    draft = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft", headers=headers
    )

    assert draft.status_code == 200
    assert "manifest_id" not in draft.json()
    assert repository.get_provider(provider.provider_id).status == "discovered"
    assert repository.get_offering(candidate.offering_id).status == "discovered"

    submitted = client.post(
        "/merchant/manifests", headers=headers, json=draft.json()["manifest"]
    )
    challenge = client.post(
        f"/merchant/manifests/{submitted.json()['manifest_id']}/claim-challenge",
        headers=headers,
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert challenge.status_code == 200
    assert repository.get_provider(provider.provider_id).status == "discovered"
    assert repository.get_offering(candidate.offering_id).status == "discovered"


def test_bazaar_rows_materialize_only_from_successful_candidate_manifest(
    client, repository, monkeypatch
):
    account = Account.create()
    provider, candidate = store_candidate(repository)
    headers = merchant_headers(repository, account.address)
    manifest = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=headers,
    ).json()["manifest"]
    submitted = client.post("/merchant/manifests", headers=headers, json=manifest)
    manifest_id = submitted.json()["manifest_id"]
    challenge = client.post(
        f"/merchant/manifests/{manifest_id}/claim-challenge", headers=headers
    )
    claim = ManifestClaim.model_validate(challenge.json()["claim"])
    signature = Account.sign_message(
        encode_typed_data(full_message=claim.typed_data()), account.key
    ).signature.hex()

    wallet_verified = client.post(
        f"/merchant/manifests/{manifest_id}/submit-claim",
        headers=headers,
        json={
            "claim": claim.model_dump(mode="json"),
            "signature": signature,
            "wallet_address": account.address,
        },
    )
    monkeypatch.setattr(
        "services.domain_verification.DomainVerifier.verify",
        lambda _self, **payload: payload,
    )
    domain_verified = client.post(
        f"/merchant/providers/{provider.provider_id}/verify-domain",
        headers=headers,
    )

    assert submitted.status_code == wallet_verified.status_code == 200
    assert domain_verified.status_code == 200
    with repository.sessions() as session:
        provider_row = session.get(ProviderRow, provider.provider_id)
        offering_row = session.get(OfferingRow, candidate.offering_id)
        assert provider_row.wallet_address == account.address.lower()
        assert provider_row.status == "domain_verified"
        assert provider_row.payload["source"] == "clink_manifest"
        assert offering_row.status == "submitted"
        assert offering_row.payload["metadata"] == {
            "claim_source": "cdp_bazaar",
            "claimed_offering_id": candidate.offering_id,
        }

def test_manifest_submission_is_idempotent_for_same_owner(client, repository):
    _, candidate = store_candidate(repository)
    headers = merchant_headers(repository)
    manifest = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=headers,
    ).json()["manifest"]

    first = client.post("/merchant/manifests", headers=headers, json=manifest)
    second = client.post("/merchant/manifests", headers=headers, json=manifest)

    assert first.status_code == second.status_code == 200
    assert first.json()["manifest_id"] == second.json()["manifest_id"]
    with repository.sessions() as session:
        assert len(session.scalars(select(ManifestRow)).all()) == 1


def test_same_manifest_hash_is_owner_scoped(client, repository):
    _, candidate = store_candidate(repository)
    owner_headers = merchant_headers(repository)
    manifest = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=owner_headers,
    ).json()["manifest"]
    first = client.post("/merchant/manifests", headers=owner_headers, json=manifest)

    reused = client.post(
        "/merchant/manifests",
        headers=merchant_headers(repository, OTHER_WALLET),
        json=manifest,
    )

    assert first.status_code == 200
    assert reused.status_code == 200
    assert reused.json()["manifest_id"] != first.json()["manifest_id"]
    assert reused.json()["manifest_hash"] == first.json()["manifest_hash"]
    with repository.sessions() as session:
        assert len(session.scalars(select(ManifestRow)).all()) == 2
        assert session.get(ProviderRow, manifest["provider"]["provider_id"]).status == "discovered"
        assert session.get(OfferingRow, candidate.offering_id).status == "discovered"


def test_verified_bazaar_offering_cannot_be_claimed_as_candidate(client, repository):
    _, candidate = store_candidate(repository, status="verified")

    response = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers=merchant_headers(repository),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "candidate not found"
