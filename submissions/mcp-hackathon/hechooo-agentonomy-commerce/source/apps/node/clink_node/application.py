from __future__ import annotations

import os
import re
import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Protocol

import redis
import uvicorn
from sqlalchemy import create_engine
from starlette.types import ASGIApp

from .adapters.core import CoreHttpAdapter
from .adapters.http import DownstreamError
from .adapters.marketplace import MarketplaceHttpAdapter
from .adapters.prediction_markets import PredictionMarketsHttpAdapter
from .agent_access import AgentAccessService, CompositeRuntimeAuthenticator
from .agent_access_http import attach_opc_routes
from .agent_access_mcp import AgentScopedMcpProxy
from .api import NodeApiContext, create_app
from .config import (
    MINIAPP_SECRET_NAMES,
    EventBackend,
    InteractionMode,
    ModuleMode,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageBackend,
    validate_miniapp_secret_values,
)
from .events import MemoryEventSink, OutboxDispatcher, RedisEventSink
from .hermes.client import HermesClient
from .instance_lock import InstanceLock
from .interactions import InteractionService
from .mcp_gateway import build_native_tools, create_mcp_application
from .mcp_proxy import McpToolProxy, StreamableHttpMcpClient
from .opc_core_client import OpcCoreClient
from .modules import default_module_definitions
from .miniapp import (
    MemoryMiniAppTrafficGuard,
    MiniAppChatService,
    MiniAppTrafficPolicy,
    RedisMiniAppTrafficGuard,
)
from .runtime import ManagedEnvironmentBuilder
from .schema_contract import prepare_sqlite_path
from .service_manager import LifecycleLock, ServiceManager
from .secrets import (
    EnvelopeCipher,
    KeyringSecretStore,
    RestrictedFileSecretStore,
    SecretStore,
    VaultSecretStore,
)
from .storage.base import NodeRepository
from .storage.agent_access import AgentAccessRepository
from .storage.postgres import PostgresNodeRepository
from .storage.sqlite import SQLiteNodeRepository
from .supervisor import ModuleSupervisor


_EVM_ADDRESS = re.compile(r"^0[xX]([0-9a-fA-F]{40})$")
_AGENT_ACCESS_CONTROL_SECRET = "agent-access-control-token"
_AGENT_ACCESS_TOKEN_KEY_SECRET = "agent-access-token-key"
_FACILITATOR_MODE_ENV = "CLINK_FACILITATOR_MODE"
_HOSTED_REGISTRY_FILE_ENV = "CLINK_HOSTED_WALLET_CREDENTIALS_FILE"
_AGENT_ACCESS_INTERNAL_SECRET_NAMES = (
    ManagedEnvironmentBuilder.CORE_TOKEN,
    ManagedEnvironmentBuilder.RECEIPT_KEY,
    ManagedEnvironmentBuilder.MARKETPLACE_TOKEN,
    ManagedEnvironmentBuilder.PREDICTION_TOKEN,
    ManagedEnvironmentBuilder.CREDENTIAL_KEY,
)
_AGENT_ACCESS_INTERNAL_ENV_NAMES = (
    "CLINK_CORE_INTERNAL_API_TOKEN",
    "CLINK_RECEIPT_SIGNING_KEY",
    "MARKETPLACE_INTERNAL_API_TOKEN",
    "PREDICTION_MARKETS_INTERNAL_API_TOKEN",
    "PREDICTION_MARKETS_CORE_INTERNAL_API_TOKEN",
    "CLINK_CREDENTIAL_ENCRYPTION_KEY",
)


class Supervisor(Protocol):
    def start_all(self) -> None: ...

    def stop_all(self) -> None: ...

    def refresh(self) -> list: ...


