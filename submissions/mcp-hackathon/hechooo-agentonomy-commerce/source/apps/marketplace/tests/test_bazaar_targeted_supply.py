from pathlib import Path

from adapters.cdp_bazaar import CdpBazaarAdapter
from services.marketplace_repository import MarketplaceRepository
from services.marketplace_worker import _sync_registries
from services.registry_aggregation import RegistryAggregator
from shared.bazaar_targets import DEFAULT_BAZAAR_TARGETS, BazaarTarget
from shared.config import AppConfig


def resource(
    *,
    name: str,
    endpoint: str,
    description: str = "",
    tags: list[str] | None = None,
) -> dict:
    return {
        "resource": endpoint,
        "serviceName": name,
        "description": description,
        "tags": tags or [],
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "amount": "10000",
                "payTo": "0x" + "1" * 40,
            }
        ],
    }


class TargetedAdapter:
    def __init__(self, results: dict[str, list[dict]], *, total: int = 0) -> None:
        self.results = results
        self.total = total
        self.search_requests: list[dict] = []

    def search(self, query, *, network=None, max_usd_price=None, limit=20):
        self.search_requests.append(
            {
                "query": query,
                "network": network,
                "max_usd_price": max_usd_price,
                "limit": limit,
            }
        )
        return self.results.get(query, [])

    def fetch_page(self, *, offset, limit, etag):
        return {
            "items": [],
            "offset": offset,
            "count": 0,
            "limit": limit,
            "total": self.total,
            "etag": etag,
        }

    def normalize_resource(self, item):
        return CdpBazaarAdapter().normalize_resource(item)


def repository(tmp_path):
    return MarketplaceRepository(
        f"sqlite+pysqlite:///{Path(tmp_path) / 'marketplace.sqlite3'}"
    )


def test_default_target_supply_contains_requested_ten_brands():
    assert [(item.category, item.name) for item in DEFAULT_BAZAAR_TARGETS] == [
        ("data", "CoinGecko"),
        ("data", "Nansen"),
        ("data", "Allium"),
        ("search", "Firecrawl"),
        ("search", "Exa"),
        ("infrastructure", "Alchemy"),
        ("infrastructure", "Pinata"),
        ("inference", "Venice"),
        ("inference", "ElevenLabs"),
        ("media", "dTelecom"),
    ]


def test_target_supply_can_be_replaced_from_json_configuration(monkeypatch):
    monkeypatch.setenv(
        "MARKETPLACE_BAZAAR_TARGETS_JSON",
        '[{"category":"data","name":"Custom Data","first_party_domains":["data.example"]}]',
    )

    config = AppConfig.from_env()

    assert config.bazaar_targets == (
        BazaarTarget("data", "Custom Data", ("data.example",)),
    )


def test_targeted_supply_imports_matching_results_without_network_or_price_filter(tmp_path):
    repo = repository(tmp_path)
    target = BazaarTarget("data", "Nansen", ("nansen.ai",))
    adapter = TargetedAdapter(
        {
            "Nansen": [
                resource(
                    name="Nansen",
                    endpoint="https://api.nansen.ai/api/v1/chains/chain-rank",
                    tags=["analytics"],
                ),
                resource(
                    name="Unrelated",
                    endpoint="https://unrelated.example/v1/data",
                ),
            ]
        }
    )
    aggregator = RegistryAggregator(
        repo,
        {"cdp_bazaar": adapter},
        targeted_supply=(target,),
    )

    result = aggregator.sync_registry("cdp_bazaar")

    assert result["targeted_count"] == 1
    assert adapter.search_requests == [
        {
            "query": "Nansen",
            "network": None,
            "max_usd_price": None,
            "limit": 20,
        }
    ]
    candidates = repo.list_bazaar_candidates(query="Nansen", limit=20)
    assert len(candidates) == 1
    imported = candidates[0]["offering"]
    assert imported.status == "discovered"
    assert imported.metadata["bazaar_targets"] == [
        {
            "name": "Nansen",
            "category": "data",
            "relationship": "first_party",
        }
    ]


