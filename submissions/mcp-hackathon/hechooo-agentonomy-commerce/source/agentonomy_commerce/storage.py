"""SQLite implementation of Marketplace's TTL store for a review deployment."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time


RESULT_RETENTION_SECONDS = 7 * 86400


class SQLiteStore:
    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock or time.time
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS ttl_values "
                       "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)")
            db.execute("DELETE FROM ttl_values WHERE expires <= ?", (self.clock(),))
        os.chmod(self.path, 0o600)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def set(self, key, value, ttl=900):
        if key.startswith("purchase_result:"):
            ttl = RESULT_RETENTION_SECONDS
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        with self._connection() as db:
            db.execute("INSERT INTO ttl_values VALUES (?, ?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires=excluded.expires",
                       (key, encoded, self.clock() + max(1, int(ttl))))

    def get(self, key):
        with self._connection() as db:
            db.execute("DELETE FROM ttl_values WHERE expires <= ?", (self.clock(),))
            row = db.execute("SELECT value FROM ttl_values WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def acquire(self, key, ttl=900):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM ttl_values WHERE key = ? AND expires > ?",
                             (key, self.clock())).fetchone()
            if row is None:
                db.execute("DELETE FROM ttl_values WHERE key = ?", (key,))
                return None
            db.execute("UPDATE ttl_values SET expires = ? WHERE key = ?",
                       (self.clock() + max(1, int(ttl)), key))
            return json.loads(row[0])

    def delete(self, key):
        with self._connection() as db:
            return bool(db.execute("DELETE FROM ttl_values WHERE key = ?", (key,)).rowcount)

    def pop(self, key):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM ttl_values WHERE key = ? AND expires > ?",
                             (key, self.clock())).fetchone()
            db.execute("DELETE FROM ttl_values WHERE key = ?", (key,))
        return json.loads(row[0]) if row else None
