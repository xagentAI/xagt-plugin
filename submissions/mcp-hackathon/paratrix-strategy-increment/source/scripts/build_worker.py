#!/usr/bin/env python3
"""Build an isolated, pinned Python Worker project without accessing Cloudflare.

Local:   python scripts/build_worker.py
Release: python scripts/build_worker.py --release --public-origin https://example.workers.dev
Then:    cd runtime/worker-bundle && npm ci && uv run --locked pywrangler dev
Use ``pywrangler deploy`` only after configuring the production SESSION_SECRET.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.source_version import source_digest  # noqa: E402


TOOLCHAIN_FILES = ("pyproject.toml", "uv.lock", "pylock.toml", "package.json", "package-lock.json")


def release_commit(source: Path) -> str:
    """Never label uncommitted source with an unrelated published commit."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True, stderr=subprocess.PIPE
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=source,
            text=True,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Release build requires a Git checkout with an existing commit") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or dirty.strip():
        raise ValueError("Release build requires a clean Git checkout; commit reviewed changes first")
    return commit


def public_origin(value: str, *, release: bool) -> str:
    if not value and not release:
        return "http://127.0.0.1:8787"
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ({"https"} if release else {"http", "https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("PUBLIC_ORIGIN must be a complete HTTPS origin for release builds")
    return value.rstrip("/")


def recorded_fixtures(source: Path) -> dict[str, bytes]:
    directory = source / "fixtures" / "recorded" / "aimm"
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    files = {"manifest.json": manifest_raw}
    for row in manifest["cases"]:
        name = row["file"]
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".jsonl"):
            raise ValueError("Recorded fixture manifest contains an unsafe filename")
        path = directory / name
        if path.is_symlink():
            raise ValueError("Recorded fixtures must be ordinary reviewed files")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError(f"Recorded fixture integrity check failed: {name}")
        files[name] = raw
    return files


def build(source: Path, *, release: bool = False, origin: str = "") -> dict:
    source = source.resolve()
    origin = public_origin(origin, release=release)
    commit = release_commit(source) if release else ""
    digest = source_digest(source)
    fixtures = recorded_fixtures(source)
    output = source / "runtime" / "worker-bundle"
    # Rebuild only generated files, preserving Wrangler's local Durable Object
    # state, dependency caches, and the local-only signing secret between runs.
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Worker build output must not be a symbolic link")
    output.mkdir(parents=True, exist_ok=True)
    code_output = output / "src"
    app_output = code_output / "app"
    if code_output.is_symlink() or app_output.is_symlink():
        raise ValueError("Worker application output must not be a symbolic link")
    if app_output.exists():
        shutil.rmtree(app_output)
    for path in sorted((source / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        target = code_output / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    generated = [
        '"""Generated from reviewed source; rebuild with scripts/build_worker.py."""',
        f"SOURCE_HASH = {digest!r}",
        f"REVIEW_COMMIT = {commit!r}",
        "FIXTURE_BYTES = {",
        *(f"    {name!r}: {raw!r}," for name, raw in sorted(fixtures.items())),
        "}",
        "",
    ]
    (app_output / "_worker_build.py").write_text("\n".join(generated), encoding="utf-8")
    shutil.copyfile(source / "worker.py", code_output / "worker.py")
    for name in TOOLCHAIN_FILES:
        shutil.copyfile(source / "workers" / name, output / name)
    config = json.loads((source / "wrangler.jsonc").read_text(encoding="utf-8"))
    config["main"] = "src/worker.py"
    config["assets"]["directory"] = "../../web"
    config.setdefault("vars", {}).update(
        PUBLIC_ORIGIN=origin, COOKIE_SECURE="true" if release or origin.startswith("https:") else "false"
    )
    (output / "wrangler.jsonc").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if not release:
        secret_path = output / ".dev.vars"
        if not secret_path.exists():
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(f'SESSION_SECRET="{secrets.token_hex(32)}"\n')
    result = {
        "output": str(output),
        "source_sha256": digest,
        "review_commit": commit or None,
        "public_origin": origin,
        "mode": "release" if release else "local",
        "fixture_files": sorted(fixtures),
    }
    (output / "build-info.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release", action="store_true", help="Require clean Git source and a public HTTPS origin"
    )
    parser.add_argument("--public-origin", default=os.environ.get("PUBLIC_ORIGIN", ""))
    args = parser.parse_args()
    try:
        result = build(Path(__file__).resolve().parents[1], release=args.release, origin=args.public_origin)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Worker build failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
