from __future__ import annotations
import json, os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
from shared.bazaar_targets import BazaarTarget, load_bazaar_targets
from shared.container_config import build_database_url, parse_boolean, validate_container_environment
load_dotenv()


def _database_url_from_env() -> str:
    configured = os.getenv("MARKETPLACE_DATABASE_URL")
    if configured:
        return configured
    if all(os.getenv(name) for name in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")):
        return build_database_url()
    return "postgresql+psycopg://clink:clink-local-only@127.0.0.1:5432/clink_marketplace"

@dataclass(frozen=True)
class AppConfig:
    registry_host: str; registry_port: int; mcp_host: str; mcp_port: int
    database_url: str; redis_url: str; bazaar_search_url: str; bazaar_resources_url: str
    bazaar_sync_page_size: int; bazaar_sync_max_pages: int; bazaar_request_timeout_seconds: float
    bazaar_sync_queries: tuple[str, ...]; bazaar_network: str | None; bazaar_max_usd_price: str | None
    bazaar_targets: tuple[BazaarTarget, ...]
    public_base_url: str; admin_wallets: tuple[str, ...]; admin_disabled: bool
    native_provider_ids: tuple[str, ...]
    siwe_allowed_domains: tuple[str, ...]
    peer_registries: tuple[dict, ...]; core_action_url: str; core_policy_url: str
    core_audit_url: str; core_funding_url: str; core_account_url: str
    core_internal_api_token: str
    internal_api_token: str; purchase_preview_ttl_seconds: int
    registry_verified_max_price_usd: str
    worker_heartbeat_timeout_seconds: int; eip3009_domains: dict[str, dict[str, str]]
    worker_cycle_interval_seconds: int; registry_freshness_timeout_seconds: int
    offering_verify_interval_seconds: int; offering_verify_batch_size: int
    endpoint_verify_timeout_seconds: float; endpoint_verify_attempts: int
    domain_verify_interval_seconds: int
    worker_stage_timeout_seconds: int; core_health_timeout_seconds: float
    core_health_deadline_seconds: float

    @classmethod
    def from_env(cls):
        if os.getenv("MARKETPLACE_DEPLOYMENT_MODE", "development").lower() == "production":
            validate_container_environment(
                os.getenv("MARKETPLACE_PROCESS_ROLE", "api")
            )
        peers = json.loads(os.getenv("MARKETPLACE_PEER_REGISTRIES_JSON", "[]"))
        domains = json.loads(os.getenv("MARKETPLACE_EIP3009_DOMAINS_JSON", "{}"))
        if not isinstance(peers, list) or not isinstance(domains, dict):
            raise ValueError("Marketplace JSON configuration is invalid")
        config=cls(
            os.getenv("MARKETPLACE_REGISTRY_HOST", "127.0.0.1"), int(os.getenv("MARKETPLACE_REGISTRY_PORT", "8050")),
            os.getenv("MARKETPLACE_MCP_HOST", "127.0.0.1"), int(os.getenv("MARKETPLACE_MCP_PORT", "9050")),
            _database_url_from_env(),
            os.getenv(
                "MARKETPLACE_REDIS_URL",
                os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1"),
            ),
            os.getenv("MARKETPLACE_CDP_BAZAAR_SEARCH_URL", "https://api.cdp.coinbase.com/platform/v2/x402/discovery/search"),
            os.getenv("MARKETPLACE_CDP_BAZAAR_RESOURCES_URL", "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"),
            int(os.getenv("MARKETPLACE_BAZAAR_SYNC_PAGE_SIZE", "100")),
            int(os.getenv("MARKETPLACE_BAZAAR_SYNC_MAX_PAGES", "10")),
            float(os.getenv("MARKETPLACE_BAZAAR_REQUEST_TIMEOUT_SECONDS", "8")),
            tuple(x.strip() for x in os.getenv("MARKETPLACE_BAZAAR_SYNC_QUERIES", "defi analytics|token security|wallet risk|dex quote|onchain market data").split("|") if x.strip()),
            os.getenv("MARKETPLACE_BAZAAR_NETWORK", "eip155:137") or None,
            os.getenv("MARKETPLACE_BAZAAR_MAX_USD_PRICE", "0.10") or None,
            load_bazaar_targets(os.getenv("MARKETPLACE_BAZAAR_TARGETS_JSON")),
            os.getenv("MARKETPLACE_PUBLIC_BASE_URL", "http://127.0.0.1:8050").rstrip("/"),
            tuple(x.lower() for x in os.getenv("MARKETPLACE_ADMIN_WALLETS", "").split(",") if x),
            parse_boolean(
                os.getenv("MARKETPLACE_ADMIN_DISABLED", "false"),
                name="MARKETPLACE_ADMIN_DISABLED",
            ),
            tuple(
                value.strip().lower()
                for value in os.getenv("MARKETPLACE_NATIVE_PROVIDER_IDS", "").split(",")
                if value.strip()
            ),
            tuple(x.lower() for x in os.getenv("MARKETPLACE_SIWE_ALLOWED_DOMAINS", "marketplace.clink.local").split(",") if x),
            tuple(x for x in peers if isinstance(x, dict)),
            os.getenv("CLINK_CORE_ACTION_SERVICE_URL", "http://127.0.0.1:8016"),
            os.getenv("CLINK_CORE_POLICY_SERVICE_URL", "http://127.0.0.1:8015"),
            os.getenv("CLINK_CORE_AUDIT_SERVICE_URL", "http://127.0.0.1:8017"),
            os.getenv("CLINK_CORE_FUNDING_SERVICE_URL", "http://127.0.0.1:8018"),
            os.getenv("CLINK_CORE_ACCOUNT_SERVICE_URL", "http://127.0.0.1:8019"),
            os.getenv("CLINK_CORE_INTERNAL_API_TOKEN", ""), os.getenv("MARKETPLACE_INTERNAL_API_TOKEN", ""),
            int(os.getenv("MARKETPLACE_PURCHASE_PREVIEW_TTL_SECONDS", "300")),
            os.getenv("MARKETPLACE_REGISTRY_VERIFIED_MAX_USD", "0.10"),
            int(os.getenv("MARKETPLACE_WORKER_HEARTBEAT_TIMEOUT_SECONDS", "240")), domains,
            int(os.getenv("MARKETPLACE_WORKER_CYCLE_INTERVAL_SECONDS", "60")),
            int(os.getenv("MARKETPLACE_REGISTRY_FRESHNESS_TIMEOUT_SECONDS", "900")),
            int(os.getenv("MARKETPLACE_OFFERING_VERIFY_INTERVAL_SECONDS", "900")),
            int(os.getenv("MARKETPLACE_OFFERING_VERIFY_BATCH_SIZE", "5")),
            float(os.getenv("MARKETPLACE_ENDPOINT_VERIFY_TIMEOUT_SECONDS", "5")),
            int(os.getenv("MARKETPLACE_ENDPOINT_VERIFY_ATTEMPTS", "2")),
            int(os.getenv("MARKETPLACE_DOMAIN_VERIFY_INTERVAL_SECONDS", "86400")),
            int(os.getenv("MARKETPLACE_WORKER_STAGE_TIMEOUT_SECONDS", "120")),
            float(os.getenv("MARKETPLACE_CORE_HEALTH_TIMEOUT_SECONDS", "0.75")),
            float(os.getenv("MARKETPLACE_CORE_HEALTH_DEADLINE_SECONDS", "2.5")),
        )
        positive={
            "worker cycle interval":config.worker_cycle_interval_seconds,
            "worker heartbeat timeout":config.worker_heartbeat_timeout_seconds,
            "worker stage timeout":config.worker_stage_timeout_seconds,
            "registry freshness timeout":config.registry_freshness_timeout_seconds,
            "offering verify interval":config.offering_verify_interval_seconds,
            "offering verify batch size":config.offering_verify_batch_size,
            "endpoint verify timeout":config.endpoint_verify_timeout_seconds,
            "endpoint verify attempts":config.endpoint_verify_attempts,
            "domain verify interval":config.domain_verify_interval_seconds,
            "Core health timeout":config.core_health_timeout_seconds,
            "Core health deadline":config.core_health_deadline_seconds,
            "Bazaar page size":config.bazaar_sync_page_size,
            "Bazaar max pages":config.bazaar_sync_max_pages,
            "Bazaar request timeout":config.bazaar_request_timeout_seconds,
        }
        if any(value<=0 for value in positive.values()):
            raise ValueError("Marketplace intervals and timeouts must be positive")
        if config.worker_heartbeat_timeout_seconds<=config.worker_cycle_interval_seconds+config.worker_stage_timeout_seconds:
            raise ValueError("worker heartbeat timeout must exceed cycle plus stage timeout")
        if config.core_health_deadline_seconds<config.core_health_timeout_seconds:
            raise ValueError("Core health deadline must cover individual health timeout")
        if (
            config.bazaar_sync_max_pages * config.bazaar_request_timeout_seconds
            >= config.worker_stage_timeout_seconds
        ):
            raise ValueError("Bazaar sync request budget must fit worker stage timeout")
        if (
            config.offering_verify_batch_size
            * config.endpoint_verify_timeout_seconds
            * config.endpoint_verify_attempts
            >= config.worker_stage_timeout_seconds
        ):
            raise ValueError("offering verification request budget must fit worker stage timeout")
        if any(not value.startswith("provider_") for value in config.native_provider_ids):
            raise ValueError("MARKETPLACE_NATIVE_PROVIDER_IDS contains an invalid provider id")
        try:
            registry_cap=Decimal(config.registry_verified_max_price_usd)
        except InvalidOperation as exc:
            raise ValueError("MARKETPLACE_REGISTRY_VERIFIED_MAX_USD must be numeric") from exc
        if registry_cap<=0:
            raise ValueError("MARKETPLACE_REGISTRY_VERIFIED_MAX_USD must be positive")
        return config
    @property
    def registry_url(self): return f"http://{self.registry_host}:{self.registry_port}"
    @property
    def mcp_url(self): return f"http://{self.mcp_host}:{self.mcp_port}/mcp/"
