from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.account_service.repository import AccountRepository
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity, AuthorizationResolutionRequest
from services.account_service.service import AccountService
from services.funding_service.schemas import CreateDirectTransferRequest
from services.funding_service.service import FundingService
from shared.config import AppConfig
from shared.hosted_facilitator_protocol import DeviceSigningKey

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
DEST = "0x" + "2" * 40
SPENDER = "0x" + "3" * 40
NETWORK = "eip155:8453"


def setup_service(tmp_path, monkeypatch, products=None, **config_changes):
    from services.funding_service.transfer_service import DirectTransferService

    now = datetime.now(UTC)
    url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = AppConfig(funding_database_url=url, clink_direct_transfers_enabled=True,
        clink_facilitator_mode="hosted", clink_hosted_facilitator_chain_targets={
            NETWORK: {"origin": "https://hosted.example", "executor_contract": SPENDER,
                      "server_public_jwk": DeviceSigningKey.generate().public_jwk}},
        **config_changes)
    repo = AccountRepository(url)
    repo.save_wallet_identity(WalletIdentity(wallet_identity_id="wallet_1", user_id="u", wallet_address="0x" + "1" * 40,
        status="active", proof_hash="test-proof", verified_at=now, created_at=now, updated_at=now))
    repo.save_spending_grant(SpendingGrant(spending_grant_id="grant_1", wallet_identity_id="wallet_1", user_id="u",
        agent_id="hermes", status="active", max_amount_usdc=Decimal("20"), per_transaction_limit_usdc=Decimal("5"),
        hourly_limit_usdc=Decimal("5"), daily_limit_usdc=Decimal("20"), product_scopes=products or ["marketplace", "transfers"],
        venue_scopes=["clink_marketplace", "clink_transfers"], network_scopes=[NETWORK], asset_scopes=[TOKEN], notification_mode="silent_under_limits",
        starts_at=now-timedelta(days=1), expires_at=now+timedelta(days=7), created_at=now, updated_at=now))
    repo.save_asset_allowance(AssetAllowance(asset_allowance_id="allow_1", wallet_identity_id="wallet_1", network=NETWORK,
        token_address=TOKEN, token_symbol="USDC", token_decimals=6, spender_address=SPENDER,
        approved_amount_atomic=20000000, observed_allowance_atomic=20000000, status="active", confirmed_block=1,
        last_chain_check_at=now, created_at=now, updated_at=now))
    account = AccountService(repo, domain="https://dev.example")
    funding = FundingService(config=config, storage_file=tmp_path / "funding.jsonl")
    # Isolate the external settlement boundary; real policy, audit, resolution and ledger remain active.
    calls = []
    def settle(reservation_id, request):
        calls.append((reservation_id, request.payment_authorization))
        return funding.get_reservation(reservation_id)
    monkeypatch.setattr(funding, "settle_reservation", settle)
    service = DirectTransferService(funding, resolve_authorization=lambda payload:
        account.resolve_authorization(AuthorizationResolutionRequest(**payload)).model_dump(mode="json"))
    return service, funding, repo, calls


def command(**updates):
    return CreateDirectTransferRequest(user_id="u", agent_id="hermes", request_id="test-1", to_address=DEST,
        network=NETWORK, amount_usdc="2", **updates)


