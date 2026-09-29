from __future__ import annotations

import errno
import ipaddress
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .paths import NodePaths, PathIdentity
from .release_runtime import (
    UnsafeReleaseConfiguration,
    release_node_paths,
    validate_release_writable_paths,
)


class Profile(StrEnum):
    PERSONAL = "personal"
    SERVER = "server"


class StorageBackend(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class EventBackend(StrEnum):
    MEMORY = "memory"
    REDIS = "redis"


class SecretBackend(StrEnum):
    KEYCHAIN = "keychain"
    VAULT = "vault"
    FILE = "file"


class InteractionMode(StrEnum):
    LOCAL = "local"
    SELF_HOSTED = "self_hosted"
    RELAY = "relay"


class ModuleMode(StrEnum):
    MANAGED = "managed"
    EXTERNAL = "external"
    DISABLED = "disabled"


MINIAPP_SECRET_NAMES = (
    "telegram-miniapp-bot-token",
    "hermes-api-server-key",
    "miniapp-cookie-key",
    "hermes-session-key",
)
_MINIAPP_LONG_SECRET_NAMES = frozenset(
    {"miniapp-cookie-key", "hermes-session-key"}
)
_MAX_CONFIG_DOCUMENT_BYTES = 1_048_576


def validate_miniapp_secret_value(name: str, value: object) -> bytes:
    if (
        name not in MINIAPP_SECRET_NAMES
        or not isinstance(value, bytes)
        or not value
        or len(value) > 4_096
        or any(byte < 0x21 or byte > 0x7E for byte in value)
        or (name in _MINIAPP_LONG_SECRET_NAMES and len(value) < 32)
    ):
        raise ValueError("invalid Mini App secret value")
    return value


def validate_miniapp_secret_values(
    values: Mapping[str, object],
) -> dict[str, bytes]:
    return {
        name: validate_miniapp_secret_value(name, values.get(name))
        for name in MINIAPP_SECRET_NAMES
    }


@dataclass(frozen=True)
class StorageSettings:
    backend: StorageBackend
    sqlite_path: Path | None = None
    postgres_url: str | None = None


@dataclass(frozen=True)
class EventSettings:
    backend: EventBackend
    redis_url: str | None = None


@dataclass(frozen=True)
class SecretSettings:
    backend: SecretBackend
    service_name: str = "clink-node"
    vault_address: str | None = None
    vault_token: str | None = field(default=None, repr=False)
    vault_mount: str = "secret"
    vault_path_prefix: str = "clink"


@dataclass(frozen=True)
class InteractionSettings:
    mode: InteractionMode
    public_base_url: str | None = None
    relay_url: str | None = None
    session_ttl_seconds: int = 900


@dataclass(frozen=True)
class ModuleSettings:
    mode: ModuleMode = ModuleMode.MANAGED
    endpoint: str | None = None
    mcp_url: str | None = None
    service_urls: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionGateSettings:
    live_funding: bool = False
    native_facilitator: bool = False
    prediction_markets_live: bool = False
    risk_provider: str = field(default="misttrack", repr=False)
    risk_mode: str = field(default="shadow", repr=False)


@dataclass(frozen=True)
class MiniAppSettings:
    enabled: bool = False
    hermes_base_url: str = "http://127.0.0.1:8642"
    auth_max_age_seconds: int = 300
    session_ttl_seconds: int = 86_400
    connect_timeout_seconds: int = 3
    read_timeout_seconds: int = 60
    max_stream_seconds: int = 900
    max_active_runs_per_subject: int = 1
    ip_general_limit: int = 240
    session_exchange_limit: int = 10
    subject_general_limit: int = 120
    message_submit_limit: int = 12
    operation_link_limit: int = 12
    stop_limit: int = 12
    traffic_window_seconds: int = 60
    max_sse_per_subject: int = 1
    sse_lease_ttl_seconds: int = 960


_MINIAPP_DOCUMENT_KEYS = frozenset(
    MiniAppSettings.__dataclass_fields__
)


@dataclass(frozen=True)
class AgentAccessSettings:
    enabled: bool = False
    issuer: str = ""
    mcp_public_url: str = ""


@dataclass(frozen=True)
class OpcSettings:
    """Public OPC device ingress settings.

    OPC does not reuse the C control-plane credentials.  Core's internal URL
    and bearer are supplied by the managed environment at assembly time.
    """

    enabled: bool = False
    public_origin: str = ""


@dataclass(frozen=True)
class NodeSettings:
    profile: Profile
    paths: NodePaths
    host: str
    port: int
    mcp_host: str
    mcp_port: int
    multi_tenant: bool
    storage: StorageSettings
    events: EventSettings
    secrets: SecretSettings
    interaction: InteractionSettings
    execution: ExecutionGateSettings = field(
        default_factory=ExecutionGateSettings
    )
    modules: dict[str, ModuleSettings] = field(default_factory=dict)
    miniapp: MiniAppSettings = field(default_factory=MiniAppSettings)
    agent_access: AgentAccessSettings = field(default_factory=AgentAccessSettings)
    release_mode: bool = False
    opc: OpcSettings = field(default_factory=OpcSettings)

    @classmethod
    def defaults(
        cls,
        profile: Profile = Profile.PERSONAL,
        *,
        paths: NodePaths | None = None,
    ) -> "NodeSettings":
        node_paths = paths or NodePaths.discover()
        module_defaults = {
            "core": ModuleSettings(),
            "marketplace": ModuleSettings(),
            "prediction-markets": ModuleSettings(),
        }
        if profile is Profile.PERSONAL:
            return cls(
                profile=profile,
                paths=node_paths,
                host="127.0.0.1",
                port=8170,
                mcp_host="127.0.0.1",
                mcp_port=9170,
                multi_tenant=False,
                storage=StorageSettings(
                    backend=StorageBackend.SQLITE,
                    sqlite_path=node_paths.data / "clink.db",
                ),
                events=EventSettings(backend=EventBackend.MEMORY),
                secrets=SecretSettings(backend=SecretBackend.KEYCHAIN),
                interaction=InteractionSettings(mode=InteractionMode.LOCAL),
                modules=module_defaults,
            )
        return cls(
            profile=profile,
            paths=node_paths,
            host="127.0.0.1",
            port=8170,
            mcp_host="127.0.0.1",
            mcp_port=9170,
            multi_tenant=True,
            storage=StorageSettings(backend=StorageBackend.POSTGRES),
            events=EventSettings(backend=EventBackend.REDIS),
            secrets=SecretSettings(backend=SecretBackend.VAULT),
            interaction=InteractionSettings(
                mode=InteractionMode.SELF_HOSTED
            ),
            modules=module_defaults,
        )

    @classmethod
    def load(
        cls,
        config_path: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        release_mode: bool | None = None,
        paths: NodePaths | None = None,
    ) -> "NodeSettings":
        source = dict(os.environ if env is None else env)
        effective_release_mode = (
            "CLINK_RUNTIME_ROOT" in source
            if release_mode is None
            else release_mode
        )
        node_paths = (
            paths
            if paths is not None
            else release_node_paths(source)
            if effective_release_mode
            else NodePaths.discover(source)
        )
        requested_profile = Profile(source.get("CLINK_PROFILE", "personal"))
        path = config_path or node_paths.config
        document: dict[str, Any] = {}
        if effective_release_mode:
            document = read_managed_config(path).document
        elif path.is_file():
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        if document:
            requested_profile = Profile(
                source.get(
                    "CLINK_PROFILE",
                    document.get("node", {}).get(
                        "profile",
                        requested_profile,
                    ),
                )
            )

        if effective_release_mode:
            _reject_release_live_gate_attempts(document, source)

        settings = replace(
            cls.defaults(requested_profile, paths=node_paths),
            release_mode=effective_release_mode,
        )
        settings = _apply_document(settings, document)
        settings = _apply_environment(settings, source)
        if effective_release_mode:
            validate_release_writable_paths(settings, source)
        return settings

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not (1 <= self.port <= 65535):
            errors.append("node port must be between 1 and 65535")
        if not (1 <= self.mcp_port <= 65535):
            errors.append("MCP port must be between 1 and 65535")
        if self.port == self.mcp_port and self.host == self.mcp_host:
            errors.append("node HTTP and MCP ports must be different")

        if self.storage.backend is StorageBackend.SQLITE:
            if self.storage.sqlite_path is None:
                errors.append("sqlite storage requires sqlite_path")
        elif not self.storage.postgres_url:
            errors.append("postgres storage requires CLINK_DATABASE_URL")

        if (
            self.events.backend is EventBackend.REDIS
            and not self.events.redis_url
        ):
            errors.append("redis event backend requires CLINK_REDIS_URL")

        if self.secrets.backend is SecretBackend.VAULT:
            if not self.secrets.vault_address:
                errors.append(
                    "vault secret backend requires CLINK_VAULT_ADDR"
                )
            if not self.secrets.vault_token:
                errors.append(
                    "vault secret backend requires CLINK_VAULT_TOKEN"
                )
            elif self.secrets.vault_address and not _vault_address_is_safe(
                self.secrets.vault_address
            ):
                errors.append(
                    "Vault address must use HTTPS except explicit "
                    "loopback development"
                )

        non_loopback_node = not (
            _is_literal_loopback_host(self.host)
            and _is_literal_loopback_host(self.mcp_host)
        )
        if non_loopback_node:
            if self.secrets.backend is not SecretBackend.VAULT:
                errors.append(
                    "non-loopback development requires Vault secrets"
                )
            elif not self.secrets.vault_address or not self.secrets.vault_address.startswith(
                "https://"
            ):
                errors.append(
                    "non-loopback development requires HTTPS Vault"
                )

        if self.interaction.mode is InteractionMode.RELAY:
            if not self.interaction.relay_url:
                errors.append("relay interaction mode requires CLINK_RELAY_URL")
        if self.interaction.mode is InteractionMode.SELF_HOSTED:
            if not self.interaction.public_base_url:
                errors.append(
                    "self_hosted interaction mode requires "
                    "CLINK_PUBLIC_BASE_URL"
                )

        for name, module in self.modules.items():
            if module.mode is ModuleMode.EXTERNAL and not module.endpoint:
                errors.append(
                    f"external module {name} requires an endpoint"
                )
        prediction = self.modules.get("prediction-markets")
        if prediction is not None:
            for service, label in (
                ("preview", "preview"),
                ("execution", "execution"),
                ("funding", "funding"),
                ("deposit_wallet", "deposit wallet"),
            ):
                configured = prediction.service_urls.get(service)
                if configured and not _is_internal_service_base_url(
                    configured
                ):
                    errors.append(
                        "Prediction Markets "
                        + label
                        + " service URL is invalid"
                    )
        errors.extend(_miniapp_validation_errors(self))
        errors.extend(_agent_access_validation_errors(self))
        errors.extend(_opc_validation_errors(self))
        return errors

    def redacted(self) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "home": str(self.paths.home),
            "http": f"http://{self.host}:{self.port}",
            "mcp": f"http://{self.mcp_host}:{self.mcp_port}/mcp",
            "multi_tenant": self.multi_tenant,
            "storage": {
                "backend": self.storage.backend.value,
                "configured": bool(
                    self.storage.sqlite_path or self.storage.postgres_url
                ),
            },
            "events": {
                "backend": self.events.backend.value,
                "configured": (
                    self.events.backend is EventBackend.MEMORY
                    or bool(self.events.redis_url)
                ),
            },
            "secrets": {"backend": self.secrets.backend.value},
            "interaction": {"mode": self.interaction.mode.value},
            "execution": {
                "live_funding": self.execution.live_funding,
                "native_facilitator": self.execution.native_facilitator,
                "prediction_markets_live": (
                    self.execution.prediction_markets_live
                ),
                "risk_provider": self.execution.risk_provider,
                "risk_mode": self.execution.risk_mode,
            },
            "release_mode": self.release_mode,
            "agent_access": {"enabled": self.agent_access.enabled},
            "opc": {"enabled": self.opc.enabled},
            "miniapp": {
                "enabled": self.miniapp.enabled,
                "hermes_transport": "loopback_http",
                "auth_max_age_seconds": (
                    self.miniapp.auth_max_age_seconds
                ),
                "session_ttl_seconds": self.miniapp.session_ttl_seconds,
                "max_stream_seconds": self.miniapp.max_stream_seconds,
                "max_active_runs_per_subject": (
                    self.miniapp.max_active_runs_per_subject
                ),
                "max_sse_per_subject": (
                    self.miniapp.max_sse_per_subject
                ),
            },
            "modules": {
                name: {"mode": module.mode.value}
                for name, module in self.modules.items()
            },
        }


