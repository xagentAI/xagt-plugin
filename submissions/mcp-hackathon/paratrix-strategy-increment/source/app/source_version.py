"""Stable source identity shared by the local server and Cloudflare build."""

from __future__ import annotations

import hashlib
from pathlib import Path


_DEPLOYMENT_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "worker.py",
    "wrangler.jsonc",
    "workers/pyproject.toml",
    "workers/uv.lock",
    "workers/pylock.toml",
    "workers/package.json",
    "workers/package-lock.json",
    "scripts/build_worker.py",
)


def source_digest(root: Path) -> str:
    """Hash deployable application, assets, dependencies and build instructions.

    Generated bundles, developer tools and runtime data are deliberately outside
    this source tree fingerprint. Simulation payloads have their own integrity
    hashes in the fixture manifest and exported experiment evidence.
    """
    root = Path(root)
    paths = [
        *root.joinpath("app").rglob("*.py"),
        *root.joinpath("web").glob("*"),
        *(root / name for name in _DEPLOYMENT_INPUTS),
    ]
    value = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file() and "__pycache__" not in p.parts):
        value.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return value.hexdigest()
