"""Offline integration: real Core state machine, simulated external Hosted/Watcher."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from services.funding_service.schemas import CreateDirectTransferRequest
from services.funding_service.service import FundingService
from services.policy_service.risk_provider import RiskProviderResult
from test_direct_transfer_service import setup_service, command, NETWORK
from test_task_2b_hosted_routing import _RecordingHostedClient


class RiskProvider:
    def __init__(self, score=0):
        self.score = score

    def assess(self, *, subject, network, asset="USDC"):
        now = datetime.now(UTC)
        return RiskProviderResult(provider="misttrack", endpoint="v2/risk_score", subject=subject,
            network=network, asset=asset, coin="USDC-Base", score=self.score,
            risk_level="severe" if self.score >= 91 else "moderate" if self.score >= 31 else "low",
            indicators=(), risk_details=(), hacking_event=None, assessed_at=now,
            expires_at=now+timedelta(minutes=5), response_sha256="a" * 64)


def hosted_context(tmp_path, monkeypatch, **client_options):
    service, funding, repo, _ = setup_service(tmp_path, monkeypatch)
    monkeypatch.setattr(funding, "settle_reservation", FundingService.settle_reservation.__get__(funding))
    funding.config.clink_live_funding = True
    funding.config.risk_mode = "enforce"
    funding.config.clink_receipt_signing_key = "direct-transfer-test-receipt-key-not-for-production"
    funding.config.clink_hosted_facilitator_tenant_id = "tenant_1"
    funding.config.clink_hosted_facilitator_node_id = "node_1"
    funding.config.clink_hosted_facilitator_wallet_binding_id = "binding_1"
    funding.policy_service.risk_provider = RiskProvider()
    client = _RecordingHostedClient(NETWORK, **client_options)
    client._delegate._clock = lambda: int(datetime.now(UTC).timestamp())
    funding.hosted_clients = MappingProxyType({NETWORK: client})
    return service, funding, repo, client


def test_real_core_hosted_watcher_settlement_and_replay(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch, recover_state="finalized")
    first = service.create(command())
    assert first["status"] == "pending", first["reason_code"]
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert repo.spending_grant("grant_1").used_amount_usdc == 0
    final = service.get(first["transfer_id"], user_id="u", agent_id="hermes")
    assert final["status"] == "succeeded", final
    assert final["tx_hash"] and final["receipt_id"]
    assert repo.spending_grant("grant_1").reserved_amount_usdc == 0
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("2")
    replay = service.create(command())
    assert replay == final
    assert len(client.submit_calls) == 1
    assert len(funding.ledger.list_records("reservation")) == 1
    assert funding.get_reservation(first["reservation_id"])["hosted_watcher_evidence"]["state"] == "finalized"


def test_unknown_post_recovers_by_original_id_without_resubmit(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch,
        submit_unknown=True, lookup_state="finalized")
    first = service.create(command())
    assert first["status"] == "pending", first
    assert first["next_action"] == "query_transfer"
    final = service.create(command())
    assert final["status"] == "succeeded", final
    assert len(client.submit_calls) == 1
    assert len(client.lookup_calls) == 1
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("2")


def test_definitive_lookup_miss_rearms_same_transfer_after_safety_delay(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(
        tmp_path,
        monkeypatch,
        submit_unknown=True,
        lookup_not_found=True,
    )
    first = service.create(command())
    assert first["status"] == "pending", first
    assert len(client.submit_calls) == 1

    service.clock = lambda: datetime.now(UTC) + timedelta(minutes=6)
    rearmed = service.create(command())
    assert rearmed["status"] == "reserved", rearmed
    assert rearmed["next_action"] == "retry_same_request"
    assert len(client.submit_calls) == 1

    client.submit_unknown = False
    retried = service.create(command())
    assert retried["transfer_id"] == first["transfer_id"]
    assert retried["reservation_id"] == first["reservation_id"]
    assert retried["status"] == "pending", retried
    assert len(client.submit_calls) == 2
    assert len(funding.ledger.list_records("reservation")) == 1
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")


@pytest.mark.parametrize("score,reason", [(99, "RISK_PROVIDER_DENIED"), (40, "RISK_PROVIDER_HOLD")])
def test_real_policy_blocks_denied_or_hold_without_agent_self_confirmation(tmp_path, monkeypatch, score, reason):
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch)
    funding.policy_service.risk_provider = RiskProvider(score)
    result = service.create(command())
    assert result["reason_code"] == reason
    assert not client.submit_calls
    assert repo.spending_grant("grant_1").reserved_amount_usdc == 0


def test_forged_finalized_watcher_amount_cannot_settle(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch,
        recover_state="finalized", recover_updates={"amount_atomic": "3000000"})
    first = service.create(command())
    assert first["status"] == "pending", first
    result = service.get(first["transfer_id"], user_id="u", agent_id="hermes")
    assert result["status"] != "succeeded"
    assert repo.spending_grant("grant_1").used_amount_usdc == 0
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")


def test_crash_after_hosted_acceptance_only_recovers_never_posts_again(tmp_path, monkeypatch):
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch, lookup_state="finalized")
    original = client.submit
    def crash(request):
        original(request)
        raise SystemExit("simulated process exit after external acceptance")
    monkeypatch.setattr(client, "submit", crash)
    with pytest.raises(SystemExit):
        service.create(command())
    monkeypatch.setattr(client, "submit", original)
    recovered = service.create(command())
    assert recovered["status"] == "succeeded", recovered["reason_code"]
    assert len(client.submit_calls) == 1
    assert len(client.lookup_calls) == 1
    assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("2")


def test_registry_drift_does_not_rewrite_original_transfer(tmp_path, monkeypatch):
    from shared.canonical_assets import CanonicalAssetRegistry
    service, funding, repo, client = hosted_context(tmp_path, monkeypatch, recover_state="finalized")
    first = service.create(command())
    final = service.get(first["transfer_id"], user_id="u", agent_id="hermes")
    original_token = final["token_address"]
    funding.asset_registry = CanonicalAssetRegistry({NETWORK: "0x" + "9" * 40})
    with pytest.raises(ValueError, match="TRANSFER_ASSET_CONFIGURATION_CHANGED"):
        service.create(command())
    saved = service.get(first["transfer_id"], user_id="u", agent_id="hermes")
    assert saved["token_address"] == original_token
    assert len(client.submit_calls) == 1


def test_late_worker_after_lease_takeover_cannot_submit_twice(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service, funding, repo, client = hosted_context(tmp_path, monkeypatch)
    old_paused, release_old, new_submitted, release_new = (Event() for _ in range(4))
    original_capability, original_submit = funding._hosted_capability, client.submit
    calls = 0

    def pause_old(*args, **kwargs):
        nonlocal calls
        result = original_capability(*args, **kwargs)
        calls += 1
        if calls == 1:
            old_paused.set()
            assert release_old.wait(10)
        return result

    def pause_new(request):
        result = original_submit(request)
        new_submitted.set()
        if len(client.submit_calls) == 1:
            assert release_new.wait(10)
        return result

    monkeypatch.setattr(funding, "_hosted_capability", pause_old)
    monkeypatch.setattr(client, "submit", pause_new)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(service.create, command())
        try:
            assert old_paused.wait(10)
            service.clock = lambda: datetime.now(UTC) + timedelta(minutes=6)
            new = pool.submit(service.create, command())
            assert new_submitted.wait(10)
            release_old.set()
            old.result(timeout=5)
        finally:
            release_old.set()
            release_new.set()
        new.result(timeout=10)
    assert len(client.submit_calls) == 1
    assert len(funding.ledger.list_records("reservation")) == 1
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
