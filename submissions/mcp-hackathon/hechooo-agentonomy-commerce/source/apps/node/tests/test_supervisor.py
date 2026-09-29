from __future__ import annotations

import pickle
import tempfile
import unittest
from pathlib import Path

from clink_node.config import ModuleMode
from clink_node.health import HealthResult
from clink_node.modules import ModuleDefinition, dependency_order
from clink_node.storage import SQLiteNodeRepository
from clink_node.supervisor import ModuleSupervisor


class FakeHandle:
    def __init__(self, pid: int) -> None:
        self._pid = pid
        self.returncode = None
        self.terminated = False

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.returncode = -9


class FakeProcessBackend:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.handles: dict[str, FakeHandle] = {}
        self.environments: dict[str, dict[str, str]] = {}

    def start(self, command, cwd, env, log_path):
        name = cwd.name
        self.started.append(name)
        self.environments[name] = dict(env)
        handle = FakeHandle(100 + len(self.started))
        self.handles[name] = handle
        return handle

    def run_stop(self, command, cwd, env) -> int:
        self.stopped.append(cwd.name)
        return 0


class FakeHealthProbe:
    def __init__(
        self,
        failing: set[str] | None = None,
        body_status: dict[str, str] | None = None,
    ) -> None:
        self.failing = failing or set()
        self.body_status = body_status or {}
        self.checked: list[str] = []

    def check(self, url: str) -> HealthResult:
        self.checked.append(url)
        if url in self.failing:
            return HealthResult(False, 503, "not ready", None)
        return HealthResult(
            True,
            200,
            None,
            {"status": self.body_status.get(url, "ok")},
        )


def module(
    name: str,
    *,
    dependencies: tuple[str, ...] = (),
    mode: ModuleMode = ModuleMode.MANAGED,
    readiness_urls: tuple[str, ...] = (),
) -> ModuleDefinition:
    return ModuleDefinition(
        name=name,
        root=Path("/tmp") / name,
        dependencies=dependencies,
        mode=mode,
        start_command=("bash", "run_demo.sh"),
        stop_command=("bash", "run_demo_stop.sh"),
        health_urls=(f"http://{name}/healthz",),
        endpoint=f"http://{name}",
        mcp_url=f"http://{name}/mcp",
        readiness_urls=readiness_urls,
    )


class ModuleSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteNodeRepository(
            Path(self.temporary.name) / "clink.db"
        )
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dependency_order_places_core_first(self) -> None:
        ordered = dependency_order(
            (
                module("marketplace", dependencies=("core",)),
                module("core"),
            )
        )

        self.assertEqual([item.name for item in ordered], ["core", "marketplace"])

    def test_dependency_cycle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            dependency_order(
                (
                    module("a", dependencies=("b",)),
                    module("b", dependencies=("a",)),
                )
            )

    def test_start_and_stop_follow_dependency_order(self) -> None:
        backend = FakeProcessBackend()
        supervisor = ModuleSupervisor(
            (
                module("marketplace", dependencies=("core",)),
                module("core"),
            ),
            self.repository,
            process_backend=backend,
            health_probe=FakeHealthProbe(),
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        supervisor.stop_all()

        self.assertEqual(backend.started, ["core", "marketplace"])
        self.assertEqual(backend.stopped, ["marketplace", "core"])
        self.assertEqual(
            [record.status for record in self.repository.list_modules()],
            ["stopped", "stopped"],
        )

    def test_misttrack_key_is_exposed_only_to_managed_core(self) -> None:
        backend = FakeProcessBackend()
        supervisor = ModuleSupervisor(
            (
                module("marketplace", dependencies=("core",)),
                module("prediction-markets", dependencies=("core",)),
                module("core"),
            ),
            self.repository,
            process_backend=backend,
            health_probe=FakeHealthProbe(),
            environment={
                "PATH": "/usr/bin",
                "CLINK_REDIS_URL": "rediss://redis.example:6380/0",
                "MISTTRACK_API_KEY": "core-only-test-key",
                "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN": "hosted-access-token",
                "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY": "hosted-device-key",
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS": "hosted-targets",
            },
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()

        self.assertEqual(
            backend.environments["core"]["MISTTRACK_API_KEY"],
            "core-only-test-key",
        )
        self.assertEqual(
            backend.environments["core"]["CLINK_REDIS_URL"],
            "rediss://redis.example:6380/0",
        )
        self.assertNotIn(
            "MISTTRACK_API_KEY",
            backend.environments["marketplace"],
        )
        self.assertNotIn(
            "CLINK_REDIS_URL",
            backend.environments["marketplace"],
        )
        self.assertNotIn(
            "MISTTRACK_API_KEY",
            backend.environments["prediction-markets"],
        )
        self.assertNotIn(
            "CLINK_REDIS_URL",
            backend.environments["prediction-markets"],
        )
        for module_name in ("marketplace", "prediction-markets"):
            self.assertNotIn(
                "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN",
                backend.environments[module_name],
            )
            self.assertNotIn(
                "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY",
                backend.environments[module_name],
            )
            self.assertNotIn(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS",
                backend.environments[module_name],
            )
        self.assertEqual(
            backend.environments["core"]["CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN"],
            "hosted-access-token",
        )
        serialized_state = repr(supervisor._runtime)
        self.assertNotIn("core-only-test-key", serialized_state)
        self.assertNotIn("api_key=", serialized_state)

    def test_hosted_live_execution_settings_are_exposed_only_to_core(self) -> None:
        backend = FakeProcessBackend()
        supervisor = ModuleSupervisor(
            (
                module("marketplace", dependencies=("core",)),
                module("prediction-markets", dependencies=("core",)),
                module("core"),
            ),
            self.repository,
            process_backend=backend,
            health_probe=FakeHealthProbe(),
            environment={
                "CLINK_FACILITATOR_MODE": "hosted",
                "CLINK_LIVE_FUNDING": "true",
                "CLINK_NATIVE_FACILITATOR_ENABLED": "false",
                "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY": "secret",
                "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN": "token",
            },
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()

        for name in ("marketplace", "prediction-markets"):
            child_environment = backend.environments[name]
            self.assertNotIn("CLINK_FACILITATOR_MODE", child_environment)
            self.assertNotIn("CLINK_LIVE_FUNDING", child_environment)
            self.assertNotIn(
                "CLINK_NATIVE_FACILITATOR_ENABLED",
                child_environment,
            )
            self.assertNotIn(
                "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY",
                child_environment,
            )
        self.assertEqual(
            backend.environments["core"]["CLINK_FACILITATOR_MODE"],
            "hosted",
        )

    def test_supervisor_serialization_is_safely_rejected(self) -> None:
        supervisor = ModuleSupervisor(
            (module("core"),),
            None,  # type: ignore[arg-type]
            process_backend=FakeProcessBackend(),
            health_probe=FakeHealthProbe(),
            environment={
                "MISTTRACK_API_KEY": "pickle-key-must-not-leak",
                "CLINK_CORE_INTERNAL_API_TOKEN": (
                    "pickle-token-must-not-leak"
                ),
            },
            log_directory=Path(self.temporary.name) / "logs",
        )

        with self.assertRaises(TypeError) as captured:
            pickle.dumps(supervisor)

        error = str(captured.exception)
        self.assertEqual(error, "ModuleSupervisor serialization is disabled")
        self.assertNotIn("pickle-key-must-not-leak", error)
        self.assertNotIn("pickle-token-must-not-leak", error)
        self.assertNotIn("api_key=", error)

    def test_failed_child_rolls_back_modules_started_before_it(self) -> None:
        backend = FakeProcessBackend()
        supervisor = ModuleSupervisor(
            (
                module("core"),
                module("marketplace", dependencies=("core",)),
            ),
            self.repository,
            process_backend=backend,
            health_probe=FakeHealthProbe(
                {"http://marketplace/healthz"}
            ),
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0,
            poll_interval_seconds=0,
        )

        with self.assertRaisesRegex(RuntimeError, "marketplace"):
            supervisor.start_all()

        self.assertIn("core", backend.stopped)
        self.assertEqual(
            self.repository.get_module("core").status,
            "stopped",
        )

    def test_external_module_is_probed_but_not_spawned(self) -> None:
        backend = FakeProcessBackend()
        supervisor = ModuleSupervisor(
            (module("core", mode=ModuleMode.EXTERNAL),),
            self.repository,
            process_backend=backend,
            health_probe=FakeHealthProbe(),
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()

        self.assertEqual(backend.started, [])
        self.assertEqual(
            self.repository.get_module("core").status,
            "ready",
        )

    def test_external_module_keeps_http_only_health_contract(self) -> None:
        backend = FakeProcessBackend()
        probe = FakeHealthProbe(
            body_status={"http://prediction-markets/healthz": "degraded"},
        )
        supervisor = ModuleSupervisor(
            (
                module(
                    "prediction-markets",
                    mode=ModuleMode.EXTERNAL,
                ),
            ),
            self.repository,
            process_backend=backend,
            health_probe=probe,
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        supervisor.refresh()

        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "ready",
        )

    def test_startup_uses_health_urls_but_refresh_uses_readiness_urls(self) -> None:
        backend = FakeProcessBackend()
        probe = FakeHealthProbe({"http://prediction/runtime"})
        prediction = module(
            "prediction-markets",
            readiness_urls=("http://prediction/runtime",),
        )
        supervisor = ModuleSupervisor(
            (prediction,),
            self.repository,
            process_backend=backend,
            health_probe=probe,
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "ready",
        )
        self.assertEqual(probe.checked, ["http://prediction-markets/healthz"])

        supervisor.refresh()

        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "degraded",
        )
        self.assertEqual(
            probe.checked,
            [
                "http://prediction-markets/healthz",
                "http://prediction/runtime",
            ],
        )

    def test_refresh_requires_every_runtime_readiness_url(self) -> None:
        backend = FakeProcessBackend()
        readiness_urls = tuple(
            f"http://prediction/{service}"
            for service in ("router", "preview", "execution")
        )
        probe = FakeHealthProbe({"http://prediction/execution"})
        prediction = module(
            "prediction-markets",
            readiness_urls=readiness_urls,
        )
        supervisor = ModuleSupervisor(
            (prediction,),
            self.repository,
            process_backend=backend,
            health_probe=probe,
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        supervisor.refresh()

        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "degraded",
        )
        self.assertEqual(
            probe.checked,
            [
                "http://prediction-markets/healthz",
                "http://prediction/router",
                "http://prediction/preview",
                "http://prediction/execution",
            ],
        )

    def test_refresh_marks_module_ready_when_all_runtime_urls_are_healthy(self) -> None:
        backend = FakeProcessBackend()
        readiness_urls = (
            "http://prediction/router",
            "http://prediction/preview",
        )
        probe = FakeHealthProbe()
        prediction = module(
            "prediction-markets",
            readiness_urls=readiness_urls,
        )
        supervisor = ModuleSupervisor(
            (prediction,),
            self.repository,
            process_backend=backend,
            health_probe=probe,
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        supervisor.refresh()

        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "ready",
        )
        self.assertEqual(
            probe.checked,
            [
                "http://prediction-markets/healthz",
                "http://prediction/router",
                "http://prediction/preview",
            ],
        )

    def test_refresh_rejects_degraded_runtime_body_on_http_success(self) -> None:
        backend = FakeProcessBackend()
        probe = FakeHealthProbe(
            body_status={"http://prediction/funding": "degraded"},
        )
        prediction = module(
            "prediction-markets",
            readiness_urls=("http://prediction/funding",),
        )
        supervisor = ModuleSupervisor(
            (prediction,),
            self.repository,
            process_backend=backend,
            health_probe=probe,
            log_directory=Path(self.temporary.name) / "logs",
            startup_timeout_seconds=0.1,
            poll_interval_seconds=0,
        )

        supervisor.start_all()
        supervisor.refresh()

        self.assertEqual(
            self.repository.get_module("prediction-markets").status,
            "degraded",
        )


if __name__ == "__main__":
    unittest.main()
