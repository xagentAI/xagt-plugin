"""HTTP behavior with asynchronous storage and an injected static-asset binding."""

import subprocess
import sys

from fastapi.testclient import TestClient

from app.evidence import reproduce
from app.storage import StorageUnavailable
from support.application import FixtureAssets, SOURCE, make_app
from support.storage import SQLiteTestStore


class AsyncStore:
    def __init__(self, path):
        self.local = SQLiteTestStore(path)
        self.secret = self.local.secret

    def __getattr__(self, name):
        async def invoke(*args, **kwargs):
            return getattr(self.local, name)(*args, **kwargs)

        return invoke


def test_async_storage_full_flow_and_session_boundary(tmp_path):
    app = make_app(
        store=AsyncStore(tmp_path / "async.sqlite3"),
        settings={"PUBLIC_ORIGIN": "https://research.example", "COOKIE_SECURE": "true"},
        source_hash="a" * 64,
    )
    with TestClient(app, base_url="https://research.example") as client:
        health = client.get("/health")
        assert health.json()["source_sha256"] == "a" * 64
        assert "Secure" in health.headers["set-cookie"]
        case = client.get("/v1/demo-cases/aimm-weight").json()
        pair = {}
        for side in ("baseline", "candidate"):
            response = client.post("/v1/data-snapshots", json={"curve": case[side]})
            assert response.status_code == 201
            pair[side + "_snapshot_id"] = response.json()["snapshot_id"]
        assert client.post("/v1/comparison-inputs/validate", json=pair).json()["comparable"]
        response = client.post("/v1/experiments", json=pair)
        assert response.status_code == 201
        record = response.json()
        assert reproduce(client.get(record["evidence_url"]).json())["verified"]
        assert len(client.get("/v1/experiments").json()["experiments"]) == 1
        assert (
            client.post(
                "/v1/experiments", json=pair, headers={"Origin": "https://attacker.example"}
            ).status_code
            == 403
        )
        with TestClient(app, base_url="https://research.example") as other:
            assert other.get(record["evidence_url"]).status_code == 404


def test_worker_assets_are_allowlisted_and_use_security_headers(tmp_path):
    assets = FixtureAssets()
    app = make_app(tmp_path / "local.sqlite3", assets=assets)
    with TestClient(app) as client:
        for path in ("/", "/static/app.js", "/static/styles.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert client.get("/static/README.md").status_code == 404
        assert client.get("/static/unknown.py").status_code == 404
    assert assets.requests == [
        "https://assets.internal/index.html",
        "https://assets.internal/app.js",
        "https://assets.internal/styles.css",
    ]


def test_remote_storage_failure_is_sanitized(tmp_path):
    store = AsyncStore(tmp_path / "async.sqlite3")

    async def fail():
        raise StorageUnavailable("private storage details")

    store.health = fail
    with TestClient(make_app(store=store)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "storage_unavailable"
        assert "private storage details" not in response.text


def test_http_factory_requires_explicit_bindings_without_creating_storage(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from app.main import create_app; create_app()",
            str(SOURCE),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "TypeError: create_app() missing" in result.stderr
    assert list(tmp_path.iterdir()) == []