class ServerRunner(Protocol):
    def start(self) -> None: ...

    def run(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class NodeAssembly:
    repository: NodeRepository
    supervisor: Supervisor
    context: NodeApiContext
    mcp_proxy: McpToolProxy | AgentScopedMcpProxy
    api_application: ASGIApp
    mcp_application: ASGIApp
    event_dispatcher: OutboxDispatcher | None = None
    resource_closers: tuple[Callable[[], None], ...] = ()
    lifecycle_lock: LifecycleLock | None = None
    instance_lock: InstanceLock | None = None

    def release_lifecycle_locks(self) -> None:
        instance_lock = self.instance_lock
        lifecycle_lock = self.lifecycle_lock
        object.__setattr__(self, "instance_lock", None)
        object.__setattr__(self, "lifecycle_lock", None)
        if instance_lock is not None:
            instance_lock.release()
        if lifecycle_lock is not None:
            lifecycle_lock.release()

    def __del__(self) -> None:
        try:
            self.release_lifecycle_locks()
        except Exception:
            pass


def assemble_node(
    settings: NodeSettings,
    *,
    secret_store: SecretStore | None = None,
    repository: NodeRepository | None = None,
) -> NodeAssembly:
    settings.paths.ensure()
    lifecycle_lock = LifecycleLock(
        settings.paths.runtime / "lifecycle.lock",
        exclusive=False,
    ).acquire()
    instance_lock = InstanceLock(
        settings.paths.runtime / "node.lock"
    ).acquire()
    try:
        ServiceManager(settings.paths).ensure_not_quiesced()
        if settings.release_mode and settings.storage.sqlite_path is not None:
            prepare_sqlite_path(settings.storage.sqlite_path)
        assembly = _assemble_node(
            settings,
            secret_store=secret_store,
            repository=repository,
        )
    except BaseException:
        instance_lock.release()
        lifecycle_lock.release()
        raise
    return replace(
        assembly,
        lifecycle_lock=lifecycle_lock,
        instance_lock=instance_lock,
    )


def _assemble_node(
    settings: NodeSettings,
    *,
    secret_store: SecretStore | None = None,
    repository: NodeRepository | None = None,
) -> NodeAssembly:
    validation_errors = settings.validation_errors()
    if (settings.agent_access.enabled or settings.opc.enabled) and validation_errors:
        raise RuntimeError(
            "Agent ingress settings are invalid: "
            + "; ".join(validation_errors)
        )
    store = secret_store or _secret_store(settings)
    repo = repository or _repository(settings, store)
    repo.migrate()

    environment = ManagedEnvironmentBuilder(settings, store).build()
    root = Path(__file__).resolve().parents[3]
    definitions = default_module_definitions(root, settings)
    supervisor = ModuleSupervisor(
        definitions,
        repo,
        environment=environment,
        log_directory=settings.paths.logs / "modules",
    )

    core = CoreHttpAdapter(
        account_url=environment["CLINK_CORE_ACCOUNT_SERVICE_URL"],
        action_url=environment["CLINK_CORE_ACTION_SERVICE_URL"],
        policy_url=environment["CLINK_CORE_POLICY_SERVICE_URL"],
        audit_url=environment["CLINK_CORE_AUDIT_SERVICE_URL"],
        funding_url=environment["CLINK_CORE_FUNDING_SERVICE_URL"],
        internal_token=environment["CLINK_CORE_INTERNAL_API_TOKEN"],
        public_base_url=_interaction_base_url(settings),
    )
    marketplace = MarketplaceHttpAdapter(
        base_url=(
            settings.modules["marketplace"].endpoint
            or "http://127.0.0.1:8050"
        ),
        internal_token=environment["MARKETPLACE_INTERNAL_API_TOKEN"],
    )
    prediction_live_enabled = (
        environment.get("PREDICTION_MARKETS_LIVE_MODE", "false").lower()
        == "true"
    )
    prediction = PredictionMarketsHttpAdapter(
        base_url=(
            settings.modules["prediction-markets"].endpoint
            or "http://127.0.0.1:8040"
        ),
        account_binding_url=(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("account_binding")
            or "http://127.0.0.1:8047"
        ),
        preview_url=(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("preview")
            or "http://127.0.0.1:8041"
        ),
        execution_url=(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("execution")
            or "http://127.0.0.1:8042"
        ),
        funding_url=(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("funding")
            or "http://127.0.0.1:8046"
        ),
        deposit_wallet_url=(
            settings.modules[
                "prediction-markets"
            ].service_urls.get("deposit_wallet")
        ),
        internal_token=environment[
            "PREDICTION_MARKETS_INTERNAL_API_TOKEN"
        ],
        account_binding_internal_token=environment[
            "CLINK_CORE_INTERNAL_API_TOKEN"
        ],
        public_base_url=_interaction_base_url(settings),
        live_operations_enabled=prediction_live_enabled,
    )
    miniapp_service, miniapp_resource_closers = _assemble_miniapp(
        settings,
        store=store,
        repository=repo,
        account_link_factory=core.create_account_session,
        polymarket_link_factory=_miniapp_polymarket_link_factory(
            core,
            prediction,
        ),
        polymarket_live_operations=(
            prediction if prediction_live_enabled else None
        ),
    )
    resource_closers = list(miniapp_resource_closers)
    try:
        interaction_service = InteractionService(
            repo,
            base_url=_interaction_base_url(settings),
            ttl_seconds=settings.interaction.session_ttl_seconds,
        )
        session_token = _persistent_text_secret(
            store,
            "node-local-session-token",
        )
        (
            agent_access_service,
            agent_control_token,
            agent_access_resource_closers,
        ) = _assemble_agent_access(
            settings,
            store=store,
            repository=repo,
            environment=environment,
            node_session_token=session_token,
        )
        resource_closers.extend(agent_access_resource_closers)
        opc_core_client = _assemble_opc_core_client(
            settings,
            environment=environment,
        )
        if opc_core_client is not None:
            resource_closers.append(opc_core_client.close)
        runtime_access_service = _compose_runtime_authenticator(
            agent_access_service,
            opc_core_client,
        )
        context = NodeApiContext(
            settings=settings,
            repository=repo,
            interaction_service=interaction_service,
            session_token=session_token,
            core=core,
            marketplace=marketplace,
            prediction_markets=prediction,
            miniapp_service=miniapp_service,
            agent_access_service=agent_access_service,
            agent_control_token=agent_control_token,
        )

        downstreams = {}
        for definition in definitions:
            if (
                definition.name == "core"
                or definition.mode is ModuleMode.DISABLED
                or not definition.mcp_url
            ):
                continue
            downstreams[definition.name] = StreamableHttpMcpClient(
                definition.mcp_url
            )
        proxy = McpToolProxy(
            downstreams,
            native_tools=build_native_tools(context),
        )
        if runtime_access_service is None:
            assembly_proxy = proxy
            mcp_application = create_mcp_application(proxy)
        else:
            assembly_proxy = AgentScopedMcpProxy(proxy, context)
            mcp_application = create_mcp_application(
                assembly_proxy,
                access_service=runtime_access_service,
            )
        event_sink = _event_sink(settings)
        if isinstance(event_sink, RedisEventSink):
            resource_closers.append(event_sink.client.close)
        event_dispatcher = OutboxDispatcher(repo, event_sink)
        api_application = create_app(context)
        if opc_core_client is not None:
            attach_opc_routes(
                api_application,
                opc_core_client,
                public_origin=settings.opc.public_origin,
                account_public_origin=_interaction_base_url(settings),
                control_token=agent_control_token or None,
                allow_loopback_http=True,
                add_ingress=not settings.agent_access.enabled,
            )
        return NodeAssembly(
            repository=repo,
            supervisor=supervisor,
            context=context,
            mcp_proxy=assembly_proxy,
            api_application=api_application,
            mcp_application=mcp_application,
            event_dispatcher=event_dispatcher,
            resource_closers=tuple(resource_closers),
        )
    except BaseException:
        _close_resources(tuple(resource_closers))
        raise


def _compose_runtime_authenticator(
    agent_access_service: AgentAccessService | None,
    opc_core_client: OpcCoreClient | None,
):
    if agent_access_service is not None and opc_core_client is not None:
        return CompositeRuntimeAuthenticator(
            agent_access_service,
            opc_core_client,
        )
    return agent_access_service or opc_core_client


def _assemble_opc_core_client(
    settings: NodeSettings,
    *,
    environment: dict[str, str],
) -> OpcCoreClient | None:
    if not settings.opc.enabled:
        return None
    account_url = environment.get("CLINK_CORE_ACCOUNT_SERVICE_URL")
    internal_token = environment.get("CLINK_CORE_INTERNAL_API_TOKEN")
    if not isinstance(account_url, str) or not account_url:
        raise RuntimeError("OPC Core account service URL is not configured")
    if not isinstance(internal_token, str) or not internal_token:
        raise RuntimeError("OPC Core internal credential is not configured")
    try:
        return OpcCoreClient(
            account_url=account_url,
            internal_token=internal_token,
            public_origin=settings.opc.public_origin,
            account_public_origin=_interaction_base_url(settings),
            allow_loopback_http=True,
        )
    except ValueError:
        raise RuntimeError("OPC Core client configuration is invalid") from None


def _assemble_agent_access(
    settings: NodeSettings,
    *,
    store: SecretStore,
    repository: NodeRepository,
    environment: dict[str, str],
    node_session_token: str,
) -> tuple[
    AgentAccessService | None,
    str,
    tuple[Callable[[], None], ...],
]:
    if not settings.agent_access.enabled:
        return None, "", ()

    _require_hosted_registry_configuration(environment)
    control_token, token_key = _load_agent_access_secrets(
        store,
        environment=environment,
        node_session_token=node_session_token,
    )
    access_repository, resource_closers = _agent_access_repository(
        repository
    )
    try:
        service = AgentAccessService(
            access_repository,
            issuer=settings.agent_access.issuer,
            token_key=token_key,
        )
    except BaseException:
        _close_resources(resource_closers)
        raise
    return service, control_token.decode("ascii"), resource_closers


def _require_hosted_registry_configuration(
    environment: dict[str, str],
) -> None:
    mode = environment.get(_FACILITATOR_MODE_ENV, "")
    if not isinstance(mode, str) or mode.strip().lower() != "hosted":
        raise RuntimeError(
            "Agent access requires Hosted facilitator mode"
        )

    registry_file = environment.get(_HOSTED_REGISTRY_FILE_ENV, "")
    if (
        not isinstance(registry_file, str)
        or not registry_file
        or registry_file != registry_file.strip()
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in registry_file
        )
        or not Path(registry_file).is_absolute()
    ):
        raise RuntimeError(
            "Agent access requires an absolute Hosted wallet registry file"
        )


