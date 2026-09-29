"""Zero-body enforcement and concurrent idempotent storage for the Chaos Lab."""

import sqlite3
import threading
import warnings
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, SAWarning
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.api.outcomes import _require_empty_lab_body
from app.core.config import _parse_max_lab_receipts
from app.main import app
from app.models.db import Base, OutcomeLabReceiptRow, OutcomeReceiptRow
from app.services import outcomes
from app.services.outcomes import (
    LabStorageUnavailable,
    LabWriteConflict,
    _is_transient_lab_lock_error,
    _serialize_postgres_lab_retention,
)

client = TestClient(app)

EXPECTED_IDS = (
    "consensus-success",
    "provider-disagreement",
    "schema-invalid",
    "upstream-failure",
    "over-budget",
    "origin-convergence",
)

SAFE_DETAIL = {"detail": "Lab scenarios accept no request body"}


class _FakeLabRequest:
    """Minimal stand-in exposing only what the zero-body gate may touch."""

    def __init__(self, headers, chunks=()):
        self.headers = headers
        self._chunks = list(chunks)
        self.consumed = 0

    async def stream(self):
        for chunk in self._chunks:
            self.consumed += 1
            yield chunk


def _production_rows():
    db = Session(outcomes.engine)
    try:
        return {row.id: row.receipt_json for row in db.query(OutcomeReceiptRow).all()}
    finally:
        db.close()


def _lab_rows():
    db = Session(outcomes.engine)
    try:
        return {row.id: row.receipt_json for row in db.query(OutcomeLabReceiptRow).all()}
    finally:
        db.close()


# --- Finding 1: exact zero-byte contract ------------------------------------


@pytest.mark.parametrize("body", [
    b" ",
    b"\n\t",
    b"{}",
    b'{"expected_verdict": "VERIFIED"}',
    b"\x00\x01\x02\xff",
    b'{"urls": ["https://evil.example/quote"], "responses": [1]}',
    b'{"timing": {"created_at": "2000-01-01T00:00:00Z", "latency_ms": 9999}',
    b"x" * 1024,
])
def test_nonempty_bodies_return_same_safe_400(body):
    before_lab, before_prod = _lab_rows(), _production_rows()
    response = client.post("/api/outcomes/lab/consensus-success", content=body)
    assert response.status_code == 400
    assert response.json() == SAFE_DETAIL
    assert _lab_rows() == before_lab
    assert _production_rows() == before_prod


def test_empty_body_runs_normally():
    assert client.post("/api/outcomes/lab/consensus-success").status_code == 200
    assert client.post("/api/outcomes/lab/consensus-success", content=b"").status_code == 200
    body = client.post("/api/outcomes/lab/consensus-success").json()
    assert body["passed"] is True


@pytest.mark.asyncio
async def test_content_length_rejected_without_reading_stream():
    touched = []

    class _Untouchable(_FakeLabRequest):
        async def stream(self):
            touched.append(1)
            yield b"must never be read"
            raise AssertionError("body stream must not be touched")

    request = _Untouchable(Headers({"content-length": "2000000"}))
    with pytest.raises(Exception) as excinfo:
        await _require_empty_lab_body(request)
    assert getattr(excinfo.value, "status_code", None) == 400
    assert touched == []


@pytest.mark.asyncio
async def test_chunked_stream_rejected_after_first_chunk_without_buffering():
    first = b"x" * (2 * 1024 * 1024)
    request = _FakeLabRequest(Headers({"transfer-encoding": "chunked"}), [first, b"y" * 1024, b"z"])
    with pytest.raises(Exception) as excinfo:
        await _require_empty_lab_body(request)
    assert getattr(excinfo.value, "status_code", None) == 400
    assert request.consumed == 1


@pytest.mark.asyncio
async def test_missing_length_empty_stream_passes():
    request = _FakeLabRequest(Headers({}), [])
    await _require_empty_lab_body(request)
    assert request.consumed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [["1", "1"], ["0", "0"], ["abc"], ["-1"], [""], ["12x"], [" 5 "]])