def test_targeted_supply_discovers_pinata_x402_v1_resource(tmp_path):
    repo = repository(tmp_path)
    target = BazaarTarget("infrastructure", "Pinata", ("pinata.cloud",))
    pinata = resource(
        name="",
        endpoint="https://402-server.pinata-marketing-enterprise.workers.dev/v1/retrieve/private/cid",
        description="Pay to retrieve a private file from Pinata by CID",
    )
    pinata["x402Version"] = 1
    payment = pinata["accepts"][0]
    payment.pop("amount")
    payment["maxAmountRequired"] = "100"
    payment["network"] = "base"
    payment["asset"] = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

    result = RegistryAggregator(
        repo,
        {"cdp_bazaar": TargetedAdapter({"Pinata": [pinata]})},
        targeted_supply=(target,),
    ).sync_registry("cdp_bazaar")

    assert result["status"] == "succeeded"
    assert result["targeted_count"] == 1
    assert repo.bazaar_target_coverage((target,))[0]["status"] == "discovered"


def test_targeted_supply_labels_third_party_brand_usage_without_impersonation(tmp_path):
    repo = repository(tmp_path)
    target = BazaarTarget("inference", "Venice", ("venice.ai",))
    adapter = TargetedAdapter(
        {
            "Venice": [
                resource(
                    name="CheapTokens",
                    endpoint="https://cheaptokens.ai/api/buy",
                    description="OpenAI-compatible Venice API access",
                    tags=["Venice", "Inference"],
                )
            ]
        }
    )
    aggregator = RegistryAggregator(
        repo,
        {"cdp_bazaar": adapter},
        targeted_supply=(target,),
    )

    aggregator.sync_registry("cdp_bazaar")

    candidates = repo.list_bazaar_candidates(query="CheapTokens", limit=20)
    assert candidates[0]["provider"].name == "CheapTokens"
    assert candidates[0]["offering"].metadata["bazaar_targets"][0] == {
        "name": "Venice",
        "category": "inference",
        "relationship": "powered_by",
    }


def test_targeted_supply_is_not_requeried_mid_inventory_when_coverage_exists(tmp_path):
    repo = repository(tmp_path)
    target = BazaarTarget("data", "Nansen", ("nansen.ai",))
    adapter = TargetedAdapter(
        {
            "Nansen": [
                resource(
                    name="Nansen",
                    endpoint="https://api.nansen.ai/api/v1/chains/chain-rank",
                )
            ]
        }
    )
    aggregator = RegistryAggregator(
        repo,
        {"cdp_bazaar": adapter},
        targeted_supply=(target,),
    )
    aggregator.sync_registry("cdp_bazaar")
    owner = "mid-inventory-test"
    assert repo.acquire_registry_lease("cdp_bazaar", owner)
    assert repo.save_registry_cursor(
        "cdp_bazaar",
        cursor="100",
        etag=None,
        status="running",
        owner_token=owner,
        release_lease=True,
    )
    adapter.search_requests.clear()
    adapter.total = 100

    result = aggregator.sync_registry("cdp_bazaar")

    assert result["status"] == "succeeded"
    assert adapter.search_requests == []


def test_targeted_supply_failure_is_isolated_to_one_brand(tmp_path):
    repo = repository(tmp_path)
    targets = (
        BazaarTarget("data", "Nansen", ("nansen.ai",)),
        BazaarTarget("search", "Exa", ("exa.ai",)),
    )

    class PartiallyBrokenAdapter(TargetedAdapter):
        def search(self, query, *, network=None, max_usd_price=None, limit=20):
            if query == "Nansen":
                raise RuntimeError("Nansen timeout with token=super-secret")
            return super().search(
                query,
                network=network,
                max_usd_price=max_usd_price,
                limit=limit,
            )

    adapter = PartiallyBrokenAdapter(
        {
            "Exa": [
                resource(
                    name="Exa",
                    endpoint="https://api.exa.ai/search",
                )
            ]
        }
    )

    result = RegistryAggregator(
        repo,
        {"cdp_bazaar": adapter},
        targeted_supply=targets,
    ).sync_registry("cdp_bazaar")

    assert result["status"] == "succeeded"
    assert result["targeted_count"] == 1
    assert result["target_errors"] == [
        {
            "name": "Nansen",
            "error": "RuntimeError: Nansen timeout with token=<redacted>",
        }
    ]
    assert len(repo.list_bazaar_candidates(query="Exa", limit=20)) == 1


