from __future__ import annotations

import os
import signal
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from apps.node.clink_node.application import (
    ClinkNodeRuntime,
    NodeAssembly,
    assemble_node,
)
from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.adapters.core import CoreHttpAdapter
from apps.node.clink_node.adapters.prediction_markets import (
    PredictionMarketsHttpAdapter,
)
from apps.node.clink_node.config import (
    EventBackend,
    EventSettings,
    InteractionMode,
    InteractionSettings,
    MiniAppSettings,
    ModuleMode,
    ModuleSettings,
    NodeSettings,
    Profile,
    SecretBackend,
    SecretSettings,
    StorageBackend,
    StorageSettings,
)
from apps.node.clink_node.hermes.client import HermesClient
from apps.node.clink_node.events import RedisEventSink
from apps.node.clink_node.miniapp.traffic import (
    MemoryMiniAppTrafficGuard,
    RedisMiniAppTrafficGuard,
)
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.secrets import MemorySecretStore
from apps.node.clink_node.storage import PostgresNodeRepository


class FakeSupervisor:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.refreshed = 0

    def start_all(self) -> None:
        self.started += 1

    def stop_all(self) -> None:
        self.stopped += 1

    def refresh(self) -> list:
        self.refreshed += 1
        return []


class InterruptedSupervisor(FakeSupervisor):
    def start_all(self) -> None:
        super().start_all()
        raise SystemExit(0)


class FakeDispatcher:
    def __init__(self) -> None:
        self.dispatched = 0

    def dispatch(self) -> object:
        self.dispatched += 1
        return object()


class FakeServer:
    def __init__(self) -> None:
        self.started = 0
        self.ran = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def run(self) -> None:
        self.ran += 1

    def stop(self) -> None:
        self.stopped += 1


class RaisingServer(FakeServer):
    def run(self) -> None:
        super().run()
        raise RuntimeError("primary-exit")


class TrackingSecretStore(MemorySecretStore):
    def __init__(self, values: dict[str, bytes]) -> None:
        super().__init__(values)
        self.read_names: list[str] = []

    def get(self, name: str) -> bytes | None:
        self.read_names.append(name)
        return super().get(name)


class RecordingCloser:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def __call__(self) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("close-failed")