def _apply_document(
    settings: NodeSettings,
    document: dict[str, Any],
) -> NodeSettings:
    node = document.get("node", {})
    storage = document.get("storage", {})
    events = document.get("events", {})
    secrets = document.get("secrets", {})
    interaction = document.get("interaction", {})
    execution = document.get("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("execution must be a TOML table")
    miniapp = _document_table(document, "miniapp")
    agent_access = _document_table(document, "agent_access")
    opc = _document_table(document, "opc")
    if set(agent_access).difference({"enabled", "issuer", "mcp_public_url"}):
        raise ValueError("unknown agent access setting")
    if set(opc).difference({"enabled", "public_origin"}):
        raise ValueError("unknown OPC setting")
    unknown_miniapp_keys = sorted(
        set(miniapp).difference(_MINIAPP_DOCUMENT_KEYS)
    )
    if unknown_miniapp_keys:
        raise ValueError(
            "unknown miniapp setting: " + unknown_miniapp_keys[0]
        )
    modules_doc = document.get("modules", {})

    configured_modules = dict(settings.modules)
    for name, raw in modules_doc.items():
        baseline = configured_modules.get(name, ModuleSettings())
        configured_modules[name] = replace(
            baseline,
            mode=ModuleMode(raw.get("mode", baseline.mode)),
            endpoint=raw.get("endpoint", baseline.endpoint),
            mcp_url=raw.get("mcp_url", baseline.mcp_url),
            service_urls={
                str(key): str(value)
                for key, value in raw.get(
                    "services",
                    baseline.service_urls,
                ).items()
            },
        )

    sqlite_path = settings.storage.sqlite_path
    if storage.get("sqlite_path"):
        sqlite_path = Path(storage["sqlite_path"]).expanduser()

    return replace(
        settings,
        host=node.get("host", settings.host),
        port=int(node.get("port", settings.port)),
        mcp_host=node.get("mcp_host", settings.mcp_host),
        mcp_port=int(node.get("mcp_port", settings.mcp_port)),
        multi_tenant=bool(
            node.get("multi_tenant", settings.multi_tenant)
        ),
        storage=StorageSettings(
            backend=StorageBackend(
                storage.get("backend", settings.storage.backend)
            ),
            sqlite_path=sqlite_path,
            postgres_url=storage.get(
                "postgres_url", settings.storage.postgres_url
            ),
        ),
        events=EventSettings(
            backend=EventBackend(
                events.get("backend", settings.events.backend)
            ),
            redis_url=events.get("redis_url", settings.events.redis_url),
        ),
        secrets=SecretSettings(
            backend=SecretBackend(
                secrets.get("backend", settings.secrets.backend)
            ),
            service_name=secrets.get(
                "service_name", settings.secrets.service_name
            ),
            vault_address=secrets.get(
                "vault_address", settings.secrets.vault_address
            ),
            vault_token=settings.secrets.vault_token,
            vault_mount=secrets.get(
                "vault_mount", settings.secrets.vault_mount
            ),
            vault_path_prefix=secrets.get(
                "vault_path_prefix",
                settings.secrets.vault_path_prefix,
            ),
        ),
        interaction=InteractionSettings(
            mode=InteractionMode(
                interaction.get("mode", settings.interaction.mode)
            ),
            public_base_url=interaction.get(
                "public_base_url",
                settings.interaction.public_base_url,
            ),
            relay_url=interaction.get(
                "relay_url", settings.interaction.relay_url
            ),
            session_ttl_seconds=int(
                interaction.get(
                    "session_ttl_seconds",
                    settings.interaction.session_ttl_seconds,
                )
            ),
        ),
        execution=ExecutionGateSettings(
            live_funding=_execution_boolean(
                execution,
                "live_funding",
                settings.execution.live_funding,
            ),
            native_facilitator=_execution_boolean(
                execution,
                "native_facilitator",
                settings.execution.native_facilitator,
            ),
            prediction_markets_live=_execution_boolean(
                execution,
                "prediction_markets_live",
                settings.execution.prediction_markets_live,
            ),
            risk_provider=_execution_string(
                execution,
                "risk_provider",
                settings.execution.risk_provider,
            ),
            risk_mode=_execution_string(
                execution,
                "risk_mode",
                settings.execution.risk_mode,
            ),
        ),
        modules=configured_modules,
        agent_access=AgentAccessSettings(
            enabled=_document_boolean(agent_access, "enabled", settings.agent_access.enabled),
            issuer=agent_access.get("issuer", settings.agent_access.issuer),
            mcp_public_url=agent_access.get("mcp_public_url", settings.agent_access.mcp_public_url),
        ),
        opc=OpcSettings(
            enabled=_document_boolean(opc, "enabled", settings.opc.enabled),
            public_origin=_document_string(
                opc,
                "public_origin",
                settings.opc.public_origin,
            ),
        ),
        miniapp=MiniAppSettings(
            enabled=_document_boolean(
                miniapp,
                "enabled",
                settings.miniapp.enabled,
            ),
            hermes_base_url=miniapp.get(
                "hermes_base_url",
                settings.miniapp.hermes_base_url,
            ),
            auth_max_age_seconds=_document_integer(
                miniapp,
                "auth_max_age_seconds",
                settings.miniapp.auth_max_age_seconds,
            ),
            session_ttl_seconds=_document_integer(
                miniapp,
                "session_ttl_seconds",
                settings.miniapp.session_ttl_seconds,
            ),
            connect_timeout_seconds=_document_integer(
                miniapp,
                "connect_timeout_seconds",
                settings.miniapp.connect_timeout_seconds,
            ),
            read_timeout_seconds=_document_integer(
                miniapp,
                "read_timeout_seconds",
                settings.miniapp.read_timeout_seconds,
            ),
            max_stream_seconds=_document_integer(
                miniapp,
                "max_stream_seconds",
                settings.miniapp.max_stream_seconds,
            ),
            max_active_runs_per_subject=_document_integer(
                miniapp,
                "max_active_runs_per_subject",
                settings.miniapp.max_active_runs_per_subject,
            ),
            ip_general_limit=_document_integer(
                miniapp,
                "ip_general_limit",
                settings.miniapp.ip_general_limit,
            ),
            session_exchange_limit=_document_integer(
                miniapp,
                "session_exchange_limit",
                settings.miniapp.session_exchange_limit,
            ),
            subject_general_limit=_document_integer(
                miniapp,
                "subject_general_limit",
                settings.miniapp.subject_general_limit,
            ),
            message_submit_limit=_document_integer(
                miniapp,
                "message_submit_limit",
                settings.miniapp.message_submit_limit,
            ),
            operation_link_limit=_document_integer(
                miniapp,
                "operation_link_limit",
                settings.miniapp.operation_link_limit,
            ),
            stop_limit=_document_integer(
                miniapp,
                "stop_limit",
                settings.miniapp.stop_limit,
            ),
            traffic_window_seconds=_document_integer(
                miniapp,
                "traffic_window_seconds",
                settings.miniapp.traffic_window_seconds,
            ),
            max_sse_per_subject=_document_integer(
                miniapp,
                "max_sse_per_subject",
                settings.miniapp.max_sse_per_subject,
            ),
            sse_lease_ttl_seconds=_document_integer(
                miniapp,
                "sse_lease_ttl_seconds",
                settings.miniapp.sse_lease_ttl_seconds,
            ),
        ),
    )


def _apply_environment(
    settings: NodeSettings,
    env: dict[str, str],
) -> NodeSettings:
    storage = replace(
        settings.storage,
        postgres_url=env.get(
            "CLINK_DATABASE_URL", settings.storage.postgres_url
        ),
    )
    if env.get("CLINK_SQLITE_PATH"):
        storage = replace(
            storage,
            sqlite_path=Path(env["CLINK_SQLITE_PATH"]).expanduser(),
        )

    interaction = replace(
        settings.interaction,
        public_base_url=env.get(
            "CLINK_PUBLIC_BASE_URL",
            settings.interaction.public_base_url,
        ),
        relay_url=env.get(
            "CLINK_RELAY_URL", settings.interaction.relay_url
        ),
    )

    miniapp = replace(
        settings.miniapp,
        enabled=_environment_boolean(
            env,
            "CLINK_MINIAPP_ENABLED",
            settings.miniapp.enabled,
        ),
        hermes_base_url=env.get(
            "CLINK_MINIAPP_HERMES_BASE_URL",
            settings.miniapp.hermes_base_url,
        ),
        **{
            field_name: _environment_integer(
                env,
                f"CLINK_MINIAPP_{field_name.upper()}",
                getattr(settings.miniapp, field_name),
            )
            for field_name in _MINIAPP_INTEGER_BOUNDS
        },
    )

    opc = replace(
        settings.opc,
        enabled=_environment_boolean(
            env,
            "CLINK_OPC_ENABLED",
            settings.opc.enabled,
        ),
        public_origin=env.get(
            "CLINK_OPC_PUBLIC_ORIGIN",
            settings.opc.public_origin,
        ),
    )

    modules = dict(settings.modules)
    for name, module in modules.items():
        prefix = name.upper().replace("-", "_")
        raw_mode = env.get(f"CLINK_MODULE_{prefix}_MODE")
        endpoint = env.get(f"CLINK_MODULE_{prefix}_URL", module.endpoint)
        mcp_url = env.get(f"CLINK_MODULE_{prefix}_MCP_URL", module.mcp_url)
        modules[name] = replace(
            module,
            mode=ModuleMode(raw_mode) if raw_mode else module.mode,
            endpoint=endpoint,
            mcp_url=mcp_url,
        )
    core = modules.get("core")
    if core is not None:
        service_urls = dict(core.service_urls)
        for service in (
            "account",
            "action",
            "policy",
            "audit",
            "funding",
        ):
            variable = f"CLINK_CORE_{service.upper()}_SERVICE_URL"
            if env.get(variable):
                service_urls[service] = env[variable]
        modules["core"] = replace(core, service_urls=service_urls)

    prediction = modules.get("prediction-markets")
    if prediction is not None:
        service_urls = dict(prediction.service_urls)
        for service, variable in {
            "account_binding": (
                "CLINK_PREDICTION_MARKETS_ACCOUNT_BINDING_SERVICE_URL"
            ),
            "preview": "CLINK_PREDICTION_MARKETS_PREVIEW_SERVICE_URL",
            "execution": (
                "CLINK_PREDICTION_MARKETS_EXECUTION_SERVICE_URL"
            ),
            "funding": (
                "CLINK_PREDICTION_MARKETS_FUNDING_ADAPTER_SERVICE_URL"
            ),
            "deposit_wallet": (
                "CLINK_PREDICTION_MARKETS_DEPOSIT_WALLET_SERVICE_URL"
            ),
        }.items():
            configured = env.get(variable)
            if configured:
                service_urls[service] = configured
        modules["prediction-markets"] = replace(
            prediction,
            service_urls=service_urls,
        )

    execution = settings.execution
    for variable, attribute in _EXECUTION_ENV_GATES.items():
        if variable in env:
            execution = replace(
                execution,
                **{
                    attribute: _environment_boolean(
                        env,
                        variable,
                        getattr(execution, attribute),
                    )
                },
            )
    if not settings.release_mode:
        execution = replace(
            execution,
            risk_provider=env.get(
                "CLINK_RISK_PROVIDER",
                execution.risk_provider,
            ),
            risk_mode=env.get("CLINK_RISK_MODE", execution.risk_mode),
        )

    return replace(
        settings,
        host=env.get("CLINK_NODE_HOST", settings.host),
        port=int(env.get("CLINK_NODE_PORT", settings.port)),
        mcp_host=env.get("CLINK_MCP_HOST", settings.mcp_host),
        mcp_port=int(env.get("CLINK_MCP_PORT", settings.mcp_port)),
        storage=storage,
        events=replace(
            settings.events,
            redis_url=env.get(
                "CLINK_REDIS_URL", settings.events.redis_url
            ),
        ),
        secrets=replace(
            settings.secrets,
            vault_address=env.get(
                "CLINK_VAULT_ADDR",
                settings.secrets.vault_address,
            ),
            vault_token=env.get(
                "CLINK_VAULT_TOKEN",
                settings.secrets.vault_token,
            ),
            vault_mount=env.get(
                "CLINK_VAULT_MOUNT",
                settings.secrets.vault_mount,
            ),
            vault_path_prefix=env.get(
                "CLINK_VAULT_PATH_PREFIX",
                settings.secrets.vault_path_prefix,
            ),
        ),
        interaction=interaction,
        execution=execution,
        modules=modules,
        miniapp=miniapp,
        agent_access=replace(
            settings.agent_access,
            enabled=_environment_boolean(env, "CLINK_AGENT_ACCESS_ENABLED", settings.agent_access.enabled),
            issuer=env.get("CLINK_AGENT_ACCESS_ISSUER", settings.agent_access.issuer),
            mcp_public_url=env.get("CLINK_AGENT_ACCESS_MCP_PUBLIC_URL", settings.agent_access.mcp_public_url),
        ),
        opc=opc,
    )


def _agent_access_validation_errors(settings: NodeSettings) -> list[str]:
    access = settings.agent_access
    if not access.enabled:
        return []
    errors = []
    if settings.profile is not Profile.SERVER or not settings.multi_tenant:
        errors.append("agent access requires the multi-tenant Server Profile")
    if settings.miniapp.enabled:
        errors.append("agent access requires a dedicated Node ingress with MiniApp disabled")
    if not isinstance(access.issuer, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", access.issuer):
        errors.append("agent access requires a stable issuer identifier")
    safe = False
    try:
        parsed = urlsplit(access.mcp_public_url)
        safe = (
            parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and (parsed.scheme == "https" or _is_literal_loopback_host(parsed.hostname))
            and parsed.path.rstrip("/").endswith("/mcp")
            and not any(ord(ch) <= 32 for ch in access.mcp_public_url)
        )
        parsed.port  # Reject malformed ports too.
    except (TypeError, ValueError, AttributeError):
        safe = False
    if not safe:
        errors.append("agent access requires an HTTPS MCP URL without credentials, query or fragment")
    return errors


def _opc_validation_errors(settings: NodeSettings) -> list[str]:
    opc = settings.opc
    if not opc.enabled:
        return []
    errors: list[str] = []
    if settings.profile is not Profile.SERVER or not settings.multi_tenant:
        errors.append("OPC requires the multi-tenant Server Profile")
    if settings.miniapp.enabled:
        errors.append("OPC requires a dedicated Node ingress with MiniApp disabled")
    if not _is_safe_opc_public_origin(opc.public_origin):
        errors.append(
            "OPC requires an HTTPS public origin without credentials, path, query or fragment"
        )
    return errors


def _is_safe_opc_public_origin(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(ord(character) <= 32 for character in value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject malformed ports too.
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except (TypeError, ValueError, AttributeError):
        return False
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port is not None and not (
        (parsed.scheme == "https" and port == 443)
        or (parsed.scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    canonical = f"{parsed.scheme}://{host}"
    return (
        parsed.scheme in {"https", "http"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and (
            parsed.scheme == "https"
            or _is_literal_loopback_host(parsed.hostname)
        )
        and value == canonical
    )


_EXECUTION_ENV_GATES = {
    "CLINK_LIVE_FUNDING": "live_funding",
    "CLINK_NATIVE_FACILITATOR_ENABLED": "native_facilitator",
    "PREDICTION_MARKETS_LIVE_MODE": "prediction_markets_live",
}


_MINIAPP_INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "auth_max_age_seconds": (1, 3_600),
    "session_ttl_seconds": (60, 2_592_000),
    "connect_timeout_seconds": (1, 60),
    "read_timeout_seconds": (1, 300),
    "max_stream_seconds": (60, 3_600),
    "max_active_runs_per_subject": (1, 1),
    "ip_general_limit": (1, 1_000_000),
    "session_exchange_limit": (1, 1_000_000),
    "subject_general_limit": (1, 1_000_000),
    "message_submit_limit": (1, 1_000_000),
    "operation_link_limit": (1, 1_000_000),
    "stop_limit": (1, 1_000_000),
    "traffic_window_seconds": (1, 3_600),
    "max_sse_per_subject": (1, 1),
    "sse_lease_ttl_seconds": (900, 86_400),
}


def _document_table(
    document: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a table")
    return value


def _document_boolean(
    document: dict[str, Any],
    name: str,
    default: bool,
) -> bool:
    value = document.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"miniapp.{name} must be a boolean")
    return value


def _execution_boolean(
    document: dict[str, Any],
    name: str,
    default: bool,
) -> bool:
    value = document.get(name, default)
    if type(value) is not bool:
        raise ValueError(f"execution.{name} must be a boolean")
    return value


def _execution_string(
    document: dict[str, Any],
    name: str,
    default: str,
) -> str:
    value = document.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"execution.{name} must be a string")
    return value


def _document_integer(
    document: dict[str, Any],
    name: str,
    default: int,
) -> int:
    value = document.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"miniapp.{name} must be an integer")
    return value


def _document_string(
    document: dict[str, Any],
    name: str,
    default: str,
) -> str:
    value = document.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"opc.{name} must be a string")
    return value


def _environment_boolean(
    env: dict[str, str],
    name: str,
    default: bool,
) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ValueError(f"{name} must be true or false")


def _environment_integer(
    env: dict[str, str],
    name: str,
    default: int,
) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if str(value) != raw:
        raise ValueError(f"{name} must be a canonical integer")
    return value


@dataclass(frozen=True)
class ManagedConfigSnapshot:
    document: dict[str, Any]
    identity: PathIdentity | None


def read_managed_config(
    path: Path,
    *,
    expected_parent_identity: PathIdentity | None = None,
) -> ManagedConfigSnapshot:
    """Read a release config through owner-only, no-follow descriptors."""

    parent = path.parent
    try:
        parent_metadata = os.lstat(parent)
    except FileNotFoundError:
        if expected_parent_identity is not None:
            raise PermissionError(
                f"config directory disappeared: {parent}"
            ) from None
        return ManagedConfigSnapshot(document={}, identity=None)
    _validate_managed_config_directory(parent, parent_metadata)
    parent_identity = PathIdentity.from_stat(parent_metadata)
    if (
        expected_parent_identity is not None
        and not expected_parent_identity.matches(parent_metadata)
    ):
        raise PermissionError(f"config directory changed: {parent}")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        parent_descriptor = os.open(parent, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise PermissionError(
                f"config directory must not be a symlink: {parent}"
            ) from None
        raise
    try:
        opened_parent = os.fstat(parent_descriptor)
        _validate_managed_config_directory(parent, opened_parent)
        if not parent_identity.matches(opened_parent):
            raise PermissionError(
                f"config directory changed during validation: {parent}"
            )
        try:
            metadata = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return ManagedConfigSnapshot(document={}, identity=None)
        _validate_managed_config_file(path, metadata)
        expected_identity = PathIdentity.from_stat(metadata)
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(
                path.name,
                file_flags,
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PermissionError(
                    f"config file must not be a symlink: {path}"
                ) from None
            raise
        try:
            opened = os.fstat(descriptor)
            _validate_managed_config_file(path, opened)
            if not expected_identity.matches(opened):
                raise PermissionError(
                    f"config file changed during validation: {path}"
                )
            raw = os.read(descriptor, _MAX_CONFIG_DOCUMENT_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > _MAX_CONFIG_DOCUMENT_BYTES:
            raise ValueError("config file exceeds the allowed size")
        current = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _validate_managed_config_file(path, current)
        if not expected_identity.matches(current):
            raise PermissionError(f"config file changed: {path}")
        return ManagedConfigSnapshot(
            document=tomllib.loads(raw.decode("utf-8")),
            identity=expected_identity,
        )
    finally:
        os.close(parent_descriptor)


def _validate_managed_config_directory(
    path: Path,
    metadata: os.stat_result,
) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"config parent must be a real directory: {path}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"config directory owner must be uid {os.getuid()}: {path}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PermissionError(f"config directory permissions must be 0700: {path}")


def _validate_managed_config_file(
    path: Path,
    metadata: os.stat_result,
) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PermissionError(f"config file must be a regular file: {path}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"config file owner must be uid {os.getuid()}: {path}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PermissionError(f"config file permissions must be 0600: {path}")
    if metadata.st_nlink != 1:
        raise PermissionError(f"config file must have exactly one link: {path}")


def _reject_release_live_gate_attempts(
    document: dict[str, Any],
    env: dict[str, str],
) -> None:
    execution = document.get("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("execution must be a TOML table")
    facilitator_mode = env.get("CLINK_FACILITATOR_MODE")
    if facilitator_mode is not None:
        normalized_mode = facilitator_mode.strip().lower()
        if normalized_mode not in {"disabled", "hosted", "native"}:
            raise ValueError(
                "CLINK_FACILITATOR_MODE must be disabled, hosted, or native"
            )
        if normalized_mode == "native":
            raise UnsafeReleaseConfiguration(
                "unsafe release configuration: CLINK_FACILITATOR_MODE"
            )
    for variable, attribute in _EXECUTION_ENV_GATES.items():
        if attribute in execution and _execution_boolean(
            execution,
            attribute,
            False,
        ):
            raise UnsafeReleaseConfiguration(
                "unsafe release configuration: " + attribute
            )
        if variable in env and _environment_boolean(env, variable, False):
            raise UnsafeReleaseConfiguration(
                "unsafe release configuration: " + variable
            )


def _is_literal_loopback_host(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _vault_address_is_safe(value: str) -> bool:
    if not value or value != value.strip() or "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except (UnicodeError, ValueError):
        return False
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and _is_literal_loopback_host(
        parsed.hostname
    )


def _miniapp_validation_errors(settings: NodeSettings) -> list[str]:
    miniapp = settings.miniapp
    errors: list[str] = []
    if not isinstance(miniapp.enabled, bool):
        errors.append("Mini App enabled must be a boolean")
    if not _is_loopback_http_url(miniapp.hermes_base_url):
        errors.append("Mini App Hermes base URL must be loopback HTTP")
    for name, (minimum, maximum) in _MINIAPP_INTEGER_BOUNDS.items():
        value = getattr(miniapp, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
            or value > maximum
        ):
            if name == "max_active_runs_per_subject":
                errors.append(
                    "Mini App max active runs per subject must equal 1"
                )
            elif name == "max_sse_per_subject":
                errors.append("Mini App max SSE per subject must equal 1")
            else:
                errors.append(
                    f"Mini App {name.replace('_', ' ')} must be between "
                    f"{minimum} and {maximum}"
                )
    if (
        isinstance(miniapp.sse_lease_ttl_seconds, int)
        and isinstance(miniapp.max_stream_seconds, int)
        and miniapp.sse_lease_ttl_seconds < miniapp.max_stream_seconds
    ):
        errors.append(
            "Mini App SSE lease TTL must cover the maximum stream duration"
        )
    if (
        miniapp.enabled
        and settings.profile is Profile.SERVER
        and (
            settings.events.backend is not EventBackend.REDIS
            or not settings.events.redis_url
        )
    ):
        errors.append("Server Mini App requires shared Redis")
    return errors


def _is_loopback_http_url(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def _is_internal_service_base_url(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except (UnicodeError, ValueError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
