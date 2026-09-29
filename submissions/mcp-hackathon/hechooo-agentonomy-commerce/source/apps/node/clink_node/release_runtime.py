from __future__ import annotations

import importlib
import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .paths import NodePaths

if TYPE_CHECKING:
    from .config import NodeSettings


MODULE_NAMES = ("core", "marketplace", "prediction-markets")


class UnsafeReleaseConfiguration(ValueError):
    """Raised when a signed release is asked to use an unsafe topology."""


class ReleaseRuntimePolicy:
    """The fail-closed topology supported by the signed Personal release."""

    @staticmethod
    def validate(
        settings: "NodeSettings",
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if settings.profile.value != "personal":
            _unsafe("server-profile")
        if not _literal_loopback(settings.host):
            _unsafe("public-http-host")
        if not _literal_loopback(settings.mcp_host):
            _unsafe("public-mcp-host")
        if settings.multi_tenant:
            _unsafe("multi-tenant")
        if settings.storage.backend.value != "sqlite":
            _unsafe("postgres-storage")
        if settings.events.backend.value != "memory":
            _unsafe("redis-events")
        if settings.secrets.backend.value not in {"keychain", "file"}:
            _unsafe("unsupported-secret-backend")
        if settings.interaction.mode.value != "local":
            _unsafe("non-local-interaction")

        expected_modules = set(MODULE_NAMES)
        if set(settings.modules) != expected_modules:
            _unsafe(
                "modules must contain exactly core, marketplace, and "
                "prediction-markets"
            )
        for name in MODULE_NAMES:
            module = settings.modules[name]
            if (
                module.mode.value != "managed"
                or module.endpoint is not None
                or module.mcp_url is not None
                or module.service_urls
            ):
                _unsafe(
                    f"external-{name}: release modules must be managed "
                    "and unconfigured"
                )

        execution = settings.execution
        if execution.live_funding:
            _unsafe("live_funding")
        if execution.native_facilitator:
            _unsafe("native_facilitator")
        if execution.prediction_markets_live:
            _unsafe("prediction_markets_live")
        if execution.risk_provider.strip().lower() != "misttrack":
            _unsafe("risk_provider")
        if execution.risk_mode.strip().lower() not in {"shadow", "enforce"}:
            _unsafe("risk_mode")
        if settings.release_mode:
            validate_release_writable_paths(settings, env)


class ReleaseSelfCheckDependencies(Protocol):
    def import_available(self, module_name: str) -> bool: ...

    def path_is_file(self, path: Path) -> bool: ...


class LocalReleaseSelfCheckDependencies:
    def import_available(self, module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
        except Exception:
            return False
        return True

    def path_is_file(self, path: Path) -> bool:
        return path.is_file()


def runtime_root(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    configured = source.get("CLINK_RUNTIME_ROOT")
    if configured is not None:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise ValueError("CLINK_RUNTIME_ROOT must be absolute")
        return candidate.resolve(strict=True)
    return Path(__file__).resolve().parents[3]


def release_state_root(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    version_root = _trusted_release_runtime_root(source)
    launcher_home = source.get("HOME")
    if not launcher_home:
        _unsafe("HOME is required from the trusted release launcher")
    home = Path(launcher_home)
    if not home.is_absolute():
        _unsafe("HOME must be absolute in release mode")
    state_root = Path(os.path.abspath(os.fspath(home / ".clink")))
    if _paths_overlap(state_root, version_root):
        _unsafe("release state root overlaps the read-only version tree")
    return state_root


def release_node_paths(env: Mapping[str, str] | None = None) -> NodePaths:
    source = os.environ if env is None else env
    expected = release_state_root(source)
    configured = source.get("CLINK_HOME")
    if configured is not None:
        candidate = Path(configured)
        if not candidate.is_absolute():
            _unsafe("CLINK_HOME must be absolute in release mode")
        if candidate.resolve(strict=False) != expected.resolve(strict=False):
            _unsafe(
                "CLINK_HOME must resolve to the launcher HOME/.clink "
                "state root"
            )
    return NodePaths.from_home(expected)


def validate_release_writable_paths(
    settings: "NodeSettings",
    env: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if env is None else env
    version_root = _trusted_release_runtime_root(source)
    expected_state_root = release_state_root(source).resolve(strict=False)
    actual_state_root = settings.paths.home.resolve(strict=False)
    if actual_state_root != expected_state_root:
        _unsafe("CLINK_HOME must resolve to the launcher HOME/.clink state root")

    writable_paths = {
        "config": settings.paths.config,
        "data": settings.paths.data,
        "runtime": settings.paths.runtime,
        "logs": settings.paths.logs,
        "secrets": settings.paths.secrets,
    }
    for name, configured_path in writable_paths.items():
        canonical = configured_path.resolve(strict=False)
        if not _strict_descendant(canonical, expected_state_root):
            _unsafe(f"{name} path escapes the release state root")
        if _paths_overlap(canonical, version_root):
            _unsafe(f"{name} path overlaps the read-only version tree")

    for module_name in MODULE_NAMES:
        managed_runtime = (
            settings.paths.runtime / "modules" / module_name
        ).resolve(strict=False)
        if not _strict_descendant(managed_runtime, expected_state_root):
            _unsafe(
                f"{module_name} managed runtime path escapes the release "
                "state root"
            )
        if _paths_overlap(managed_runtime, version_root):
            _unsafe(
                f"{module_name} managed runtime path overlaps the read-only "
                "version tree"
            )

    sqlite_path = settings.storage.sqlite_path
    if settings.storage.backend.value == "sqlite":
        if sqlite_path is None:
            _unsafe("sqlite path is required in release mode")
        canonical_sqlite = sqlite_path.resolve(strict=False)
        if not _strict_descendant(canonical_sqlite, expected_state_root):
            _unsafe("sqlite path escapes the release state root")
        if _paths_overlap(canonical_sqlite, version_root):
            _unsafe("sqlite path overlaps the read-only version tree")


def discover_module_roots(env: Mapping[str, str] | None = None) -> dict[str, Path]:
    root = runtime_root(env)
    return {name: root / "apps" / name for name in MODULE_NAMES}


def run_release_self_check(
    settings: "NodeSettings",
    *,
    env: Mapping[str, str] | None = None,
    dependencies: ReleaseSelfCheckDependencies | None = None,
) -> dict[str, object]:
    probes = dependencies or LocalReleaseSelfCheckDependencies()
    imports = (
        "clink_node.config",
        "clink_node.runtime",
        "clink_node.application",
        "clink_node.cli",
    )
    missing_imports = [
        module_name
        for module_name in imports
        if not probes.import_available(module_name)
    ]
    module_roots = discover_module_roots(env)
    expected_paths = [
        module_root / script
        for module_root in module_roots.values()
        for script in (
            "run_demo.sh",
            "run_demo_stop.sh",
            "run_demo_status.sh",
        )
    ]
    missing_paths = [
        str(path)
        for path in expected_paths
        if not probes.path_is_file(path)
    ]
    policy_detail = list(settings.validation_errors())
    try:
        ReleaseRuntimePolicy.validate(settings, env=env)
    except UnsafeReleaseConfiguration as exc:
        policy_detail.append(str(exc))
    checks = {
        "imports": {"ok": not missing_imports, "detail": missing_imports},
        "layout": {"ok": not missing_paths, "detail": missing_paths},
        "policy": {"ok": not policy_detail, "detail": policy_detail},
    }
    ok = all(check["ok"] for check in checks.values())
    return {
        "status": "ok" if ok else "failed",
        "profile": settings.profile.value,
        "execution": settings.redacted()["execution"],
        "checks": checks,
    }


def _literal_loopback(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
        return address.version == 4 and address.is_loopback
    except ValueError:
        return False


def _trusted_release_runtime_root(source: Mapping[str, str]) -> Path:
    configured = source.get("CLINK_RUNTIME_ROOT")
    if not configured:
        _unsafe("CLINK_RUNTIME_ROOT is required from the trusted launcher")
    try:
        return runtime_root(source)
    except (FileNotFoundError, ValueError) as exc:
        raise UnsafeReleaseConfiguration(
            "unsafe release configuration: invalid CLINK_RUNTIME_ROOT"
        ) from exc


def _strict_descendant(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _paths_overlap(left: Path, right: Path) -> bool:
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
    )


def _unsafe(detail: str) -> None:
    raise UnsafeReleaseConfiguration(f"unsafe release configuration: {detail}")
