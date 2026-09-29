"""SQLite-backed Durable Objects with atomic, chunked, session-scoped records.

Only JSON text crosses the Workers binding boundary. Financial values are decoded
in Python, avoiding JavaScript Number conversion of precise input integers.
"""

import hashlib
import json
import re
import secrets

from workers import DurableObject, Request, Response

from .storage import (
    IntegrityError,
    QuotaExceeded,
    StorageUnavailable,
    canonical,
    digest,
    finalize_experiment,
    now,
)

CHUNK_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
OWNER_PATTERN = re.compile(r"[0-9a-f]{64}")
TABLES = {"snapshots", "experiments"}


def validate_owner(owner):
    if not isinstance(owner, str) or OWNER_PATTERN.fullmatch(owner) is None:
        raise ValueError("Invalid session owner")
    return owner


def utf8_chunks(text, chunk_bytes=CHUNK_BYTES):
    """Yield independently valid UTF-8 strings, bounded by bytes rather than characters."""
    if chunk_bytes < 4:
        raise ValueError("Chunk size must accommodate a UTF-8 code point")
    data = text.encode("utf-8")
    if len(data) > MAX_PAYLOAD_BYTES:
        raise QuotaExceeded()
    start = 0
    while start < len(data):
        end = min(start + chunk_bytes, len(data))
        while end < len(data) and data[end] & 0xC0 == 0x80:
            end -= 1
        yield data[start:end].decode("utf-8")
        start = end


def history_summary(record):
    """Keep history reads independent of the potentially multi-megabyte result."""
    return {
        "experiment_id": record["experiment_id"],
        "created_at": record["created_at"],
        "config": {key: record["config"][key] for key in ("start", "end")},
        "provenance": {
            "baseline": {"name": record["provenance"]["baseline"]["name"]},
            "candidate": {"name": record["provenance"]["candidate"]["name"]},
            "effective_mode": record["provenance"]["effective_mode"],
        },
        "result": {"status": record["result"]["status"]},
    }