async def test_malformed_content_length_fails_closed(values):
    # Duplicates, non-numeric, negative, empty, and nonzero lengths all reject.
    request = _FakeLabRequest(Headers(raw=[(b"content-length", value.encode()) for value in values]), [])
    with pytest.raises(Exception) as excinfo:
        await _require_empty_lab_body(request)
    assert getattr(excinfo.value, "status_code", None) == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [["0"], ["00"], [" 0 "]])
async def test_zero_content_length_passes_without_reading(values):
    request = _FakeLabRequest(Headers(raw=[(b"content-length", value.encode()) for value in values]), [b"late"])
    await _require_empty_lab_body(request)
    assert request.consumed == 0


def test_chunked_multimegabyte_body_rejected():
    def _stream():
        yield b"q" * (1024 * 1024)
        yield b"q" * (1024 * 1024)

    response = client.post("/api/outcomes/lab/consensus-success", content=_stream())
    assert response.status_code == 400
    assert response.json() == SAFE_DETAIL


@pytest.mark.parametrize("headers,body", [
    ({"transfer-encoding": "chunked", "content-length": "5"}, b"hello"),
    ({"transfer-encoding": "chunked", "content-length": "0"}, b""),
    ([("transfer-encoding", "chunked"), ("content-length", "5"), ("content-length", "5")], b"hello"),
    ({"transfer-encoding": "xchunkedx", "content-length": "5"}, b"hello"),
    ({"transfer-encoding": "gzip"}, b""),
    ({"transfer-encoding": "gzip, chunked"}, b""),
    ({"transfer-encoding": "chunked, gzip"}, b""),
    ([("transfer-encoding", "chunked"), ("transfer-encoding", "chunked")], b""),
    ({"transfer-encoding": ""}, b""),
    ({"transfer-encoding": " "}, b""),
    ({"transfer-encoding": ","}, b""),
    ({"transfer-encoding": "compress"}, b""),
    ({"transfer-encoding": "identity"}, b""),
])
def test_ambiguous_or_unsupported_framing_rejected(headers, body):
    before_lab, before_prod = _lab_rows(), _production_rows()
    response = client.post("/api/outcomes/lab/consensus-success", headers=headers, content=body)
    assert response.status_code == 400
    assert response.json() == SAFE_DETAIL
    assert _lab_rows() == before_lab
    assert _production_rows() == before_prod


class _UntouchableStream(_FakeLabRequest):
    """Fake whose stream records any read; the gate must never touch it."""

    async def stream(self):
        self.consumed += 1
        yield b"must never be read"
        raise AssertionError("body stream must not be touched")


@pytest.mark.asyncio
@pytest.mark.parametrize("lengths", [["0"], ["5"], ["5", "5"]])
async def test_chunked_with_any_content_length_rejects_without_stream_read(lengths):
    raw = [(b"transfer-encoding", b"chunked")]
    raw += [(b"content-length", value.encode()) for value in lengths]
    request = _UntouchableStream(Headers(raw=raw))
    with pytest.raises(Exception) as excinfo:
        await _require_empty_lab_body(request)
    assert getattr(excinfo.value, "status_code", None) == 400
    assert request.consumed == 0


@pytest.mark.asyncio
async def test_exact_single_chunked_empty_stream_passes():
    request = _FakeLabRequest(Headers({"transfer-encoding": "chunked"}), [])
    await _require_empty_lab_body(request)
    assert request.consumed == 0


def test_openapi_advertises_no_request_body():
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/outcomes/lab/{scenario_id}"]["post"]
    assert "requestBody" not in operation


# --- Finding 2: atomic idempotent storage ------------------------------------


