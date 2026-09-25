"""Create a clean review copy; this does not replace official submission validation."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

PROJECT = Path(__file__).resolve().parents[2]
MAX_FILES = 2000
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    "runtime",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".git",
    "coverage",
    "htmlcov",
    ".venv-workers",
    ".wrangler",
    "python_modules",
}
EXCLUDED_FILES = {".coverage", ".DS_Store"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".log"}
SECRET_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
# Match the official validator's baseline patterns. This is not a complete secret detector.
SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    )
)


class PackageError(ValueError):
    """The local review package failed a preparation check."""


def release_manifest(project, files):
    """Bind the review artifact to clean source without a self-referential commit."""
    config = next((content for path, content in files if path == Path("submission-config.json")), None)
    if config is None:
        return None
    if any(path == Path("submission.json") for path, _ in files):
        raise PackageError("generate the review manifest from the source repository, not a review copy")
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=project, text=True, stderr=subprocess.PIPE
        ).strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project, text=True, stderr=subprocess.PIPE
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=project, text=True,
            stderr=subprocess.PIPE,
        )
        manifest = json.loads(config)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise PackageError("review metadata requires a valid configuration and Git checkout") from exc
    if Path(root).resolve() != project or dirty.strip() or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PackageError("review metadata requires a clean source repository with a committed release")
    if not isinstance(manifest, dict) or "reviewCommit" in manifest:
        raise PackageError("submission configuration must omit the generated reviewCommit")
    manifest["reviewCommit"] = commit
    return (json.dumps(manifest, indent=2) + "\n").encode()


def _read_checked(path, relative):
    """Read a bounded regular file once so scanning and copying use the same bytes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise PackageError(f"non-regular files are not allowed: {relative}")
        if metadata.st_size > MAX_FILE_BYTES:
            raise PackageError(f"a source file exceeds 5MiB: {relative}")
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise PackageError(f"a source file exceeds 5MiB: {relative}")
    text = content.decode("utf-8", errors="replace")
    if text.startswith("version https://git-lfs.github.com/spec/v1"):
        raise PackageError(f"Git LFS pointers are not review source: {relative}")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise PackageError(f"possible secret detected: {relative}")
    return content


def _collect(project):
    files = []
    total = 0

    def walk(directory):
        nonlocal total
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(project)
            # Generated trees are intentionally absent from the review copy, including
            # their environment symlinks. Every included path is checked below.
            if path.name in EXCLUDED_DIRS and (path.is_dir() or path.is_symlink()):
                continue
            if path.is_symlink():
                raise PackageError(f"source package cannot contain symlinks: {relative}")
            if path.is_dir():
                walk(path)
                continue
            name = path.name.lower()
            if (
                (name.startswith(".env") and name != ".env.example")
                or name.startswith(".dev.vars")
                or path.suffix.lower() in SECRET_SUFFIXES
            ):
                raise PackageError(f"secret-bearing file type is not allowed: {relative}")
            if path.name in EXCLUDED_FILES or path.suffix.lower() in GENERATED_SUFFIXES:
                continue
            content = _read_checked(path, relative)
            total += len(content)
            if len(files) + 1 > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise PackageError("package exceeds submission limits")
            files.append((relative, content))

    walk(project)
    if not files:
        raise PackageError("source package is empty")
    return files, total


def package_submission(destination, *, project=PROJECT):
    """Copy one project without overwriting a destination or leaving a failed package."""
    project = Path(project)
    requested_target = Path(destination)
    if project.is_symlink() or not project.is_dir():
        raise PackageError("project must be a real directory")
    project = project.resolve()
    if requested_target.is_symlink():
        raise PackageError("destination must not be a symlink")
    target = requested_target.resolve()
    if target.exists() or target == project or project in target.parents:
        raise PackageError("destination must not exist and must be outside the project")
    files, total = _collect(project)
    manifest = release_manifest(project, files)
    if manifest is not None:
        metadata = json.loads(manifest)
        binding = (
            "\n## Release identity\n\n"
            f"Review commit: `{metadata['reviewCommit']}`\n\n"
            "The deployment health and proof endpoints must report this exact source revision.\n"
        ).encode()
        for index, (relative, content) in enumerate(files):
            if relative == Path("SUBMISSION.md"):
                if len(content) + len(binding) > MAX_FILE_BYTES:
                    raise PackageError("a source file exceeds 5MiB: SUBMISSION.md")
                files[index] = (relative, content + binding)
                total += len(binding)
        files.append((Path("submission.json"), manifest))
        total += len(manifest)
        if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES or len(manifest) > MAX_FILE_BYTES:
            raise PackageError("package exceeds submission limits")
    # Reserve after validation, then remove only our own directory if a write fails.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        for relative, content in files:
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
    except BaseException:
        shutil.rmtree(target)
        raise
    return {"files": len(files), "bytes": total, "destination": str(target)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, help="A new directory outside this project")
    args = parser.parse_args()
    try:
        result = package_submission(args.destination)
    except (PackageError, OSError) as exc:
        parser.error(str(exc))
    print(f"Clean review copy: {result['files']} files, {result['bytes']} bytes -> {result['destination']}")
    print("This is a local copy, not a published or officially validated submission.")


if __name__ == "__main__":
    main()
