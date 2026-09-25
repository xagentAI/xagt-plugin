"""SQLite fixture for isolated HTTP contract tests, never a product runtime."""

import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.storage import IntegrityError, QuotaExceeded, StorageUnavailable, canonical, digest, finalize_experiment, now


class SQLiteTestStore:
    def __init__(self, path, limit=100):
        self.path = Path(path)
        self.limit = limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshot_owner ON snapshots(owner);
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS experiment_owner ON experiments(owner, created_at);
            """)
            con.execute(
                "INSERT OR IGNORE INTO settings VALUES ('session_secret', ?)", (secrets.token_hex(32),)
            )
            self.secret = con.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()[0]
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        # Mirror the Durable Object adapter's error boundary, not a SQLite API.
        con = None
        try:
            con = sqlite3.connect(self.path, timeout=10)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA synchronous=FULL")
            with con:
                yield con
        except sqlite3.Error:
            raise StorageUnavailable() from None
        finally:
            if con is not None:
                con.close()

    def health(self):
        with self.connect() as con:
            return con.execute("SELECT 1").fetchone()[0] == 1

    def snapshot(self, owner, curve, raw_curve=None):
        raw_curve = curve if raw_curve is None else raw_curve
        record = {
            "snapshot_id": "s_" + secrets.token_hex(16),
            "created_at": now(),
            "content_hash": digest(curve),
            "curve": curve,
            "raw_curve": raw_curve,
            "raw_content_hash": digest(raw_curve),
            "normalization_version": "complete-daily/v1",
        }
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if (
                con.execute("SELECT count(*) FROM snapshots WHERE owner=?", (owner,)).fetchone()[0]
                >= self.limit
            ):
                raise QuotaExceeded()
            con.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    record["snapshot_id"],
                    owner,
                    record["created_at"],
                    record["content_hash"],
                    canonical(record),
                ),
            )
        return record

    def get(self, table, owner, record_id):
        if table not in {"snapshots", "experiments"}:
            raise ValueError("Invalid record type")
        with self.connect() as con:
            row = con.execute(
                f"SELECT payload FROM {table} WHERE id=? AND owner=?", (record_id, owner)
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        record = json.loads(row[0])
        if table == "snapshots":
            if digest(record["curve"]) != record["content_hash"]:
                raise IntegrityError()
            if "raw_curve" in record and digest(record["raw_curve"]) != record["raw_content_hash"]:
                raise IntegrityError()
        return record

    def experiments(self, owner):
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload FROM experiments WHERE owner=? ORDER BY created_at DESC, id DESC", (owner,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_experiment(self, owner, record):
        # Exploration history is inspected under the same write lock as insertion.
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute("SELECT payload FROM experiments WHERE owner=?", (owner,)).fetchall()
            if len(rows) >= self.limit:
                raise QuotaExceeded()
            history = [json.loads(row[0]) for row in rows]
            record = record(history) if callable(record) else finalize_experiment(record, history)
            con.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?)",
                (record["experiment_id"], owner, record["created_at"], canonical(record)),
            )
        return record