def _load_agent_access_secrets(
    store: SecretStore,
    *,
    environment: dict[str, str],
    node_session_token: str,
) -> tuple[bytes, bytes]:
    try:
        control_token = store.get(_AGENT_ACCESS_CONTROL_SECRET)
        token_key = store.get(_AGENT_ACCESS_TOKEN_KEY_SECRET)
        internal_values = [
            store.get(name) for name in _AGENT_ACCESS_INTERNAL_SECRET_NAMES
        ]
        miniapp_values = [store.get(name) for name in MINIAPP_SECRET_NAMES]
    except Exception:
        raise RuntimeError("Agent access secret store unavailable") from None

    missing = []
    if control_token is None:
        missing.append(_AGENT_ACCESS_CONTROL_SECRET)
    if token_key is None:
        missing.append(_AGENT_ACCESS_TOKEN_KEY_SECRET)
    if missing:
        raise RuntimeError(
            "Agent access required secrets are not configured: "
            + ", ".join(missing)
        )

    if (
        not isinstance(control_token, bytes)
        or len(control_token) < 32
        or any(byte < 0x21 or byte > 0x7E for byte in control_token)
    ):
        raise RuntimeError("Agent access control token is invalid")
    if not isinstance(token_key, bytes) or len(token_key) < 32:
        raise RuntimeError("Agent access token key is invalid")
    if control_token == token_key:
        raise RuntimeError("Agent access credentials must be distinct")

    forbidden_values = {
        value for value in (*internal_values, *miniapp_values)
        if isinstance(value, bytes)
    }
    forbidden_values.add(node_session_token.encode("ascii"))
    for name in _AGENT_ACCESS_INTERNAL_ENV_NAMES:
        value = environment.get(name)
        if value is None:
            continue
        try:
            forbidden_values.add(value.encode("ascii"))
        except UnicodeEncodeError:
            continue
    if control_token in forbidden_values or token_key in forbidden_values:
        raise RuntimeError(
            "Agent access credentials must not reuse internal credentials"
        )
    return control_token, token_key


