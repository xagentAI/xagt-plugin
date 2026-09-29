from __future__ import annotations

import errno
import fcntl
import json
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .paths import NodePaths


class LifecycleLockBusy(RuntimeError):
    """Another lifecycle mutation is in progress."""


class ServiceLifecycleError(RuntimeError):
    """A service lifecycle operation is unsafe or unavailable."""


class SystemdController(Protocol):
    def daemon_reload(self) -> None: ...

    def start(self, unit: str) -> None: ...

    def stop(self, unit: str) -> None: ...

    def is_active(self, unit: str) -> bool: ...


class SubprocessSystemd:
    def _run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["systemctl", "--user", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def daemon_reload(self) -> None:
        self._run("daemon-reload")

    def start(self, unit: str) -> None:
        self._run("start", unit)

    def stop(self, unit: str) -> None:
        self._run("stop", unit)

    def is_active(self, unit: str) -> bool:
        result = self._run("is-active", unit, check=False)
        return result.returncode == 0 and result.stdout.strip() == "active"


class LifecycleLock:
    """A shared/exclusive process-wide lock for lifecycle mutations."""

    def __init__(
        self,
        path: Path,
        *,
        exclusive: bool,
        blocking: bool = True,
    ) -> None:
        self.path = Path(path)
        self.exclusive = exclusive
        self.blocking = blocking
        self._descriptor: int | None = None

    def acquire(self) -> "LifecycleLock":
        if self._descriptor is not None:
            raise LifecycleLockBusy("lifecycle lock is already acquired")
        _validate_parent(self.path.parent)
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR}:
                raise ServiceLifecycleError(
                    f"lifecycle lock must be a regular file: {self.path}"
                ) from None
            raise
        try:
            metadata = os.fstat(descriptor)
            _validate_lock_file(self.path, metadata)
            operation = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
            if not self.blocking:
                operation |= fcntl.LOCK_NB
            try:
                fcntl.flock(descriptor, operation)
            except BlockingIOError:
                raise LifecycleLockBusy(
                    "another lifecycle operation is in progress"
                ) from None
            self._descriptor = descriptor
            return self
        except Exception:
            os.close(descriptor)
            raise

    def release(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "LifecycleLock":
        return self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()


@dataclass(frozen=True)
class ServiceStatus:
    active: bool
    mode: str
    detail: str


class ServiceManager:
    """Coordinate quiesce, systemd and detached Node lifecycle operations."""

    unit_name = "clink-node.service"
    quiesce_name = "maintenance.quiesced"

    def __init__(
        self,
        paths: NodePaths,
        *,
        systemd: SystemdController | None = None,
        detached_runner: Callable[[], object] | None = None,
        unit_source: Path | None = None,
    ) -> None:
        self.paths = paths
        self.systemd = systemd or SubprocessSystemd()
        self.detached_runner = detached_runner or self._default_detached_runner
        self.unit_source = unit_source or (
            Path(__file__).resolve().parents[3]
            / "packaging/linux/systemd/clink.service"
        )

    @property
    def lifecycle_path(self) -> Path:
        return self.paths.runtime / "lifecycle.lock"

    @property
    def quiesce_path(self) -> Path:
        return self.paths.runtime / self.quiesce_name

    def quiesce(self, *, reason: str = "maintenance") -> None:
        try:
            lock = LifecycleLock(
                self.lifecycle_path,
                exclusive=True,
                blocking=False,
            ).acquire()
        except LifecycleLockBusy:
            raise ServiceLifecycleError(
                "Node is running; stop it before maintenance"
            ) from None
        try:
            payload = json.dumps(
                {"reason": reason, "pid": os.getpid()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _atomic_private_write(self.quiesce_path, payload)
        finally:
            lock.release()

    def resume(self) -> None:
        with self._exclusive_lock(blocking=False):
            _remove_private_file(self.quiesce_path)

    def is_quiesced(self) -> bool:
        try:
            metadata = os.lstat(self.quiesce_path)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ServiceLifecycleError(
                f"quiesce sentinel must be a regular file: {self.quiesce_path}"
            )
        if (
            metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ServiceLifecycleError(
                f"quiesce sentinel must be owner-only: {self.quiesce_path}"
            )
        return True

    def ensure_not_quiesced(self) -> None:
        if self.is_quiesced():
            raise ServiceLifecycleError("Node is quiesced for maintenance")

    def install_unit(self, target: Path) -> Path:
        with self._exclusive_lock(blocking=False):
            if self.unit_source is None:
                raise ServiceLifecycleError("systemd unit source is unavailable")
            try:
                content = self.unit_source.read_bytes()
            except OSError as exc:
                raise ServiceLifecycleError("cannot read systemd unit") from exc
            target = Path(target)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _atomic_private_write(target, content, mode=0o644)
            # Installation intentionally does not enable or start the unit.
            return target

    def start(self, *, detach: bool = False, systemd: bool = False) -> None:
        if detach and systemd:
            raise ServiceLifecycleError(
                "detached and systemd service modes are mutually exclusive"
            )
        try:
            lock = self._exclusive_lock(blocking=False)
            lock.__enter__()
        except LifecycleLockBusy:
            raise ServiceLifecycleError(
                "Node is running; stop it before starting a service"
            ) from None
        try:
            self.ensure_not_quiesced()
            if systemd:
                self.systemd.start(self.unit_name)
            elif detach:
                self.detached_runner()
            else:
                raise ServiceLifecycleError(
                    "choose detached or systemd service mode"
                )
        finally:
            lock.__exit__(None, None, None)

    def stop(self, *, systemd: bool = False) -> None:
        if not systemd:
            raise ServiceLifecycleError("detached stop is owned by clink stop")
        # A running Node owns the shared lifecycle lock. Ask systemd to stop
        # it before taking the exclusive lock, otherwise stop would deadlock
        # behind the process it is supposed to terminate.
        self.systemd.stop(self.unit_name)
        with self._exclusive_lock(blocking=False):
            return

    def status(self, *, systemd: bool = False) -> ServiceStatus:
        with LifecycleLock(
            self.lifecycle_path,
            exclusive=False,
            blocking=True,
        ):
            if systemd:
                active = self.systemd.is_active(self.unit_name)
                return ServiceStatus(
                    active=active,
                    mode="systemd",
                    detail="active" if active else "inactive",
                )
            return ServiceStatus(
                active=False,
                mode="detached",
                detail="use clink status for detached pid state",
            )

    def uninstall(self, target: Path) -> None:
        with self._exclusive_lock(blocking=False):
            _remove_private_file(Path(target))
            # No enable/disable/start/stop command is implicit in uninstall.

    @contextmanager
    def _exclusive_lock(self, *, blocking: bool = True) -> Iterator[LifecycleLock]:
        with LifecycleLock(
            self.lifecycle_path,
            exclusive=True,
            blocking=blocking,
        ) as lock:
            yield lock

    def _default_detached_runner(self) -> object:
        return subprocess.Popen(
            [sys.executable, "-m", "clink_node", "_run"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )


def _validate_parent(parent: Path) -> None:
    metadata = os.lstat(parent)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ServiceLifecycleError(
            f"lifecycle directory must be a real directory: {parent}"
        )
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ServiceLifecycleError(
            f"lifecycle directory must be owner-only: {parent}"
        )


def _validate_lock_file(path: Path, metadata: os.stat_result) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ServiceLifecycleError(
            f"lifecycle lock must be owner-only: {path}"
        )


def _atomic_private_write(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    _validate_parent(path.parent)
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{os.urandom(6).hex()}"
    )
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temporary, flags, mode)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _remove_private_file(path: Path) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ServiceLifecycleError(f"refusing to remove unsafe path: {path}")
    if (
        metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in {0o600, 0o644}
    ):
        raise ServiceLifecycleError(f"refusing to remove foreign path: {path}")
    path.unlink()
