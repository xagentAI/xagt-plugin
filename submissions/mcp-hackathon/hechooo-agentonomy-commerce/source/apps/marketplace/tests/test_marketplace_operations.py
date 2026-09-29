from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from services.identity_service import IdentityService
from services.core_gateway import HttpCoreGateway
from services.marketplace_app import create_marketplace_app
from services.marketplace_repository import MarketplaceRepository
from services import marketplace_worker
from services.marketplace_worker import _verify_offerings, run_cycle
from shared.config import AppConfig
from shared.models import Provider, ServiceOffering


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


class UnreachableCore:
    def health(self):
        raise RuntimeError("Core unavailable")


def make_repository(tmp_path):
    return MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace-operations.sqlite3'}"
    )


def test_worker_purchase_service_uses_shared_redis_store(tmp_path):
    repository = make_repository(tmp_path)
    config = make_config(
        repository, redis_url="redis://redis.example:6380/7"
    )

    service = marketplace_worker._build_purchase_service(
        config, repository, core=object()
    )

    assert service.inputs.redis is not None
    assert service.inputs.redis.connection_pool.connection_kwargs["host"] == "redis.example"
    assert service.inputs.redis.connection_pool.connection_kwargs["port"] == 6380
    assert service.inputs.redis.connection_pool.connection_kwargs["db"] == 7


def make_config(repository, **changes):
    values = {
        "database_url": str(repository.engine.url),
        "redis_url": "",
        "registry_freshness_timeout_seconds": 900,
        "worker_heartbeat_timeout_seconds": 180,
    }
    values.update(changes)
    return replace(
        AppConfig.from_env(),
        **values,
    )


def save_registry_state(repository, *, status="succeeded", last_error=None):
    repository.initialize_registry_cursor(
        "cdp_bazaar", cursor="0", etag=None, status="pending"
    )
    assert repository.acquire_registry_lease("cdp_bazaar", "operations-test")
    assert repository.save_registry_cursor(
        "cdp_bazaar",
        cursor="0",
        etag=None,
        status=status,
        last_error=last_error,
        owner_token="operations-test",
        release_lease=True,
    )


def make_client(repository, *, core=None, **config_changes):
    config = make_config(repository, **config_changes)
    return TestClient(
        create_marketplace_app(
            config,
            repository,
            IdentityService(repository),
            core=HealthyCore() if core is None else core,
        )
    )


def offering(provider, suffix, status):
    return ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id=f"https://{provider.domain}/{suffix}",
        name=f"Service {suffix}",
        endpoint=f"https://{provider.domain}/{suffix}",
        method="POST",
        status=status,
        payment_options=[],
    )


def popular_offering(provider, offering_id, calls, last_called_at):
    quality = {}
    if calls is not None:
        quality["l30DaysTotalCalls"] = calls
    if last_called_at is not None:
        quality["lastCalledAt"] = last_called_at
    return ServiceOffering(
        offering_id=offering_id,
        provider_id=provider.provider_id,
        source="merchant",
        source_id=f"POST https://{provider.domain}/{offering_id}",
        name=offering_id,
        endpoint=f"https://{provider.domain}/{offering_id}",
        method="POST",
        status="verified",
        metadata={"quality": quality},
    )


def test_empty_catalog_search_orders_fresh_services_by_popularity(tmp_path):
    repository = make_repository(tmp_path)
    provider = Provider(
        name="Popular Provider",
        domain="popular.example",
        source="merchant",
        status="active",
    )
    repository.upsert_provider(provider, wallet_address="0x" + "4" * 40)
    rows = [
        popular_offering(
            provider,
            "service_c",
            2,
            "2026-07-25T10:00:00Z",
        ),
        popular_offering(
            provider,
            "service_b",
            8,
            "2026-07-25T11:00:00Z",
        ),
        popular_offering(
            provider,
            "service_a",
            8,
            "2026-07-25T11:00:00Z",
        ),
        popular_offering(
            provider,
            "service_missing",
            None,
            None,
        ),
    ]
    for row in rows:
        repository.upsert_offering(
            row,
            verified_at=datetime.now(UTC),
        )

    result = repository.search("", limit=3)

    assert [item.offering_id for item in result] == [
        "service_a",
        "service_b",
        "service_c",
    ]