def _agent_access_repository(
    repository: NodeRepository,
) -> tuple[AgentAccessRepository, tuple[Callable[[], None], ...]]:
    if isinstance(repository, PostgresNodeRepository):
        # Server profile and its access repository share one transaction pool.
        return AgentAccessRepository(repository.engine), ()

    if isinstance(repository, SQLiteNodeRepository):
        engine = create_engine(
            f"sqlite+pysqlite:///{repository.path}"
        )
        try:
            access_repository = AgentAccessRepository(engine)
        except BaseException:
            engine.dispose()
            raise
        return access_repository, (engine.dispose,)

    engine = getattr(repository, "engine", None)
    if engine is not None:
        return AgentAccessRepository(engine), ()
    raise RuntimeError("Agent access requires a SQLAlchemy Node repository")


class UvicornServer:
    def __init__(
        self,
        application: ASGIApp,
        *,
        host: str,
        port: int,
        log_level: str = "info",
    ) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(
                application,
                host=host,
                port=port,
                log_level=log_level,
                access_log=False,
            )
        )
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("server already started")
        self.thread = threading.Thread(
            target=self.server.run,
            name="clink-mcp-server",
            daemon=True,
        )
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError("Clink server exited during startup")
            if time.monotonic() >= deadline:
                raise TimeoutError("Clink server did not become ready")
            time.sleep(0.05)

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=15)


