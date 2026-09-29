from __future__ import annotations

import base64
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import (
    InteractionMode,
    NodeSettings,
    Profile,
    StorageBackend,
)
from .hosted_release_runtime import build_core_hosted_projection
from .secrets import SecretStore


LEGACY_RISK_ENV_PREFIX = "CREDIT" "MODEL_"


class ManagedEnvironmentBuilder:
    """Build the authoritative environment for legacy business modules.

    Managed modules do not source their historical .env files. The Node owns
    internal credentials and local persistence locations while live-money
    settings remain opt-in operator configuration.
    """

    CORE_TOKEN = "core-internal-api-token"
    RECEIPT_KEY = "core-receipt-signing-key"
    MARKETPLACE_TOKEN = "marketplace-internal-api-token"
    PREDICTION_TOKEN = "prediction-markets-internal-api-token"
    CREDENTIAL_KEY = "prediction-credential-encryption-key"

    def __init__(
        self,
        settings: NodeSettings,
        secret_store: SecretStore,
        *,
        base_env: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.secret_store = secret_store
        self.base_env = dict(os.environ if base_env is None else base_env)

    def build(self) -> dict[str, str]:
        env = {
            name: value
            for name, value in self.base_env.items()
            if not name.startswith(LEGACY_RISK_ENV_PREFIX)
        }
        if self.settings.release_mode:
            env = {
                name: value
                for name, value in env.items()
                if not _release_owned_environment_variable(name)
            }
        env.update(self._common())
        env.update(self._core())
        env.update(self._marketplace())
        env.update(self._prediction_markets())
        if self.settings.release_mode:
            env.update(
                build_core_hosted_projection(
                    self.secret_store,
                    env=self.base_env,
                )
            )
        return env

    def _common(self) -> dict[str, str]:
        executable_directory = str(Path(sys.executable).parent)
        current_path = self.base_env.get("PATH", "")
        return {
            "CLINK_NODE_MANAGED": "1",
            "CLINK_MODULE_RUNTIME_ROOT": str(self.settings.paths.runtime / "modules"),
            "PYTHONUNBUFFERED": "1",
            "PYTHON_BIN": sys.executable,
            "PATH": (
                f"{executable_directory}{os.pathsep}{current_path}"
                if current_path
                else executable_directory
            ),
            "CLINK_CORE_INTERNAL_API_TOKEN": self._text_secret(
                self.CORE_TOKEN,
                32,
            ),
        }

    def _core(self) -> dict[str, str]:
        live_funding = self.base_env.get(
            "CLINK_LIVE_FUNDING",
            "true" if self.settings.execution.live_funding else "false",
        )
        native_facilitator = self.base_env.get(
            "CLINK_NATIVE_FACILITATOR_ENABLED",
            "true"
            if self.settings.execution.native_facilitator
            else "false",
        )
        risk_provider = self.base_env.get(
            "CLINK_RISK_PROVIDER",
            self.settings.execution.risk_provider,
        )
        risk_mode = self.base_env.get(
            "CLINK_RISK_MODE",
            self.settings.execution.risk_mode,
        )
        if self.settings.release_mode:
            live_funding = str(self.settings.execution.live_funding).lower()
            native_facilitator = str(
                self.settings.execution.native_facilitator
            ).lower()
            risk_provider = self.settings.execution.risk_provider
            risk_mode = self.settings.execution.risk_mode
        environment = {
            "CLINK_PROFILE": self.settings.profile.value,
            "CLINK_REDIS_URL": self.settings.events.redis_url or "",
            "AUTHORIZATION_SERVICE_HOST": "127.0.0.1",
            "POLICY_SERVICE_HOST": "127.0.0.1",
            "ACTION_SERVICE_HOST": "127.0.0.1",
            "AUDIT_SERVICE_HOST": "127.0.0.1",
            "FUNDING_SERVICE_HOST": "127.0.0.1",
            "ACCOUNT_SERVICE_HOST": "127.0.0.1",
            "AUTHORIZATION_MCP_HOST": "127.0.0.1",
            "POLICY_MCP_HOST": "127.0.0.1",
            "ACTION_MCP_HOST": "127.0.0.1",
            "AUDIT_MCP_HOST": "127.0.0.1",
            "FUNDING_MCP_HOST": "127.0.0.1",
            "CLINK_ACCOUNT_PUBLIC_BASE_URL": self._node_public_base_url(),
            "CLINK_AUDIT_SERVICE_URL": self._core_service_url(
                "audit",
                "http://127.0.0.1:8017",
            ),
            "CLINK_FUNDING_DATABASE_URL": self._database_url(),
            "CLINK_RECEIPT_SIGNING_KEY": self._text_secret(
                self.RECEIPT_KEY,
                48,
            ),
            "CLINK_LIVE_FUNDING": live_funding,
            "CLINK_NATIVE_FACILITATOR_ENABLED": native_facilitator,
            "CLINK_RISK_PROVIDER": risk_provider,
            "CLINK_RISK_MODE": risk_mode,
            "MISTTRACK_BASE_URL": self.base_env.get(
                "MISTTRACK_BASE_URL",
                "https://openapi.misttrack.io",
            ),
            "MISTTRACK_TIMEOUT_SECONDS": self.base_env.get(
                "MISTTRACK_TIMEOUT_SECONDS",
                "5",
            ),
            "MISTTRACK_MAX_ATTEMPTS": self.base_env.get(
                "MISTTRACK_MAX_ATTEMPTS",
                "2",
            ),
            "CLINK_RISK_HOLD_SCORE": self.base_env.get(
                "CLINK_RISK_HOLD_SCORE",
                "31",
            ),
            "CLINK_RISK_DENY_SCORE": self.base_env.get(
                "CLINK_RISK_DENY_SCORE",
                "71",
            ),
            "CLINK_RISK_MAX_AGE_SECONDS": self.base_env.get(
                "CLINK_RISK_MAX_AGE_SECONDS",
                "300",
            ),
            "CLINK_RISK_CACHE_TTL_SECONDS": self.base_env.get(
                "CLINK_RISK_CACHE_TTL_SECONDS",
                "300",
            ),
        }
        if self.settings.release_mode:
            environment["AUTHORIZATION_SESSION_FILE"] = str(
                self.settings.paths.data / "authorizations.jsonl"
            )
        return environment

    def _marketplace(self) -> dict[str, str]:
        return {
            "MARKETPLACE_DEPLOYMENT_MODE": "development",
            "MARKETPLACE_DATABASE_URL": self._database_url(),
            "MARKETPLACE_REDIS_URL": "",
            "REDIS_URL": "",
            "MARKETPLACE_REGISTRY_HOST": "127.0.0.1",
            "MARKETPLACE_MCP_HOST": "127.0.0.1",
            "MARKETPLACE_PUBLIC_BASE_URL": self._node_public_base_url(),
            "MARKETPLACE_ADMIN_DISABLED": "true",
            "MARKETPLACE_INTERNAL_API_TOKEN": self._text_secret(
                self.MARKETPLACE_TOKEN,
                32,
            ),
            "CLINK_CORE_ACTION_SERVICE_URL": self._core_service_url(
                "action",
                "http://127.0.0.1:8016",
            ),
            "CLINK_CORE_POLICY_SERVICE_URL": self._core_service_url(
                "policy",
                "http://127.0.0.1:8015",
            ),
            "CLINK_CORE_AUDIT_SERVICE_URL": self._core_service_url(
                "audit",
                "http://127.0.0.1:8017",
            ),
            "CLINK_CORE_FUNDING_SERVICE_URL": self._core_service_url(
                "funding",
                "http://127.0.0.1:8018",
            ),
            "CLINK_CORE_ACCOUNT_SERVICE_URL": self._core_service_url(
                "account",
                "http://127.0.0.1:8019",
            ),
        }

    def _prediction_markets(self) -> dict[str, str]:
        prediction_live = self.base_env.get(
            "PREDICTION_MARKETS_LIVE_MODE",
            "true"
            if self.settings.execution.prediction_markets_live
            else "false",
        )
        if self.settings.release_mode:
            prediction_live = str(
                self.settings.execution.prediction_markets_live
            ).lower()
        database_path = (
            str(self._database_path())
            if self.settings.profile is Profile.PERSONAL
            else self.base_env.get(
                "PREDICTION_MARKETS_LEDGER_DB_FILE",
                str(
                    self.settings.paths.data
                    / "prediction-markets.sqlite3"
                ),
            )
        )
        credential_path = str(
            self.settings.paths.data / "polymarket_credentials.jsonl"
        )
        environment = {
            "PREDICTION_MARKETS_ROUTER_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_MCP_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_PREVIEW_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_CONTEXT_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_EXECUTION_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_FUNDING_ADAPTER_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_DEPOSIT_WALLET_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_ACCOUNT_BINDING_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_SYNC_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_PORTFOLIO_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_DASHBOARD_HOST": "127.0.0.1",
            "PREDICTION_MARKETS_SKIP_LEGACY_DASHBOARD": "true",
            "PREDICTION_MARKETS_ACCOUNT_BINDING_CONSOLE_BASE_URL": (
                self._node_public_base_url()
            ),
            "PREDICTION_MARKETS_EXECUTION_CONSOLE_BASE_URL": (
                self._node_public_base_url()
            ),
            "PREDICTION_MARKETS_LEDGER_DB_FILE": database_path,
            "PREDICTION_MARKETS_CREDENTIAL_STORE_FILE": credential_path,
            "CLINK_CREDENTIAL_ENCRYPTION_KEY": (
                self._fernet_secret(self.CREDENTIAL_KEY)
            ),
            "CLINK_CREDENTIAL_STORE_DEV_SECRET": "",
            "PREDICTION_MARKETS_LIVE_MODE": prediction_live,
            "PREDICTION_MARKETS_REQUIRE_USER_CONFIRMATION": "true",
            "PREDICTION_MARKETS_INTERNAL_API_TOKEN": self._text_secret(
                self.PREDICTION_TOKEN,
                32,
            ),
            "PREDICTION_MARKETS_CORE_INTERNAL_API_TOKEN": (
                self._text_secret(self.CORE_TOKEN, 32)
            ),
        }
        if self.settings.release_mode:
            environment.update(
                {
                    "PREDICTION_MARKETS_BRIDGE_DATABASE_PATH": str(
                        self.settings.paths.data / "polymarket_bridge.sqlite3"
                    ),
                    "PREDICTION_MARKETS_ORDER_SIGNING_SESSION_FILE": str(
                        self.settings.paths.data
                        / "polymarket_order_signing_sessions.sqlite3"
                    ),
                    "PREDICTION_MARKETS_PREVIEW_FILE": str(
                        self.settings.paths.data / "order_previews.jsonl"
                    ),
                    "PREDICTION_MARKETS_EXECUTION_FILE": str(
                        self.settings.paths.data / "executions.jsonl"
                    ),
                    "PREDICTION_MARKETS_DEPOSIT_WALLET_STATE_FILE": str(
                        self.settings.paths.data / "deposit_wallet_states.jsonl"
                    ),
                    "PREDICTION_MARKETS_ACCOUNT_BINDING_FILE": str(
                        self.settings.paths.data / "polymarket_bindings.jsonl"
                    ),
                }
            )
        return environment

    def _database_path(self) -> Path:
        if (
            self.settings.storage.backend is not StorageBackend.SQLITE
            or self.settings.storage.sqlite_path is None
        ):
            raise RuntimeError(
                "managed Personal modules require SQLite storage"
            )
        return self.settings.storage.sqlite_path.expanduser()

    def _database_url(self) -> str:
        if self.settings.profile is Profile.SERVER:
            if not self.settings.storage.postgres_url:
                raise RuntimeError("Server Profile database is not configured")
            return self.settings.storage.postgres_url
        return f"sqlite+pysqlite:///{self._database_path()}"

    def _text_secret(self, name: str, byte_count: int) -> str:
        value = self.secret_store.get(name)
        if value is None:
            value = secrets.token_urlsafe(byte_count).encode("ascii")
            self.secret_store.set(name, value)
        return value.decode("ascii")

    def _fernet_secret(self, name: str) -> str:
        value = self.secret_store.get(name)
        if value is None:
            value = base64.urlsafe_b64encode(secrets.token_bytes(32))
            self.secret_store.set(name, value)
        return value.decode("ascii")

    def _module_endpoint(self, name: str, default: str) -> str:
        module = self.settings.modules[name]
        return (module.endpoint or default).rstrip("/")

    def _core_service_url(self, service: str, default: str) -> str:
        module = self.settings.modules["core"]
        configured = module.service_urls.get(service)
        if configured:
            return configured.rstrip("/")
        if module.mode.value == "external" and module.endpoint:
            return module.endpoint.rstrip("/")
        return default

    def _node_public_base_url(self) -> str:
        interaction = self.settings.interaction
        if interaction.mode is InteractionMode.LOCAL:
            return (
                f"http://{self.settings.host}:{self.settings.port}"
            ).rstrip("/")
        if interaction.mode is InteractionMode.SELF_HOSTED:
            if not interaction.public_base_url:
                raise RuntimeError(
                    "public interaction URL is not configured"
                )
            return interaction.public_base_url.rstrip("/")
        if not interaction.relay_url:
            raise RuntimeError("Link Relay URL is not configured")
        return interaction.relay_url.rstrip("/")


def _release_owned_environment_variable(name: str) -> bool:
    return (
        name.startswith("CLINK_HOSTED_FACILITATOR_")
        or name.startswith("CLINK_NATIVE_FACILITATOR_")
        or name
        in {
            "CLINK_FACILITATOR_MODE",
            "CLINK_LIVE_FUNDING",
            "CLINK_NATIVE_FACILITATOR_ENABLED",
            "PREDICTION_MARKETS_LIVE_MODE",
        }
    )


@dataclass(frozen=True)
class RuntimeStatus:
    running: bool
    pid: int | None
    profile: str
    http_url: str
    mcp_url: str