def test_page_budget_exhaustion_is_progress_not_registry_failure(tmp_path):
    repo = repository(tmp_path)

    class PagedAdapter(TargetedAdapter):
        def fetch_page(self, *, offset, limit, etag):
            return {
                "items": [
                    resource(
                        name=f"Service {offset}",
                        endpoint=f"https://service-{offset}.example/v1",
                    )
                ],
                "offset": offset,
                "count": 1,
                "limit": limit,
                "total": 3,
                "etag": etag,
            }

    result = RegistryAggregator(
        repo,
        {"cdp_bazaar": PagedAdapter({})},
        page_size=1,
        max_pages=1,
    ).sync_registry("cdp_bazaar")

    assert result == {
        "registry_id": "cdp_bazaar",
        "status": "in_progress",
        "count": 1,
        "next_offset": 1,
    }
    assert repo.get_registry_cursor("cdp_bazaar")["status"] == "running"
    assert repo.get_registry_cursor("cdp_bazaar")["last_error"] is None


def test_registry_failure_exposes_safe_diagnostic(tmp_path):
    repo = repository(tmp_path)

    class BrokenAdapter(TargetedAdapter):
        def fetch_page(self, *, offset, limit, etag):
            raise RuntimeError("Bazaar timeout with bearer super-secret-value")

    result = RegistryAggregator(
        repo,
        {"cdp_bazaar": BrokenAdapter({})},
    ).sync_registry("cdp_bazaar")

    assert result["status"] == "partial"
    assert result["last_error"].startswith("RuntimeError: Bazaar timeout")
    assert "super-secret-value" not in result["last_error"]
    assert repo.get_registry_cursor("cdp_bazaar")["last_error"] == result["last_error"]


def test_worker_treats_fresh_registry_progress_as_success(tmp_path):
    repo = repository(tmp_path)

    class Aggregator:
        def sync(self):
            return [
                {
                    "registry_id": "cdp_bazaar",
                    "status": "in_progress",
                    "count": 1000,
                    "next_offset": 1000,
                }
            ]

    result = _sync_registries(repo, Aggregator())

    assert result[0]["status"] == "in_progress"
    assert repo.get_registry_cursor("cdp_bazaar")["status"] == "running"
    assert repo.get_registry_cursor("cdp_bazaar")["last_error"] is None


def test_target_coverage_reports_discovered_and_missing_supply(tmp_path):
    repo = repository(tmp_path)
    targets = (
        BazaarTarget("data", "Nansen", ("nansen.ai",)),
        BazaarTarget("search", "Exa", ("exa.ai",)),
    )
    adapter = TargetedAdapter(
        {
            "Nansen": [
                resource(
                    name="Nansen",
                    endpoint="https://api.nansen.ai/api/v1/chains/chain-rank",
                )
            ],
            "Exa": [],
        }
    )
    RegistryAggregator(
        repo,
        {"cdp_bazaar": adapter},
        targeted_supply=targets,
    ).sync_registry("cdp_bazaar")

    assert repo.bazaar_target_coverage(targets) == [
        {
            "name": "Nansen",
            "category": "data",
                "status": "discovered",
                "candidate_offerings": 1,
                "registry_verified_offerings": 0,
                "clink_verified_offerings": 0,
                "verified_offerings": 0,
        },
        {
            "name": "Exa",
            "category": "search",
                "status": "missing",
                "candidate_offerings": 0,
                "registry_verified_offerings": 0,
                "clink_verified_offerings": 0,
                "verified_offerings": 0,
        },
    ]