class ClinkNodeRuntime:
    def __init__(
        self,
        settings: NodeSettings,
        *,
        assembly: NodeAssembly | None = None,
        http_server: ServerRunner | None = None,
        mcp_server: ServerRunner | None = None,
        refresh_interval_seconds: float = 5,
    ) -> None:
        self.settings = settings
        owns_assembly = assembly is None
        self.assembly = assembly or assemble_node(settings)
        try:
            self.http_server = http_server or UvicornServer(
                self.assembly.api_application,
                host=settings.host,
                port=settings.port,
            )
            self.mcp_server = mcp_server or UvicornServer(
                self.assembly.mcp_application,
                host=settings.mcp_host,
                port=settings.mcp_port,
            )
        except BaseException:
            if owns_assembly:
                _close_resources(self.assembly.resource_closers)
                self.assembly.release_lifecycle_locks()
            raise
        self.refresh_interval_seconds = refresh_interval_seconds
        self._refresh_stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None
        self._resource_close_lock = threading.Lock()
        self._resources_closed = False

    def run(self) -> None:
        primary_error: BaseException | None = None
        cleanup_errors: list[BaseException] = []
        try:
            self.settings.paths.ensure()
            try:
                with self._termination_guard(), self._pid_guard():
                    try:
                        self.assembly.supervisor.start_all()
                        if self.assembly.event_dispatcher is not None:
                            self.assembly.event_dispatcher.dispatch()
                        self.mcp_server.start()
                        self._start_refresh_loop()
                        self.http_server.run()
                    except BaseException as exc:
                        primary_error = exc
                    finally:
                        self._refresh_stop.set()
                        if (
                            self._refresh_thread is not None
                            and self._refresh_thread.is_alive()
                        ):
                            _attempt_cleanup(
                                lambda: self._refresh_thread.join(
                                    timeout=5
                                ),
                                cleanup_errors,
                            )
                        for cleanup in (
                            self.http_server.stop,
                            self.mcp_server.stop,
                            self.assembly.supervisor.stop_all,
                        ):
                            _attempt_cleanup(cleanup, cleanup_errors)
            except BaseException as exc:
                if primary_error is None:
                    primary_error = exc
                else:
                    cleanup_errors.append(exc)
        except BaseException as exc:
            primary_error = exc
        finally:
            cleanup_errors.extend(self._close_owned_resources())

        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__)
        if cleanup_errors:
            first_error = cleanup_errors[0]
            raise first_error.with_traceback(first_error.__traceback__)

    def _close_owned_resources(self) -> tuple[BaseException, ...]:
        with self._resource_close_lock:
            if self._resources_closed:
                return ()
            self._resources_closed = True
        errors = list(_close_resources(self.assembly.resource_closers))
        try:
            self.assembly.release_lifecycle_locks()
        except BaseException as exc:
            errors.append(exc)
        return tuple(errors)

    @contextmanager
    def _termination_guard(self) -> Iterator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        previous = signal.getsignal(signal.SIGTERM)

        def request_shutdown(signum, frame) -> None:
            del signum, frame
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, request_shutdown)
        try:
            yield
        finally:
            signal.signal(signal.SIGTERM, previous)

    def _start_refresh_loop(self) -> None:
        if self.refresh_interval_seconds <= 0:
            return

        def refresh() -> None:
            while not self._refresh_stop.wait(
                self.refresh_interval_seconds
            ):
                self.assembly.supervisor.refresh()
                if self.assembly.event_dispatcher is not None:
                    self.assembly.event_dispatcher.dispatch()

        self._refresh_thread = threading.Thread(
            target=refresh,
            name="clink-module-health",
            daemon=True,
        )
        self._refresh_thread.start()

    @contextmanager
    def _pid_guard(self) -> Iterator[None]:
        path = self.settings.paths.runtime / "node.pid"
        if path.exists():
            try:
                existing = int(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                existing = None
            if existing is not None and _process_running(existing):
                raise RuntimeError(
                    f"another Clink Node is running (pid={existing})"
                )
            path.unlink(missing_ok=True)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _repository(
    settings: NodeSettings,
    store: SecretStore,
) -> NodeRepository:
    if settings.storage.backend is StorageBackend.SQLITE:
        if settings.storage.sqlite_path is None:
            raise RuntimeError("SQLite path is not configured")
        return SQLiteNodeRepository(
            settings.storage.sqlite_path,
            cipher=EnvelopeCipher(store),
        )
    if not settings.storage.postgres_url:
        raise RuntimeError("Postgres URL is not configured")
    return PostgresNodeRepository(
        settings.storage.postgres_url,
        cipher=EnvelopeCipher(store),
    )


def _secret_store(settings: NodeSettings) -> SecretStore:
    if settings.secrets.backend is SecretBackend.KEYCHAIN:
        return KeyringSecretStore(settings.secrets.service_name)
    if settings.secrets.backend is SecretBackend.FILE:
        if settings.profile is Profile.SERVER:
            raise RuntimeError("Server Profile cannot use file secrets")
        return RestrictedFileSecretStore(
            settings.paths.secrets / "node-secrets.json"
        )
    if (
        not settings.secrets.vault_address
        or not settings.secrets.vault_token
    ):
        raise RuntimeError("Vault secret backend is not configured")
    return VaultSecretStore(
        settings.secrets.vault_address,
        token=settings.secrets.vault_token,
        mount=settings.secrets.vault_mount,
        path_prefix=settings.secrets.vault_path_prefix,
    )


def _event_sink(settings: NodeSettings):
    if settings.events.backend is EventBackend.MEMORY:
        return MemoryEventSink()
    if not settings.events.redis_url:
        raise RuntimeError("Redis event backend is not configured")
    return RedisEventSink(settings.events.redis_url)


def _close_resources(
    resource_closers: tuple[Callable[[], None], ...],
) -> tuple[BaseException, ...]:
    errors: list[BaseException] = []
    for closer in reversed(resource_closers):
        _attempt_cleanup(closer, errors)
    return tuple(errors)


def _attempt_cleanup(
    cleanup: Callable[[], None],
    errors: list[BaseException],
) -> None:
    try:
        cleanup()
    except BaseException as exc:
        errors.append(exc)


def _assemble_miniapp(
    settings: NodeSettings,
    *,
    store: SecretStore,
    repository: NodeRepository,
    account_link_factory: Callable[[str], dict],
    polymarket_link_factory: Callable[[str], str],
    polymarket_live_operations: PredictionMarketsHttpAdapter | None,
) -> tuple[MiniAppChatService | None, tuple[Callable[[], None], ...]]:
    miniapp = settings.miniapp
    if not miniapp.enabled:
        return None, ()
    if miniapp.max_active_runs_per_subject != 1:
        raise RuntimeError(
            "Mini App max active runs per subject must equal 1"
        )
    if miniapp.max_sse_per_subject != 1:
        raise RuntimeError("Mini App max SSE per subject must equal 1")
    try:
        secret_values = {
            name: store.get(name)
            for name in MINIAPP_SECRET_NAMES
        }
    except Exception:
        raise RuntimeError("Mini App secret store unavailable") from None
    missing = [
        name for name, value in secret_values.items() if value is None
    ]
    if missing:
        raise RuntimeError(
            "Mini App required secrets are not configured: "
            + ", ".join(missing)
        )
    try:
        secret_values = validate_miniapp_secret_values(secret_values)
    except ValueError:
        raise RuntimeError(
            "Mini App secret configuration is invalid"
        ) from None

    policy = MiniAppTrafficPolicy(
        ip_general_limit=miniapp.ip_general_limit,
        session_exchange_limit=miniapp.session_exchange_limit,
        subject_general_limit=miniapp.subject_general_limit,
        message_submit_limit=miniapp.message_submit_limit,
        operation_link_limit=miniapp.operation_link_limit,
        stop_limit=miniapp.stop_limit,
        window_seconds=miniapp.traffic_window_seconds,
        sse_lease_ttl_seconds=miniapp.sse_lease_ttl_seconds,
    )
    closers: list[Callable[[], None]] = []
    try:
        if settings.profile is Profile.SERVER:
            if (
                settings.events.backend is not EventBackend.REDIS
                or not settings.events.redis_url
            ):
                raise RuntimeError(
                    "Server Mini App requires shared Redis"
                )
            redis_client = redis.Redis.from_url(
                settings.events.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            closers.append(redis_client.close)
            traffic_guard = RedisMiniAppTrafficGuard(
                client=redis_client,
                policy=policy,
            )
        else:
            traffic_guard = MemoryMiniAppTrafficGuard(policy=policy)

        hermes_client = HermesClient(
            base_url=miniapp.hermes_base_url,
            api_key=secret_values["hermes-api-server-key"],
            connect_timeout_seconds=miniapp.connect_timeout_seconds,
            read_timeout_seconds=miniapp.read_timeout_seconds,
            max_stream_seconds=miniapp.max_stream_seconds,
        )
        closers.append(hermes_client.close)
        service = MiniAppChatService(
            repository=repository,
            hermes_client=hermes_client,
            account_link_factory=account_link_factory,
            polymarket_link_factory=polymarket_link_factory,
            polymarket_live_operations=polymarket_live_operations,
            telegram_bot_token=secret_values[
                "telegram-miniapp-bot-token"
            ],
            cookie_secret=secret_values["miniapp-cookie-key"],
            hermes_session_secret=secret_values["hermes-session-key"],
            allowed_origin=_interaction_base_url(settings),
            auth_max_age_seconds=miniapp.auth_max_age_seconds,
            session_ttl_seconds=miniapp.session_ttl_seconds,
            traffic_guard=traffic_guard,
        )
    except BaseException:
        _close_resources(tuple(closers))
        raise
    return service, tuple(closers)


def _miniapp_polymarket_link_factory(
    core: CoreHttpAdapter,
    prediction: PredictionMarketsHttpAdapter,
) -> Callable[[str], str]:
    def create_binding_link(user_id: str) -> str:
        readiness = core.account_readiness(user_id)
        wallet_address = _trusted_core_wallet(
            readiness,
            expected_user=user_id,
        )
        return prediction.create_binding_session(
            user_id,
            wallet_address=wallet_address,
        )

    return create_binding_link


def _trusted_core_wallet(
    readiness: object,
    *,
    expected_user: str,
) -> str:
    if (
        not isinstance(readiness, dict)
        or readiness.get("user_id") != expected_user
        or readiness.get("wallet_bound") is not True
    ):
        raise DownstreamError(
            "core",
            404,
            "Core account readiness is unavailable",
        )
    wallet_address = readiness.get("wallet_address")
    match = (
        _EVM_ADDRESS.fullmatch(wallet_address)
        if isinstance(wallet_address, str)
        else None
    )
    if match is None:
        raise DownstreamError(
            "core",
            404,
            "Core account readiness is unavailable",
        )
    normalized_wallet = "0x" + match.group(1).lower()
    if normalized_wallet == "0x" + "0" * 40:
        raise DownstreamError(
            "core",
            404,
            "Core account readiness is unavailable",
        )
    return normalized_wallet


def _interaction_base_url(settings: NodeSettings) -> str:
    mode = settings.interaction.mode
    if mode is InteractionMode.LOCAL:
        return f"http://{settings.host}:{settings.port}"
    if mode is InteractionMode.SELF_HOSTED:
        if settings.interaction.public_base_url is None:
            raise RuntimeError("public interaction URL is not configured")
        return settings.interaction.public_base_url
    if settings.interaction.relay_url is None:
        raise RuntimeError("Link Relay URL is not configured")
    return settings.interaction.relay_url


def _persistent_text_secret(store: SecretStore, name: str) -> str:
    value = store.get(name)
    if value is None:
        import secrets

        value = secrets.token_urlsafe(32).encode("ascii")
        store.set(name, value)
    return value.decode("ascii")


def _process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    import subprocess

    try:
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if state.returncode != 0:
        return False
    if state.stdout.strip().upper().startswith("Z"):
        return False
    return True