class FakeRedisClient:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FakeHermesClient:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class ApplicationTests(unittest.TestCase):
    MINIAPP_SECRETS = {
        "telegram-miniapp-bot-token": b"bot-token-value",
        "hermes-api-server-key": b"hermes-api-value",
        "miniapp-cookie-key": b"c" * 32,
        "hermes-session-key": b"s" * 32,
    }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = NodePaths.from_home(
            Path(self.temporary.name) / ".clink"
        )
        self.settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=self.paths,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_assembly_uses_one_repository_and_two_downstreams(self) -> None:
        assembly = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )

        self.assertEqual(
            assembly.repository.path,
            self.paths.data / "clink.db",
        )
        self.assertEqual(
            set(assembly.mcp_proxy.downstreams),
            {"marketplace", "prediction-markets"},
        )
        self.assertEqual(
            assembly.context.repository,
            assembly.repository,
        )
        self.assertIsNone(assembly.context.miniapp_service)

    def test_disabled_miniapp_reads_no_miniapp_secrets_or_clients(
        self,
    ) -> None:
        store = TrackingSecretStore(dict(self.MINIAPP_SECRETS))

        assembly = assemble_node(self.settings, secret_store=store)

        self.assertIsNone(assembly.context.miniapp_service)
        self.assertEqual(
            set(store.read_names).intersection(self.MINIAPP_SECRETS),
            set(),
        )
        self.assertEqual(assembly.resource_closers, ())

    def test_personal_miniapp_assembles_from_four_secret_store_values(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        store = TrackingSecretStore(dict(self.MINIAPP_SECRETS))

        assembly = assemble_node(settings, secret_store=store)

        service = assembly.context.miniapp_service
        self.assertIsNotNone(service)
        assert service is not None
        self.assertIsInstance(service.hermes_client, HermesClient)
        self.assertIsInstance(
            service.traffic_guard,
            MemoryMiniAppTrafficGuard,
        )
        self.assertEqual(
            set(store.read_names).intersection(self.MINIAPP_SECRETS),
            set(self.MINIAPP_SECRETS),
        )
        self.assertIs(
            getattr(service._account_link_factory, "__self__", None),
            assembly.context.core,
        )
        self.assertIsNone(
            getattr(service._polymarket_link_factory, "__self__", None)
        )
        self.assertEqual(
            assembly.context.prediction_markets.public_base_url,
            "http://127.0.0.1:8170",
        )
        self.assertEqual(
            assembly.context.prediction_markets.deposit_wallet_url,
            "http://127.0.0.1:8048",
        )
        self.assertEqual(len(assembly.resource_closers), 1)
        managed_environment = assembly.supervisor.environment
        serialized_environment = repr(managed_environment)
        for name, value in self.MINIAPP_SECRETS.items():
            self.assertNotIn(name, managed_environment)
            self.assertNotIn(value.decode("ascii"), serialized_environment)

    def test_personal_miniapp_live_operations_are_gated_by_live_mode(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        with patch.dict(
            os.environ,
            {"PREDICTION_MARKETS_LIVE_MODE": "false"},
        ):
            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore(dict(self.MINIAPP_SECRETS)),
            )
        try:
            service = assembly.context.miniapp_service
            self.assertIsNotNone(service)
            assert service is not None
            self.assertFalse(service.polymarket_live_operations_enabled)
        finally:
            for closer in reversed(assembly.resource_closers):
                closer()

    def test_miniapp_polymarket_link_uses_subject_core_wallet(self) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        subject = "telegram:101"
        core_wallet = "0x" + "A" * 40
        signing_url = (
            "https://www.agentonomy.xyz/polymarket/binding-console/"
            "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
        )

        with (
            patch.object(
                CoreHttpAdapter,
                "account_readiness",
                return_value={
                    "user_id": subject,
                    "wallet_bound": True,
                    "wallet_address": core_wallet,
                },
            ) as account_readiness,
            patch.object(
                PredictionMarketsHttpAdapter,
                "create_binding_session",
                return_value=signing_url,
            ) as create_binding_session,
        ):
            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore(dict(self.MINIAPP_SECRETS)),
            )
            try:
                service = assembly.context.miniapp_service
                self.assertIsNotNone(service)
                assert service is not None

                result = service._polymarket_link_factory(subject)
            finally:
                for closer in reversed(assembly.resource_closers):
                    closer()

        self.assertEqual(result, signing_url)
        account_readiness.assert_called_once_with(subject)
        create_binding_session.assert_called_once_with(
            subject,
            wallet_address=core_wallet.lower(),
        )

    def test_miniapp_polymarket_link_rejects_untrusted_core_wallet(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        subject = "telegram:101"
        wallet = "0x" + "a" * 40
        cases = (
            None,
            {
                "user_id": "telegram:202",
                "wallet_bound": True,
                "wallet_address": wallet,
            },
            {
                "user_id": subject,
                "wallet_bound": False,
                "wallet_address": wallet,
            },
            {
                "user_id": subject,
                "wallet_bound": True,
                "wallet_address": None,
            },
            {
                "user_id": subject,
                "wallet_bound": True,
                "wallet_address": "not-an-address",
            },
            {
                "user_id": subject,
                "wallet_bound": True,
                "wallet_address": "0x" + "0" * 40,
            },
        )

        with (
            patch.object(
                CoreHttpAdapter,
                "account_readiness",
            ) as account_readiness,
            patch.object(
                PredictionMarketsHttpAdapter,
                "create_binding_session",
                return_value="https://www.agentonomy.xyz/polymarket/link",
            ) as create_binding_session,
        ):
            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore(dict(self.MINIAPP_SECRETS)),
            )
            try:
                service = assembly.context.miniapp_service
                self.assertIsNotNone(service)
                assert service is not None

                for readiness in cases:
                    with self.subTest(readiness=readiness):
                        account_readiness.return_value = readiness
                        create_binding_session.reset_mock()
                        try:
                            service._polymarket_link_factory(subject)
                        except DownstreamError:
                            pass
                        except Exception as exc:
                            self.fail(
                                "Core readiness validation leaked "
                                f"{type(exc).__name__}"
                            )
                        else:
                            self.fail("untrusted Core readiness was accepted")
                        create_binding_session.assert_not_called()
            finally:
                for closer in reversed(assembly.resource_closers):
                    closer()

    def test_enabled_miniapp_fails_closed_with_all_missing_names(self) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        store = TrackingSecretStore({})

        with self.assertRaises(RuntimeError) as caught:
            assemble_node(settings, secret_store=store)

        message = str(caught.exception)
        for name in self.MINIAPP_SECRETS:
            self.assertIn(name, message)
        self.assertEqual(
            set(store.read_names).intersection(self.MINIAPP_SECRETS),
            set(self.MINIAPP_SECRETS),
        )

    def test_enabled_miniapp_rejects_malformed_secret_store_values(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        cases = (
            ("telegram-miniapp-bot-token", "not-bytes"),
            ("miniapp-cookie-key", b"short"),
            ("hermes-api-server-key", b"line\nbreak"),
            ("hermes-api-server-key", b"non-ascii-\xff"),
            ("hermes-session-key", b"x" * 4_097),
        )

        for name, malformed in cases:
            with self.subTest(name=name, value_type=type(malformed)):
                values = dict(self.MINIAPP_SECRETS)
                values[name] = malformed
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^Mini App secret configuration is invalid$",
                ) as caught:
                    assemble_node(
                        settings,
                        secret_store=TrackingSecretStore(values),
                    )

                self.assertIsNone(caught.exception.__cause__)

    def test_assembly_failure_closes_constructed_miniapp_resources(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        hermes_client = FakeHermesClient()

        with patch(
            "apps.node.clink_node.application.HermesClient",
            return_value=hermes_client,
        ):
            with patch(
                "apps.node.clink_node.application._persistent_text_secret",
                side_effect=RuntimeError("node-session-secret-failed"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "node-session-secret-failed",
                ):
                    assemble_node(
                        settings,
                        secret_store=TrackingSecretStore(
                            dict(self.MINIAPP_SECRETS)
                        ),
                    )

        self.assertEqual(hermes_client.closed, 1)

    def test_miniapp_assembly_cleanup_preserves_base_exception(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            miniapp=replace(self.settings.miniapp, enabled=True),
        )

        class CloseFailingHermesClient(FakeHermesClient):
            def close(self) -> None:
                super().close()
                raise RuntimeError("close-failed")

        hermes_client = CloseFailingHermesClient()
        with patch(
            "apps.node.clink_node.application.HermesClient",
            return_value=hermes_client,
        ):
            with patch(
                "apps.node.clink_node.application.MiniAppChatService",
                side_effect=SystemExit("assembly-primary"),
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "^assembly-primary$",
                ):
                    assemble_node(
                        settings,
                        secret_store=TrackingSecretStore(
                            dict(self.MINIAPP_SECRETS)
                        ),
                    )

        self.assertEqual(hermes_client.closed, 1)

    def test_server_miniapp_uses_redis_guard_without_memory_fallback(
        self,
    ) -> None:
        from sqlalchemy import create_engine

        settings = replace(
            self.settings,
            profile=Profile.SERVER,
            multi_tenant=True,
            storage=StorageSettings(
                backend=StorageBackend.POSTGRES,
                postgres_url="postgresql+psycopg://clink@db/clink",
            ),
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="redis://redis:6379/0",
            ),
            secrets=SecretSettings(
                backend=SecretBackend.VAULT,
                vault_address="https://vault.example",
                vault_token="vault-token",
            ),
            interaction=InteractionSettings(
                mode=InteractionMode.SELF_HOSTED,
                public_base_url="https://node.example",
            ),
            miniapp=replace(self.settings.miniapp, enabled=True),
        )
        repository = PostgresNodeRepository(
            settings.storage.postgres_url,
            engine=create_engine("sqlite+pysqlite:///:memory:"),
        )
        traffic_redis_client = FakeRedisClient()
        event_redis_client = FakeRedisClient()
        hermes_client = FakeHermesClient()

        try:
            with patch(
                "apps.node.clink_node.application.HermesClient",
                return_value=hermes_client,
            ):
                with patch(
                    "apps.node.clink_node.application.redis.Redis.from_url",
                    side_effect=(
                        traffic_redis_client,
                        event_redis_client,
                    ),
                ) as redis_from_url:
                    assembly = assemble_node(
                        settings,
                        secret_store=TrackingSecretStore(
                            dict(self.MINIAPP_SECRETS)
                        ),
                        repository=repository,
                    )
        finally:
            repository.engine.dispose()

        service = assembly.context.miniapp_service
        self.assertIsNotNone(service)
        assert service is not None
        self.assertIsInstance(
            service.traffic_guard,
            RedisMiniAppTrafficGuard,
        )
        self.assertEqual(redis_from_url.call_count, 2)
        redis_from_url.assert_any_call(
            "redis://redis:6379/0",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self.assertEqual(len(assembly.resource_closers), 3)
        for closer in reversed(assembly.resource_closers):
            closer()
        self.assertEqual(traffic_redis_client.closed, 1)
        self.assertEqual(event_redis_client.closed, 1)
        self.assertEqual(hermes_client.closed, 1)

    def test_server_miniapp_without_redis_fails_closed(self) -> None:
        from sqlalchemy import create_engine

        settings = replace(
            self.settings,
            profile=Profile.SERVER,
            storage=StorageSettings(
                backend=StorageBackend.POSTGRES,
                postgres_url="postgresql+psycopg://clink@db/clink",
            ),
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url=None,
            ),
            interaction=InteractionSettings(
                mode=InteractionMode.SELF_HOSTED,
                public_base_url="https://node.example",
            ),
            miniapp=MiniAppSettings(enabled=True),
        )
        repository = PostgresNodeRepository(
            settings.storage.postgres_url,
            engine=create_engine("sqlite+pysqlite:///:memory:"),
        )

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "Server Mini App requires shared Redis",
            ):
                assemble_node(
                    settings,
                    secret_store=TrackingSecretStore(
                        dict(self.MINIAPP_SECRETS)
                    ),
                    repository=repository,
                )
        finally:
            repository.engine.dispose()

    def test_runtime_owns_pid_servers_and_module_lifecycle(self) -> None:
        self.paths.ensure()
        supervisor = FakeSupervisor()
        http = FakeServer()
        mcp = FakeServer()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = NodeAssembly(
            repository=real.repository,
            supervisor=supervisor,
            context=real.context,
            mcp_proxy=real.mcp_proxy,
            api_application=real.api_application,
            mcp_application=real.mcp_application,
            event_dispatcher=FakeDispatcher(),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=http,
            mcp_server=mcp,
            refresh_interval_seconds=0,
        )

        runtime.run()

        self.assertEqual(supervisor.started, 1)
        self.assertEqual(supervisor.stopped, 1)
        self.assertEqual(assembly.event_dispatcher.dispatched, 1)
        self.assertEqual(mcp.started, 1)
        self.assertEqual(mcp.stopped, 1)
        self.assertEqual(http.ran, 1)
        self.assertEqual(http.stopped, 1)
        self.assertFalse((self.paths.runtime / "node.pid").exists())

    def test_runtime_closes_owned_resources_once(self) -> None:
        self.paths.ensure()
        closer = RecordingCloser()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=FakeSupervisor(),
            resource_closers=(closer,),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=FakeServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        runtime.run()
        runtime._close_owned_resources()

        self.assertEqual(closer.calls, 1)

    def test_resource_close_failure_does_not_mask_primary_exit(self) -> None:
        self.paths.ensure()
        closer = RecordingCloser(fail=True)
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=FakeSupervisor(),
            resource_closers=(closer,),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=RaisingServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "primary-exit"):
            runtime.run()

        self.assertEqual(closer.calls, 1)

    def test_runtime_preserves_primary_error_and_attempts_all_cleanup(
        self,
    ) -> None:
        self.paths.ensure()

        class StopFailingServer(RaisingServer):
            def __init__(self, message: str) -> None:
                super().__init__()
                self.message = message

            def stop(self) -> None:
                super().stop()
                raise RuntimeError(self.message)

        class StopFailingMcpServer(FakeServer):
            def stop(self) -> None:
                super().stop()
                raise RuntimeError("mcp-stop")

        class StopFailingSupervisor(FakeSupervisor):
            def stop_all(self) -> None:
                super().stop_all()
                raise RuntimeError("supervisor-stop")

        http = StopFailingServer("http-stop")
        mcp = StopFailingMcpServer()
        supervisor = StopFailingSupervisor()
        failing_closer = RecordingCloser(fail=True)
        successful_closer = RecordingCloser()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=supervisor,
            resource_closers=(successful_closer, failing_closer),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=http,
            mcp_server=mcp,
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "^primary-exit$"):
            runtime.run()

        self.assertEqual(http.stopped, 1)
        self.assertEqual(mcp.stopped, 1)
        self.assertEqual(supervisor.stopped, 1)
        self.assertEqual(failing_closer.calls, 1)
        self.assertEqual(successful_closer.calls, 1)

    def test_runtime_raises_first_cleanup_error_after_all_attempts(
        self,
    ) -> None:
        self.paths.ensure()

        class StopFailingServer(FakeServer):
            def __init__(self, message: str) -> None:
                super().__init__()
                self.message = message

            def stop(self) -> None:
                super().stop()
                raise RuntimeError(self.message)

        class StopFailingSupervisor(FakeSupervisor):
            def stop_all(self) -> None:
                super().stop_all()
                raise RuntimeError("supervisor-stop")

        http = StopFailingServer("http-stop")
        mcp = StopFailingServer("mcp-stop")
        supervisor = StopFailingSupervisor()
        failing_closer = RecordingCloser(fail=True)
        successful_closer = RecordingCloser()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=supervisor,
            resource_closers=(successful_closer, failing_closer),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=http,
            mcp_server=mcp,
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "^http-stop$"):
            runtime.run()

        self.assertEqual(http.stopped, 1)
        self.assertEqual(mcp.stopped, 1)
        self.assertEqual(supervisor.stopped, 1)
        self.assertEqual(failing_closer.calls, 1)
        self.assertEqual(successful_closer.calls, 1)

    def test_runtime_raises_owned_resource_cleanup_error_without_primary(
        self,
    ) -> None:
        self.paths.ensure()
        failing_closer = RecordingCloser(fail=True)
        successful_closer = RecordingCloser()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=FakeSupervisor(),
            resource_closers=(successful_closer, failing_closer),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=FakeServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "^close-failed$"):
            runtime.run()

        self.assertEqual(failing_closer.calls, 1)
        self.assertEqual(successful_closer.calls, 1)

    def test_runtime_constructor_closes_owned_assembly_on_server_error(
        self,
    ) -> None:
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        scenarios = (
            [RuntimeError("http-construction")],
            [FakeServer(), RuntimeError("mcp-construction")],
        )

        for side_effect in scenarios:
            with self.subTest(error=str(side_effect[-1])):
                closer = RecordingCloser()
                assembly = replace(real, resource_closers=(closer,))
                with patch(
                    "apps.node.clink_node.application.assemble_node",
                    return_value=assembly,
                ):
                    with patch(
                        "apps.node.clink_node.application.UvicornServer",
                        side_effect=side_effect,
                    ):
                        with self.assertRaises(RuntimeError):
                            ClinkNodeRuntime(self.settings)

                self.assertEqual(closer.calls, 1)

    def test_runtime_closes_resources_when_pid_guard_rejects_startup(
        self,
    ) -> None:
        self.paths.ensure()
        (self.paths.runtime / "node.pid").write_text(
            str(os.getpid()),
            encoding="ascii",
        )
        closer = RecordingCloser()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(
            real,
            supervisor=FakeSupervisor(),
            resource_closers=(closer,),
        )
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=FakeServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "is running"):
            runtime.run()

        self.assertEqual(closer.calls, 1)

    def test_startup_interruption_still_stops_managed_modules(self) -> None:
        self.paths.ensure()
        supervisor = InterruptedSupervisor()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(real, supervisor=supervisor)
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=FakeServer(),
            mcp_server=FakeServer(),
        )

        with self.assertRaises(SystemExit):
            runtime.run()

        self.assertEqual(supervisor.started, 1)
        self.assertEqual(supervisor.stopped, 1)
        self.assertFalse((self.paths.runtime / "node.pid").exists())

    def test_runtime_installs_a_startup_sigterm_guard(self) -> None:
        self.paths.ensure()
        supervisor = FakeSupervisor()
        real = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )
        assembly = replace(real, supervisor=supervisor)
        runtime = ClinkNodeRuntime(
            self.settings,
            assembly=assembly,
            http_server=FakeServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        with patch(
            "apps.node.clink_node.application.signal.signal"
        ) as install_signal:
            runtime.run()

        installed_signals = {
            call.args[0]
            for call in install_signal.call_args_list
            if call.args
        }
        self.assertIn(signal.SIGTERM, installed_signals)

    def test_assembly_configures_event_dispatcher(self) -> None:
        assembly = assemble_node(
            self.settings,
            secret_store=MemorySecretStore({}),
        )

        self.assertIsNotNone(assembly.event_dispatcher)

    def test_runtime_closes_owned_redis_event_sink_on_normal_exit(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="redis://events:6379/0",
            ),
        )
        event_client = FakeRedisClient()
        sink = RedisEventSink(
            "redis://unused",
            client=event_client,
        )
        with patch(
            "apps.node.clink_node.application._event_sink",
            return_value=sink,
        ):
            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore({}),
            )
        runtime = ClinkNodeRuntime(
            settings,
            assembly=replace(assembly, supervisor=FakeSupervisor()),
            http_server=FakeServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        runtime.run()

        self.assertEqual(event_client.closed, 1)

    def test_assembly_failure_closes_owned_redis_event_sink(self) -> None:
        settings = replace(
            self.settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="redis://events:6379/0",
            ),
        )
        event_client = FakeRedisClient()
        sink = RedisEventSink(
            "redis://unused",
            client=event_client,
        )
        with patch(
            "apps.node.clink_node.application._event_sink",
            return_value=sink,
        ):
            with patch(
                "apps.node.clink_node.application.create_app",
                side_effect=RuntimeError("api-construction"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^api-construction$",
                ):
                    assemble_node(
                        settings,
                        secret_store=MemorySecretStore({}),
                    )

        self.assertEqual(event_client.closed, 1)

    def test_redis_event_close_does_not_mask_runtime_primary_error(
        self,
    ) -> None:
        settings = replace(
            self.settings,
            events=EventSettings(
                backend=EventBackend.REDIS,
                redis_url="redis://events:6379/0",
            ),
        )
        event_client = FakeRedisClient()
        sink = RedisEventSink(
            "redis://unused",
            client=event_client,
        )
        with patch(
            "apps.node.clink_node.application._event_sink",
            return_value=sink,
        ):
            assembly = assemble_node(
                settings,
                secret_store=MemorySecretStore({}),
            )
        runtime = ClinkNodeRuntime(
            settings,
            assembly=replace(assembly, supervisor=FakeSupervisor()),
            http_server=RaisingServer(),
            mcp_server=FakeServer(),
            refresh_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "^primary-exit$"):
            runtime.run()

        self.assertEqual(event_client.closed, 1)

    def test_server_assembly_uses_external_module_service_urls(self) -> None:
        from sqlalchemy import create_engine

        server = NodeSettings.defaults(
            Profile.SERVER,
            paths=self.paths,
        )
        server = replace(
            server,
            storage=StorageSettings(
                backend=server.storage.backend,
                postgres_url="postgresql+psycopg://clink@db/clink",
            ),
            events=EventSettings(
                backend=server.events.backend,
                redis_url="redis://redis:6379/0",
            ),
            secrets=SecretSettings(
                backend=server.secrets.backend,
                vault_address="https://vault.example",
                vault_token="token",
            ),
            interaction=InteractionSettings(
                mode=server.interaction.mode,
                public_base_url="https://node.example",
            ),
            modules={
                "core": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="http://core-account:8019",
                    service_urls={
                        "account": "http://core-account:8019",
                        "action": "http://core-action:8016",
                        "policy": "http://core-policy:8015",
                        "audit": "http://core-audit:8017",
                        "funding": "http://core-funding:8018",
                    },
                ),
                "marketplace": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="http://marketplace:8050",
                    mcp_url="http://marketplace:9050/mcp",
                ),
                "prediction-markets": ModuleSettings(
                    mode=ModuleMode.EXTERNAL,
                    endpoint="http://prediction:8040",
                    mcp_url="http://prediction:9040/mcp",
                    service_urls={
                        "account_binding": (
                            "http://prediction-binding:8047"
                        ),
                        "deposit_wallet": (
                            "http://prediction-deposit:8048"
                        ),
                    },
                ),
            },
        )
        repository = PostgresNodeRepository(
            server.storage.postgres_url,
            engine=create_engine("sqlite+pysqlite:///:memory:"),
        )

        try:
            assembly = assemble_node(
                server,
                secret_store=MemorySecretStore({}),
                repository=repository,
            )
        finally:
            repository.engine.dispose()

        self.assertEqual(
            assembly.context.core.funding_url,
            "http://core-funding:8018",
        )
        self.assertEqual(
            assembly.context.marketplace.base_url,
            "http://marketplace:8050",
        )
        self.assertEqual(
            assembly.context.prediction_markets.base_url,
            "http://prediction:8040",
        )
        self.assertEqual(
            assembly.context.prediction_markets.account_binding_url,
            "http://prediction-binding:8047",
        )
        self.assertEqual(
            assembly.context.prediction_markets.deposit_wallet_url,
            "http://prediction-deposit:8048",
        )


if __name__ == "__main__":
    unittest.main()
