"""Storage contract tests using SQLite and a narrow Workers binding substitute.

These tests exercise persistence/rollback/precision; workerd integration tests
separately verify actual Durable Object binding and concurrency semantics.
"""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import types
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from app.storage import IntegrityError, QuotaExceeded, StorageUnavailable, finalize_experiment
from support.storage import SQLiteTestStore

OWNER = "a" * 64
OTHER_OWNER = "b" * 64


class FakeRequest:
    def __init__(self, url, *, method="GET", body="", headers=None):
        self.url, self.method, self.body = url, method, body
        self.js_object = self

    async def text(self):
        return self.body


class FakeResponse:
    def __init__(self, body, **options):
        self.body = body

    async def text(self):
        return self.body


class FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx


class FakeCursor:
    def __init__(self, cursor):
        self.rows = cursor.fetchall()

    def raw(self):
        return self

    def toArray(self):
        return self.rows


class FakeSql:
    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.failed_chunk = None
        self.read_queries = []

    def exec(self, query, *bindings):
        if query.startswith("INSERT INTO chunks") and bindings[2] == self.failed_chunk:
            raise OSError("PRIVATE_DATABASE_DETAILS")
        if query.lstrip().startswith("CREATE TABLE"):
            self.con.executescript(query)
            return FakeCursor(self.con.execute("SELECT 1 WHERE 0"))
        if query.startswith("SELECT"):
            self.read_queries.append(query)
        return FakeCursor(self.con.execute(query, bindings))


class FakeStorage:
    def __init__(self):
        self.sql = FakeSql()

    def transactionSync(self, callback):
        with self.sql.con:
            return callback()