def test_transient_lock_classifier():
    def _operational(message, code=None):
        class _Orig(sqlite3.OperationalError):
            pass

        orig = _Orig(message)
        if code is not None:
            orig.sqlite_errorcode = code
        return OperationalError("SELECT 1", {}, orig)

    assert _is_transient_lab_lock_error(_operational("database is locked")) is True
    assert _is_transient_lab_lock_error(_operational("database table is locked")) is True
    assert _is_transient_lab_lock_error(_operational("anything", code=5)) is True
    assert _is_transient_lab_lock_error(_operational("anything", code=6)) is True
    assert _is_transient_lab_lock_error(_operational("syntax error", code=1)) is False
    assert _is_transient_lab_lock_error(_operational("deadlock detected")) is False
    assert _is_transient_lab_lock_error(ValueError("nope")) is False
    assert _is_transient_lab_lock_error(RuntimeError("nope")) is False


def test_postgres_retention_uses_self_conflicting_table_lock():
    class _FakeSession:
        def __init__(self, dialect_name):
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
            self.statements = []

        def get_bind(self):
            return self.bind

        def execute(self, statement):
            self.statements.append(str(statement))

    postgres = _FakeSession("postgresql")
    _serialize_postgres_lab_retention(postgres)
    assert postgres.statements == [
        "LOCK TABLE outcome_lab_receipts IN SHARE ROW EXCLUSIVE MODE"
    ]

    sqlite = _FakeSession("sqlite")
    _serialize_postgres_lab_retention(sqlite)
    assert sqlite.statements == []


def test_retry_only_for_transient_lock_errors(monkeypatch):
    calls = []

    def _flaky(receipt, payload):
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr(outcomes, "_store_lab_receipt_attempt", _flaky)
    outcomes.store_lab_receipt({"receipt_id": "x" * 24, "created_at": "t"})
    assert len(calls) == 3


def _failing_attempt_factory(calls, error):
    def _failing(receipt, payload):
        calls.append(1)
        raise error

    return _failing


@pytest.mark.parametrize("error", [
    OperationalError("SELECT bogus", {}, Exception("boom")),
    RuntimeError("boom"),
    ValueError("boom"),
])
def test_no_retry_for_arbitrary_errors(monkeypatch, error):
    calls: list = []
    monkeypatch.setattr(outcomes, "_store_lab_receipt_attempt", _failing_attempt_factory(calls, error))
    with pytest.raises(LabStorageUnavailable):
        outcomes.store_lab_receipt({"receipt_id": "y" * 24, "created_at": "t"})
    assert calls == [1]


def test_conflicting_same_id_row_fails_closed_without_overwrite():
    receipt_id = "c" * 24
    with Session(outcomes.engine) as db, db.begin():
        db.merge(OutcomeLabReceiptRow(id=receipt_id, created_at="2026-01-01T00:00:00Z",
                                      receipt_json='{"marker": "original"}'))
    with pytest.raises(LabWriteConflict):
        outcomes.store_lab_receipt({"receipt_id": receipt_id, "created_at": "2026-01-01T00:00:00Z",
                                    "marker": "conflicting"})
    with Session(outcomes.engine) as db:
        assert db.get(OutcomeLabReceiptRow, receipt_id).receipt_json == '{"marker": "original"}'


