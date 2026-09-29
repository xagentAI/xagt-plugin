from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from sqlalchemy import update

from adapters.cdp_bazaar import CdpBazaarAdapter
from adapters.clink_peer import ClinkPeerAdapter
from services.marketplace_repository import MarketplaceRepository, WorkerStageRow
from services.purchase_service import PurchaseService
from services.registry_aggregation import RegistryAggregator
from services.marketplace_worker import run_cycle
from services.core_gateway import HttpCoreGateway
from shared.models import PaymentOption, Provider, ServiceOffering
from shared.config import AppConfig


def repository(tmp_path: Path) -> MarketplaceRepository:
    return MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'task6-production.sqlite3'}"
    )


def bazaar_resource(*, pay_to: str) -> dict:
    return {
        "resource": "https://risk.example/v1/check",
        "serviceName": "Risk API",
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:137",
                "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                "amount": "10000",
                "payTo": pay_to,
            }
        ],
    }


class BazaarPage:
    def __init__(self, resource: dict) -> None:
        self.resource = resource

    def fetch_page(self, *, offset, limit, etag):
        del limit, etag
        return {
            "items": [self.resource],
            "offset": offset,
            "count": 1,
            "total": 1,
        }

    def normalize_resource(self, resource):
        return CdpBazaarAdapter().normalize_resource(resource)


def verified_offering(provider: Provider) -> ServiceOffering:
    return ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id=f"POST https://{provider.domain}/v1/check",
        name="Risk API",
        endpoint=f"https://{provider.domain}/v1/check",
        method="POST",
        status="verified",
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                amount_atomic="10000",
                pay_to="0x" + "1" * 40,
            )
        ],
    )


def test_registry_pay_to_drift_delists_without_overwriting_verified_canonical(tmp_path):
    repo = repository(tmp_path)
    first = bazaar_resource(pay_to="0x" + "1" * 40)
    adapter = BazaarPage(first)
    aggregator = RegistryAggregator(repo, {"cdp_bazaar": adapter})
    assert aggregator.sync_registry("cdp_bazaar")["status"] == "succeeded"

    provider, offering = CdpBazaarAdapter().normalize_resource(first)
    repo.upsert_provider(provider.model_copy(update={"status": "active"}))
    repo.upsert_offering(
        offering.model_copy(update={"status": "verified"}),
        verified_at=datetime.now(UTC),
    )

    adapter.resource = bazaar_resource(pay_to="0x" + "2" * 40)
    assert aggregator.sync_registry("cdp_bazaar")["status"] == "succeeded"

    canonical = repo.get_offering(offering.offering_id)
    assert canonical.status == "verifying"
    assert canonical.payment_options[0].pay_to == "0x" + "1" * 40
    assert repo.search("Risk") == []
    candidate = repo.get_offering_verification_target(offering.offering_id)
    assert candidate.payment_options[0].pay_to == "0x" + "2" * 40


