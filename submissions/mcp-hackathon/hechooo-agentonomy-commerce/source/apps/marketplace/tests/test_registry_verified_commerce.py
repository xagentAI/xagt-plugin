from datetime import UTC, datetime

import pytest

from services.marketplace_repository import MarketplaceRepository
from services.candidate_service import CandidateService
from services.purchase_service import PurchaseService
from shared.models import PaymentOption, Provider, ServiceOffering


def make_repository(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return MarketplaceRepository(f"sqlite+pysqlite:///{tmp_path / 'market.db'}")


def bazaar_candidate(provider, *, price="0.05"):
    return ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://risk.example/check",
        name="Wallet risk check",
        endpoint="https://risk.example/check",
        method="POST",
        status="discovered",
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                amount_atomic=str(int(float(price) * 1_000_000)),
                pay_to="0x" + "3" * 40,
                price_usd=price,
            )
        ],
    )


def store_candidate(repository, *, price="0.05"):
    provider = Provider(
        name="Bazaar Risk",
        domain="risk.example",
        source="cdp_bazaar",
        status="discovered",
    )
    offering = bazaar_candidate(provider, price=price)
    repository.upsert_provider(provider)
    repository.upsert_offering(offering)
    repository.add_provenance(
        offering.offering_id,
        "cdp_bazaar",
        offering.source_id,
        offering.model_dump(mode="json"),
    )
    return provider, offering


def verify_candidate(repository, offering):
    snapshot = repository.get_offering_verification_snapshot(offering.offering_id)
    return repository.complete_offering_verification(
        offering.offering_id,
        True,
        expected_payload_hash=snapshot[1],
        checked_at=datetime.now(UTC),
    )


def test_unclaimed_bazaar_candidate_is_due_and_promoted_to_registry_verified(tmp_path):
    repository = make_repository(tmp_path)
    provider, offering = store_candidate(repository)

    assert [item.offering_id for item in repository.due_offerings(datetime.now(UTC))] == [
        offering.offering_id
    ]

    completion = verify_candidate(repository, offering)
    promoted = repository.get_offering(offering.offering_id)

    assert completion["status"] == "registry_verified"
    assert promoted.status == "registry_verified"
    assert promoted.metadata["trust_tier"] == "registry_verified"
    assert repository.get_provider(provider.provider_id).status == "discovered"


def test_discovered_offering_without_registry_provenance_cannot_be_promoted(tmp_path):
    repository = make_repository(tmp_path)
    provider = Provider(
        name="Unproven",
        domain="unproven.example",
        source="unknown",
        status="discovered",
    )
    offering = bazaar_candidate(provider)
    repository.upsert_provider(provider)
    repository.upsert_offering(offering)
    snapshot = repository.get_offering_verification_snapshot(offering.offering_id)

    result = repository.complete_offering_verification(
        offering.offering_id,
        True,
        expected_payload_hash=snapshot[1],
    )

    assert result["applied"] is False
    assert result["reason"] == "registry_provenance_required"
    assert repository.get_offering(offering.offering_id).status == "discovered"


def test_registry_verified_offering_is_public_with_explicit_trust_tier(tmp_path):
    repository = make_repository(tmp_path)
    _, offering = store_candidate(repository)
    verify_candidate(repository, offering)

    results = repository.search("wallet risk")

    assert len(results) == 1
    assert results[0].metadata["trust_tier"] == "registry_verified"
    assert repository.active_offering(offering.offering_id) is not None


def test_registry_verified_purchase_is_external_and_capped(tmp_path):
    repository = make_repository(tmp_path)
    provider, offering = store_candidate(repository)
    verify_candidate(repository, offering)
    service = PurchaseService(
        repository,
        core=object(),
        native_provider_ids={provider.provider_id},
        registry_verified_max_price_usd="0.10",
    )

    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"address": "0x" + "1" * 40},
    )

    assert preview.execution_mode == "external_x402_signature"
    assert preview.payment_capability == {
        "rail": "external_x402_signature",
        "mandate_compatible": False,
        "auto_pay_compatible": False,
        "requires_purchase_signature": True,
        "reason_code": "MERCHANT_SCOPED_EIP3009_SIGNATURE_REQUIRED",
    }

    expensive_repository = make_repository(tmp_path / "expensive")
    _, expensive = store_candidate(expensive_repository, price="0.11")
    verify_candidate(expensive_repository, expensive)
    expensive_service = PurchaseService(
        expensive_repository,
        core=object(),
        registry_verified_max_price_usd="0.10",
    )
    with pytest.raises(ValueError, match="registry-verified offering exceeds"):
        expensive_service.create_preview(
            user_id="user",
            offering_id=expensive.offering_id,
            service_input={"address": "0x" + "1" * 40},
        )


