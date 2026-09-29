from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import (
    MINIAPP_SECRET_NAMES,
    EventBackend,
    ModuleMode,
    NodeSettings,
    Profile,
    SecretBackend,
    StorageBackend,
    validate_miniapp_secret_value,
    validate_miniapp_secret_values,
)
from .instance_lock import InstanceLock
from .migration import LegacyArtifactMigrator
from .modules import default_module_definitions
from .paths import NodePaths
from .hosted_enrollment import EnrollmentConflict, HostedEnrollmentManager
from .hosted_release_runtime import HostedReleaseRuntime
from .hosted_wallet_bundle import write_core_provisioning_bundle
from .release_runtime import (
    ReleaseRuntimePolicy,
    release_node_paths,
    run_release_self_check,
    runtime_root,
)
from .runtime import RuntimeStatus
from .service_manager import ServiceLifecycleError, ServiceManager
from .storage.postgres import PostgresNodeRepository
from .storage.sqlite import SQLiteNodeRepository


STOPPED_EXIT_CODE = 3
_MISTTRACK_OFFICIAL_BASE_URL = "https://openapi.misttrack.io"
_MISTTRACK_V1_MAX_HOLD_SCORE = 31
_MISTTRACK_V1_MAX_DENY_SCORE = 71
_MISTTRACK_MAX_TIMEOUT_SECONDS = 30.0
_MISTTRACK_MAX_ATTEMPTS = 5
_MISTTRACK_MAX_CACHE_TTL_SECONDS = 86_400
_MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW = 1_000
_MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS = 3_600
_MAX_REDIS_OPERATION_TIMEOUT_SECONDS = 5.0
_MAX_RISK_SECRET_LENGTH = 4_096
_EXTERNAL_CORE_READINESS_TIMEOUT_SECONDS = 5.0
_RISK_RESPONSE_LIMIT_BYTES = 4_096
_SAFE_RISK_PROBE_CATEGORIES = frozenset(
    {
        "not_required",
        "reachable",
        "not_configured",
        "invalid_key",
        "payment_required",
        "plan_expired",
        "rate_limited",
        "redis_unavailable",
        "unavailable",
        "provider_error",
        "invalid_response",
        "invalid_configuration",
    }
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so internal authorization never changes origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _InvalidRiskResponse(Exception):
    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        super().error("invalid command arguments")


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    namespace = parser.parse_args(arguments)
    try:
        return int(namespace.handler(namespace))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Clink: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="clink",
        description="Run the local-first Clink Node.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    from .opc_cli import configure_opc_parser

    configure_opc_parser(commands)

    init = commands.add_parser("init", help="Create one Clink configuration.")
    init.add_argument(
        "--profile",
        choices=[profile.value for profile in Profile],
        default=Profile.PERSONAL.value,
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing config file.",
    )
    init.set_defaults(handler=_init)

    start = commands.add_parser("start", help="Start the unified Node.")
    start.add_argument(
        "--detach",
        action="store_true",
        help="Run the Node in the background.",
    )
    start.add_argument(
        "--systemd",
        action="store_true",
        help="Start the installed user systemd unit.",
    )
    start.set_defaults(handler=_start)

    run = commands.add_parser("_run")
    run.add_argument("--systemd", action="store_true")
    run.set_defaults(handler=_run)

    stop = commands.add_parser("stop", help="Stop the unified Node.")
    stop.set_defaults(handler=_stop)

    status = commands.add_parser("status", help="Read Node status.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=_status)

    doctor = commands.add_parser(
        "doctor",
        help="Validate configuration and local prerequisites.",
    )
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument(
        "--release-self-check",
        action="store_true",
        help="Run the side-effect-free signed Personal release preflight.",
    )
    doctor.set_defaults(handler=_doctor)

    migrate = commands.add_parser(
        "migrate",
        help="Apply the Node control schema.",
    )
    migrate.add_argument(
        "--legacy-root",
        type=Path,
        help=(
            "Archive and index legacy JSONL/SQLite state after applying "
            "the Node schema."
        ),
    )
    migrate.set_defaults(handler=_migrate)

    export = commands.add_parser(
        "export",
        help="Export redacted diagnostic configuration.",
    )
    export.set_defaults(handler=_export)

    secret = commands.add_parser(
        "secret",
        help="Manage an allowlisted Node secret.",
    )
    secret_commands = secret.add_subparsers(
        dest="secret_command",
        required=True,
    )
    secret_set = secret_commands.add_parser(
        "set",
        help="Read and store one secret without echoing it.",
    )
    secret_set.add_argument("name", choices=MINIAPP_SECRET_NAMES)
    secret_set.set_defaults(handler=_secret_set)

    maintenance = commands.add_parser(
        "maintenance",
        help="Quiesce or resume lifecycle mutations.",
    )
    maintenance_commands = maintenance.add_subparsers(
        dest="maintenance_command",
        required=True,
    )
    maintenance_quiesce = maintenance_commands.add_parser("quiesce")
    maintenance_quiesce.add_argument("--reason", default="maintenance")
    maintenance_quiesce.set_defaults(handler=_maintenance_quiesce)
    maintenance_resume = maintenance_commands.add_parser("resume")
    maintenance_resume.set_defaults(handler=_maintenance_resume)
    maintenance_status = maintenance_commands.add_parser("status")
    maintenance_status.add_argument("--json", action="store_true")
    maintenance_status.set_defaults(handler=_maintenance_status)

    service = commands.add_parser(
        "service",
        help="Manage the explicit user systemd service.",
    )
    service_commands = service.add_subparsers(
        dest="service_command",
        required=True,
    )
    service_install = service_commands.add_parser("install")
    service_install.add_argument("--target", type=Path)
    service_install.set_defaults(handler=_service_install)
    for service_command, handler in (
        ("start", _service_start),
        ("stop", _service_stop),
        ("status", _service_status),
        ("uninstall", _service_uninstall),
    ):
        command = service_commands.add_parser(service_command)
        if service_command in {"status", "uninstall"}:
            command.add_argument("--target", type=Path)
        if service_command == "status":
            command.add_argument("--json", action="store_true")
            command.add_argument("--systemd", action="store_true")
        command.set_defaults(handler=handler)

    upgrade = commands.add_parser(
        "upgrade",
        help="Quiesce and install one verified release bundle.",
    )
    upgrade.add_argument("--version", required=True)
    upgrade.add_argument("--bundle", type=Path)
    upgrade.add_argument("--installer", default="clink-installer")
    upgrade.add_argument("--release-root", type=Path)
    upgrade.add_argument("--public-key")
    upgrade.add_argument("--public-key-file", type=Path)
    upgrade.set_defaults(handler=_upgrade)

    rollback = commands.add_parser(
        "rollback",
        help="Quiesce and explicitly select the previous release.",
    )
    rollback.add_argument("--installer", default="clink-installer")
    rollback.add_argument("--release-root", type=Path)
    rollback.set_defaults(handler=_rollback)

    enrollment = commands.add_parser(
        "enrollment",
        help="Manage this signed Hosted enrollment.",
    )
    enrollment_commands = enrollment.add_subparsers(
        dest="enrollment_command",
        required=True,
    )
    enroll = enrollment_commands.add_parser(
        "enroll",
        help="Enroll this Node with one invite code.",
    )
    enroll.add_argument("--wallet-binding-id", required=True)
    enroll.set_defaults(handler=_enrollment_enroll)
    enrollment_status = enrollment_commands.add_parser(
        "status",
        help="Read local enrollment status.",
    )
    enrollment_status.add_argument("--json", action="store_true")
    enrollment_status.set_defaults(handler=_enrollment_status)
    rotate = enrollment_commands.add_parser(
        "rotate",
        help="Rotate the current enrollment credential.",
    )
    rotate.set_defaults(handler=_enrollment_rotate)
    revoke = enrollment_commands.add_parser(
        "revoke",
        help="Revoke the current enrollment.",
    )
    revoke.set_defaults(handler=_enrollment_revoke)
    export_core_wallet = enrollment_commands.add_parser(
        "export-core-wallet-bundle",
        help="Write an owner-only Core provisioning bundle.",
    )
    export_core_wallet.add_argument("--user-id", required=True)
    export_core_wallet.add_argument("--wallet-identity-id", required=True)
    export_core_wallet.add_argument("--request-id", required=True)
    export_core_wallet.add_argument("--output", required=True, type=Path)
    export_core_wallet.set_defaults(handler=_enrollment_export_core_wallet_bundle)
    return parser


def _init(namespace: argparse.Namespace) -> int:
    profile = Profile(namespace.profile)
    paths = NodePaths.discover()
    paths.ensure()
    if paths.config.exists() and not namespace.force:
        raise FileExistsError(
            f"{paths.config} already exists; use --force to replace it"
        )
    paths.config.write_text(
        _config_template(profile, paths),
        encoding="utf-8",
    )
    paths.config.chmod(0o600)
    print(
        f"Initialized Clink Node profile={profile.value} "
        f"config={paths.config}"
    )
    return 0


def _start(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    if namespace.detach and namespace.systemd:
        raise ServiceLifecycleError(
            "detached and systemd service modes are mutually exclusive"
        )
    if namespace.systemd:
        ServiceManager(settings.paths).start(systemd=True)
        print("Clink Node systemd service started.")
        return 0
    status = _runtime_status(settings)
    if status.running:
        print(f"Clink Node is already running (pid={status.pid}).")
        return 0
    if not namespace.detach:
        return _run(namespace)

    settings.paths.ensure()
    log_path = settings.paths.logs / "node.log"
    with log_path.open("ab", buffering=0) as log:
        subprocess.Popen(
            [sys.executable, "-m", "clink_node", "_run"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = _runtime_status(settings)
        if status.running:
            print(
                f"Clink Node started pid={status.pid} "
                f"http={status.http_url} mcp={status.mcp_url}"
            )
            return 0
        time.sleep(0.2)
    raise RuntimeError(f"Node did not start; inspect {log_path}")


def _run(namespace: argparse.Namespace) -> int:
    del namespace
    settings = _load_valid_settings()
    from .application import ClinkNodeRuntime

    ClinkNodeRuntime(settings).run()
    return 0


def _maintenance_manager() -> ServiceManager:
    settings = _load_valid_settings()
    return ServiceManager(settings.paths)


def _maintenance_quiesce(namespace: argparse.Namespace) -> int:
    _maintenance_manager().quiesce(reason=namespace.reason)
    print("Clink Node maintenance quiesced.")
    return 0


def _maintenance_resume(namespace: argparse.Namespace) -> int:
    del namespace
    _maintenance_manager().resume()
    print("Clink Node maintenance resumed.")
    return 0


def _maintenance_status(namespace: argparse.Namespace) -> int:
    manager = _maintenance_manager()
    payload = {"quiesced": manager.is_quiesced()}
    if namespace.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("quiesced" if payload["quiesced"] else "active")
    return 0


def _service_target(namespace: argparse.Namespace) -> Path:
    target = getattr(namespace, "target", None)
    return target or (
        Path.home() / ".config" / "systemd" / "user" / "clink-node.service"
    )


def _service_manager() -> ServiceManager:
    return ServiceManager(_load_valid_settings().paths)


def _service_install(namespace: argparse.Namespace) -> int:
    manager = _service_manager()
    target = manager.install_unit(_service_target(namespace))
    manager.systemd.daemon_reload()
    print(f"Installed {target}; enable/start remain explicit.")
    return 0


def _service_start(namespace: argparse.Namespace) -> int:
    del namespace
    _service_manager().start(systemd=True)
    print("Clink Node systemd service started.")
    return 0


def _service_stop(namespace: argparse.Namespace) -> int:
    del namespace
    _service_manager().stop(systemd=True)
    print("Clink Node systemd service stopped.")
    return 0


def _service_status(namespace: argparse.Namespace) -> int:
    status = _service_manager().status(systemd=True)
    payload = {
        "active": status.active,
        "mode": status.mode,
        "detail": status.detail,
    }
    if namespace.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"systemd {status.detail}")
    return 0 if status.active else STOPPED_EXIT_CODE


def _service_uninstall(namespace: argparse.Namespace) -> int:
    manager = _service_manager()
    manager.uninstall(_service_target(namespace))
    manager.systemd.daemon_reload()
    print("Clink Node systemd service uninstalled.")
    return 0


def _release_root(namespace: argparse.Namespace) -> Path:
    if namespace.release_root is not None:
        return namespace.release_root
    configured = os.environ.get("CLINK_RELEASE_ROOT")
    if configured:
        return Path(configured)
    return Path.home() / ".clink"


def _run_installer(namespace: argparse.Namespace, operation: str) -> int:
    settings = _load_valid_settings()
    manager = ServiceManager(settings.paths)
    root = _release_root(namespace)
    if operation == "install":
        if namespace.bundle is None:
            raise ValueError("upgrade requires --bundle")
        verify_command = [
            namespace.installer,
            "verify",
            "--bundle",
            str(namespace.bundle),
        ]
        if namespace.public_key:
            verify_command.extend(("--public-key", namespace.public_key))
        if namespace.public_key_file:
            verify_command.extend(
                ("--public-key-file", str(namespace.public_key_file))
            )
        verified = subprocess.run(
            verify_command,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if f"version={namespace.version}" not in verified.stdout:
            raise ServiceLifecycleError(
                "verified bundle version does not match requested version"
            )
        command = [
            namespace.installer,
            "install",
            "--bundle",
            str(namespace.bundle),
            "--root",
            str(root),
        ]
        if namespace.public_key:
            command.extend(("--public-key", namespace.public_key))
        if namespace.public_key_file:
            command.extend(("--public-key-file", str(namespace.public_key_file)))
    else:
        command = [namespace.installer, "rollback", "--root", str(root)]
    manager.quiesce(reason=operation)
    try:
        _prepare_upgrade_storage(settings, operation)
        result = subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if operation == "install":
            expected = f"version={namespace.version}"
            if expected not in result.stdout:
                raise ServiceLifecycleError(
                    "installer selected an unexpected release version"
                )
        if result.stdout:
            print(result.stdout, end="")
    finally:
        manager.resume()
    print(f"Clink Node {operation} completed.")
    return 0


def _prepare_upgrade_storage(settings: NodeSettings, operation: str) -> None:
    """Validate and privately back up SQLite state before release switching."""

    if settings.storage.backend is not StorageBackend.SQLITE:
        return
    sqlite_path = settings.storage.sqlite_path
    if sqlite_path is None:
        raise ServiceLifecycleError("sqlite storage path is not configured")
    repository = SQLiteNodeRepository(sqlite_path)
    repository.checkpoint_and_validate()
    backup_directory = settings.paths.data / "upgrade-backups"
    backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    label = "upgrade" if operation == "install" else "rollback"
    backup_path = backup_directory / f"{label}-{time.time_ns()}.db"
    repository.create_upgrade_backup(backup_path)


def _upgrade(namespace: argparse.Namespace) -> int:
    return _run_installer(namespace, "install")


def _rollback(namespace: argparse.Namespace) -> int:
    return _run_installer(namespace, "rollback")


_ENROLLMENT_IDENTIFIER = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$"
)
_ENROLLMENT_PENDING_ACTIONS = {
    "enrollment_pending": "enroll",
    "rotation_pending": "resume_rotation",
    "revocation_pending": "resume_revocation",
}


def _require_signed_enrollment_release(settings: NodeSettings) -> None:
    if not settings.release_mode:
        raise RuntimeError(
            "Hosted enrollment requires a signed release runtime"
        )


def _open_enrollment_manager(
    settings: NodeSettings,
) -> tuple[HostedEnrollmentManager, Any]:
    """Open the release-pinned enrollment manager and its closable transport."""

    from .application import _secret_store
    from .hosted_enrollment_transport import HttpxEnrollmentTransport

    trust = HostedReleaseRuntime(env=os.environ).load_trust()
    transport = HttpxEnrollmentTransport(trust.enrollment_endpoint)
    try:
        manager = HostedEnrollmentManager(
            secret_store=_secret_store(settings),
            transport=transport,
            trust=trust,
        )
    except BaseException:
        transport.close()
        raise
    return manager, transport


def _enrollment_enroll(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    _require_signed_enrollment_release(settings)
    wallet_binding_id = namespace.wallet_binding_id
    if (
        type(wallet_binding_id) is not str
        or _ENROLLMENT_IDENTIFIER.fullmatch(wallet_binding_id) is None
    ):
        raise ValueError("wallet binding id is invalid")

    with InstanceLock(settings.paths.runtime / "node.lock"):
        manager, transport = _open_enrollment_manager(settings)
        try:
            current = manager.current()
            if current is not None:
                if current.state != "enrollment_pending":
                    raise EnrollmentConflict("Node is already enrolled")
                if current.wallet_binding_id != wallet_binding_id:
                    raise EnrollmentConflict(
                        "Pending enrollment does not match this request"
                    )
            invite_code = getpass.getpass("Invite code: ")
            bundle = manager.enroll(
                invite_code=invite_code,
                wallet_binding_id=wallet_binding_id,
            )
            _print_enrollment_status(bundle)
        finally:
            transport.close()
    return 0


def _enrollment_status(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    _require_signed_enrollment_release(settings)
    manager, transport = _open_enrollment_manager(settings)
    try:
        bundle = manager.current()
        payload = _enrollment_status_payload(bundle)
    finally:
        transport.close()
    if namespace.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            " ".join(
                f"{key}={value}"
                for key, value in payload.items()
            )
        )
    return 0


def _enrollment_rotate(namespace: argparse.Namespace) -> int:
    del namespace
    settings = _load_valid_settings()
    _require_signed_enrollment_release(settings)
    with InstanceLock(settings.paths.runtime / "node.lock"):
        manager, transport = _open_enrollment_manager(settings)
        try:
            current = manager.current()
            if current is None or current.state not in {
                "active",
                "rotation_pending",
            }:
                raise EnrollmentConflict("An active enrollment is required")
            bundle = (
                manager.resume_rotation()
                if current.state == "rotation_pending"
                else manager.rotate()
            )
            _print_enrollment_status(bundle)
        finally:
            transport.close()
    return 0


def _enrollment_revoke(namespace: argparse.Namespace) -> int:
    del namespace
    settings = _load_valid_settings()
    _require_signed_enrollment_release(settings)
    with InstanceLock(settings.paths.runtime / "node.lock"):
        manager, transport = _open_enrollment_manager(settings)
        try:
            current = manager.current()
            if current is None or current.state not in {
                "active",
                "rotation_pending",
                "revocation_pending",
            }:
                raise EnrollmentConflict("An active enrollment is required")
            if current.state == "revocation_pending":
                manager.resume_revocation()
            else:
                manager.revoke()
            print("Enrollment revoked.")
        finally:
            transport.close()
    return 0


def _enrollment_export_core_wallet_bundle(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    _require_signed_enrollment_release(settings)
    with InstanceLock(settings.paths.runtime / "node.lock"):
        manager, transport = _open_enrollment_manager(settings)
        try:
            bundle = manager.current()
            result = write_core_provisioning_bundle(
                bundle,
                user_id=namespace.user_id,
                wallet_identity_id=namespace.wallet_identity_id,
                request_id=namespace.request_id,
                output_path=namespace.output,
            )
        finally:
            transport.close()
    print(json.dumps(result, sort_keys=True))
    return 0


def _enrollment_status_payload(bundle: object | None) -> dict[str, object]:
    if bundle is None:
        return {
            "state": "not_enrolled",
            "tenant_id": None,
            "node_id": None,
            "wallet_binding_id": None,
            "credential_epoch": 0,
            "pending_action": "enroll",
        }
    state = getattr(bundle, "state")
    return {
        "state": state,
        "tenant_id": getattr(bundle, "tenant_id"),
        "node_id": getattr(bundle, "node_id"),
        "wallet_binding_id": getattr(bundle, "wallet_binding_id"),
        "credential_epoch": getattr(bundle, "credential_epoch"),
        "pending_action": _ENROLLMENT_PENDING_ACTIONS.get(state),
    }


def _print_enrollment_status(bundle: object) -> None:
    print(json.dumps(_enrollment_status_payload(bundle), sort_keys=True))


def _stop(namespace: argparse.Namespace) -> int:
    del namespace
    settings = NodeSettings.load()
    status = _runtime_status(settings)
    if not status.running or status.pid is None:
        _remove_stale_pid(settings)
        _stop_managed_modules(settings)
        print("Clink Node is not running.")
        return 0
    os.kill(status.pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not _process_running(status.pid):
            _remove_stale_pid(settings)
            _stop_managed_modules(settings)
            print("Clink Node stopped.")
            return 0
        time.sleep(0.25)
    raise TimeoutError(f"Node pid {status.pid} did not stop")


def _stop_managed_modules(settings: NodeSettings) -> None:
    definitions = default_module_definitions(
        _repository_root(),
        settings,
    )
    failures: list[str] = []
    for module in reversed(definitions):
        if (
            module.mode is not ModuleMode.MANAGED
            or module.stop_command is None
        ):
            continue
        result = subprocess.run(
            module.stop_command,
            cwd=module.root,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            failures.append(module.name)
    if failures:
        raise RuntimeError(
            "failed to stop managed modules: " + ", ".join(failures)
        )


def _status(namespace: argparse.Namespace) -> int:
    settings = NodeSettings.load()
    status = _runtime_status(settings)
    payload = {
        "running": status.running,
        "pid": status.pid,
        "profile": status.profile,
        "http_url": status.http_url,
        "mcp_url": status.mcp_url,
    }
    if namespace.json:
        print(json.dumps(payload, sort_keys=True))
    elif status.running:
        print(
            f"Clink Node running pid={status.pid} "
            f"http={status.http_url} mcp={status.mcp_url}"
        )
    else:
        print("Clink Node stopped.")
    return 0 if status.running else STOPPED_EXIT_CODE


def _release_self_check(namespace: argparse.Namespace) -> int:
    try:
        settings = replace(
            NodeSettings.defaults(
                Profile.PERSONAL,
                paths=release_node_paths(dict(os.environ)),
            ),
            release_mode=True,
        )
        report = run_release_self_check(
            settings,
            env=dict(os.environ),
        )
    except Exception as exc:
        report = {
            "status": "failed",
            "checks": {
                "release_runtime": {
                    "ok": False,
                    "detail": type(exc).__name__,
                }
            },
        }
    if getattr(namespace, "json", False):
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"[{'OK' if report['status'] == 'ok' else 'FAIL'}] release_self_check")
        for name, check in report.get("checks", {}).items():
            print(f"[{('OK' if check['ok'] else 'FAIL')}] {name}: {check['detail']}")
    return 0 if report["status"] == "ok" else 1


def _doctor(namespace: argparse.Namespace) -> int:
    if namespace.release_self_check:
        return _release_self_check(namespace)
    settings = NodeSettings.load()
    if settings.release_mode:
        ReleaseRuntimePolicy.validate(settings)
    checks: dict[str, dict[str, Any]] = {}
    errors = settings.validation_errors()
    checks["configuration"] = {
        "ok": not errors,
        "detail": errors,
    }
    root = _repository_root()
    expected = (
        root / "apps/core/run_demo.sh",
        root / "apps/marketplace/run_demo.sh",
        root / "apps/prediction-markets/run_demo.sh",
    )
    missing = [str(path) for path in expected if not path.is_file()]
    checks["repository_layout"] = {
        "ok": not missing,
        "detail": missing,
    }
    occupied = [
        address
        for address in (
            (settings.host, settings.port),
            (settings.mcp_host, settings.mcp_port),
        )
        if not _port_available(*address)
    ]
    current = _runtime_status(settings)
    checks["ports"] = {
        "ok": not occupied or current.running,
        "detail": [f"{host}:{port}" for host, port in occupied],
    }
    checks["secrets"] = {
        "ok": not (
            settings.profile is Profile.SERVER
            and settings.secrets.backend is not SecretBackend.VAULT
        ),
        "detail": settings.secrets.backend.value,
    }
    storage_ok, storage_detail = _check_storage(settings)
    checks["storage"] = {
        "ok": storage_ok,
        "detail": storage_detail,
    }
    events_ok, events_detail = _check_events(settings)
    checks["events"] = {
        "ok": events_ok,
        "detail": events_detail,
    }
    miniapp_ok, miniapp_detail = _check_miniapp(settings)
    checks["miniapp"] = {
        "ok": miniapp_ok,
        "detail": miniapp_detail,
    }
    risk_ok, risk_detail = _check_risk_provider(settings)
    risk_ok, risk_detail = _normalize_risk_probe_result(
        risk_ok,
        risk_detail,
    )
    checks["risk_provider"] = {
        "ok": risk_ok,
        "detail": risk_detail,
        **_risk_doctor_projection(settings, risk_detail),
    }
    ok = all(item["ok"] for item in checks.values())
    report = {
        "status": "ok" if ok else "failed",
        "profile": settings.profile.value,
        "checks": checks,
    }
    if namespace.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for name, item in checks.items():
            marker = "OK" if item["ok"] else "FAIL"
            if name == "risk_provider":
                print(
                    f"[{marker}] {name}: "
                    f"provider={item['provider']} "
                    f"mode={item['mode']} "
                    f"configured={str(item['configured']).lower()} "
                    f"probe={item['probe']}"
                )
            else:
                print(f"[{marker}] {name}: {item['detail']}")
    return 0 if ok else 1


def _migrate(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    with InstanceLock(settings.paths.runtime / "node.lock"):
        if settings.storage.backend is StorageBackend.SQLITE:
            repository = SQLiteNodeRepository(settings.storage.sqlite_path)
        else:
            repository = PostgresNodeRepository(
                settings.storage.postgres_url or ""
            )
        repository.migrate()
        print(f"schema_version={repository.schema_version()}")
        if namespace.legacy_root:
            report = LegacyArtifactMigrator(
                repository=repository,
                archive_root=settings.paths.data / "imports",
            ).import_root(namespace.legacy_root)
            print(json.dumps(report.as_json(), sort_keys=True))
    return 0


def _export(namespace: argparse.Namespace) -> int:
    del namespace
    settings = _load_valid_settings()
    print(json.dumps(settings.redacted(), indent=2, sort_keys=True))
    return 0


def _secret_set(namespace: argparse.Namespace) -> int:
    settings = _load_valid_settings()
    if namespace.name not in MINIAPP_SECRET_NAMES:
        raise ValueError("unsupported secret name")
    value = _validated_secret_input(
        namespace.name,
        getpass.getpass("Secret value: "),
    )
    from .application import _secret_store

    with InstanceLock(settings.paths.runtime / "node.lock"):
        _secret_store(settings).set(namespace.name, value)
    print("Secret stored.")
    return 0


def _load_valid_settings() -> NodeSettings:
    settings = NodeSettings.load()
    if settings.release_mode:
        runtime_root()
        ReleaseRuntimePolicy.validate(settings)
    errors = settings.validation_errors()
    if errors:
        raise ValueError("; ".join(errors))
    settings.paths.ensure()
    return settings


def _runtime_status(settings: NodeSettings) -> RuntimeStatus:
    pid_path = settings.paths.runtime / "node.pid"
    pid: int | None = None
    if pid_path.is_file():
        try:
            pid = int(pid_path.read_text(encoding="ascii").strip())
        except (ValueError, OSError):
            pid = None
    running = pid is not None and _process_running(pid)
    return RuntimeStatus(
        running=running,
        pid=pid if running else None,
        profile=settings.profile.value,
        http_url=f"http://{settings.host}:{settings.port}",
        mcp_url=f"http://{settings.mcp_host}:{settings.mcp_port}/mcp",
    )


def _process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
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


def _remove_stale_pid(settings: NodeSettings) -> None:
    (settings.paths.runtime / "node.pid").unlink(missing_ok=True)


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _check_storage(
    settings: NodeSettings,
) -> tuple[bool, str]:
    if settings.storage.backend is StorageBackend.SQLITE:
        path = settings.storage.sqlite_path
        if path is None:
            return False, "sqlite path is not configured"
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"{type(exc).__name__}: storage unavailable"
        return True, "sqlite path is writable"
    if not settings.storage.postgres_url:
        return False, "postgres URL is not configured"
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(
            settings.storage.postgres_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except Exception as exc:
        return False, f"{type(exc).__name__}: postgres unavailable"
    return True, "postgres reachable"


def _check_events(
    settings: NodeSettings,
) -> tuple[bool, str]:
    if settings.events.backend.value == "memory":
        return True, "in-process event sink"
    if not settings.events.redis_url:
        return False, "redis URL is not configured"
    try:
        import redis

        client = redis.Redis.from_url(
            settings.events.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        client.close()
    except Exception as exc:
        return False, f"{type(exc).__name__}: redis unavailable"
    return True, "redis reachable"


def _check_risk_provider(settings: NodeSettings) -> tuple[bool, str]:
    core = settings.modules.get("core")
    if core is not None and core.mode is ModuleMode.EXTERNAL:
        return _check_external_core_risk_provider(settings)
    return _check_local_risk_provider(settings)


def _check_external_core_risk_provider(
    settings: NodeSettings,
) -> tuple[bool, str]:
    core = settings.modules.get("core")
    if core is None:
        return False, "invalid_configuration"
    policy_url = core.service_urls.get("policy")
    if not policy_url or policy_url.strip() != policy_url:
        return False, "invalid_configuration"
    try:
        parsed = urllib.parse.urlsplit(policy_url)
    except Exception:
        return False, "invalid_configuration"
    loopback_http = (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if (
        (parsed.scheme != "https" and not loopback_http)
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False, "invalid_configuration"
    try:
        internal_token = _load_core_internal_token(settings)
    except Exception:
        return False, "unavailable"
    if not internal_token:
        return False, "invalid_configuration"
    try:
        request = urllib.request.Request(
            f"{policy_url.rstrip('/')}/risk/readiness",
            headers={"Authorization": f"Bearer {internal_token}"},
            method="GET",
        )
    except Exception:
        return False, "invalid_configuration"
    timeout = _EXTERNAL_CORE_READINESS_TIMEOUT_SECONDS
    deadline = time.monotonic() + timeout
    try:
        with _open_external_core_readiness(
            request,
            timeout=timeout,
        ) as response:
            body = _read_bounded_risk_response(
                response,
                deadline=deadline,
            )
        payload = json.loads(body.decode("utf-8"))
    except (
        _InvalidRiskResponse,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return False, "invalid_response"
    except urllib.error.HTTPError:
        return False, "unavailable"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "unavailable"
    except Exception:
        return False, "provider_error"
    if (
        not isinstance(payload, dict)
        or set(payload) != {"ok", "detail"}
        or type(payload.get("ok")) is not bool
        or payload.get("detail") not in _SAFE_RISK_PROBE_CATEGORIES
    ):
        return False, "invalid_response"
    successful = payload["detail"] in {"reachable", "not_required"}
    if payload["ok"] is not successful:
        return False, "invalid_response"
    return payload["ok"], payload["detail"]


def _open_external_core_readiness(
    request: urllib.request.Request,
    *,
    timeout: int | float,
) -> Any:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


def _open_local_misttrack_status(
    request: urllib.request.Request,
    *,
    timeout: int | float,
) -> Any:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


def _read_bounded_risk_response(
    response: Any,
    *,
    deadline: float,
) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _close_risk_response(response)
        raise TimeoutError("risk provider response timed out")
    outcome: dict[str, object] = {}
    completed = threading.Event()

    def read() -> None:
        try:
            _set_risk_response_read_timeout(response, remaining)
            outcome["value"] = response.read(
                _RISK_RESPONSE_LIMIT_BYTES + 1
            )
        except Exception as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _close_risk_response(response)
        raise TimeoutError("risk provider response timed out")
    if not completed.wait(timeout=remaining):
        _close_risk_response(response)
        raise TimeoutError("risk provider response timed out")
    if time.monotonic() >= deadline:
        _close_risk_response(response)
        raise TimeoutError("risk provider response timed out")
    error = outcome.get("error")
    if isinstance(error, Exception):
        raise error
    body = outcome.get("value")
    if (
        not isinstance(body, bytes)
        or len(body) > _RISK_RESPONSE_LIMIT_BYTES
    ):
        raise _InvalidRiskResponse("risk provider returned invalid response")
    return body


def _close_risk_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _set_risk_response_read_timeout(response: Any, timeout: float) -> None:
    pending = [response]
    visited: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in visited:
            continue
        visited.add(id(candidate))
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(timeout)
            except Exception:
                pass
        for attribute in (
            "fp",
            "raw",
            "_fp",
            "_sock",
            "sock",
            "connection",
            "_connection",
        ):
            try:
                nested = getattr(candidate, attribute, None)
            except Exception:
                nested = None
            if nested is not None:
                pending.append(nested)


def _load_core_internal_token(settings: NodeSettings) -> str | None:
    """Read the existing Core token without creating or exposing it."""
    from .application import _secret_store
    from .runtime import ManagedEnvironmentBuilder

    value = _secret_store(settings).get(ManagedEnvironmentBuilder.CORE_TOKEN)
    if not isinstance(value, bytes) or not value:
        return None
    try:
        token = value.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not _is_valid_risk_secret(token):
        return None
    return token


def _is_valid_risk_secret(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= _MAX_RISK_SECRET_LENGTH
        and all(33 <= ord(character) <= 126 for character in value)
    )


def _check_local_risk_provider(settings: NodeSettings) -> tuple[bool, str]:
    mode = os.getenv("CLINK_RISK_MODE", "shadow").strip().lower()
    provider = os.getenv("CLINK_RISK_PROVIDER", "misttrack").strip().lower()
    live_funding = os.getenv("CLINK_LIVE_FUNDING", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if mode not in {"shadow", "enforce"} or provider != "misttrack":
        return False, "invalid_configuration"
    base_url = os.getenv(
        "MISTTRACK_BASE_URL",
        _MISTTRACK_OFFICIAL_BASE_URL,
    ).strip()
    try:
        parsed_base_url = urllib.parse.urlsplit(base_url)
        invalid_base_url = (
            parsed_base_url.scheme != "https"
            or parsed_base_url.hostname != "openapi.misttrack.io"
            or parsed_base_url.port is not None
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.path not in {"", "/"}
            or bool(parsed_base_url.query)
            or bool(parsed_base_url.fragment)
        )
    except Exception:
        invalid_base_url = True
    if invalid_base_url:
        return False, "invalid_configuration"
    try:
        timeout = float(os.getenv("MISTTRACK_TIMEOUT_SECONDS", "5"))
        max_attempts = int(os.getenv("MISTTRACK_MAX_ATTEMPTS", "2"))
        hold_score = int(os.getenv("CLINK_RISK_HOLD_SCORE", "31"))
        deny_score = int(os.getenv("CLINK_RISK_DENY_SCORE", "71"))
        max_age = int(os.getenv("CLINK_RISK_MAX_AGE_SECONDS", "300"))
        cache_ttl = int(os.getenv("CLINK_RISK_CACHE_TTL_SECONDS", "300"))
        redis_timeout = float(
            os.getenv("CLINK_REDIS_OPERATION_TIMEOUT_SECONDS", "1")
        )
        rate_requests_value = os.getenv(
            "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW", ""
        ).strip()
        rate_window_value = os.getenv(
            "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS", ""
        ).strip()
        rate_requests = int(rate_requests_value) if rate_requests_value else None
        rate_window = int(rate_window_value) if rate_window_value else None
    except (TypeError, ValueError):
        return False, "invalid_configuration"
    if (
        not 0 < timeout <= _MISTTRACK_MAX_TIMEOUT_SECONDS
        or not 1 <= max_attempts <= _MISTTRACK_MAX_ATTEMPTS
        or not 1 <= hold_score < deny_score <= 100
        or max_age <= 0
        or not 1 <= cache_ttl <= _MISTTRACK_MAX_CACHE_TTL_SECONDS
        or not 0 < redis_timeout <= _MAX_REDIS_OPERATION_TIMEOUT_SECONDS
        or (
            rate_requests is not None
            and not (
                1
                <= rate_requests
                <= _MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW
            )
        )
        or (
            rate_window is not None
            and not (
                1
                <= rate_window
                <= _MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS
            )
        )
        or (rate_requests is None) != (rate_window is None)
    ):
        return False, "invalid_configuration"
    if mode == "enforce" and (
        hold_score > _MISTTRACK_V1_MAX_HOLD_SCORE
        or deny_score > _MISTTRACK_V1_MAX_DENY_SCORE
    ):
        return False, "invalid_configuration"
    api_key = os.getenv("MISTTRACK_API_KEY", "")
    if api_key and not _is_valid_risk_secret(api_key):
        return False, "invalid_configuration"
    if settings.profile is Profile.SERVER and api_key and rate_requests is None:
        return False, "invalid_configuration"
    if live_funding and mode != "enforce":
        return False, "invalid_configuration"
    if not api_key:
        if mode == "shadow" and not live_funding:
            return True, "not_required"
        return False, "not_configured"
    if settings.profile is Profile.SERVER:
        limiter_ok, limiter_detail = _check_managed_server_risk_limiter(
            settings,
            requests_per_window=rate_requests,
            window_seconds=rate_window,
            timeout_seconds=redis_timeout,
        )
        if not limiter_ok:
            return False, _safe_risk_probe_category(limiter_detail)
    try:
        url = (
            _MISTTRACK_OFFICIAL_BASE_URL
            + "/v1/status?"
            + urllib.parse.urlencode({"api_key": api_key})
        )
        request = urllib.request.Request(url, method="GET")
    except Exception:
        return False, "invalid_configuration"
    deadline = time.monotonic() + timeout
    try:
        with _open_local_misttrack_status(
            request,
            timeout=timeout,
        ) as response:
            body = _read_bounded_risk_response(
                response,
                deadline=deadline,
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, "invalid_response"
        if not isinstance(payload, dict) or not (
            payload.get("success") is True
            or payload.get("status") in {"ok", "success"}
            or (
                type(payload.get("code")) is int
                and payload.get("code") == 0
            )
            or payload.get("code") == "0"
        ):
            return False, "invalid_response"
    except _InvalidRiskResponse:
        return False, "invalid_response"
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return False, "unavailable"
        if exc.code in {401, 403}:
            return False, "invalid_key"
        if exc.code == 402:
            return False, "payment_required"
        if exc.code == 429:
            return False, "rate_limited"
        if exc.code in {500, 502, 503, 504}:
            return False, "unavailable"
        return False, "provider_error"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "unavailable"
    except Exception:
        return False, "provider_error"
    return True, "reachable"


def _check_managed_server_risk_limiter(
    settings: NodeSettings,
    *,
    requests_per_window: int | None,
    window_seconds: int | None,
    timeout_seconds: float,
) -> tuple[bool, str]:
    if (
        settings.profile is not Profile.SERVER
        or settings.events.backend is not EventBackend.REDIS
        or not settings.events.redis_url
        or type(requests_per_window) is not int
        or not (
            1
            <= requests_per_window
            <= _MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW
        )
        or type(window_seconds) is not int
        or not (
            1
            <= window_seconds
            <= _MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS
        )
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= _MAX_REDIS_OPERATION_TIMEOUT_SECONDS
    ):
        return False, "invalid_configuration"

    client: Any | None = None
    try:
        import redis

        client = redis.Redis.from_url(
            settings.events.redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        limiter_class = _load_core_risk_rate_limiter_class()
        limiter = limiter_class(
            client,
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
        )
        limiter.check_ready()
        result = limiter.acquire()
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            return False, "redis_unavailable"
        allowed, retry_after_ms = result
        if (
            type(allowed) is not bool
            or type(retry_after_ms) is not int
            or retry_after_ms < 0
            or (allowed and retry_after_ms != 0)
            or (not allowed and retry_after_ms <= 0)
        ):
            return False, "redis_unavailable"
        if not allowed:
            return False, "rate_limited"
    except Exception:
        return False, "redis_unavailable"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return True, "reachable"


def _load_core_risk_rate_limiter_class() -> type[Any]:
    """Load Core's limiter implementation without maintaining a Node copy."""
    module_path = (
        _repository_root()
        / "apps"
        / "core"
        / "services"
        / "policy_service"
        / "risk_rate_limiter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_clink_core_risk_rate_limiter",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Core risk rate limiter is unavailable")
    module = importlib.util.module_from_spec(spec)
    core_import_root = str(module_path.parents[2])
    added_import_root = core_import_root not in sys.path
    if added_import_root:
        sys.path.insert(0, core_import_root)
    try:
        spec.loader.exec_module(module)
    finally:
        if added_import_root:
            try:
                sys.path.remove(core_import_root)
            except ValueError:
                pass
    limiter_class = getattr(module, "RedisRiskRateLimiter", None)
    if not isinstance(limiter_class, type):
        raise RuntimeError("Core risk rate limiter is unavailable")
    return limiter_class


def _safe_risk_probe_category(value: object) -> str:
    if isinstance(value, str) and value in _SAFE_RISK_PROBE_CATEGORIES:
        return value
    return "provider_error"


def _normalize_risk_probe_result(
    ok: object,
    detail: object,
) -> tuple[bool, str]:
    if (
        type(ok) is not bool
        or not isinstance(detail, str)
        or detail not in _SAFE_RISK_PROBE_CATEGORIES
    ):
        return False, "invalid_response"
    successful = detail in {"reachable", "not_required"}
    if ok is not successful:
        return False, "invalid_response"
    return ok, detail


def _risk_doctor_projection(
    settings: NodeSettings,
    probe: str,
) -> dict[str, object]:
    core = settings.modules.get("core")
    if core is not None and core.mode is ModuleMode.EXTERNAL:
        return {
            "provider": "misttrack",
            "mode": "external",
            "configured": probe
            not in {"not_configured", "invalid_configuration"},
            "probe": _safe_risk_probe_category(probe),
        }
    provider = os.getenv("CLINK_RISK_PROVIDER", "misttrack").strip().lower()
    mode = os.getenv("CLINK_RISK_MODE", "shadow").strip().lower()
    return {
        "provider": "misttrack" if provider == "misttrack" else "invalid",
        "mode": mode if mode in {"shadow", "enforce"} else "invalid",
        "configured": bool(os.getenv("MISTTRACK_API_KEY", "")),
        "probe": _safe_risk_probe_category(probe),
    }


def _check_miniapp(settings: NodeSettings) -> tuple[bool, str]:
    if not settings.miniapp.enabled:
        return True, "disabled"
    try:
        from .application import _secret_store

        store = _secret_store(settings)
        values = {
            name: store.get(name) for name in MINIAPP_SECRET_NAMES
        }
    except Exception:
        return False, "secret store unavailable"
    try:
        validate_miniapp_secret_values(values)
    except ValueError:
        return False, "required secrets are not configured"
    return True, "configured"


def _validated_secret_input(name: str, value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("invalid Mini App secret value")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("invalid Mini App secret value") from None
    return validate_miniapp_secret_value(name, encoded)


def _repository_root() -> Path:
    if os.environ.get("CLINK_RUNTIME_ROOT"):
        return runtime_root(dict(os.environ))
    return Path(__file__).resolve().parents[3]


def _config_template(profile: Profile, paths: NodePaths) -> str:
    if profile is Profile.PERSONAL:
        return (
            '[node]\nprofile = "personal"\nhost = "127.0.0.1"\n'
            'port = 8170\nmcp_host = "127.0.0.1"\nmcp_port = 9170\n'
            "multi_tenant = false\n\n"
            '[storage]\nbackend = "sqlite"\n'
            f'sqlite_path = "{paths.data / "clink.db"}"\n\n'
            '[events]\nbackend = "memory"\n\n'
            '[secrets]\nbackend = "keychain"\n'
            'service_name = "clink-node"\n\n'
            '[interaction]\nmode = "local"\nsession_ttl_seconds = 900\n\n'
            '[miniapp]\nenabled = false\n\n'
            '[modules.core]\nmode = "managed"\n\n'
            '[modules.marketplace]\nmode = "managed"\n\n'
            '[modules.prediction-markets]\nmode = "managed"\n'
        )
    return (
        '[node]\nprofile = "server"\nhost = "127.0.0.1"\n'
        'port = 8170\nmcp_host = "127.0.0.1"\nmcp_port = 9170\n'
        "multi_tenant = true\n\n"
        '[storage]\nbackend = "postgres"\n\n'
        '[events]\nbackend = "redis"\n\n'
        '[secrets]\nbackend = "vault"\n\n'
        '[interaction]\nmode = "self_hosted"\n\n'
        '[miniapp]\nenabled = false\n\n'
        '[modules.core]\nmode = "external"\n'
        'endpoint = "http://127.0.0.1:8019"\n\n'
        '[modules.core.services]\n'
        'account = "http://127.0.0.1:8019"\n'
        'action = "http://127.0.0.1:8016"\n'
        'policy = "http://127.0.0.1:8015"\n'
        'audit = "http://127.0.0.1:8017"\n'
        'funding = "http://127.0.0.1:8018"\n\n'
        '[modules.marketplace]\nmode = "external"\n'
        'endpoint = "http://127.0.0.1:8050"\n'
        'mcp_url = "http://127.0.0.1:9050/mcp"\n\n'
        '[modules.prediction-markets]\nmode = "external"\n'
        'endpoint = "http://127.0.0.1:8040"\n'
        'mcp_url = "http://127.0.0.1:9040/mcp"\n\n'
        '[modules.prediction-markets.services]\n'
        'account_binding = "http://127.0.0.1:8047"\n'
        'execution = "http://127.0.0.1:8042"\n'
    )