def test_named_catalog_search_ignores_invalid_popularity_metadata(tmp_path):
    repository = make_repository(tmp_path)
    provider = Provider(
        name="Search Provider",
        domain="search.example",
        source="merchant",
        status="active",
    )
    repository.upsert_provider(provider, wallet_address="0x" + "5" * 40)
    row = popular_offering(
        provider,
        "wallet_risk",
        "invalid-count",
        "invalid-time",
    ).model_copy(update={"name": "Wallet risk"})
    repository.upsert_offering(
        row,
        verified_at=datetime.now(UTC),
    )

    result = repository.search("wallet risk")

    assert [item.offering_id for item in result] == ["wallet_risk"]


def test_health_is_degraded_when_registry_failed_but_liveness_stays_ok(tmp_path):
    repository = make_repository(tmp_path)
    save_registry_state(repository, status="failed", last_error="timeout")
    repository.heartbeat("worker-1", "running")
    client = make_client(repository)

    health = client.get("/healthz")
    liveness = client.get("/livez")

    assert health.status_code == 503
    assert health.json()["status"] == "degraded"
    assert health.json()["registries"][0]["status"] == "failed"
    assert health.json()["registries"][0]["last_error"] == "timeout"
    assert liveness.status_code == 200
    assert liveness.json() == {"service": "clink_marketplace", "status": "alive"}


def test_health_is_degraded_when_registry_or_worker_is_stale(tmp_path):
    repository = make_repository(tmp_path)
    save_registry_state(repository)
    repository.heartbeat("worker-1", "running")

    stale_registry = make_client(
        repository, registry_freshness_timeout_seconds=-1
    ).get("/healthz")
    stale_worker = make_client(
        repository, worker_heartbeat_timeout_seconds=-1
    ).get("/healthz")

    assert stale_registry.status_code == 503
    assert stale_registry.json()["registries"][0]["status"] == "stale"
    assert stale_worker.status_code == 503
    assert stale_worker.json()["worker"]["status"] == "stale"


def test_health_marks_stuck_registry_progress_as_stale(tmp_path):
    repository = make_repository(tmp_path)
    save_registry_state(repository, status="running")
    repository.heartbeat("worker-1", "running")

    response = make_client(
        repository, registry_freshness_timeout_seconds=-1
    ).get("/healthz")

    assert response.status_code == 503
    assert response.json()["registries"][0]["status"] == "stale"
    assert response.json()["registries"][0]["raw_status"] == "running"


def test_health_reports_core_failure_without_hiding_verified_catalog(tmp_path):
    repository = make_repository(tmp_path)
    save_registry_state(repository)
    repository.heartbeat("worker-1", "running")
    provider = Provider(
        name="Risk Provider", domain="risk.example", source="merchant", status="active"
    )
    repository.upsert_provider(provider, wallet_address="0x" + "1" * 40)
    row = offering(provider, "risk", "verified")
    repository.upsert_offering(row, verified_at=datetime.now(UTC))
    client = make_client(repository, core=UnreachableCore())

    health = client.get("/healthz")
    catalog = client.post("/catalog/search", json={"query": "risk"})

    assert health.status_code == 503
    assert health.json()["core"]["status"] == "unavailable"
    assert catalog.status_code == 200
    assert catalog.json()["count"] == 1


def test_health_does_not_compute_admin_analytics(tmp_path):
    repository = make_repository(tmp_path)
    save_registry_state(repository)
    repository.heartbeat("worker-1", "running")
    mandatory = (
        "registry_sync",
        "offering_verify",
        "domain_verify",
        "purchase_finalization",
    )
    for stage in mandatory:
        repository.start_worker_stage("worker-1", stage, "cycle-1")
        repository.complete_worker_stage("worker-1", stage, "cycle-1", "succeeded")
    admin_wallet = "0x" + "a" * 40
    admin_token = "admin-session"
    repository.create_merchant_session(
        sha256(admin_token.encode()).hexdigest(),
        admin_wallet,
        datetime.now(UTC) + timedelta(hours=1),
    )
    client = make_client(
        repository,
        admin_wallets=(admin_wallet,),
    )
    original_metrics = repository.pilot_metrics
    original_supply_targets = repository.bazaar_target_coverage
    repository.pilot_metrics = lambda: (_ for _ in ()).throw(
        AssertionError("health must not compute admin metrics")
    )
    repository.bazaar_target_coverage = lambda *_args: (_ for _ in ()).throw(
        AssertionError("health must not compute supply targets")
    )
    try:
        health = client.get("/healthz")
    finally:
        repository.pilot_metrics = original_metrics
        repository.bazaar_target_coverage = original_supply_targets

    assert health.status_code == 200
    assert "metrics" not in health.json()
    assert "supply_targets" not in health.json()
    status = client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert status.status_code == 200
    assert "metrics" in status.json()
    assert "supply_targets" in status.json()


