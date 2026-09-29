from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import services.marketplace_app as marketplace_app
from services.identity_service import IdentityService
from services.marketplace_repository import MarketplaceRepository
from services.registry_aggregation import RegistryAggregator
from shared.config import AppConfig
from storage.tables import ProvenanceRow


def resource(index: int) -> dict:
    return {
        "resource": f"https://risk-{index}.example.com/v1/check",
        "serviceName": f"Risk {index}",
        "accepts": [{
            "scheme": "exact",
            "network": "eip155:137",
            "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            "amount": "5000",
            "payTo": "0x" + "1" * 40,
        }],
    }


def page(offset: int, count: int, *, total: int, etag: str | None = None) -> dict:
    return {
        "items": [resource(index) for index in range(offset, offset + count)],
        "offset": offset,
        "count": count,
        "limit": count,
        "total": total,
        "etag": etag,
    }


class FakeBazaarAdapter:
    def __init__(self, *, pages: dict[int, dict], fail_at: int | None = None) -> None:
        self.pages = pages
        self.fail_at = fail_at
        self.requests: list[dict] = []

    def fetch_page(self, *, offset: int, limit: int, etag: str | None) -> dict:
        self.requests.append({"offset": offset, "limit": limit, "etag": etag})
        if offset == self.fail_at:
            raise RuntimeError("Bazaar page unavailable")
        return self.pages[offset]

    def normalize_resource(self, item: dict):
        from adapters.cdp_bazaar import CdpBazaarAdapter

        return CdpBazaarAdapter().normalize_resource(item)


@pytest.fixture
def repository(tmp_path):
    return MarketplaceRepository(f"sqlite+pysqlite:///{Path(tmp_path) / 'marketplace.sqlite3'}")


def test_bazaar_inventory_sync_pages_until_total_and_deduplicates(repository):
    adapter = FakeBazaarAdapter(pages={0: page(0, 2, total=3, etag="page-zero"), 2: page(2, 1, total=3)})
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})

    result = aggregator.sync_registry("cdp_bazaar")
    repeated = aggregator.sync_registry("cdp_bazaar")

    assert result == {"registry_id": "cdp_bazaar", "status": "succeeded", "count": 3, "next_offset": 0}
    assert repeated["status"] == "succeeded"
    assert repository.stats()["offerings"] == 3


def test_bazaar_inventory_sync_reports_progress_after_each_page(repository):
    adapter = FakeBazaarAdapter(
        pages={
            0: page(0, 1, total=3),
            1: page(1, 1, total=3),
            2: page(2, 1, total=3),
        }
    )
    progress = []
    aggregator = RegistryAggregator(
        repository,
        {"cdp_bazaar": adapter},
        page_size=1,
        max_pages=3,
        progress_callback=lambda: progress.append("page"),
    )

    result = aggregator.sync_registry("cdp_bazaar")

    assert result["status"] == "succeeded"
    assert progress == ["page", "page", "page"]


def test_bazaar_inventory_sync_skips_one_malformed_resource(repository):
    valid = resource(0)
    malformed = {
        **resource(1),
        "accepts": [{**resource(1)["accepts"][0], "amount": "0"}],
    }
    adapter = FakeBazaarAdapter(
        pages={
            0: {
                "items": [valid, malformed],
                "offset": 0,
                "count": 2,
                "limit": 100,
                "total": 2,
                "etag": None,
            }
        }
    )

    result = RegistryAggregator(
        repository, {"cdp_bazaar": adapter}
    ).sync_registry("cdp_bazaar")

    assert result["status"] == "succeeded"
    assert result["count"] == 2
    assert result["skipped_count"] == 1
    assert "payment amount must be positive" in result["item_errors"][0]["error"]
    assert repository.stats()["offerings"] == 1


def test_provenance_hashes_oversized_source_id_without_losing_payload(repository):
    from adapters.cdp_bazaar import CdpBazaarAdapter

    provider, offering = CdpBazaarAdapter().normalize_resource(resource(0))
    repository.upsert_provider(provider)
    repository.upsert_offering(offering)
    long_source_id = "GET https://risk.example/v1/check?input=" + "a" * 600
    payload = {**offering.model_dump(mode="json"), "source_id": long_source_id}

    repository.add_provenance(
        offering.offering_id,
        "cdp_bazaar",
        long_source_id,
        payload,
    )

    with repository.sessions() as session:
        row = session.query(ProvenanceRow).one()
    assert row.source_id.startswith("sha256:")
    assert len(row.source_id) == 71
    assert row.payload["source_id"] == long_source_id


def test_bazaar_sync_resumes_after_partial_page_failure(repository):
    adapter = FakeBazaarAdapter(pages={0: page(0, 2, total=3, etag="page-zero"), 2: page(2, 1, total=3)}, fail_at=2)
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})

    partial = aggregator.sync_registry("cdp_bazaar")
    assert partial["status"] == "partial"
    assert repository.get_registry_cursor("cdp_bazaar")["cursor"] == "2"

    adapter.fail_at = None
    resumed = aggregator.sync_registry("cdp_bazaar")

    assert repository.get_registry_cursor("cdp_bazaar")["cursor"] == "0"
    assert resumed == {"registry_id": "cdp_bazaar", "status": "succeeded", "count": 1, "next_offset": 0}
    assert adapter.requests[-1]["offset"] == 2
    assert repository.stats()["offerings"] == 3


