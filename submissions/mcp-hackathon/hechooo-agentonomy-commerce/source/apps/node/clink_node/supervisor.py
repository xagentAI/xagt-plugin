from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .config import ModuleMode
from .health import HealthResult, HttpHealthProbe
from .modules import ModuleDefinition, dependency_order
from .storage.base import ModuleRecord, NodeRepository


_CORE_ONLY_ENVIRONMENT_VARIABLES = frozenset(
    {
        "CLINK_REDIS_URL",
        "MISTTRACK_API_KEY",
        "CLINK_FACILITATOR_MODE",
        "CLINK_LIVE_FUNDING",
        "CLINK_NATIVE_FACILITATOR_ENABLED",
        "CLINK_NATIVE_FACILITATOR_GAS_LIMIT",
        "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY",
    }
)
_CORE_ONLY_ENVIRONMENT_PREFIXES = ("CLINK_HOSTED_FACILITATOR_",)


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class ProcessBackend(Protocol):
    def start(
        self,
        command: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> ProcessHandle: ...

    def run_stop(
        self,
        command: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
    ) -> int: ...


class SubprocessBackend:
    def start(
        self,
        command: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = log_path.open("ab", buffering=0)
        try:
            return subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()

    def run_stop(
        self,
        command: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
    ) -> int:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=60,
        ).returncode


@dataclass(frozen=True)
class ModuleRuntime:
    definition: ModuleDefinition
    handle: ProcessHandle | None


class ModuleSupervisor:
    def __init__(
        self,
        modules: tuple[ModuleDefinition, ...],
        repository: NodeRepository,
        *,
        process_backend: ProcessBackend | None = None,
        health_probe: HttpHealthProbe | None = None,
        environment: dict[str, str] | None = None,
        log_directory: Path,
        startup_timeout_seconds: float = 45,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.modules = dependency_order(modules)
        self.repository = repository
        self.process_backend = process_backend or SubprocessBackend()
        self.health_probe = health_probe or HttpHealthProbe()
        self.environment = dict(environment or os.environ)
        self.log_directory = log_directory
        self.startup_timeout_seconds = startup_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._runtime: dict[str, ModuleRuntime] = {}

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ModuleSupervisor serialization is disabled")

    def start_all(self) -> None:
        started: list[str] = []
        try:
            for module in self.modules:
                if module.mode is ModuleMode.DISABLED:
                    self._persist(module, "disabled", None, None)
                    continue
                self._ensure_dependencies_ready(module)
                handle: ProcessHandle | None = None
                if module.mode is ModuleMode.MANAGED:
                    if not module.start_command:
                        raise RuntimeError(
                            f"managed module {module.name} has no command"
                        )
                    self._persist(module, "starting", None, None)
                    handle = self.process_backend.start(
                        module.start_command,
                        module.root,
                        self._environment_for(module),
                        self.log_directory / f"{module.name}.log",
                    )
                    started.append(module.name)
                self._runtime[module.name] = ModuleRuntime(module, handle)
                self._wait_until_ready(module, handle)
                self._persist(
                    module,
                    "ready",
                    handle.pid if handle else None,
                    None,
                )
        except Exception:
            self._rollback(started)
            raise

    def stop_all(self) -> None:
        for module in reversed(self.modules):
            runtime = self._runtime.get(module.name)
            self._stop_one(module, runtime.handle if runtime else None)

    def refresh(self) -> list[ModuleRecord]:
        for module in self.modules:
            if module.mode is ModuleMode.DISABLED:
                continue
            runtime = self._runtime.get(module.name)
            handle = runtime.handle if runtime else None
            health = self._check_module(module)
            if handle is not None and handle.poll() is not None:
                self._persist(
                    module,
                    "failed",
                    handle.pid,
                    "managed module process exited",
                )
            elif health.ok:
                self._persist(
                    module,
                    "ready",
                    handle.pid if handle else None,
                    None,
                )
            else:
                self._persist(
                    module,
                    "degraded",
                    handle.pid if handle else None,
                    health.detail,
                )
        return self.repository.list_modules()

    def _wait_until_ready(
        self,
        module: ModuleDefinition,
        handle: ProcessHandle | None,
    ) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        last_detail = "health probe has not completed"
        while True:
            if handle is not None and handle.poll() is not None:
                raise RuntimeError(
                    f"{module.name} exited during startup"
                )
            result = self._check_urls(module.health_urls)
            if result.ok:
                return
            last_detail = result.detail or "health check failed"
            if time.monotonic() >= deadline:
                break
            time.sleep(self.poll_interval_seconds)
        raise RuntimeError(
            f"{module.name} did not become ready: {last_detail}"
        )

    def _check_module(self, module: ModuleDefinition) -> HealthResult:
        uses_runtime_readiness = (
            module.mode is ModuleMode.MANAGED
            and bool(module.readiness_urls)
        )
        return self._check_urls(
            module.readiness_urls or module.health_urls,
            require_healthy_status=uses_runtime_readiness,
        )

    def _check_urls(
        self,
        urls: tuple[str, ...],
        *,
        require_healthy_status: bool = False,
    ) -> HealthResult:
        bodies: dict[str, object] = {}
        for url in urls:
            result = self.health_probe.check(url)
            if not result.ok:
                return result
            if require_healthy_status:
                status = result.body.get("status") if result.body else None
                if status != "ok":
                    return HealthResult(
                        False,
                        result.status_code,
                        f"health check returned status {status!r}",
                        result.body,
                    )
            bodies[url] = result.body
        return HealthResult(True, 200, None, bodies)

    def _ensure_dependencies_ready(
        self,
        module: ModuleDefinition,
    ) -> None:
        for dependency in module.dependencies:
            record = self.repository.get_module(dependency)
            if record is None or record.status != "ready":
                raise RuntimeError(
                    f"{module.name} dependency {dependency} is not ready"
                )

    def _rollback(self, started: list[str]) -> None:
        for name in reversed(started):
            runtime = self._runtime.get(name)
            module = next(item for item in self.modules if item.name == name)
            self._stop_one(module, runtime.handle if runtime else None)

    def _stop_one(
        self,
        module: ModuleDefinition,
        handle: ProcessHandle | None,
    ) -> None:
        if module.mode is ModuleMode.EXTERNAL:
            self._persist(module, "external", None, None)
            return
        self._persist(
            module,
            "stopping",
            handle.pid if handle else None,
            None,
        )
        if module.stop_command:
            self.process_backend.run_stop(
                module.stop_command,
                module.root,
                self._environment_for(module),
            )
        if handle is not None and handle.poll() is None:
            handle.terminate()
            try:
                handle.wait(timeout=10)
            except subprocess.TimeoutExpired:
                handle.kill()
                handle.wait(timeout=5)
        self._persist(module, "stopped", None, None)

    def _environment_for(self, module: ModuleDefinition) -> dict[str, str]:
        environment = dict(self.environment)
        # Runtime metadata belongs to this Node's private state, never the
        # signed/read-only application tree. Start and stop use the same path.
        runtime_root = environment.get("CLINK_MODULE_RUNTIME_ROOT")
        environment["CLINK_MODULE_RUNTIME_DIR"] = str(
            Path(runtime_root) / module.name
            if runtime_root
            else self.log_directory / module.name / "runtime"
        )
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if module.name != "core":
            for name in tuple(environment):
                if name in _CORE_ONLY_ENVIRONMENT_VARIABLES or any(
                    name.startswith(prefix)
                    for prefix in _CORE_ONLY_ENVIRONMENT_PREFIXES
                ):
                    environment.pop(name, None)
        return environment

    def _persist(
        self,
        module: ModuleDefinition,
        status: str,
        pid: int | None,
        detail: str | None,
    ) -> None:
        self.repository.set_module(
            ModuleRecord(
                name=module.name,
                mode=module.mode.value,
                status=status,
                pid=pid,
                endpoint=module.endpoint,
                mcp_url=module.mcp_url,
                detail=detail,
                updated_at=datetime.now(UTC),
            )
        )