def test_pilot_metrics_report_candidate_claimed_verified_and_stale(tmp_path):
    repository = make_repository(tmp_path)
    unclaimed = Provider(
        name="Candidate", domain="candidate.example", source="cdp_bazaar"
    )
    claimed = Provider(
        name="Claimed", domain="claimed.example", source="merchant", status="active"
    )
    repository.upsert_provider(unclaimed)
    repository.upsert_provider(claimed, wallet_address="0x" + "2" * 40)
    repository.upsert_offering(offering(unclaimed, "candidate", "discovered"))
    candidate=offering(unclaimed,"candidate","discovered")
    repository.add_provenance(candidate.offering_id,"cdp_bazaar",candidate.source_id,candidate.model_dump(mode="json"))
    repository.upsert_offering(
        offering(claimed, "verified", "verified"), verified_at=datetime.now(UTC)
    )
    repository.upsert_offering(offering(claimed, "stale", "stale"))

    metrics = repository.pilot_metrics()

    assert metrics == {
        "candidate_offerings": 1,
        "claimed_providers": 1,
        "verified_offerings": 1,
        "registry_verified_offerings": 0,
        "clink_verified_offerings": 1,
        "stale_offerings": 1,
    }


def test_stale_offering_without_prior_success_is_due_for_reverification(tmp_path):
    repository = make_repository(tmp_path)
    provider = Provider(
        name="Retry Provider",
        domain="retry.example",
        source="merchant",
        status="active",
    )
    repository.upsert_provider(provider, wallet_address="0x" + "3" * 40)
    row = offering(provider, "retry", "stale")
    repository.upsert_offering(row)

    due = repository.due_offerings(datetime.now(UTC))

    assert [item.offering_id for item in due] == [row.offering_id]


def test_offering_verification_is_bounded_and_reports_progress(tmp_path):
    repository = make_repository(tmp_path)
    provider = Provider(
        name="Bounded Provider",
        domain="bounded.example",
        source="merchant",
        status="active",
    )
    repository.upsert_provider(provider, wallet_address="0x" + "3" * 40)
    rows = [
        ServiceOffering(
            provider_id=provider.provider_id,
            source="merchant",
            source_id=f"bounded-{index}",
            name=f"Bounded {index}",
            endpoint=f"https://bounded.example/{index}",
            method="POST",
            status="stale",
        )
        for index in range(3)
    ]
    for row in rows:
        repository.upsert_offering(row)

    verified = []
    progress = []

    class Verifier:
        def verify(self, candidate):
            verified.append(candidate.offering_id)
            return type("Result", (), {"verified": False})()

    result = _verify_offerings(
        repository,
        Verifier(),
        interval_seconds=900,
        batch_size=2,
        progress_callback=lambda: progress.append("tick"),
    )

    assert result["checked"] == 2
    assert len(verified) == 2
    assert progress == ["tick", "tick"]


def test_worker_cycle_is_ordered_and_stage_errors_do_not_stop_later_stages(tmp_path):
    repository = make_repository(tmp_path)
    events = []

    class FailingAggregator:
        def sync(self):
            events.append("registry_sync")
            raise RuntimeError("registry unavailable")

    class Verifier:
        def verify(self, _offering):
            raise AssertionError("no offerings are due")

    class DomainVerifier:
        def verify(self, **_kwargs):
            raise AssertionError("no providers are due")

    original_due_offerings = repository.due_offerings
    original_due_providers = repository.due_providers
    original_claim_finalizations = repository.claim_finalizations
    original_heartbeat = repository.heartbeat
    repository.due_offerings = (
        lambda _cutoff, limit=20: events.append("offering_verify") or []
    )
    repository.due_providers = lambda _cutoff: events.append("domain_verify") or []
    repository.claim_finalizations = (
        lambda: events.append("purchase_finalization") or []
    )
    repository.heartbeat = lambda worker_id, status: (
        events.append("heartbeat"), original_heartbeat(worker_id, status)
    )[1]

    try:
        stages = run_cycle(
            repository,
            FailingAggregator(),
            Verifier(),
            DomainVerifier(),
            purchases=object(),
            worker_id="worker-ordered",
            offering_verify_interval_seconds=900,
            domain_verify_interval_seconds=86400,
        )
    finally:
        repository.due_offerings = original_due_offerings
        repository.due_providers = original_due_providers
        repository.claim_finalizations = original_claim_finalizations
        repository.heartbeat = original_heartbeat

    assert events == [
        "registry_sync",
        "offering_verify",
        "domain_verify",
        "purchase_finalization",
        "heartbeat",
    ]
    assert stages["registry_sync"]["status"] == "failed"
    assert stages["registry_sync"]["last_error"] == "registry unavailable"
    assert stages["offering_verify"]["status"] == "succeeded"
    assert stages["heartbeat"]["status"] == "succeeded"
    persisted = repository.worker_stage_health("worker-ordered")
    assert persisted["registry_sync"]["status"] == "failed"
    assert persisted["purchase_finalization"]["status"] == "succeeded"