def test_registry_verified_notify_all_mandate_requires_explicit_confirmation(tmp_path):
    class Core:
        def resolve_authorization(self, payload):
            assert payload["merchant_trust_tier"] == "registry_verified"
            return {
                "ready": True,
                "authorization_rail": "external_x402",
                "wallet_identity_id": "wallet_identity_1",
                "spending_grant_id": "spending_grant_1",
                "notification_mode": "notify_all",
                "user_interaction_required": True,
                "interaction_reason_code": "NOTIFICATION_POLICY_REQUIRES_CONFIRMATION",
            }

        def create_action(self, _payload):
            raise AssertionError("action must wait for the configured notification confirmation")

    repository = make_repository(tmp_path)
    _, offering = store_candidate(repository)
    verify_candidate(repository, offering)
    service = PurchaseService(repository, Core())
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"address": "0x" + "1" * 40},
    )

    result = service.execute(preview.preview_id, user_confirmed=False)

    assert result.state == "confirmation_required"
    assert result.reason_code == "NOTIFICATION_POLICY_REQUIRES_CONFIRMATION"


def test_registry_verified_confirmation_requires_unified_spending_grant(tmp_path):
    class Core:
        def __init__(self):
            self.action_created = False

        def resolve_authorization(self, _payload):
            return {
                "ready": False,
                "reason_code": "SPENDING_GRANT_REQUIRED",
                "next_action": "create_spending_grant",
            }

        def create_account_session(self, user_id):
            assert user_id == "user"
            return {
                "account_url": "https://core.clink.example/account/session",
                "expires_at": "2030-01-01T00:00:00Z",
            }

        def create_action(self, _payload):
            self.action_created = True
            raise AssertionError("action must not be created without spending grant")

    repository = make_repository(tmp_path)
    _, offering = store_candidate(repository)
    verify_candidate(repository, offering)
    core = Core()
    service = PurchaseService(repository, core)
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"address": "0x" + "1" * 40},
    )

    result = service.execute(preview.preview_id, user_confirmed=True)

    assert result.state == "confirmation_required"
    assert result.reason_code == "SPENDING_GRANT_REQUIRED"
    assert result["purchase"].metadata["account_url"] == (
        "https://core.clink.example/account/session"
    )
    assert core.action_created is False


def test_registry_verified_confirmation_reserves_unified_external_x402_budget(tmp_path):
    class Core:
        def __init__(self):
            self.reserve_payload = None

        def resolve_authorization(self, payload):
            assert payload["authorization_rail"] == "external_x402"
            assert payload["product"] == "marketplace"
            assert payload["merchant_trust_tier"] == "registry_verified"
            return {
                "ready": True,
                "authorization_rail": "external_x402",
                "wallet_identity_id": "wallet_identity_1",
                "spending_grant_id": "spending_grant_1",
                "notification_mode": "silent_under_limits",
                "user_interaction_required": True,
                "interaction_reason_code": "EXTERNAL_X402_SIGNATURE_REQUIRED",
                "next_action": "create_action_and_evaluate_policy",
            }

        def create_action(self, _payload):
            return {"action_id": "action_1"}

        def evaluate_policy(self, _payload):
            return {"policy_decision_id": "policy_1", "approved": True}

        def update_action(self, *_args, **_kwargs):
            return {}

        def audit(self, _payload):
            return {"event_id": "audit_1"}

        def reserve(self, payload):
            self.reserve_payload = payload
            return {
                "reservation_id": "reserve_1",
                "nonce": "0x" + "9" * 64,
                "valid_after": "100",
                "valid_before": "200",
            }

    repository = make_repository(tmp_path)
    _, offering = store_candidate(repository)
    verify_candidate(repository, offering)
    core = Core()
    service = PurchaseService(
        repository,
        core,
        public_base_url="https://marketplace.clink.example",
    )
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"address": "0x" + "1" * 40},
    )

    result = service.execute(preview.preview_id, user_confirmed=False)

    assert result.state == "signing_required"
    assert result.reason_code == "EXTERNAL_X402_SIGNATURE_REQUIRED"
    signing_url = result["purchase"].metadata["signing_url"]
    assert signing_url.startswith(
        "https://marketplace.clink.example/x402/checkout/purchase_"
    )
    assert "#token=" in signing_url
    assert core.reserve_payload["spending_authorization_id"] is None
    assert core.reserve_payload["authorization_rail"] == "external_x402"
    assert core.reserve_payload["merchant_trust_tier"] == "registry_verified"
    assert core.reserve_payload["wallet_identity_id"] == "wallet_identity_1"
    assert core.reserve_payload["spending_grant_id"] == "spending_grant_1"
    assert core.reserve_payload["asset_allowance_id"] is None
    assert core.reserve_payload["product"] == "marketplace"


def test_registry_verified_offering_can_be_claimed_without_duplicate(tmp_path):
    repository = make_repository(tmp_path)
    provider, offering = store_candidate(repository)
    verify_candidate(repository, offering)

    draft = CandidateService(repository).create_manifest_draft(
        offering.offering_id,
        "0x" + "4" * 40,
    )

    assert draft.provider.provider_id == provider.provider_id
    assert draft.offerings[0].endpoint == offering.endpoint
    assert draft.offerings[0].metadata["claimed_offering_id"] == offering.offering_id
