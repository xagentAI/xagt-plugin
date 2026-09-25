"""Release identity, fixture integrity, and preservation of local Worker state."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_worker.py"
_spec = importlib.util.spec_from_file_location("build_worker", SCRIPT)
worker_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_build)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "engine.py").write_text("answer = 42\n")
    (root / "app" / "source_version.py").write_bytes(
        (SCRIPT.parents[1] / "app" / "source_version.py").read_bytes()
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "build_worker.py").write_bytes(SCRIPT.read_bytes())
    (root / "web").mkdir()
    (root / "web" / "index.html").write_text("<p>Research</p>")
    (root / "pyproject.toml").write_text("[project]\n")
    (root / "uv.lock").write_text("version = 1\n")
    (root / "worker.py").write_text("# entrypoint\n")
    (root / "workers").mkdir()
    for name in worker_build.TOOLCHAIN_FILES:
        (root / "workers" / name).write_text("{}\n" if name.endswith("json") else "# pinned\n")
    (root / "wrangler.jsonc").write_text(
        json.dumps({"main": "runtime/worker-bundle/worker.py", "assets": {"directory": "web"}})
    )
    fixtures = root / "fixtures" / "recorded" / "aimm"
    fixtures.mkdir(parents=True)
    raw = b'{"ts": 0, "equity": 10000}\n'
    (fixtures / "example.jsonl").write_bytes(raw)
    (fixtures / "manifest.json").write_text(
        json.dumps({"cases": [{"file": "example.jsonl", "sha256": hashlib.sha256(raw).hexdigest()}]})
    )
    return root


def test_bundle_preserves_exact_fixture_bytes_and_local_state(source):
    result = worker_build.build(source)
    bundle = Path(result["output"])
    config = json.loads((bundle / "wrangler.jsonc").read_text())
    entry = bundle / config["main"]
    assert entry.is_file()
    # Wrangler discovers Python modules relative to the entrypoint; keeping
    # tooling and local state out prevents them from entering the upload.
    assert {path.name for path in entry.parent.iterdir()} == {"app", "worker.py"}
    assert entry.parent != bundle
    namespace = {}
    exec((bundle / "src" / "app" / "_worker_build.py").read_text(), namespace)
    assert namespace["REVIEW_COMMIT"] == ""
    original = source / "fixtures" / "recorded" / "aimm" / "example.jsonl"
    assert namespace["FIXTURE_BYTES"]["example.jsonl"] == original.read_bytes()
    assert not (bundle / "runtime").exists()
    assets = bundle / config["assets"]["directory"]
    assert assets.parent == bundle
    assert (assets / "index.html").read_bytes() == (source / "web" / "index.html").read_bytes()
    secret = (bundle / ".dev.vars").read_bytes()
    assert (bundle / ".dev.vars").stat().st_mode & 0o777 == 0o600
    state = bundle / ".wrangler" / "state"
    state.mkdir(parents=True)
    (state / "saved").write_text("existing sessions")
    (bundle / "src" / "app" / "removed_module.py").write_text("# stale generated file")
    (assets / "removed.html").write_text("stale generated asset")
    worker_build.build(source)
    assert (bundle / ".dev.vars").read_bytes() == secret
    assert (state / "saved").read_text() == "existing sessions"
    assert not (bundle / "src" / "app" / "removed_module.py").exists()
    assert not (assets / "removed.html").exists()
    assert "SESSION_SECRET" not in (bundle / "wrangler.jsonc").read_text()


def test_bundle_keeps_python_and_assets_together_until_explicit_rebuild(source):
    first = worker_build.build(source)
    bundle = Path(first["output"])
    original_code = (bundle / "src" / "app" / "engine.py").read_text()
    original_html = (bundle / "assets" / "index.html").read_text()
    (source / "app" / "engine.py").write_text("answer = 43\n")
    (source / "web" / "index.html").write_text("<p>Updated research</p>")

    assert (bundle / "src" / "app" / "engine.py").read_text() == original_code
    assert (bundle / "assets" / "index.html").read_text() == original_html
    assert worker_build.source_digest(source) != first["source_sha256"]

    second = worker_build.build(source)
    assert (bundle / "src" / "app" / "engine.py").read_text() == "answer = 43\n"
    assert (bundle / "assets" / "index.html").read_text() == "<p>Updated research</p>"
    namespace = {}
    exec((bundle / "src" / "app" / "_worker_build.py").read_text(), namespace)
    assert namespace["SOURCE_HASH"] == second["source_sha256"]
    assert second["source_sha256"] != first["source_sha256"]


@pytest.mark.parametrize("broken", ["content", "traversal"])
def test_untrusted_or_changed_fixture_rejected_before_output(source, broken):
    directory = source / "fixtures" / "recorded" / "aimm"
    if broken == "content":
        (directory / "example.jsonl").write_text("changed")
    else:
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["cases"][0]["file"] = "../example.jsonl"
        (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        worker_build.build(source)
    assert not (source / "runtime").exists()


def test_production_requires_https_and_committed_source(source):
    with pytest.raises(ValueError, match="HTTPS"):
        worker_build.build(source, release=True, origin="http://example.com")
    with pytest.raises(ValueError, match="Git checkout"):
        worker_build.build(source, release=True, origin="https://example.com")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-qm",
            "test root",
        ],
        cwd=source,
        check=True,
    )
    with pytest.raises(ValueError, match="clean Git"):
        worker_build.build(source, release=True, origin="https://example.com")
    assert not (source / "runtime").exists()


@pytest.mark.parametrize("origin", [
    "https://example.com:garbage", "https://example.com:999999",
    "https://exa mple.com", "https://example.com\n",
])
def test_invalid_origin_rejected_before_creating_a_bundle(source, origin):
    with pytest.raises(ValueError):
        worker_build.build(source, origin=origin)
    assert not (source / "runtime").exists()


@pytest.mark.parametrize(
    "relative",
    [
        "app/engine.py",
        "web/index.html",
        "worker.py",
        "wrangler.jsonc",
        "workers/pyproject.toml",
        "workers/uv.lock",
        "workers/pylock.toml",
        "workers/package.json",
        "workers/package-lock.json",
        "scripts/build_worker.py",
    ],
)
def test_deployment_changes_change_source_identity(source, relative):
    before = worker_build.source_digest(source)
    path = source / relative
    path.write_bytes(path.read_bytes() + b"\n")
    assert worker_build.source_digest(source) != before


def test_generated_runtime_data_does_not_change_source_identity(source):
    before = worker_build.source_digest(source)
    worker_build.build(source)
    assert worker_build.source_digest(source) == before