def test_worker_persists_failed_registry_result_with_fenced_cursor(tmp_path):
    repository = make_repository(tmp_path)

    class FailedRegistryAggregator:
        def sync(self):
            return [{
                "registry_id": "cdp_bazaar",
                "status": "failed",
                "reason": "Bazaar unavailable",
            }]

    stages = run_cycle(
        repository,
        FailedRegistryAggregator(),
        verifier=object(),
        domain_verifier=object(),
        purchases=None,
        worker_id="worker-registry",
    )

    cursor = repository.get_registry_cursor("cdp_bazaar")
    assert cursor["status"] == "failed"
    assert cursor["last_error"] == "Bazaar unavailable"
    assert stages["registry_sync"]["status"] == "failed"
    assert stages["heartbeat"]["status"] == "succeeded"


def test_worker_marks_finalization_stage_failed_and_still_heartbeats(tmp_path):
    repository = make_repository(tmp_path)
    events = []

    class Aggregator:
        def sync(self):
            return []

    class Purchases:
        def process_finalization(self, _item):
            events.append("finalize")
            raise RuntimeError("Core finalize unavailable")

    repository.claim_finalizations = lambda: [{
        "outbox_id": 1,
        "purchase_id": "purchase-1",
        "target_state": "delivered",
        "payload": {},
        "claim_token":"claim-1",
    }]
    repository.finish_finalization = (
        lambda _outbox_id, _token, error=None: events.append(f"retry:{error}") or True
    )
    original_heartbeat = repository.heartbeat
    repository.heartbeat = lambda worker_id, status: (
        events.append("heartbeat"), original_heartbeat(worker_id, status)
    )[1]

    stages = run_cycle(
        repository,
        Aggregator(),
        verifier=object(),
        domain_verifier=object(),
        purchases=Purchases(),
        worker_id="worker-finalize",
    )

    assert events == [
        "finalize",
        "retry:Core finalize unavailable",
        "heartbeat",
    ]
    assert stages["purchase_finalization"]["status"] == "failed"
    assert stages["purchase_finalization"]["last_error"] == "Core finalize unavailable"
    assert stages["heartbeat"]["status"] == "succeeded"


def test_core_health_uses_read_only_health_endpoints():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok"}

    class Client:
        def __init__(self):
            self.gets = []

        def get(self, url, **_kwargs):
            self.gets.append(url)
            return Response()

        def post(self, *_args, **_kwargs):
            raise AssertionError("health probing must never POST")

    client = Client()
    core = HttpCoreGateway(
        action_url="http://core/action",
        policy_url="http://core/policy",
        audit_url="http://core/audit",
        funding_url="http://core/funding",
        account_url="http://core/account",
        token="internal-token",
        client=client,
    )

    result = core.health()

    assert result["status"] == "ok"
    assert set(client.gets) == {
        "http://core/action/healthz",
        "http://core/policy/healthz",
        "http://core/audit/healthz",
        "http://core/funding/healthz",
        "http://core/account/healthz",
    }


def test_worker_stage_migration_is_the_current_head(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'operations-migration.sqlite3'}"
    monkeypatch.setenv("MARKETPLACE_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    table = inspect(engine)
    assert table.has_table("worker_stage_runs")
    columns = {item["name"] for item in table.get_columns("worker_stage_runs")}
    assert columns == {
        "worker_id",
        "stage",
        "cycle_token",
        "status",
        "last_error",
        "started_at",
        "completed_at",
        "updated_at",
    }
    assert set(table.get_pk_constraint("worker_stage_runs")["constrained_columns"]) == {
        "worker_id",
        "stage",
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260904_0010"
    provider_columns = {item["name"] for item in table.get_columns("providers")}
    offering_columns = {item["name"] for item in table.get_columns("offerings")}
    assert "last_domain_check_at" in provider_columns
    assert {"candidate_payload", "candidate_registry_id", "last_check_attempt_at"} <= offering_columns