def test_bazaar_sync_treats_304_as_completed_without_importing(repository):
    adapter = FakeBazaarAdapter(pages={0: {"items": [], "offset": 0, "total": 0, "etag": "unchanged", "not_modified": True}})
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})
    repository.initialize_registry_cursor("cdp_bazaar", cursor="0", etag="known", status="succeeded")

    result = aggregator.sync_registry("cdp_bazaar")

    assert result == {"registry_id": "cdp_bazaar", "status": "succeeded", "count": 0, "next_offset": 0}
    assert adapter.requests == [{"offset": 0, "limit": 100, "etag": "known"}]


@pytest.mark.parametrize("status", ["registry_verified", "verified", "stale", "disabled"])
def test_bazaar_sync_preserves_existing_trusted_offering_status(repository, status):
    adapter = FakeBazaarAdapter(pages={0: page(0, 1, total=1)})
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})
    aggregator.sync_registry("cdp_bazaar")

    from adapters.cdp_bazaar import CdpBazaarAdapter

    _, normalized = CdpBazaarAdapter().normalize_resource(resource(0))
    repository.upsert_offering(normalized.model_copy(update={"status": status}))

    aggregator.sync_registry("cdp_bazaar")

    assert repository.get_offering(normalized.offering_id).status == status


@pytest.mark.parametrize("status", ["wallet_verified", "domain_verified", "active", "suspended"])
def test_bazaar_sync_preserves_existing_provider_status(repository, status):
    adapter = FakeBazaarAdapter(pages={0: page(0, 1, total=1)})
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})
    aggregator.sync_registry("cdp_bazaar")

    from adapters.cdp_bazaar import CdpBazaarAdapter

    provider, _ = CdpBazaarAdapter().normalize_resource(resource(0))
    repository.upsert_provider(provider.model_copy(update={"status": status}))

    aggregator.sync_registry("cdp_bazaar")

    assert repository.get_provider(provider.provider_id).status == status


def test_marketplace_app_wires_bazaar_inventory_configuration(monkeypatch, repository):
    captured = {}

    class Adapter:
        def __init__(self, *, search_url, resources_url):
            captured["adapter"] = {"search_url": search_url, "resources_url": resources_url}

    class Aggregator:
        def __init__(self, _repository, _adapters, *, page_size, max_pages, targeted_supply):
            captured["aggregator"] = {
                "page_size": page_size,
                "max_pages": max_pages,
                "targeted_supply": targeted_supply,
            }

    monkeypatch.setattr(marketplace_app, "CdpBazaarAdapter", Adapter)
    monkeypatch.setattr(marketplace_app, "RegistryAggregator", Aggregator)
    config = replace(
        AppConfig.from_env(),
        database_url=str(repository.engine.url),
        bazaar_search_url="https://bazaar.example/search",
        bazaar_resources_url="https://bazaar.example/resources",
        bazaar_sync_page_size=7,
        bazaar_sync_max_pages=3,
    )

    marketplace_app.create_marketplace_app(config, repository, IdentityService(repository))

    assert captured == {
        "adapter": {"search_url": "https://bazaar.example/search", "resources_url": "https://bazaar.example/resources"},
        "aggregator": {
            "page_size": 7,
            "max_pages": 3,
            "targeted_supply": config.bazaar_targets,
        },
    }


def test_registry_cursor_lease_allows_one_worker_and_blocks_stale_owner(tmp_path):
    database_url = f"sqlite+pysqlite:///{Path(tmp_path) / 'lease.sqlite3'}"
    first = MarketplaceRepository(database_url)
    second = MarketplaceRepository(database_url)
    first.initialize_registry_cursor("cdp_bazaar", cursor="0", etag=None, status="succeeded")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda token: (first if token == "first" else second).acquire_registry_lease("cdp_bazaar", token),
            ["first", "second"],
        ))

    assert results.count(True) == 1
    winner = "first" if results[0] else "second"
    loser = "second" if winner == "first" else "first"
    winning_repository = first if winner == "first" else second
    losing_repository = second if winner == "first" else first
    assert winning_repository.save_registry_cursor(
        "cdp_bazaar", cursor="0", etag="fresh", status="succeeded", owner_token=winner, release_lease=True,
    )
    assert not losing_repository.save_registry_cursor(
        "cdp_bazaar", cursor="2", etag="old", status="partial", owner_token=loser, release_lease=True,
    )
    assert first.acquire_registry_lease("cdp_bazaar", "stale-owner", lease_seconds=-1)
    assert second.acquire_registry_lease("cdp_bazaar", "fresh-owner")
    assert second.save_registry_cursor(
        "cdp_bazaar", cursor="0", etag="fresh", status="succeeded", owner_token="fresh-owner", release_lease=True,
    )
    assert not first.save_registry_cursor(
        "cdp_bazaar", cursor="2", etag="stale", status="partial", owner_token="stale-owner", release_lease=True,
    )
    assert first.get_registry_cursor("cdp_bazaar")["status"] == "succeeded"


