"""Local OPC first-run setup and additive Codex configuration handoff.

This module deliberately stops at preparing one local OPC state file and, when
explicitly requested, registering the local stdio command with Codex.  It does
not pair a device, open a wallet, or call a business endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from .opc_client import OpcClient, OpcClientStateStore


DEFAULT_OPC_ORIGIN = "https://agentonomy.xyz"
DEFAULT_DEVICE_FALLBACK = "OPC device"
MANAGED_BEGIN = "# BEGIN CLINK OPC MANAGED"
MANAGED_END = "# END CLINK OPC MANAGED"
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_HOSTNAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class OpcSetupError(ValueError):
    """A local setup input or safe-write contract was rejected."""


class ConfigConflictError(OpcSetupError):
    """The selected Codex config cannot be safely amended."""


@dataclass(frozen=True)
class ConfigWriteResult:
    path: Path
    changed: bool
    backup: Path | None = None


@dataclass(frozen=True)
class _ConfigSnapshot:
    exists: bool
    fingerprint: tuple[int, int, int, int, str] | None
    raw: bytes


@dataclass(frozen=True)
class _ConfigPlan:
    path: Path
    snapshot: _ConfigSnapshot
    replacement: bytes
    changed: bool


def default_device_label(hostname: str | None = None) -> str:
    """Return a short, control-free label derived from this device hostname."""

    if hostname is None:
        try:
            hostname = socket.gethostname()
        except OSError:
            hostname = ""
    if type(hostname) is not str:
        hostname = ""
    sanitized = _HOSTNAME_SAFE.sub("-", hostname.strip())
    sanitized = sanitized.strip("-._")
    if not sanitized:
        return DEFAULT_DEVICE_FALLBACK
    available = 80 - len("OPC - ")
    sanitized = sanitized[:available].rstrip("-._")
    return f"OPC - {sanitized}" if sanitized else DEFAULT_DEVICE_FALLBACK


def resolve_codex_config_path(config: Path | None = None) -> Path:
    """Resolve an explicit config or the supported CODEX_HOME default."""

    if config is not None:
        return _absolute(config)
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home is not None:
        return _absolute(Path(codex_home) / "config.toml")
    return _absolute(Path.home() / ".codex" / "config.toml")


def resolve_installed_executable() -> Path:
    """Find the package-owned wrapper without accepting a caller-supplied path."""

    source = Path(__file__).resolve()
    if source.parent.name != "clink_node" or source.parent.parent.name != "client":
        raise OpcSetupError("installed OPC executable is unavailable")
    candidate = source.parent.parent.parent / "bin" / "clink"
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise OpcSetupError("installed OPC executable cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OpcSetupError("installed OPC executable is not a regular file")
    if not info.st_mode & stat.S_IXUSR:
        raise OpcSetupError("installed OPC executable is not executable")
    return candidate


def _absolute(path: Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = Path.cwd() / value
    return Path(os.path.abspath(os.fspath(value)))


def _check_parent(path: Path) -> None:
    parent = path.parent
    current = Path(parent.anchor)
    missing = False
    for part in parent.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            missing = True
            break
        except OSError as exc:
            raise OpcSetupError("Codex config parent cannot be inspected") from exc
        allowed_alias = sys.platform == "darwin" and current.as_posix() in {
            "/tmp",
            "/var",
        }
        if stat.S_ISLNK(info.st_mode) and not allowed_alias:
            raise OpcSetupError("Codex config parent contains a symlink")
        if not stat.S_ISDIR(info.st_mode) and not allowed_alias:
            raise OpcSetupError("Codex config parent is not a directory")
        if (
            stat.S_IMODE(info.st_mode) & 0o022
            and current.as_posix() not in {"/tmp", "/private/tmp", "/var"}
        ):
            raise OpcSetupError("Codex config parent is writable by another user")
    if missing:
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise OpcSetupError("Codex config parent cannot be created") from exc
        # Re-walk after mkdir to reject a replacement/symlink race in the path.
        current = Path(parent.anchor)
        for part in parent.parts[1:]:
            current /= part
            try:
                info = current.lstat()
            except OSError as exc:
                raise OpcSetupError("Codex config parent cannot be inspected") from exc
            allowed_alias = sys.platform == "darwin" and current.as_posix() in {
                "/tmp",
                "/var",
            }
            if stat.S_ISLNK(info.st_mode) and not allowed_alias:
                raise OpcSetupError("Codex config parent is unsafe")
            if not stat.S_ISDIR(info.st_mode) and not allowed_alias:
                raise OpcSetupError("Codex config parent is unsafe")
    try:
        info = parent.lstat()
    except OSError as exc:
        raise OpcSetupError("Codex config parent cannot be inspected") from exc
    if (
        stat.S_IMODE(info.st_mode) & 0o022
        and parent.as_posix() not in {"/tmp", "/private/tmp", "/var"}
    ):
        raise OpcSetupError("Codex config parent is writable by another user")


def _read_regular(path: Path, label: str) -> tuple[bytes, tuple[int, int, int, int, str]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OpcSetupError(f"{label} cannot be opened safely") from exc
    try:
        first = os.fstat(descriptor)
        if stat.S_ISLNK(first.st_mode) or not stat.S_ISREG(first.st_mode):
            raise OpcSetupError(f"{label} must be a regular file")
        if first.st_size > _MAX_CONFIG_BYTES:
            raise OpcSetupError(f"{label} is too large")
        chunks: list[bytes] = []
        remaining = _MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        second = os.fstat(descriptor)
    except OpcSetupError:
        raise
    except OSError as exc:
        raise OpcSetupError(f"{label} cannot be read") from exc
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_CONFIG_BYTES:
        raise OpcSetupError(f"{label} is too large")
    identity = (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns)
    after = (second.st_dev, second.st_ino, second.st_size, second.st_mtime_ns)
    if identity != after or len(raw) != second.st_size:
        raise ConfigConflictError("Codex config changed while being read")
    return raw, (*identity, hashlib.sha256(raw).hexdigest())


def _snapshot(path: Path) -> _ConfigSnapshot:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _ConfigSnapshot(False, None, b"")
    except OSError as exc:
        raise OpcSetupError("Codex config cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode):
        raise OpcSetupError("Codex config must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise OpcSetupError("Codex config must be a regular file")
    raw, fingerprint = _read_regular(path, "Codex config")
    return _ConfigSnapshot(True, fingerprint, raw)


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise OpcSetupError("Codex config is invalid TOML") from exc
    if not isinstance(value, dict):
        raise OpcSetupError("Codex config is invalid TOML")
    return value


def _managed_span(text: str) -> tuple[int, int, str] | None:
    begins = list(re.finditer(rf"(?m)^{re.escape(MANAGED_BEGIN)}\r?$", text))
    ends = list(re.finditer(rf"(?m)^{re.escape(MANAGED_END)}\r?$", text))
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0].start() > ends[0].start():
        raise ConfigConflictError("Codex managed block markers are invalid")
    begin, end = begins[0], ends[0]
    finish = end.end()
    if text[finish:finish + 2] == "\r\n":
        finish += 2
    elif text[finish:finish + 1] == "\n":
        finish += 1
    body = text[begin.end():end.start()]
    return begin.start(), finish, body


def _entry_from_document(value: dict[str, Any]) -> dict[str, Any] | None:
    servers = value.get("mcp_servers")
    if servers is None:
        return None
    if not isinstance(servers, dict):
        raise ConfigConflictError("existing mcp_servers value conflicts with OPC setup")
    if "clink_node" not in servers:
        return None
    entry = servers["clink_node"]
    if not isinstance(entry, dict):
        raise ConfigConflictError("existing clink_node entry conflicts with OPC setup")
    return entry


def _validate_managed_entry(body: str) -> tuple[str, Path]:
    try:
        value = tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigConflictError("Codex managed block is invalid TOML") from exc
    if set(value) != {"mcp_servers"}:
        raise ConfigConflictError("Codex managed block contains unrelated settings")
    servers = value.get("mcp_servers")
    if not isinstance(servers, dict) or set(servers) != {"clink_node"}:
        raise ConfigConflictError("Codex managed block is invalid")
    entry = servers["clink_node"]
    if not isinstance(entry, dict) or set(entry) != {"command", "args"}:
        raise ConfigConflictError("Codex managed block is invalid")
    command = entry.get("command")
    args = entry.get("args")
    if (
        type(command) is not str
        or not command.startswith("/")
        or any(ord(char) < 32 or ord(char) == 127 for char in command)
        or type(args) is not list
        or len(args) != 4
        or args[:2] != ["opc", "mcp"]
        or args[2] != "--state"
        or type(args[3]) is not str
        or not Path(args[3]).is_absolute()
    ):
        raise ConfigConflictError("Codex managed block is invalid")
    return command, Path(args[3])


def _validate_executable(executable: Path) -> Path:
    path = _absolute(executable)
    try:
        info = path.lstat()
    except OSError as exc:
        raise OpcSetupError("installed OPC executable cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OpcSetupError("installed OPC executable must be a regular file")
    if not info.st_mode & stat.S_IXUSR:
        raise OpcSetupError("installed OPC executable is not executable")
    return path


def _render_block(executable: Path, state: Path) -> str:
    command = json.dumps(str(executable), ensure_ascii=False)
    args = json.dumps(
        ["opc", "mcp", "--state", str(state)],
        ensure_ascii=False,
    )
    return (
        f"{MANAGED_BEGIN}\n"
        "[mcp_servers.clink_node]\n"
        f"command = {command}\n"
        f"args = {args}\n"
        f"{MANAGED_END}\n"
    )


def _verify_rendered_entry(raw: bytes, *, executable: Path, state: Path) -> None:
    """Parse the complete candidate so no managed entry is extended elsewhere."""

    value = _parse(raw)
    entry = _entry_from_document(value)
    expected = {
        "command": str(executable),
        "args": ["opc", "mcp", "--state", str(state)],
    }
    if entry != expected:
        raise ConfigConflictError("rendered clink_node entry is invalid")


def _plan_codex_config(
    config: Path,
    *,
    executable: Path,
    state_path: Path,
) -> _ConfigPlan:
    path = resolve_codex_config_path(config)
    _check_parent(path)
    executable = _validate_executable(executable)
    state = _absolute(state_path)
    snapshot = _snapshot(path)
    raw = snapshot.raw
    value = _parse(raw)
    text = raw.decode("utf-8")
    managed = _managed_span(text)
    desired = _render_block(executable, state)
    if managed is None:
        if _entry_from_document(value) is not None:
            raise ConfigConflictError(
                "existing clink_node entry conflicts with OPC setup"
            )
        separator = "" if not raw or raw.endswith((b"\n", b"\r")) else "\n"
        replacement = raw + separator.encode("ascii") + desired.encode("utf-8")
        _verify_rendered_entry(replacement, executable=executable, state=state)
        return _ConfigPlan(path, snapshot, replacement, True)

    start, finish, body = managed
    configured_command, configured_state = _validate_managed_entry(body)
    if configured_state != state:
        raise ConfigConflictError("managed clink_node entry uses a different state")
    # Validate the complete document even for a semantic no-op.  A hostile or
    # stale config can extend the same TOML table outside the marker block;
    # silently accepting that would violate the add-only boundary.
    _verify_rendered_entry(raw, executable=Path(configured_command), state=state)
    if configured_command == str(executable):
        return _ConfigPlan(path, snapshot, raw, False)
    replacement_text = text[:start] + desired + text[finish:]
    replacement = replacement_text.encode("utf-8")
    _verify_rendered_entry(replacement, executable=executable, state=state)
    return _ConfigPlan(path, snapshot, replacement, replacement != raw)


def _assert_unchanged(snapshot: _ConfigSnapshot, path: Path) -> None:
    current = _snapshot(path)
    if current.exists != snapshot.exists or current.fingerprint != snapshot.fingerprint:
        raise ConfigConflictError("Codex config changed during setup")


def _write_owner_only(path: Path, raw: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o600)


def _backup(path: Path, raw: bytes) -> Path:
    for _ in range(32):
        candidate = path.parent / f".{path.name}.clink-opc-backup-{secrets.token_hex(8)}"
        try:
            _write_owner_only(candidate, raw)
            return candidate
        except FileExistsError:
            continue
    raise OpcSetupError("cannot create an owner-only Codex config backup")


def _apply_plan(plan: _ConfigPlan) -> ConfigWriteResult:
    if not plan.changed:
        # Setup prepares the state after planning the config. Recheck even for
        # a semantic no-op so a concurrent edit cannot be silently accepted.
        _assert_unchanged(plan.snapshot, plan.path)
        return ConfigWriteResult(plan.path, False)
    _assert_unchanged(plan.snapshot, plan.path)
    temporary = plan.path.parent / f".{plan.path.name}.clink-opc-{secrets.token_hex(8)}.tmp"
    backup: Path | None = None
    try:
        _write_owner_only(temporary, plan.replacement)
        _assert_unchanged(plan.snapshot, plan.path)
        if plan.snapshot.exists:
            backup = _backup(plan.path, plan.snapshot.raw)
            try:
                _assert_unchanged(plan.snapshot, plan.path)
            except BaseException:
                backup.unlink(missing_ok=True)
                backup = None
                raise
        os.replace(temporary, plan.path)
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            descriptor = os.open(plan.path.parent, directory_flags)
        except OSError:
            descriptor = -1
        if descriptor >= 0:
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return ConfigWriteResult(plan.path, True, backup)


def write_codex_config(
    config: Path,
    *,
    executable: Path,
    state_path: Path,
) -> ConfigWriteResult:
    """Atomically append/update one marked, secret-free Codex entry."""

    return _apply_plan(
        _plan_codex_config(config, executable=executable, state_path=state_path)
    )


def _state_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def prepare_opc_state(
    state_path: Path,
    *,
    server: str | None = None,
    label: str | None = None,
    allow_loopback_http: bool = False,
) -> tuple[object, bool, Path]:
    """Create or load one state without performing any remote OPC action."""

    state = _absolute(state_path)
    kwargs: dict[str, object] = {"allow_loopback_http": allow_loopback_http}
    created = not _state_exists(state)
    if server is not None:
        kwargs["origin"] = server
    if label is not None:
        kwargs["label"] = label
    if created:
        kwargs.setdefault("origin", DEFAULT_OPC_ORIGIN)
        kwargs.setdefault("label", default_device_label())
    client = OpcClient(OpcClientStateStore(state), **kwargs)
    return client, created, state


def generic_stdio_configuration(executable: Path, state_path: Path) -> dict[str, Any]:
    """Return a JSON-safe, secret-free stdio recipe for generic hosts."""

    return {
        "command": str(_validate_executable(executable)),
        "args": ["opc", "mcp", "--state", str(_absolute(state_path))],
    }


def setup_opc(
    *,
    agent: str,
    state_path: Path,
    config_path: Path | None = None,
    server: str | None = None,
    label: str | None = None,
    executable: Path | None = None,
    allow_loopback_http: bool = False,
    output: Callable[[str], object] = print,
    error_output: Callable[[str], object] = lambda message: print(message, file=sys.stderr),
) -> int:
    """Prepare OPC state and optionally add one Codex MCP registration."""

    if agent not in {"codex", "generic"}:
        raise OpcSetupError("supported agents are codex and generic")
    state = _absolute(state_path)
    executable = _validate_executable(executable or resolve_installed_executable())
    plan: _ConfigPlan | None = None
    if agent == "codex":
        plan = _plan_codex_config(
            resolve_codex_config_path(config_path),
            executable=executable,
            state_path=state,
        )

    client, _, state = prepare_opc_state(
        state,
        server=server,
        label=label,
        allow_loopback_http=allow_loopback_http,
    )
    try:
        if agent == "codex":
            assert plan is not None
            try:
                result = _apply_plan(plan)
            except ConfigConflictError as error:
                raise ConfigConflictError(
                    f"{error}; state was preserved; rerun setup"
                ) from error
            action = "updated" if result.changed else "already configured"
            output(
                f"Codex clink_node MCP entry {action} in {result.path}. "
                f"State prepared at {state}. Reconnect or start a new Agent session, "
                "then ask it to connect the wallet."
            )
        else:
            output(json.dumps(generic_stdio_configuration(executable, state), sort_keys=True))
            error_output(
                "Copy this stdio configuration into your Agent host; it is not "
                "hot-added to an already running task. Reconnect before asking "
                "the Agent to connect the wallet."
            )
    finally:
        client.close()
    return 0


def choose_agent(
    input_fn: Callable[[str], str] | None = None,
    output: Callable[[str], object] = print,
) -> str | None:
    """Prompt for the two supported handoff modes; cancellation is safe."""

    output("Choose Agent setup: [1] Codex  [2] generic stdio  [q] cancel")
    output("Selection: ")
    try:
        # Keep the prompt on the injected output stream.  Calling input with a
        # prompt would write that prompt directly to stdout and corrupt the
        # generic setup JSON contract when the caller routes guidance to stderr.
        choice = (input if input_fn is None else input_fn)("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if choice in {"1", "codex", "c"}:
        return "codex"
    if choice in {"2", "generic", "g"}:
        return "generic"
    return None
