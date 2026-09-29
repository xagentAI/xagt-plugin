from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass, field


@dataclass
class AppConfig:
    profile: str = "personal"
    prediction_markets_database_url: str | None = field(default=None, repr=False)
    polymarket_bridge_database_path: str = "services/funding_adapter_service/bridge.sqlite3"
    prediction_markets_internal_api_token: str = field(default="", repr=False)
    router_host: str = "127.0.0.1"
    router_port: int = 8040
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 9040
    preview_host: str = "127.0.0.1"
    preview_port: int = 8041
    polymarket_gamma_api_url: str = "https://gamma-api.polymarket.com"
    kalshi_api_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    clink_core_action_service_url: str = "http://127.0.0.1:8016"
    clink_core_policy_service_url: str = "http://127.0.0.1:8015"
    clink_core_audit_service_url: str = "http://127.0.0.1:8017"
    clink_core_funding_service_url: str = "http://127.0.0.1:8018"
    clink_core_account_service_url: str = "http://127.0.0.1:8019"
    clink_core_internal_api_token: str = field(default="", repr=False)
    preview_file: str = "services/preview_service/order_previews.jsonl"
    decision_host: str = "127.0.0.1"
    decision_port: int = 8043
    execution_host: str = "127.0.0.1"
    execution_port: int = 8042
    execution_file: str = "services/execution_service/executions.jsonl"
    order_signing_session_file: str = "services/execution_service/order_signing_sessions.jsonl"
    execution_console_base_url: str = "http://127.0.0.1:8042"
    ledger_db_file: str = "storage/trading_ledger.sqlite3"
    sync_host: str = "127.0.0.1"
    sync_port: int = 8045
    sync_interval_seconds: int = 20
    sync_stale_after_seconds: int = 60
    sync_venue_accounts: bool = True
    portfolio_host: str = "127.0.0.1"
    portfolio_port: int = 8044
    funding_adapter_host: str = "127.0.0.1"
    funding_adapter_port: int = 8046
    deposit_wallet_host: str = "127.0.0.1"
    deposit_wallet_port: int = 8048
    deposit_wallet_state_file: str = "services/deposit_wallet_service/deposit_wallet_states.jsonl"
    account_binding_host: str = "127.0.0.1"
    account_binding_port: int = 8047
    account_binding_file: str = "services/account_binding_service/polymarket_bindings.jsonl"
    account_binding_console_base_url: str = "http://127.0.0.1:8047"
    redis_url: str | None = None
    credential_store_file: str = "services/account_binding_service/polymarket_credentials.jsonl"
    credential_store_key_prefix: str = "clink:prediction-markets:credentials"
    credential_encryption_key: str = ""
    credential_store_dev_secret: str = "clink-local-development-secret"
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 4174
    live_mode: bool = False
    require_user_confirmation: bool = True
    require_funding_before_execution: bool = False
    polymarket_execution_mode: str = "browser_signed"
    polymarket_clob_host: str = "https://clob.polymarket.com"
    polymarket_signature_type: str = "3"
    polymarket_chain_id: int = 137
    polymarket_bridge_api_url: str = "https://bridge.polymarket.com"
    polymarket_deposit_wallet_address: str | None = None
    polymarket_relayer_url: str = ""
    polymarket_rpc_url: str | None = None
    polymarket_relayer_api_key: str = ""
    polymarket_relayer_api_key_address: str = ""
    polymarket_builder_api_key: str = ""
    polymarket_builder_secret: str = ""
    polymarket_builder_passphrase: str = ""
    polymarket_deposit_wallet_factory_address: str = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
    polymarket_bridge_source_chain_id: int = 137
    polymarket_bridge_source_token_address: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    polymarket_bridge_destination_chain_id: int = 137
    polymarket_pusd_token_address: str = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    kalshi_api_key_id: str | None = None
    kalshi_private_key_path: str | None = None
    kalshi_private_key_pem: str | None = None
    kalshi_order_time_in_force: str = "good_till_canceled"
    kalshi_self_trade_prevention_type: str = "taker_at_cross"
    kalshi_post_only: bool = False
    kalshi_cancel_order_on_pause: bool = False
    kalshi_reduce_only: bool = False
    kalshi_subaccount: int = 0
    kalshi_exchange_index: int = 0

    def __post_init__(self) -> None:
        self.profile = str(self.profile).strip().lower()
        if self.profile not in {"personal", "server"}:
            raise ValueError("prediction markets profile must be personal or server")
        if self.profile == "personal":
            if not str(self.polymarket_bridge_database_path).strip():
                raise ValueError("personal bridge database path is required")
            if str(self.prediction_markets_database_url or "").strip():
                raise ValueError(
                    "personal profile does not accept a server database URL"
                )
            return
        database_url = str(self.prediction_markets_database_url or "").strip()
        if not database_url.startswith("postgresql+psycopg://"):
            raise ValueError(
                "server profile requires a postgresql+psycopg database URL"
            )
        if importlib.util.find_spec("psycopg") is None:
            raise ValueError("server profile requires the psycopg driver")
        self.prediction_markets_database_url = database_url

    @classmethod
    def from_env(cls) -> "AppConfig":
        def env_bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.lower() in {"1", "true", "yes", "y", "on"}

        return cls(
            profile=os.getenv("PREDICTION_MARKETS_PROFILE", "personal"),
            prediction_markets_database_url=os.getenv("PREDICTION_MARKETS_DATABASE_URL"),
            polymarket_bridge_database_path=os.getenv(
                "PREDICTION_MARKETS_BRIDGE_DATABASE_PATH",
                "services/funding_adapter_service/bridge.sqlite3",
            ),
            prediction_markets_internal_api_token=os.getenv(
                "PREDICTION_MARKETS_INTERNAL_API_TOKEN", ""
            ),
            router_host=os.getenv("PREDICTION_MARKETS_ROUTER_HOST", "127.0.0.1"),
            router_port=int(os.getenv("PREDICTION_MARKETS_ROUTER_PORT", "8040")),
            mcp_host=os.getenv("PREDICTION_MARKETS_MCP_HOST", "127.0.0.1"),
            mcp_port=int(os.getenv("PREDICTION_MARKETS_MCP_PORT", "9040")),
            preview_host=os.getenv("PREDICTION_MARKETS_PREVIEW_HOST", "127.0.0.1"),
            preview_port=int(os.getenv("PREDICTION_MARKETS_PREVIEW_PORT", "8041")),
            polymarket_gamma_api_url=os.getenv("POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com"),
            kalshi_api_base_url=os.getenv("KALSHI_API_BASE_URL", "https://external-api.kalshi.com/trade-api/v2"),
            clink_core_action_service_url=os.getenv("CLINK_CORE_ACTION_SERVICE_URL", "http://127.0.0.1:8016"),
            clink_core_policy_service_url=os.getenv("CLINK_CORE_POLICY_SERVICE_URL", "http://127.0.0.1:8015"),
            clink_core_audit_service_url=os.getenv("CLINK_CORE_AUDIT_SERVICE_URL", "http://127.0.0.1:8017"),
            clink_core_funding_service_url=os.getenv("CLINK_CORE_FUNDING_SERVICE_URL", "http://127.0.0.1:8018"),
            clink_core_account_service_url=os.getenv("CLINK_CORE_ACCOUNT_SERVICE_URL", "http://127.0.0.1:8019"),
            clink_core_internal_api_token=os.getenv("CLINK_CORE_INTERNAL_API_TOKEN", ""),
            preview_file=os.getenv("PREDICTION_MARKETS_PREVIEW_FILE", "services/preview_service/order_previews.jsonl"),
            decision_host=os.getenv("PREDICTION_MARKETS_CONTEXT_HOST", os.getenv("PREDICTION_MARKETS_DECISION_HOST", "127.0.0.1")),
            decision_port=int(os.getenv("PREDICTION_MARKETS_CONTEXT_PORT", os.getenv("PREDICTION_MARKETS_DECISION_PORT", "8043"))),
            execution_host=os.getenv("PREDICTION_MARKETS_EXECUTION_HOST", "127.0.0.1"),
            execution_port=int(os.getenv("PREDICTION_MARKETS_EXECUTION_PORT", "8042")),
            execution_file=os.getenv("PREDICTION_MARKETS_EXECUTION_FILE", "services/execution_service/executions.jsonl"),
            order_signing_session_file=os.getenv(
                "PREDICTION_MARKETS_ORDER_SIGNING_SESSION_FILE",
                "services/execution_service/order_signing_sessions.jsonl",
            ),
            execution_console_base_url=os.getenv("PREDICTION_MARKETS_EXECUTION_CONSOLE_BASE_URL", "http://127.0.0.1:8042"),
            ledger_db_file=os.getenv("PREDICTION_MARKETS_LEDGER_DB_FILE", "storage/trading_ledger.sqlite3"),
            sync_host=os.getenv("PREDICTION_MARKETS_SYNC_HOST", "127.0.0.1"),
            sync_port=int(os.getenv("PREDICTION_MARKETS_SYNC_PORT", "8045")),
            sync_interval_seconds=int(os.getenv("PREDICTION_MARKETS_SYNC_INTERVAL_SECONDS", "20")),
            sync_stale_after_seconds=int(os.getenv("PREDICTION_MARKETS_SYNC_STALE_AFTER_SECONDS", "60")),
            sync_venue_accounts=env_bool("PREDICTION_MARKETS_SYNC_VENUE_ACCOUNTS", True),
            portfolio_host=os.getenv("PREDICTION_MARKETS_PORTFOLIO_HOST", "127.0.0.1"),
            portfolio_port=int(os.getenv("PREDICTION_MARKETS_PORTFOLIO_PORT", "8044")),
            funding_adapter_host=os.getenv("PREDICTION_MARKETS_FUNDING_ADAPTER_HOST", "127.0.0.1"),
            funding_adapter_port=int(os.getenv("PREDICTION_MARKETS_FUNDING_ADAPTER_PORT", "8046")),
            deposit_wallet_host=os.getenv("PREDICTION_MARKETS_DEPOSIT_WALLET_HOST", "127.0.0.1"),
            deposit_wallet_port=int(os.getenv("PREDICTION_MARKETS_DEPOSIT_WALLET_PORT", "8048")),
            deposit_wallet_state_file=os.getenv(
                "PREDICTION_MARKETS_DEPOSIT_WALLET_STATE_FILE",
                "services/deposit_wallet_service/deposit_wallet_states.jsonl",
            ),
            account_binding_host=os.getenv("PREDICTION_MARKETS_ACCOUNT_BINDING_HOST", "127.0.0.1"),
            account_binding_port=int(os.getenv("PREDICTION_MARKETS_ACCOUNT_BINDING_PORT", "8047")),
            account_binding_file=os.getenv(
                "PREDICTION_MARKETS_ACCOUNT_BINDING_FILE",
                "services/account_binding_service/polymarket_bindings.jsonl",
            ),
            account_binding_console_base_url=os.getenv("PREDICTION_MARKETS_ACCOUNT_BINDING_CONSOLE_BASE_URL", "http://127.0.0.1:8047"),
            redis_url=os.getenv("REDIS_URL"),
            credential_store_file=os.getenv(
                "PREDICTION_MARKETS_CREDENTIAL_STORE_FILE",
                "services/account_binding_service/polymarket_credentials.jsonl",
            ),
            credential_store_key_prefix=os.getenv("PREDICTION_MARKETS_CREDENTIAL_STORE_KEY_PREFIX", "clink:prediction-markets:credentials"),
            credential_encryption_key=os.getenv("CLINK_CREDENTIAL_ENCRYPTION_KEY", ""),
            credential_store_dev_secret=os.getenv("CLINK_CREDENTIAL_STORE_DEV_SECRET", "clink-local-development-secret"),
            dashboard_host=os.getenv("PREDICTION_MARKETS_DASHBOARD_HOST", "0.0.0.0"),
            dashboard_port=int(os.getenv("PREDICTION_MARKETS_DASHBOARD_PORT", "4174")),
            live_mode=os.getenv("PREDICTION_MARKETS_LIVE_MODE", "false").lower() == "true",
            require_user_confirmation=os.getenv("PREDICTION_MARKETS_REQUIRE_USER_CONFIRMATION", "true").lower() == "true",
            require_funding_before_execution=env_bool("PREDICTION_MARKETS_REQUIRE_FUNDING_BEFORE_EXECUTION", False),
            polymarket_execution_mode=os.getenv("POLYMARKET_EXECUTION_MODE", "browser_signed"),
            polymarket_clob_host=os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com"),
            polymarket_signature_type=os.getenv("POLYMARKET_SIGNATURE_TYPE", "3"),
            polymarket_chain_id=int(os.getenv("POLYMARKET_CHAIN_ID", "137")),
            polymarket_bridge_api_url=os.getenv("POLYMARKET_BRIDGE_API_URL", "https://bridge.polymarket.com"),
            polymarket_deposit_wallet_address=os.getenv("POLYMARKET_DEPOSIT_WALLET_ADDRESS"),
            polymarket_relayer_url=os.getenv("POLYMARKET_RELAYER_URL", ""),
            polymarket_rpc_url=os.getenv("POLYMARKET_RPC_URL"),
            polymarket_relayer_api_key=os.getenv("POLYMARKET_RELAYER_API_KEY", ""),
            polymarket_relayer_api_key_address=os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS", ""),
            polymarket_builder_api_key=os.getenv("POLYMARKET_BUILDER_API_KEY", ""),
            polymarket_builder_secret=os.getenv("POLYMARKET_BUILDER_SECRET", ""),
            polymarket_builder_passphrase=os.getenv("POLYMARKET_BUILDER_PASS_PHRASE", ""),
            polymarket_deposit_wallet_factory_address=os.getenv(
                "POLYMARKET_DEPOSIT_WALLET_FACTORY_ADDRESS",
                "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
            ),
            polymarket_bridge_source_chain_id=int(os.getenv("POLYMARKET_BRIDGE_SOURCE_CHAIN_ID", "137")),
            polymarket_bridge_source_token_address=os.getenv(
                "POLYMARKET_BRIDGE_SOURCE_TOKEN_ADDRESS",
                "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            ),
            polymarket_bridge_destination_chain_id=int(os.getenv("POLYMARKET_BRIDGE_DESTINATION_CHAIN_ID", "137")),
            polymarket_pusd_token_address=os.getenv(
                "POLYMARKET_PUSD_TOKEN_ADDRESS",
                "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
            ),
            kalshi_api_key_id=os.getenv("KALSHI_API_KEY_ID"),
            kalshi_private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
            kalshi_private_key_pem=os.getenv("KALSHI_PRIVATE_KEY_PEM"),
            kalshi_order_time_in_force=os.getenv("KALSHI_ORDER_TIME_IN_FORCE", "good_till_canceled"),
            kalshi_self_trade_prevention_type=os.getenv("KALSHI_SELF_TRADE_PREVENTION_TYPE", "taker_at_cross"),
            kalshi_post_only=env_bool("KALSHI_POST_ONLY", False),
            kalshi_cancel_order_on_pause=env_bool("KALSHI_CANCEL_ORDER_ON_PAUSE", False),
            kalshi_reduce_only=env_bool("KALSHI_REDUCE_ONLY", False),
            kalshi_subaccount=int(os.getenv("KALSHI_SUBACCOUNT", "0")),
            kalshi_exchange_index=int(os.getenv("KALSHI_EXCHANGE_INDEX", "0")),
        )

    @property
    def router_url(self) -> str:
        return f"http://{self.router_host}:{self.router_port}"

    @property
    def mcp_url(self) -> str:
        return f"http://{self.mcp_host}:{self.mcp_port}/mcp/"

    @property
    def preview_url(self) -> str:
        return f"http://{self.preview_host}:{self.preview_port}"

    @property
    def execution_url(self) -> str:
        return f"http://{self.execution_host}:{self.execution_port}"

    @property
    def sync_url(self) -> str:
        return f"http://{self.sync_host}:{self.sync_port}"

    @property
    def portfolio_url(self) -> str:
        return f"http://{self.portfolio_host}:{self.portfolio_port}"

    @property
    def funding_adapter_url(self) -> str:
        return f"http://{self.funding_adapter_host}:{self.funding_adapter_port}"

    @property
    def deposit_wallet_url(self) -> str:
        return f"http://{self.deposit_wallet_host}:{self.deposit_wallet_port}"

    @property
    def account_binding_url(self) -> str:
        return f"http://{self.account_binding_host}:{self.account_binding_port}"

    @property
    def decision_url(self) -> str:
        return f"http://{self.decision_host}:{self.decision_port}"

    def is_core_service_url(self, url: str) -> bool:
        normalized = url.rstrip("/")
        return any(
            normalized == service_url.rstrip("/")
            for service_url in (
                self.clink_core_action_service_url,
                self.clink_core_policy_service_url,
                self.clink_core_audit_service_url,
                self.clink_core_funding_service_url,
            )
        )

    def describe(self) -> dict:
        values = asdict(self)
        values["clink_core_internal_api_token"] = bool(self.clink_core_internal_api_token)
        values["prediction_markets_internal_api_token"] = bool(
            self.prediction_markets_internal_api_token
        )
        if values.get("prediction_markets_database_url"):
            values["prediction_markets_database_url"] = "<configured>"
        return values