class SessionStore(DurableObject):
    """Private binding endpoint; one object owns one hashed, authenticated session."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self.sql = self.ctx.storage.sql
        self.sql.exec("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, created_at TEXT NOT NULL,
                payload_hash TEXT NOT NULL, chunk_count INTEGER NOT NULL,
                summary TEXT NOT NULL, summary_hash TEXT NOT NULL,
                PRIMARY KEY (kind, id));
            CREATE INDEX IF NOT EXISTS record_history ON records(kind, created_at DESC, id DESC);
            CREATE TABLE IF NOT EXISTS chunks (
                kind TEXT NOT NULL, id TEXT NOT NULL, sequence INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY (kind, id, sequence));
        """)

    def _rows(self, query, *bindings):
        # SQL values are text or small bookkeeping integers, never financial numbers.
        return [tuple(row) for row in self.sql.exec(query, *bindings).raw().toArray()]

    def _bind_owner(self, owner):
        rows = self._rows("SELECT value FROM metadata WHERE key='owner'")
        if rows and rows[0][0] != owner:
            raise IntegrityError()
        if not rows:
            self.sql.exec("INSERT INTO metadata VALUES ('owner', ?)", owner)

    def _history(self):
        rows = self._rows(
            "SELECT summary, summary_hash FROM records WHERE kind='experiments' "
            "ORDER BY created_at DESC, id DESC"
        )
        result = []
        for payload, expected_hash in rows:
            if hashlib.sha256(payload.encode()).hexdigest() != expected_hash:
                raise IntegrityError()
            result.append(json.loads(payload))
        return result

    def _save(self, kind, record, limit):
        count = self._rows("SELECT count(*) FROM records WHERE kind=?", kind)[0][0]
        if count >= limit:
            raise QuotaExceeded()
        identifier = record["snapshot_id" if kind == "snapshots" else "experiment_id"]
        payload = canonical(record)
        parts = list(utf8_chunks(payload))
        summary = canonical(history_summary(record) if kind == "experiments" else {})
        self.sql.exec(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)",
            kind,
            identifier,
            record["created_at"],
            hashlib.sha256(payload.encode()).hexdigest(),
            len(parts),
            summary,
            hashlib.sha256(summary.encode()).hexdigest(),
        )
        for sequence, part in enumerate(parts):
            self.sql.exec("INSERT INTO chunks VALUES (?, ?, ?, ?)", kind, identifier, sequence, part)
        return record

    def _get(self, kind, identifier):
        if kind not in TABLES:
            raise ValueError("Invalid record type")
        rows = self._rows(
            "SELECT payload_hash, chunk_count FROM records WHERE kind=? AND id=?", kind, identifier
        )
        if not rows:
            raise KeyError(identifier)
        expected_hash, expected_count = rows[0]
        chunks = self._rows(
            "SELECT sequence, payload FROM chunks WHERE kind=? AND id=? ORDER BY sequence",
            kind,
            identifier,
        )
        if len(chunks) != expected_count or any(i != row[0] for i, row in enumerate(chunks)):
            raise IntegrityError()
        payload = "".join(row[1] for row in chunks)
        if hashlib.sha256(payload.encode()).hexdigest() != expected_hash:
            raise IntegrityError()
        record = json.loads(payload)
        if kind == "snapshots":
            if digest(record["curve"]) != record["content_hash"]:
                raise IntegrityError()
            if digest(record["raw_curve"]) != record["raw_content_hash"]:
                raise IntegrityError()
        return record

    def _dispatch(self, message):
        operation = message["operation"]
        if operation == "health":
            return self._rows("SELECT 1")[0][0] == 1
        owner = validate_owner(message["owner"])
        self._bind_owner(owner)
        limit = message.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid record limit")
        if operation == "snapshot":
            curve, raw_curve = message["curve"], message["raw_curve"]
            record = {
                "snapshot_id": "s_" + secrets.token_hex(16),
                "created_at": now(),
                "content_hash": digest(curve),
                "curve": curve,
                "raw_curve": raw_curve,
                "raw_content_hash": digest(raw_curve),
                "normalization_version": "complete-daily/v1",
            }
            return self._save("snapshots", record, limit)
        if operation == "get":
            return self._get(message["table"], message["record_id"])
        if operation == "experiments":
            return self._history()
        if operation == "save_experiment":
            record = finalize_experiment(message["record"], self._history())
            return self._save("experiments", record, limit)
        raise ValueError("Invalid storage operation")

    async def fetch(self, request):
        try:
            if request.method != "POST":
                raise ValueError("Invalid storage request")
            payload = await request.text()
            if len(payload.encode()) > MAX_PAYLOAD_BYTES:
                raise QuotaExceeded()
            message = json.loads(payload)
            failures = []

            def execute():
                try:
                    return self._dispatch(message)
                except Exception as exc:
                    # Preserve typed Python errors if the FFI rethrows a JS wrapper.
                    failures.append(exc)
                    raise

            try:
                result = self.ctx.storage.transactionSync(execute)
            except Exception:
                if failures:
                    raise failures[0] from None
                raise
            envelope = {"ok": True, "value": result}
        except KeyError:
            envelope = {"ok": False, "error": "not_found"}
        except QuotaExceeded:
            envelope = {"ok": False, "error": "quota_exceeded"}
        except IntegrityError:
            envelope = {"ok": False, "error": "integrity_error"}
        except Exception:
            # Never send SQL statements, object identifiers or exception details.
            envelope = {"ok": False, "error": "storage_unavailable"}
        return Response(canonical(envelope), headers={"content-type": "application/json"})


class DurableStore:
    """Async Store interface backed by a private Durable Object namespace binding."""

    def __init__(self, namespace, secret, limit=100):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Record limit must be between 1 and 100")
        self.namespace = namespace
        self.secret = secret
        self.limit = limit

    async def _request(self, operation, owner=None, **fields):
        if owner is None:
            if operation != "health":
                raise ValueError("Missing session owner")
            object_name = "storage-health-v1"
        else:
            validate_owner(owner)
            object_name = "session-v1:" + hashlib.sha256(owner.encode()).hexdigest()
        message = {"operation": operation, "owner": owner, "limit": self.limit, **fields}
        try:
            stub = self.namespace.get(self.namespace.idFromName(object_name))
            request = Request(
                "https://session-store.internal/",
                method="POST",
                body=canonical(message),
                headers={"content-type": "application/json"},
            )
            response = await stub.fetch(request.js_object)
            envelope = json.loads(await response.text())
            if envelope.get("ok") is True:
                return envelope["value"]
            error = envelope.get("error")
        except Exception:
            raise StorageUnavailable() from None
        if error == "not_found":
            raise KeyError(fields.get("record_id", "record"))
        if error == "quota_exceeded":
            raise QuotaExceeded()
        if error == "integrity_error":
            raise IntegrityError()
        raise StorageUnavailable()

    async def health(self):
        return await self._request("health")

    async def snapshot(self, owner, curve, raw_curve=None):
        return await self._request(
            "snapshot", owner, curve=curve, raw_curve=curve if raw_curve is None else raw_curve
        )

    async def get(self, table, owner, record_id):
        if table not in TABLES:
            raise ValueError("Invalid record type")
        return await self._request("get", owner, table=table, record_id=record_id)

    async def experiments(self, owner):
        return await self._request("experiments", owner)

    async def save_experiment(self, owner, record):
        return await self._request("save_experiment", owner, record=record)
