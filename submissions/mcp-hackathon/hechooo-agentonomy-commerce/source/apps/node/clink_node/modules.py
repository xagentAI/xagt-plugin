from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ModuleMode, NodeSettings


@dataclass(frozen=True)
class ModuleDefinition:
    name: str
    root: Path
    dependencies: tuple[str, ...]
    mode: ModuleMode
    start_command: tuple[str, ...] | None
    stop_command: tuple[str, ...] | None
    health_urls: tuple[str, ...]
    endpoint: str | None
    mcp_url: str | None
    readiness_urls: tuple[str, ...] = ()


def default_module_definitions(
    repository_root: Path,
    settings: NodeSettings,
) -> tuple[ModuleDefinition, ...]:
    core = settings.modules["core"]
    marketplace = settings.modules["marketplace"]
    prediction = settings.modules["prediction-markets"]
    core_services = {
        service: _core_service_url(core, service, default)
        for service, default in {
            "account": "http://127.0.0.1:8019",
            "policy": "http://127.0.0.1:8015",
            "action": "http://127.0.0.1:8016",
            "audit": "http://127.0.0.1:8017",
            "funding": "http://127.0.0.1:8018",
        }.items()
    }
    return (
        ModuleDefinition(
            name="core",
            root=repository_root / "apps/core",
            dependencies=(),
            mode=core.mode,
            start_command=("bash", "run_demo.sh"),
            stop_command=("bash", "run_demo_stop.sh"),
            health_urls=(
                *(f"{url}/healthz" for url in core_services.values()),
            ),
            endpoint=core_services["account"],
            mcp_url=core.mcp_url,
        ),
        ModuleDefinition(
            name="marketplace",
            root=repository_root / "apps/marketplace",
            dependencies=("core",),
            mode=marketplace.mode,
            start_command=("bash", "run_demo.sh"),
            stop_command=("bash", "run_demo_stop.sh"),
            health_urls=(
                _health_url(
                    marketplace.endpoint,
                    "http://127.0.0.1:8050",
                    path="livez",
                ),
            ),
            endpoint=marketplace.endpoint or "http://127.0.0.1:8050",
            mcp_url=(
                marketplace.mcp_url or "http://127.0.0.1:9050/mcp"
            ),
            readiness_urls=(
                _health_url(
                    marketplace.endpoint,
                    "http://127.0.0.1:8050",
                ),
            ) if marketplace.mode is ModuleMode.MANAGED else (),
        ),
        ModuleDefinition(
            name="prediction-markets",
            root=repository_root / "apps/prediction-markets",
            dependencies=("core",),
            mode=prediction.mode,
            start_command=("bash", "run_demo.sh"),
            stop_command=("bash", "run_demo_stop.sh"),
            health_urls=(
                _health_url(
                    prediction.endpoint,
                    "http://127.0.0.1:8040",
                ),
            ),
            endpoint=prediction.endpoint or "http://127.0.0.1:8040",
            mcp_url=(
                prediction.mcp_url or "http://127.0.0.1:9040/mcp"
            ),
            readiness_urls=(
                _prediction_health_urls(prediction)
                if prediction.mode is ModuleMode.MANAGED
                else ()
            ),
        ),
    )


def dependency_order(
    modules: tuple[ModuleDefinition, ...],
) -> tuple[ModuleDefinition, ...]:
    by_name = {module.name: module for module in modules}
    if len(by_name) != len(modules):
        raise ValueError("duplicate Clink module name")
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[ModuleDefinition] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"module dependency cycle contains {name}")
        module = by_name.get(name)
        if module is None:
            raise ValueError(f"unknown module dependency: {name}")
        visiting.add(name)
        for dependency in module.dependencies:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(module)

    for module in modules:
        visit(module.name)
    return tuple(ordered)


def _health_url(
    endpoint: str | None,
    default_endpoint: str,
    *,
    path: str = "healthz",
) -> str:
    return f"{(endpoint or default_endpoint).rstrip('/')}/{path}"


def _core_service_url(
    module,
    service: str,
    default: str,
) -> str:
    configured = module.service_urls.get(service)
    if configured:
        return configured.rstrip("/")
    if module.mode is ModuleMode.EXTERNAL and module.endpoint:
        return module.endpoint.rstrip("/")
    return default


def _prediction_health_urls(module) -> tuple[str, ...]:
    urls = (
        module.endpoint or "http://127.0.0.1:8040",
        module.service_urls.get("preview") or "http://127.0.0.1:8041",
        module.service_urls.get("execution") or "http://127.0.0.1:8042",
        "http://127.0.0.1:8043",
        "http://127.0.0.1:8044",
        "http://127.0.0.1:8045",
        module.service_urls.get("funding") or "http://127.0.0.1:8046",
        module.service_urls.get("account_binding") or "http://127.0.0.1:8047",
        module.service_urls.get("deposit_wallet") or "http://127.0.0.1:8048",
    )
    return tuple(f"{url.rstrip('/')}/healthz" for url in urls)