@pytest.fixture(scope="module")
def workers_module():
    fake = types.ModuleType("workers")
    fake.DurableObject, fake.Request, fake.Response = FakeDurableObject, FakeRequest, FakeResponse
    path = Path(__file__).resolve().parents[1] / "app" / "workers_storage.py"
    spec = importlib.util.spec_from_file_location("app._workers_storage_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"workers": fake}):
        spec.loader.exec_module(module)
    return module


class FakeNamespace:
    def __init__(self, module):
        self.module, self.objects, self.names = module, {}, []
        self.force_name = None

    def idFromName(self, name):
        self.names.append(name)
        return self.force_name or name

    def get(self, identifier):
        if identifier not in self.objects:
            ctx = types.SimpleNamespace(storage=FakeStorage())
            self.objects[identifier] = self.module.SessionStore(ctx, None)
        return self.objects[identifier]


@pytest.fixture
def setup_store(workers_module):
    namespace = FakeNamespace(workers_module)
    return workers_module.DurableStore(namespace, "secret" * 8), namespace


def record(identifier="e_1", start="2026-01-01T00:00:00Z", end="2026-01-02T00:00:00Z"):
    return {
        "experiment_id": identifier,
        "created_at": "2026-01-01T01:00:00Z",
        "config": {"start": start, "end": end},
        "provenance": {
            "baseline": {"name": "Baseline"},
            "candidate": {"name": "Candidate"},
            "exploration_reasons": [],
            "effective_mode": "declared_holdout",
        },
        "result": {"status": "facts_only", "precise_integer": 99999999999999999999999999999999},
    }


def test_utf8_chunking_roundtrips_every_boundary(workers_module):
    payload = "a研究💹" * 70000
    for size in (4, 5, 7, workers_module.CHUNK_BYTES):
        chunks = list(workers_module.utf8_chunks(payload, size))
        assert "".join(chunks) == payload
        assert all(0 < len(chunk.encode()) <= size for chunk in chunks)


def test_snapshot_roundtrip_preserves_precise_raw_values_and_owner(setup_store):
    store, namespace = setup_store
    curve = {"name": "研究", "equity": "0.123456789012345678901234567890123456789"}
    raw = {"equity": 999999999999999999999999999999999999999}

    async def run():
        snap = await store.snapshot(OWNER, curve, raw)
        assert (await store.get("snapshots", OWNER, snap["snapshot_id"]))["raw_curve"] == raw
        with pytest.raises(KeyError):
            await store.get("snapshots", OTHER_OWNER, snap["snapshot_id"])
        assert OWNER not in namespace.names[0]

    asyncio.run(run())


def test_large_payload_uses_chunks_and_history_reads_only_summary(setup_store, workers_module):
    store, namespace = setup_store
    payload = record()
    payload["result"]["large"] = "💹研究" * 100000

    async def run():
        saved = await store.save_experiment(OWNER, payload)
        assert await store.get("experiments", OWNER, "e_1") == saved
        obj = next(iter(namespace.objects.values()))
        sizes = obj.sql.con.execute("SELECT length(CAST(payload AS BLOB)) FROM chunks").fetchall()
        assert len(sizes) > 2
        assert all(size[0] <= workers_module.CHUNK_BYTES for size in sizes)
        obj.sql.read_queries.clear()
        history = await store.experiments(OWNER)
        assert history == [workers_module.history_summary(saved)]
        assert not any("FROM chunks" in query for query in obj.sql.read_queries)
        assert len(json.dumps(history)) < 1000

    asyncio.run(run())


def test_chunk_failure_rolls_back_index_and_all_chunks(setup_store):
    store, namespace = setup_store

    async def run():
        original = await store.snapshot(OWNER, {"equity": "100"})
        obj = next(iter(namespace.objects.values()))
        original_counts = obj.sql.con.execute("SELECT count(*) FROM records").fetchone()[0]
        obj.sql.failed_chunk = 1
        with pytest.raises(StorageUnavailable) as caught:
            await store.save_experiment(OWNER, {**record(), "padding": "x" * 600000})
        assert "PRIVATE_DATABASE_DETAILS" not in str(caught.value)
        assert obj.sql.con.execute("SELECT count(*) FROM records").fetchone()[0] == original_counts
        assert obj.sql.con.execute("SELECT count(*) FROM chunks WHERE kind='experiments'").fetchone()[0] == 0
        assert await store.get("snapshots", OWNER, original["snapshot_id"]) == original
        obj.sql.failed_chunk = None
        assert (await store.save_experiment(OWNER, record()))["experiment_id"] == "e_1"

    asyncio.run(run())


def test_quota_preserves_prior_records_and_is_per_record_kind(workers_module):
    namespace = FakeNamespace(workers_module)
    store = workers_module.DurableStore(namespace, "secret" * 8, limit=1)

    async def run():
        await store.snapshot(OWNER, {"equity": "100"})
        with pytest.raises(QuotaExceeded):
            await store.snapshot(OWNER, {"equity": "200"})
        first = await store.save_experiment(OWNER, record())
        with pytest.raises(QuotaExceeded):
            await store.save_experiment(OWNER, record("e_2"))
        assert await store.get("experiments", OWNER, "e_1") == first
        assert len(await store.experiments(OWNER)) == 1

    asyncio.run(run())


def test_duplicate_experiment_cannot_overwrite_original(setup_store):
    store, _ = setup_store

    async def run():
        saved = await store.save_experiment(OWNER, record())
        changed = record()
        changed["result"]["status"] = "different"
        with pytest.raises(StorageUnavailable):
            await store.save_experiment(OWNER, changed)
        assert await store.get("experiments", OWNER, "e_1") == saved

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["payload", "missing_chunk", "summary"])
def test_corrupt_records_are_not_returned(setup_store, corruption):
    store, namespace = setup_store

    async def run():
        await store.save_experiment(OWNER, record())
        obj = next(iter(namespace.objects.values()))
        if corruption == "summary":
            obj.sql.con.execute("UPDATE records SET summary='{}'")
        elif corruption == "missing_chunk":
            obj.sql.con.execute("DELETE FROM chunks")
        else:
            obj.sql.con.execute("UPDATE chunks SET payload='{}'")
        obj.sql.con.commit()
        with pytest.raises(IntegrityError):
            if corruption == "summary":
                await store.experiments(OWNER)
            else:
                await store.get("experiments", OWNER, "e_1")

    asyncio.run(run())


def test_misrouted_owner_is_rejected(setup_store):
    store, namespace = setup_store

    async def run():
        await store.snapshot(OWNER, {"equity": "100"})
        namespace.force_name = next(iter(namespace.objects))
        with pytest.raises(IntegrityError):
            await store.experiments(OTHER_OWNER)

    asyncio.run(run())


def test_health_uses_one_fixed_object_and_no_owner_binding(setup_store):
    store, namespace = setup_store

    async def run():
        for _ in range(4):
            assert await store.health()
        assert set(namespace.names) == {"storage-health-v1"}
        obj = next(iter(namespace.objects.values()))
        assert obj.sql.con.execute("SELECT count(*) FROM metadata").fetchone()[0] == 0

    asyncio.run(run())