def test_registry_page_commit_fences_expired_owner_data_writes(tmp_path):
    database_url = f"sqlite+pysqlite:///{Path(tmp_path) / 'fencing.sqlite3'}"
    first = MarketplaceRepository(database_url)
    second = MarketplaceRepository(database_url)
    first.initialize_registry_cursor("cdp_bazaar", cursor="0", etag=None, status="succeeded")
    assert first.acquire_registry_lease("cdp_bazaar", "owner-a", lease_seconds=-1)
    assert second.acquire_registry_lease("cdp_bazaar", "owner-b")

    from adapters.cdp_bazaar import CdpBazaarAdapter

    newer = resource(0)
    newer["serviceName"] = "New Bazaar Risk"
    provider_b, offering_b = CdpBazaarAdapter().normalize_resource(newer)
    assert second.commit_registry_page(
        "cdp_bazaar", "owner-b", [(provider_b, offering_b, offering_b.source_id)],
        cursor="0", etag="new", status="succeeded", release_lease=True,
    )

    older = resource(0)
    older["serviceName"] = "Old Bazaar Risk"
    provider_a, offering_a = CdpBazaarAdapter().normalize_resource(older)
    assert not first.commit_registry_page(
        "cdp_bazaar", "owner-a", [(provider_a, offering_a, offering_a.source_id)],
        cursor="0", etag="old", status="succeeded", release_lease=True,
    )
    assert first.get_offering(offering_b.offering_id).name == "New Bazaar Risk"


def test_registry_page_commit_uses_stable_internal_write_order(monkeypatch, tmp_path):
    from adapters.cdp_bazaar import CdpBazaarAdapter

    adapter = CdpBazaarAdapter()
    entries = []
    for index in (0, 1):
        provider, offering = adapter.normalize_resource(resource(index))
        entries.append((provider, offering, offering.source_id))

    def write_order(items, name):
        repository = MarketplaceRepository(f"sqlite+pysqlite:///{Path(tmp_path) / name}")
        repository.initialize_registry_cursor("cdp_bazaar", cursor="0", etag=None, status="succeeded")
        assert repository.acquire_registry_lease("cdp_bazaar", "owner")
        calls = []
        provider_upsert = repository._upsert_provider
        offering_upsert = repository._upsert_offering
        provenance_add = repository._add_provenance

        with monkeypatch.context() as patch:
            patch.setattr(repository, "_upsert_provider", lambda session, provider, wallet_address=None: (calls.append(("provider", provider.provider_id)), provider_upsert(session, provider, wallet_address))[1])
            patch.setattr(repository, "_upsert_offering", lambda session, offering, verified_at=None: (calls.append(("offering", offering.offering_id)), offering_upsert(session, offering, verified_at=verified_at))[1])
            patch.setattr(repository, "_add_provenance", lambda session, offering_id, registry_id, source_id, payload, cursor, etag: (calls.append(("provenance", offering_id, source_id)), provenance_add(session, offering_id, registry_id, source_id, payload, cursor, etag))[1])
            assert repository.commit_registry_page("cdp_bazaar", "owner", items, cursor="0", etag=None, status="succeeded", release_lease=True)
        return calls

    assert write_order(entries, "ordered.sqlite3") == write_order(list(reversed(entries)), "reversed.sqlite3")


def test_registry_cursor_updates_require_an_owner_token(repository):
    with pytest.raises(ValueError, match="owner token"):
        repository.save_registry_cursor("cdp_bazaar", cursor="0", etag=None, status="succeeded")

    assert repository.initialize_registry_cursor("cdp_bazaar", cursor="0", etag=None, status="succeeded")
    assert repository.initialize_registry_cursor("cdp_bazaar", cursor="2", etag=None, status="partial") is False


@pytest.mark.parametrize("invalid_page", [
    {"items": [resource(2)], "offset": 2, "count": 1},
    {"items": [resource(2)], "offset": 1, "count": 1, "total": 3},
])
def test_bazaar_sync_rejects_malformed_or_mismatched_pagination_at_current_cursor(repository, invalid_page):
    adapter = FakeBazaarAdapter(pages={0: page(0, 2, total=3), 2: invalid_page})
    aggregator = RegistryAggregator(repository, {"cdp_bazaar": adapter})

    result = aggregator.sync_registry("cdp_bazaar")

    assert result == {
        "registry_id": "cdp_bazaar",
        "status": "partial",
        "count": 2,
        "next_offset": 2,
        "last_error": "ValueError: invalid inventory pagination",
    }
    cursor = repository.get_registry_cursor("cdp_bazaar")
    assert cursor["cursor"] == "2"
    assert cursor["status"] == "partial"
