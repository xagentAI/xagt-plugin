from __future__ import annotations

import errno
import os
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathIdentity:
    device: int
    inode: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> "PathIdentity":
        return cls(device=metadata.st_dev, inode=metadata.st_ino)

    def matches(self, metadata: os.stat_result) -> bool:
        return (metadata.st_dev, metadata.st_ino) == (self.device, self.inode)


@dataclass(frozen=True)
class NodePathIdentity:
    home: PathIdentity
    data: PathIdentity
    runtime: PathIdentity
    logs: PathIdentity
    secrets: PathIdentity

    def validate_current(self, paths: "NodePaths") -> None:
        try:
            current_home = os.lstat(paths.home)
        except FileNotFoundError:
            raise PermissionError(
                f"Clink home disappeared: {paths.home}"
            ) from None
        _validate_private_directory(paths.home, current_home)
        if not self.home.matches(current_home):
            raise PermissionError(f"Clink home changed: {paths.home}")

        descriptor = _open_private_directory(paths.home, self.home)
        try:
            for directory, expected in (
                (paths.data, self.data),
                (paths.runtime, self.runtime),
                (paths.logs, self.logs),
                (paths.secrets, self.secrets),
            ):
                try:
                    metadata = os.stat(
                        directory.name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    raise PermissionError(
                        f"Clink directory disappeared: {directory}"
                    ) from None
                _validate_private_directory(directory, metadata)
                if not expected.matches(metadata):
                    raise PermissionError(
                        f"Clink directory changed: {directory}"
                    )
            final_home = os.lstat(paths.home)
            _validate_private_directory(paths.home, final_home)
            if not self.home.matches(final_home):
                raise PermissionError(f"Clink home changed: {paths.home}")
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class NodePaths:
    home: Path
    config: Path
    data: Path
    runtime: Path
    logs: Path
    secrets: Path

    @classmethod
    def from_home(cls, home: Path) -> "NodePaths":
        expanded = home.expanduser()
        absolute = Path(os.path.abspath(os.fspath(expanded)))
        # Canonicalize only the parent chain (for example macOS /var), while
        # preserving the final home component so a symlinked home is still
        # rejected by ensure() rather than silently followed.
        absolute = absolute.parent.resolve(strict=False) / absolute.name
        return cls(
            home=absolute,
            config=absolute / "config.toml",
            data=absolute / "data",
            runtime=absolute / "runtime",
            logs=absolute / "logs",
            secrets=absolute / "secrets",
        )

    @classmethod
    def discover(cls, env: dict[str, str] | None = None) -> "NodePaths":
        source = env if env is not None else os.environ
        configured = source.get("CLINK_HOME")
        home = Path(configured) if configured else Path.home() / ".clink"
        return cls.from_home(home)

    def ensure(self) -> NodePathIdentity:
        try:
            home_metadata = os.lstat(self.home)
        except FileNotFoundError:
            try:
                self.home.mkdir(mode=0o700, parents=True, exist_ok=False)
            except FileExistsError:
                pass
            home_metadata = os.lstat(self.home)
        _validate_private_directory(self.home, home_metadata)

        descriptor = _open_private_directory(
            self.home,
            PathIdentity.from_stat(home_metadata),
        )
        directories = (self.data, self.runtime, self.logs, self.secrets)
        identities: dict[str, PathIdentity] = {}
        missing: list[Path] = []
        try:
            # Preflight every existing child before creating any missing one.
            for directory in directories:
                try:
                    metadata = os.stat(
                        directory.name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    missing.append(directory)
                else:
                    _validate_private_directory(directory, metadata)
                    identities[directory.name] = PathIdentity.from_stat(metadata)

            for directory in missing:
                try:
                    os.mkdir(directory.name, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                metadata = os.stat(
                    directory.name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                _validate_private_directory(directory, metadata)
                identities[directory.name] = PathIdentity.from_stat(metadata)

            for directory in directories:
                metadata = os.stat(
                    directory.name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                _validate_private_directory(directory, metadata)
                if not identities[directory.name].matches(metadata):
                    raise PermissionError(
                        "Clink directory changed during validation: "
                        f"{directory}"
                    )

            current_home = os.lstat(self.home)
            _validate_private_directory(self.home, current_home)
            opened_home = os.fstat(descriptor)
            if not PathIdentity.from_stat(opened_home).matches(current_home):
                raise PermissionError(
                    f"Clink home changed during validation: {self.home}"
                )
            return NodePathIdentity(
                home=PathIdentity.from_stat(opened_home),
                data=identities[self.data.name],
                runtime=identities[self.runtime.name],
                logs=identities[self.logs.name],
                secrets=identities[self.secrets.name],
            )
        finally:
            os.close(descriptor)


def _open_private_directory(directory: Path, expected: PathIdentity) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise PermissionError(
                f"Clink directory must not be a symlink: {directory}"
            ) from None
        raise
    try:
        opened = os.fstat(descriptor)
        _validate_private_directory(directory, opened)
        if not expected.matches(opened):
            raise PermissionError(
                f"Clink directory changed during validation: {directory}"
            )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _validate_private_directory(
    directory: Path,
    metadata: os.stat_result,
) -> None:
    if stat.S_ISLNK(metadata.st_mode):
        raise PermissionError(
            f"Clink directory must not be a symlink: {directory}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"Clink path must be a directory: {directory}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"Clink directory owner must be uid {os.getuid()}: {directory}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        command = f"chmod 700 {shlex.quote(str(directory))}"
        raise PermissionError(
            f"Clink directory permissions must be 0700: {directory}; "
            f"run `{command}`"
        )