@pytest.mark.parametrize("owner", ["a" * 63, "A" * 64, "f" * 65, "x" * 64, None, "../session"])
def test_invalid_owner_never_contacts_namespace(setup_store, owner):
    store, namespace = setup_store
    with pytest.raises(ValueError):
        asyncio.run(store.experiments(owner))
    assert namespace.names == []


def test_storage_outage_maps_to_sanitized_error(workers_module):
    namespace = FakeNamespace(workers_module)

    def fail(name):
        raise OSError("PRIVATE_NAMESPACE_LOCATION")

    namespace.idFromName = fail
    store = workers_module.DurableStore(namespace, "secret" * 8)
    with pytest.raises(StorageUnavailable) as caught:
        asyncio.run(store.health())
    assert "PRIVATE_NAMESPACE_LOCATION" not in str(caught.value)


@pytest.mark.parametrize(
    ("first_start", "first_end", "next_start", "next_end", "overlap"),
    [
        (
            "2026-01-01T00:00:00.500000Z",
            "2026-01-02T00:00:00.500000Z",
            "2026-01-02T00:00:00Z",
            "2026-01-03T00:00:00Z",
            True,
        ),
        (
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "2026-01-02T00:00:00.500000Z",
            "2026-01-03T00:00:00.500000Z",
            False,
        ),
        (
            "2026-01-01T00:00:00.500000Z",
            "2026-01-02T00:00:00.500000Z",
            "2026-01-02T00:00:00.500000+00:00",
            "2026-01-03T00:00:00.500000+00:00",
            False,
        ),
    ],
)
def test_history_classification_matches_transactional_fixture_and_preserves_input(
    tmp_path, setup_store, first_start, first_end, next_start, next_end, overlap
):
    remote, _ = setup_store
    local = SQLiteTestStore(tmp_path / "contract.sqlite3")
    first = record("e_1", first_start, first_end)
    second = record("e_2", next_start, next_end)
    untouched = deepcopy(second)
    expected_first = local.save_experiment(OWNER, first)
    expected_second = local.save_experiment(OWNER, second)

    async def run():
        assert await remote.save_experiment(OWNER, first) == expected_first
        actual = await remote.save_experiment(OWNER, second)
        assert actual == expected_second
        assert actual["provenance"]["effective_mode"] == (
            "historical_exploration" if overlap else "declared_holdout"
        )
        assert await remote.get("experiments", OWNER, "e_1") == expected_first

    asyncio.run(run())
    assert second == untouched
    assert local.health()


def test_non_history_exploration_reason_is_preserved():
    original = record()
    original["provenance"]["exploration_reasons"] = ["The researcher selected historical exploration."]
    result = finalize_experiment(original, [])
    assert result["provenance"]["effective_mode"] == "historical_exploration"
    assert result["provenance"]["exploration_reasons"] == original["provenance"]["exploration_reasons"]


def test_concurrent_submissions_enforce_quota_and_history_together(workers_module):
    namespace = FakeNamespace(workers_module)
    store = workers_module.DurableStore(namespace, "secret" * 8, limit=5)

    async def submit(index):
        try:
            return await store.save_experiment(OWNER, record(f"e_{index}"))
        except QuotaExceeded:
            return None

    async def run():
        submissions = await asyncio.gather(*(submit(index) for index in range(8)))
        accepted = [item for item in submissions if item is not None]
        assert len(accepted) == 5
        assert sum(item["provenance"]["effective_mode"] == "declared_holdout" for item in accepted) == 1
        assert sum(item["provenance"]["effective_mode"] == "historical_exploration" for item in accepted) == 4
        assert len(await store.experiments(OWNER)) == 5

    asyncio.run(run())


def test_internal_size_cap_rejects_before_write(setup_store, workers_module, monkeypatch):
    store, namespace = setup_store
    monkeypatch.setattr(workers_module, "MAX_PAYLOAD_BYTES", 500)
    with pytest.raises(QuotaExceeded):
        asyncio.run(store.snapshot(OWNER, {"padding": "x" * 1000}))
    obj = next(iter(namespace.objects.values()))
    assert obj.sql.con.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert obj.sql.con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