def test_suspending_provider_atomically_delists_and_stops_reverification(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(
        name="Risk Provider",
        domain="risk.example",
        source="merchant",
        status="active",
    )
    offering = verified_offering(provider)
    repo.upsert_provider(provider, wallet_address="0x" + "a" * 40)
    repo.upsert_offering(offering, verified_at=datetime.now(UTC))

    assert repo.suspend_provider(provider.provider_id)

    assert repo.search("Risk") == []
    assert repo.get_offering(offering.offering_id).status == "stale"
    assert repo.due_offerings(datetime.now(UTC) + timedelta(days=1)) == []


def test_purchase_preview_and_execute_require_provider_to_remain_active(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(
        name="Risk Provider",
        domain="risk.example",
        source="merchant",
        status="active",
    )
    offering = verified_offering(provider)
    repo.upsert_provider(provider, wallet_address="0x" + "a" * 40)
    repo.upsert_offering(offering, verified_at=datetime.now(UTC))
    service = PurchaseService(repo, core=object())
    preview = service.create_preview(
        user_id="user-1",
        offering_id=offering.offering_id,
        service_input={"subject": "0x" + "b" * 40},
    )

    assert repo.suspend_provider(provider.provider_id)

    with pytest.raises(ValueError, match="active provider"):
        service.create_preview(
            user_id="user-1",
            offering_id=offering.offering_id,
            service_input={"subject": "0x" + "b" * 40},
        )
    with pytest.raises(ValueError, match="active provider"):
        service.execute(preview.preview_id)


def test_restore_requires_domain_reverification_and_does_not_republish_offerings(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(
        name="Risk Provider",
        domain="risk.example",
        source="merchant",
        status="active",
    )
    offering = verified_offering(provider)
    repo.upsert_provider(provider, wallet_address="0x" + "a" * 40)
    repo.upsert_offering(offering, verified_at=datetime.now(UTC))
    assert repo.suspend_provider(provider.provider_id)

    restored = repo.restore_provider(provider.provider_id)

    assert restored == "wallet_verified"
    assert repo.get_provider(provider.provider_id).status == "wallet_verified"
    assert repo.get_offering(offering.offering_id).status == "stale"
    assert repo.search("Risk") == []


def test_successful_local_verification_promotes_registry_candidate(tmp_path):
    repo = repository(tmp_path)
    first = bazaar_resource(pay_to="0x" + "1" * 40)
    adapter = BazaarPage(first)
    aggregator = RegistryAggregator(repo, {"cdp_bazaar": adapter})
    aggregator.sync_registry("cdp_bazaar")
    provider, offering = CdpBazaarAdapter().normalize_resource(first)
    repo.upsert_provider(provider.model_copy(update={"status": "active"}))
    repo.upsert_offering(
        offering.model_copy(update={"status": "verified"}),
        verified_at=datetime.now(UTC),
    )
    adapter.resource = bazaar_resource(pay_to="0x" + "2" * 40)
    aggregator.sync_registry("cdp_bazaar")

    class Verifier:
        def verify(self, candidate):
            assert candidate.payment_options[0].pay_to == "0x" + "2" * 40
            return SimpleNamespace(verified=True)

    run_cycle(
        repo,
        registry_aggregator=SimpleNamespace(sync=lambda: []),
        verifier=Verifier(),
        domain_verifier=object(),
        worker_id="host-startup",
    )

    promoted = repo.get_offering(offering.offering_id)
    assert promoted.status == "verified"
    assert promoted.payment_options[0].pay_to == "0x" + "2" * 40
    assert repo.search("Risk")[0].payment_options[0].pay_to == "0x" + "2" * 40


def test_failed_offering_verification_is_throttled_by_attempt_time(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(name="Risk", domain="risk.example", source="merchant", status="active")
    offering = verified_offering(provider).model_copy(update={"status": "stale"})
    repo.upsert_provider(provider, wallet_address="0x" + "a" * 40)
    repo.upsert_offering(offering)
    calls = []

    class Verifier:
        def verify(self, candidate):
            calls.append(candidate.offering_id)
            return SimpleNamespace(verified=False)

    kwargs = dict(
        repository=repo,
        registry_aggregator=SimpleNamespace(sync=lambda: []),
        verifier=Verifier(),
        domain_verifier=object(),
        worker_id="host-startup",
        offering_verify_interval_seconds=900,
    )
    run_cycle(**kwargs)
    run_cycle(**kwargs)

    assert calls == [offering.offering_id]


def test_failed_domain_verification_is_throttled_by_attempt_time(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(name="Risk", domain="risk.example", source="merchant", status="active")
    repo.upsert_provider(provider, wallet_address="0x" + "a" * 40)
    calls = []

    class DomainVerifier:
        def verify(self, **kwargs):
            calls.append(kwargs["provider_id"])
            raise RuntimeError("domain unavailable")

    kwargs = dict(
        repository=repo,
        registry_aggregator=SimpleNamespace(sync=lambda: []),
        verifier=object(),
        domain_verifier=DomainVerifier(),
        worker_id="host-startup",
        domain_verify_interval_seconds=86400,
    )
    run_cycle(**kwargs)
    run_cycle(**kwargs)

    assert calls == [provider.provider_id]
    assert repo.get_provider(provider.provider_id).status == "active"


def test_worker_stage_completion_is_fenced_by_cycle_token(tmp_path):
    repo = repository(tmp_path)
    repo.start_worker_stage("host-startup", "registry_sync", "cycle-old")
    repo.start_worker_stage("host-startup", "registry_sync", "cycle-new")

    assert not repo.complete_worker_stage(
        "host-startup", "registry_sync", "cycle-old", "succeeded"
    )
    assert repo.complete_worker_stage(
        "host-startup", "registry_sync", "cycle-new", "succeeded"
    )
    assert repo.worker_stage_health("host-startup")["registry_sync"]["status"] == "succeeded"


def test_worker_health_degrades_for_failed_missing_and_timed_out_stages(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory[:-1]:
        repo.start_worker_stage("host-startup", stage, "cycle-1")
        repo.complete_worker_stage("host-startup", stage, "cycle-1", "succeeded")

    missing = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)
    assert missing["status"] == "degraded"
    assert missing["stages"]["purchase_finalization"]["status"] == "missing"

    repo.start_worker_stage("host-startup", "purchase_finalization", "cycle-1")
    failed = repo.complete_worker_stage(
        "host-startup", "purchase_finalization", "cycle-1", "failed", last_error="Core down"
    )
    assert failed
    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)
    assert health["status"] == "degraded"


def test_worker_health_requires_all_mandatory_stages_from_same_completed_cycle(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory:
        repo.start_worker_stage("host-startup", stage, "cycle-1")
        repo.complete_worker_stage("host-startup", stage, "cycle-1", "succeeded")
    repo.start_worker_stage("host-startup", "registry_sync", "cycle-2")

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "ok"
    assert health["cycle_status"] == "running"


def test_worker_health_accepts_one_token_when_final_stage_is_running(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory[:-1]:
        repo.start_worker_stage("host-startup", stage, "cycle-1")
        repo.complete_worker_stage("host-startup", stage, "cycle-1", "succeeded")
    repo.start_worker_stage("host-startup", mandatory[-1], "cycle-1")

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "ok"
    assert health["cycle_status"] == "running"


def test_worker_health_uses_mandatory_order_for_two_token_rolling_cycle(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory:
        repo.start_worker_stage("host-startup", stage, "cycle-1")
        repo.complete_worker_stage("host-startup", stage, "cycle-1", "succeeded")
    repo.start_worker_stage("host-startup", mandatory[0], "cycle-2")
    with repo.sessions.begin() as session:
        session.execute(
            update(WorkerStageRow)
            .where(
                WorkerStageRow.worker_id == "host-startup",
                WorkerStageRow.cycle_token == "cycle-1",
            )
            .values(updated_at=datetime.now(UTC) + timedelta(seconds=1))
        )

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "ok"
    assert health["cycle_status"] == "running"


def test_worker_health_rejects_reverse_order_within_current_token_prefix(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory:
        repo.start_worker_stage("host-startup", stage, "cycle-old")
        repo.complete_worker_stage("host-startup", stage, "cycle-old", "succeeded")
    repo.start_worker_stage("host-startup", "offering_verify", "cycle-new")
    repo.complete_worker_stage("host-startup", "offering_verify", "cycle-new", "succeeded")
    repo.start_worker_stage("host-startup", "registry_sync", "cycle-new")
    repo.complete_worker_stage("host-startup", "registry_sync", "cycle-new", "succeeded")

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "degraded"
    assert health["cycle_status"] == "incomplete"


def test_worker_health_rejects_old_token_prefix_with_later_new_suffix(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory[:2]:
        repo.start_worker_stage("host-startup", stage, "cycle-old")
        repo.complete_worker_stage("host-startup", stage, "cycle-old", "succeeded")
    for stage in mandatory[2:]:
        repo.start_worker_stage("host-startup", stage, "cycle-new")
        repo.complete_worker_stage("host-startup", stage, "cycle-new", "succeeded")

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "degraded"
    assert health["cycle_status"] == "incomplete"


def test_worker_health_rejects_non_contiguous_current_token(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage, token in zip(
        mandatory,
        ("cycle-new", "cycle-old", "cycle-new", "cycle-old"),
    ):
        repo.start_worker_stage("host-startup", stage, token)
        repo.complete_worker_stage("host-startup", stage, token, "succeeded")

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "degraded"
    assert health["cycle_status"] == "incomplete"


def test_worker_health_marks_running_stage_timed_out(tmp_path):
    mandatory = ("registry_sync", "offering_verify", "domain_verify", "purchase_finalization")
    repo = repository(tmp_path)
    repo.heartbeat("host-startup", "running")
    for stage in mandatory[:-1]:
        repo.start_worker_stage("host-startup", stage, "cycle-1")
        repo.complete_worker_stage("host-startup", stage, "cycle-1", "succeeded")
    final_stage = mandatory[-1]
    repo.start_worker_stage("host-startup", final_stage, "cycle-1")
    timed_out_at = datetime.now(UTC) - timedelta(seconds=31)
    with repo.sessions.begin() as session:
        session.execute(
            update(WorkerStageRow)
            .where(
                WorkerStageRow.worker_id == "host-startup",
                WorkerStageRow.stage == final_stage,
                WorkerStageRow.cycle_token == "cycle-1",
            )
            .values(started_at=timed_out_at, updated_at=timed_out_at)
        )

    health = repo.worker_health(180, stage_timeout_seconds=30, mandatory_stages=mandatory)

    assert health["status"] == "degraded"
    assert health["cycle_status"] == "incomplete"
    assert health["stages"][final_stage]["status"] == "timed_out"


def test_finalization_claim_loss_marks_worker_stage_failed(tmp_path):
    repo = repository(tmp_path)
    repo.claim_finalizations = lambda: [{
        "outbox_id": 1,
        "purchase_id": "purchase-1",
        "target_state": "delivered",
        "payload": {},
        "claim_token": "claim-unique",
    }]
    repo.finish_finalization = lambda *_args, **_kwargs: False
    stages = run_cycle(
        repo,
        registry_aggregator=SimpleNamespace(sync=lambda: []),
        verifier=object(),
        domain_verifier=object(),
        purchases=SimpleNamespace(process_finalization=lambda _item: None),
        worker_id="host-startup",
    )

    assert stages["purchase_finalization"]["status"] == "failed"
    assert "claim lost" in stages["purchase_finalization"]["last_error"]


def test_core_health_has_short_concurrent_deadline_without_changing_write_client():
    class SlowClient:
        def get(self, *_args, **_kwargs):
            time.sleep(0.25)
            raise RuntimeError("unavailable")

        def post(self, *_args, **_kwargs):
            raise AssertionError("health must not use write calls")

    client = SlowClient()
    core = HttpCoreGateway(
        action_url="http://core/action",
        policy_url="http://core/policy",
        audit_url="http://core/audit",
        funding_url="http://core/funding",
        account_url="http://core/account",
        token="internal-token",
        client=client,
        health_timeout_seconds=0.05,
        health_deadline_seconds=0.1,
    )
    started = time.monotonic()
    result = core.health()

    assert time.monotonic() - started < 0.2
    assert result["status"] == "degraded"
    assert set(result["services"].values()) == {"unavailable"}


def test_peer_registry_uses_cursor_pages_and_resumes_through_fenced_commits(tmp_path):
    repo = repository(tmp_path)
    provider = Provider(name="Peer", domain="peer.example", source="clink_peer")
    first = verified_offering(provider).model_copy(update={"status": "discovered"})
    second = first.model_copy(
        update={
            "offering_id": None,
            "source_id": "POST https://peer.example/v1/second",
            "endpoint": "https://peer.example/v1/second",
        }
    )

    class Response:
        status_code = 200

        def __init__(self, payload, etag):
            self._payload = payload
            self.headers = {"etag": etag}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.requests = []

        def get(self, _url, *, params, headers):
            self.requests.append({"params": params, "headers": headers})
            if not params.get("cursor"):
                return Response(
                    {"offerings": [{"provider": provider.model_dump(mode="json"), "offering": first.model_dump(mode="json")}], "next_cursor": "page-2"},
                    "etag-1",
                )
            return Response(
                {"offerings": [{"provider": provider.model_dump(mode="json"), "offering": second.model_dump(mode="json")}], "next_cursor": None},
                "etag-2",
            )

    client = Client()
    adapter = ClinkPeerAdapter("https://peer-registry.example", client=client)
    aggregator = RegistryAggregator(repo, {"peer": adapter}, max_pages=1)

    partial = aggregator.sync_registry("peer")
    resumed = aggregator.sync_registry("peer")

    assert partial["status"] == "partial"
    assert repo.get_registry_cursor("peer")["cursor"] == "0"
    assert resumed["status"] == "succeeded"
    assert [request["params"].get("cursor") for request in client.requests] == [None, "page-2"]
    assert repo.stats()["offerings"] == 2


def test_candidate_metric_counts_only_bazaar_provenance(tmp_path):
    repo = repository(tmp_path)
    generic = Provider(name="Generic", domain="generic.example", source="peer")
    bazaar = Provider(name="Bazaar", domain="bazaar.example", source="cdp_bazaar")
    repo.upsert_provider(generic)
    repo.upsert_provider(bazaar)
    generic_offering = verified_offering(generic).model_copy(update={"status": "discovered"})
    bazaar_offering = verified_offering(bazaar).model_copy(update={"status": "discovered"})
    repo.upsert_offering(generic_offering)
    repo.upsert_offering(bazaar_offering)
    repo.add_provenance(
        bazaar_offering.offering_id,
        "cdp_bazaar",
        bazaar_offering.source_id,
        bazaar_offering.model_dump(mode="json"),
    )

    assert repo.pilot_metrics()["candidate_offerings"] == 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MARKETPLACE_WORKER_CYCLE_INTERVAL_SECONDS", "0"),
        ("MARKETPLACE_OFFERING_VERIFY_INTERVAL_SECONDS", "-1"),
        ("MARKETPLACE_CORE_HEALTH_DEADLINE_SECONDS", "0"),
    ],
)
def test_runtime_intervals_must_be_positive(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="positive"):
        AppConfig.from_env()


def test_heartbeat_timeout_must_exceed_cycle_and_stage_timeout(monkeypatch):
    monkeypatch.setenv("MARKETPLACE_WORKER_CYCLE_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("MARKETPLACE_WORKER_STAGE_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("MARKETPLACE_WORKER_HEARTBEAT_TIMEOUT_SECONDS", "120")

    with pytest.raises(ValueError, match="heartbeat timeout"):
        AppConfig.from_env()
