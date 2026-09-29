from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


class UnsafeSQLitePath(PermissionError):
    """The SQLite database or one of its sidecar files is unsafe."""


def validate_sqlite_artifacts(path: Path) -> None:
    """Validate SQLite, WAL and SHM paths without following symlinks.

    A missing database is valid during first boot; its existing parent and any
    existing sidecars must still be private owner-only regular files.
    """

    database = Path(os.path.abspath(os.fspath(path)))
    _validate_private_parent(database.parent)
    for candidate in (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
    ):
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise UnsafeSQLitePath(
                f"SQLite path must not be a symlink: {candidate}"
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeSQLitePath(
                f"SQLite path must be a regular file: {candidate}"
            )
        if metadata.st_uid != os.getuid():
            raise UnsafeSQLitePath(
                f"SQLite path owner must be uid {os.getuid()}: {candidate}"
            )
        if metadata.st_nlink != 1:
            raise UnsafeSQLitePath(
                f"SQLite path must have exactly one link: {candidate}"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UnsafeSQLitePath(
                f"SQLite path permissions must be 0600: {candidate}"
            )


def prepare_sqlite_path(path: Path) -> None:
    """Create a new SQLite file owner-only, or validate an existing one."""

    database = Path(os.path.abspath(os.fspath(path)))
    _validate_private_parent(database.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(database, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR}:
            raise UnsafeSQLitePath(
                f"SQLite path must be a regular file: {database}"
            ) from None
        raise
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeSQLitePath(
                f"SQLite path must be a regular file: {database}"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UnsafeSQLitePath(
                f"SQLite path permissions must be 0600: {database}"
            )
        if metadata.st_nlink != 1 or metadata.st_uid != os.getuid():
            raise UnsafeSQLitePath(
                f"SQLite path owner/link contract failed: {database}"
            )
    finally:
        os.close(descriptor)
    validate_sqlite_artifacts(database)


def _validate_private_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
    except FileNotFoundError:
        raise UnsafeSQLitePath(
            f"SQLite parent directory does not exist: {parent}"
        ) from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeSQLitePath(
            f"SQLite parent must be a real directory: {parent}"
        )
    if metadata.st_uid != os.getuid():
        raise UnsafeSQLitePath(
            f"SQLite parent owner must be uid {os.getuid()}: {parent}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise UnsafeSQLitePath(
            f"SQLite parent permissions must be 0700: {parent}"
        )
