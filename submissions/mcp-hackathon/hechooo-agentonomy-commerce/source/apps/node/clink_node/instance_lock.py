from __future__ import annotations

import errno
import fcntl
import os
import stat
from pathlib import Path


class InstanceLockError(RuntimeError):
    """The local Node already owns its process-level lock."""


class InstanceLock:
    """An owner-only, no-follow advisory lock for one Node instance."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._descriptor: int | None = None
        self._identity: tuple[int, int] | None = None

    def acquire(self) -> "InstanceLock":
        if self._descriptor is not None:
            raise InstanceLockError("instance lock is already acquired")
        _validate_parent(self.path.parent)
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR}:
                raise PermissionError(
                    f"instance lock must be a regular file: {self.path}"
                ) from None
            raise
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PermissionError(
                    f"instance lock must be a regular file: {self.path}"
                )
            if metadata.st_uid != os.getuid():
                raise PermissionError(
                    f"instance lock owner must be uid {os.getuid()}: "
                    f"{self.path}"
                )
            if metadata.st_nlink != 1:
                raise PermissionError(
                    f"instance lock must have exactly one link: {self.path}"
                )
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise PermissionError(
                    f"instance lock permissions must be 0600: {self.path}"
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstanceLockError(
                    "another Clink Node instance is already running"
                ) from None
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
            self._descriptor = descriptor
            self._identity = (metadata.st_dev, metadata.st_ino)
            return self
        except Exception:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)
            raise

    def release(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        self._identity = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()


def _validate_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"instance lock directory does not exist: {parent}"
        ) from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(
            f"instance lock directory must be a real directory: {parent}"
        )
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"instance lock directory owner must be uid {os.getuid()}: "
            f"{parent}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PermissionError(
            f"instance lock directory permissions must be 0700: {parent}"
        )