def _file_engine(path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    return engine


def _seed_production():
    with Session(outcomes.engine) as db, db.begin():
        db.merge(OutcomeReceiptRow(id="a" * 24, created_at="2026-01-02T00:00:00Z",
                                   receipt_json='{"seed": 1}'))
        db.merge(OutcomeReceiptRow(id="b" * 24, created_at="2026-01-03T00:00:00Z",
                                   receipt_json='{"seed": 2}'))


def test_concurrent_identical_runs_are_idempotent(tmp_path, monkeypatch):
    engine = _file_engine(tmp_path / "lab-concurrency.db")
    monkeypatch.setattr(outcomes, "engine", engine)
    _seed_production()
    before_prod = _production_rows()
    assert len(before_prod) == 2
    baseline_checkout = engine.pool.checkedout()

    count = 32
    barrier = threading.Barrier(count)
    outcomes_list: list = [None] * count

    def _worker(index):
        try:
            barrier.wait(timeout=30)
            outcomes_list[index] = TestClient(app).post("/api/outcomes/lab/consensus-success")
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            outcomes_list[index] = exc

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert all(not thread.is_alive() for thread in threads)
    assert all(not isinstance(item, Exception) for item in outcomes_list)
    assert [item.status_code for item in outcomes_list] == [200] * count
    bodies = [item.json() for item in outcomes_list]
    assert {body["receipt"]["receipt_id"] for body in bodies} == {
        bodies[0]["receipt"]["receipt_id"]}
    first_canonical = outcomes.canonical_json(bodies[0]["receipt"])
    assert all(outcomes.canonical_json(body["receipt"]) == first_canonical for body in bodies)
    assert all(body["passed"] is True for body in bodies)
    assert sorted(_lab_rows()) == [bodies[0]["receipt"]["receipt_id"]]
    assert _production_rows() == before_prod
    assert engine.pool.checkedout() == baseline_checkout


def test_concurrent_all_scenarios_stay_distinct_and_bounded(tmp_path, monkeypatch):
    engine = _file_engine(tmp_path / "lab-concurrency-all.db")
    monkeypatch.setattr(outcomes, "engine", engine)
    _seed_production()
    before_prod = _production_rows()

    assignments = [scenario for scenario in EXPECTED_IDS for _ in range(2)]
    barrier = threading.Barrier(len(assignments))
    outcomes_list: list = [None] * len(assignments)

    def _worker(index):
        try:
            barrier.wait(timeout=30)
            outcomes_list[index] = TestClient(app).post(f"/api/outcomes/lab/{assignments[index]}")
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            outcomes_list[index] = exc

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(len(assignments))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert all(not thread.is_alive() for thread in threads)
    assert [item.status_code for item in outcomes_list] == [200] * len(assignments)
    lab_rows = _lab_rows()
    assert len(lab_rows) == len(EXPECTED_IDS)
    assert len(set(lab_rows)) == len(EXPECTED_IDS)
    assert _production_rows() == before_prod


def test_concurrent_unique_writes_obey_small_retention_bound(tmp_path, monkeypatch):
    """The retention decision must serialize, not merely each PK insert.

    A large default limit with only six scenario IDs cannot expose stale
    concurrent counts. Use a deliberately tiny limit and many unique IDs so
    this fails whenever different writers make retention decisions in
    parallel.
    """
    engine = _file_engine(tmp_path / "lab-retention-race.db")
    monkeypatch.setattr(outcomes, "engine", engine)
    monkeypatch.setattr(outcomes, "MAX_LAB_RECEIPTS", 3)
    _seed_production()
    before_prod = _production_rows()
    baseline_checkout = engine.pool.checkedout()

    count = 24
    barrier = threading.Barrier(count)
    errors: list[Exception] = []

    def _worker(index):
        try:
            barrier.wait(timeout=30)
            outcomes.store_lab_receipt({
                "receipt_id": f"{index:024x}",
                "created_at": f"2026-01-01T00:00:{index:02d}Z",
                "marker": index,
            })
        except Exception as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(_lab_rows()) == 3
    assert _production_rows() == before_prod
    assert engine.pool.checkedout() == baseline_checkout
    assert not [warning for warning in caught if issubclass(warning.category, SAWarning)]


# --- Config hardening ---------------------------------------------------------


@pytest.mark.parametrize("good", ["1", "60", " 100 ", "007", "100000"])
def test_valid_lab_limits(good):
    assert _parse_max_lab_receipts(good) == int(good.strip())


@pytest.mark.parametrize("bad", ["0", "-1", "", "  ", "abc", "6.5", "100001", "0x10", None, "60x"])
def test_invalid_lab_limits_fail_closed(bad):
    with pytest.raises(ValueError, match="Invalid MAX_LAB_RECEIPTS"):
        _parse_max_lab_receipts(bad)