def test_transfer_reserves_real_shared_budget_and_has_honest_provenance(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    result = service.create(command())
    row = funding.get_reservation(result["reservation_id"])
    assert row["product"] == "transfers"
    assert row["venue"] == "clink_transfers"
    assert row["merchant_id"] == DEST
    assert row.get("merchant_trust_tier") is None
    assert row["amount_atomic"] == "2000000"
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert calls[0][1]["kind"] == "direct_transfer"
    assert result["status"] != "succeeded"
    assert "payment_capability" not in result


def test_old_marketplace_authority_cannot_transfer(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch, products=["marketplace"])
    result = service.create(command())
    assert result["reason_code"] == "PRODUCT_SCOPE_MISMATCH"
    assert calls == []
    assert repo.spending_grant("grant_1").reserved_amount_usdc == 0
    assert funding.ledger.list_records("reservation") == []


def test_replay_uses_same_reservation_and_budget(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    one = service.create(command())
    two = service.create(command())
    assert one["transfer_id"] == two["transfer_id"]
    assert one["reservation_id"] == two["reservation_id"]
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert len(funding.ledger.list_records("reservation")) == 1


def test_request_id_cannot_change_recipient_or_amount(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    service.create(command())
    with pytest.raises(ValueError, match="TRANSFER_REQUEST_CONFLICT"):
        service.create(command().model_copy(update={"amount_usdc": "3"}))
    with pytest.raises(ValueError, match="TRANSFER_REQUEST_CONFLICT"):
        service.create(command().model_copy(update={"to_address": "0x" + "4" * 40}))
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")


def test_get_is_owner_bound_and_never_creates_execution(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    first = service.create(command())
    with pytest.raises(ValueError, match="TRANSFER_NOT_FOUND"):
        service.get(first["transfer_id"], user_id="other", agent_id="hermes")
    result = service.get(first["transfer_id"], user_id="u", agent_id="hermes")
    assert result["transfer_id"] == first["transfer_id"]
    assert len(calls) == 1


def test_current_destination_policy_still_blocks(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch, funding_destination_denylist=(DEST,))
    result = service.create(command())
    assert result["reason_code"] == "DESTINATION_DENYLISTED"
    assert not calls
    assert repo.spending_grant("grant_1").reserved_amount_usdc == 0


def test_internal_transfer_routes_require_core_token_and_owner(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL", funding.config.funding_database_url)
    from services.funding_service import app as funding_app
    funding.config.clink_internal_api_token = "test-internal-token"
    monkeypatch.setattr(funding_app, "APP_CONFIG", funding.config)
    monkeypatch.setattr(funding_app, "SERVICE", funding)
    monkeypatch.setattr(funding_app, "DirectTransferService", lambda _: service, raising=False)
    client = TestClient(funding_app.create_app())
    assert client.post("/funding/transfers", json=command().model_dump()).status_code == 401
    headers = {"Authorization": "Bearer test-internal-token"}
    result = client.post("/funding/transfers", json=command().model_dump(), headers=headers)
    assert result.status_code == 200
    transfer_id = result.json()["transfer_id"]
    assert client.get(f"/funding/transfers/{transfer_id}", params={"user_id": "other", "agent_id": "hermes"}, headers=headers).status_code == 404
    assert client.get(f"/funding/transfers/{transfer_id}", params={"user_id": "u", "agent_id": "hermes"}, headers=headers).status_code == 200


def test_policy_revalidation_keeps_opc_installation_binding(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    result = service.create(command())
    row = funding.get_reservation(result["reservation_id"])
    row["opc_installation_id"] = "opc_" + "a" * 40
    assert funding._policy_metadata_from_reservation(row)["opc_installation_id"] == row["opc_installation_id"]


def test_simultaneous_duplicate_returns_in_progress_without_second_prepare(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    original = service.resolve_authorization
    def blocked_resolver(payload):
        entered.set()
        assert release.wait(5)
        return original(payload)
    service.resolve_authorization = blocked_resolver
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.create, command())
        assert entered.wait(5)
        try:
            duplicate = service.create(command())
            assert duplicate["reason_code"] == "TRANSFER_IN_PROGRESS"
            assert not calls
        finally:
            release.set()
        final = pending.result(timeout=5)
    assert final["reservation_id"]
    assert len(calls) == 1
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")


def test_expired_claim_cannot_overwrite_or_submit_newer_operation(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    original = service.resolve_authorization
    def blocked_resolver(payload):
        entered.set()
        assert release.wait(5)
        return original(payload)
    service.resolve_authorization = blocked_resolver
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.create, command())
        assert entered.wait(5)
        try:
            service.resolve_authorization = original
            service.clock = lambda: datetime.now(UTC) + timedelta(minutes=6)
            newer = service.create(command())
            assert newer["reservation_id"]
        finally:
            release.set()
        older = pending.result(timeout=5)
    assert older["reservation_id"] == newer["reservation_id"]
    assert len(calls) == 1
    assert len(funding.ledger.list_records("reservation")) == 1
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")


def test_switch_off_does_not_create_or_reserve(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    funding.config.clink_direct_transfers_enabled = False
    with pytest.raises(ValueError, match="DIRECT_TRANSFERS_DISABLED"):
        service.create(command())
    assert funding.ledger.list_records("direct_transfer") == []
    assert not calls


def test_opc_installation_in_request_is_not_treated_as_authorized(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    result = service.create(command(opc_installation_id="opc_" + "a" * 40))
    assert result["reason_code"] == "OPC_INSTALLATION_NOT_READY"
    assert not calls
    assert repo.spending_grant("grant_1").reserved_amount_usdc == 0


def test_transfer_and_marketplace_share_hourly_budget(tmp_path, monkeypatch):
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    service.create(command())
    marketplace = service.resolve_authorization({
        "user_id": "u", "agent_id": "hermes", "authorization_rail": "native_allowance",
        "product": "marketplace", "venue": "clink_marketplace", "merchant": "merchant",
        "merchant_trust_tier": "clink_verified", "network": NETWORK, "token_address": TOKEN,
        "spender_address": SPENDER, "amount_usdc": "4", "destination": DEST,
        "resource": "https://merchant.example/service",
    })
    assert marketplace["ready"] is False
    assert marketplace["reason_code"] == "HOURLY_LIMIT_EXCEEDED"


def test_account_transport_uses_internal_bearer_and_no_redirects(tmp_path, monkeypatch):
    import httpx
    service, funding, repo, calls = setup_service(tmp_path, monkeypatch)
    funding.config.clink_internal_api_token = "test-internal-only"
    observed = []
    def post(url, **kwargs):
        observed.append((url, kwargs))
        return httpx.Response(200, json={"ready": False, "reason_code": "SPENDING_GRANT_REQUIRED"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    result = service._resolve_over_http({"user_id": "u"})
    assert result["ready"] is False
    assert observed[0][0] == funding.config.account_service_url + "/internal/authorization-resolution"
    assert observed[0][1]["headers"] == {"Authorization": "Bearer test-internal-only"}
    assert observed[0][1]["follow_redirects"] is False
