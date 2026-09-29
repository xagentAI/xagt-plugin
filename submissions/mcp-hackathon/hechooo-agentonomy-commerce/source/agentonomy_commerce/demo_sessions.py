"""Persistent, isolated sessions for the public Commerce demonstration.

The public browser session is intentionally a small ownership layer around the
existing worker.  It stores only a digest of the browser credential and keeps
the worker state in a validated per-session directory.  The worker itself
continues to own all of the Core and Marketplace accounting rules.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable


_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_TOKEN_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = (
    ("token_digest", "TEXT"),
    ("session_id", "TEXT"),
    ("created_at", "INTEGER"),
    ("expires_at", "INTEGER"),
)


class DemoError(RuntimeError):
    """An expected public-demo failure with an HTTP-facing error code."""

    def __init__(self, code: str, status: int):
        self.code = str(code)
        self.status = int(status)
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class DemoSession:
    session_id: str
    expires_at: int


class DemoSessions:
    """A fail-closed SQLite ledger for public visitor identities."""

    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 604800,
        max_sessions: int = 128,
        creations_per_minute: int = 10,
    ):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.public_root = self.state_dir / "public-demo"
        self.sandbox_root = self.public_root / "sandboxes"
        self.db_path = self.public_root / "sessions.sqlite3"
        self.clock = clock
        self.ttl_seconds = int(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self.creations_per_minute = int(creations_per_minute)
        if self.ttl_seconds <= 0 or self.max_sessions <= 0 or self.creations_per_minute <= 0:
            raise ValueError("session limits must be positive")
        self._started = False
        self._lock = threading.RLock()
        self._creation_history: dict[str, int] = {}

    def start(self) -> None:
        """Create or validate the private ledger without repairing it."""

        with self._lock:
            try:
                public_root_existed = self.public_root.exists()
                self._ensure_private_directory(self.public_root)
                self._ensure_private_directory(self.sandbox_root)
                if self.db_path.is_symlink() or (self.db_path.exists() and not self.db_path.is_file()):
                    raise DemoError("session_store_unavailable", 503)
                if public_root_existed and not self.db_path.exists():
                    # A missing ledger after a previous startup is ambiguous:
                    # creating a new one could make an old sandbox look like a
                    # fresh, funded visitor. Require explicit recovery.
                    raise DemoError("session_store_unavailable", 503)
                database = self._connection()
                try:
                    self._ensure_schema(database)
                    self._validate_rows(database)
                    self._creation_history.update({
                        str(session_id): int(created_at)
                        for session_id, created_at in database.execute(
                            "SELECT session_id, created_at FROM sessions"
                        ).fetchall()
                    })
                finally:
                    database.close()
                os.chmod(self.db_path, 0o600)
            except DemoError:
                raise
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                raise DemoError("session_store_unavailable", 503) from exc
            self._started = True

    def resolve(self, token: str | None) -> DemoSession | None:
        """Resolve an untrusted cookie, returning no result for expiry/tampering."""

        if token is None:
            return None
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            database = self._open_started()
            try:
                digest = self._digest(token)
                row = database.execute(
                    "SELECT token_digest, session_id, created_at, expires_at "
                    "FROM sessions WHERE token_digest = ?",
                    (digest,),
                ).fetchone()
                if row is None:
                    return None
                self._validate_row(row)
                if int(row[3]) <= self._now():
                    return None
                return DemoSession(str(row[1]), int(row[3]))
            except DemoError:
                raise
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                raise DemoError("session_store_unavailable", 503) from exc
            finally:
                database.close()

    def create(self) -> tuple[DemoSession, str]:
        """Create one identity and return its one-time browser credential."""

        with self._lock:
            database = self._open_started()
            try:
                database.execute("BEGIN IMMEDIATE")
                now = self._now()
                count = database.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                if int(count) >= self.max_sessions:
                    raise DemoError("session_capacity", 429)
                recent_rows = database.execute(
                    "SELECT session_id, created_at FROM sessions WHERE created_at > ?",
                    (now - 60,),
                ).fetchall()
                recent_ids = {str(session_id) for session_id, _created_at in recent_rows}
                recent_history = sum(
                    1 for session_id, created_at in self._creation_history.items()
                    if created_at > now - 60 and session_id not in recent_ids
                )
                if len(recent_ids) + recent_history >= self.creations_per_minute:
                    raise DemoError("session_rate_limited", 429)
                for _ in range(10):
                    token = secrets.token_urlsafe(32)
                    session_id = secrets.token_hex(16)
                    expires_at = now + self.ttl_seconds
                    try:
                        database.execute(
                            "INSERT INTO sessions(token_digest, session_id, created_at, expires_at) "
                            "VALUES (?, ?, ?, ?)",
                            (self._digest(token), session_id, now, expires_at),
                        )
                        database.commit()
                        self._creation_history[session_id] = now
                        return DemoSession(session_id, expires_at), token
                    except sqlite3.IntegrityError:
                        database.rollback()
                        continue
                raise DemoError("session_store_unavailable", 503)
            except DemoError:
                database.rollback()
                raise
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                database.rollback()
                raise DemoError("session_store_unavailable", 503) from exc
            finally:
                database.close()

    def expired(self) -> list[DemoSession]:
        with self._lock:
            database = self._open_started()
            try:
                rows = database.execute(
                    "SELECT token_digest, session_id, created_at, expires_at "
                    "FROM sessions WHERE expires_at <= ? ORDER BY expires_at, session_id",
                    (self._now(),),
                ).fetchall()
                return [self._session_from_row(row) for row in rows]
            except DemoError:
                raise
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                raise DemoError("session_store_unavailable", 503) from exc
            finally:
                database.close()

    def discard_expired(self, session: DemoSession) -> None:
        """Remove one expired row and only its exact sandbox child."""

        session_id = self._validated_session_id(session)
        with self._lock:
            database = self._open_started()
            try:
                row = database.execute(
                    "SELECT token_digest, session_id, created_at, expires_at "
                    "FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    return
                self._validate_row(row)
                if int(row[3]) != int(session.expires_at) or int(row[3]) > self._now():
                    return
                candidate = self._sandbox_path(session_id)
                self._remove_sandbox(candidate)
                database.execute(
                    "DELETE FROM sessions WHERE session_id = ? AND expires_at = ?",
                    (session_id, int(session.expires_at)),
                )
                database.commit()
            except DemoError:
                raise
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                database.rollback()
                raise DemoError("session_cleanup_failed", 503) from exc
            finally:
                database.close()

    def directory(self, session: DemoSession) -> Path:
        """Return a validated state path beneath the public-demo sandbox root."""

        self._require_started()
        candidate = self._sandbox_path(self._validated_session_id(session))
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise DemoError("session_store_unavailable", 503)
        return candidate

    def _open_started(self) -> sqlite3.Connection:
        self._require_started()
        database = None
        try:
            database = self._connection()
            self._validate_schema(database)
            return database
        except DemoError:
            if database is not None:
                database.close()
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            if database is not None:
                database.close()
            raise DemoError("session_store_unavailable", 503) from exc

    def _connection(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, timeout=2)
        database.execute("PRAGMA busy_timeout=2000")
        return database

    def _ensure_schema(self, database: sqlite3.Connection) -> None:
        tables = database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        names = {str(row[0]) for row in tables}
        if not names:
            database.execute(
                "CREATE TABLE sessions ("
                "token_digest TEXT NOT NULL PRIMARY KEY, "
                "session_id TEXT NOT NULL UNIQUE, "
                "created_at INTEGER NOT NULL, "
                "expires_at INTEGER NOT NULL"
                ")"
            )
            database.commit()
            return
        if names != {"sessions"}:
            raise DemoError("session_store_unavailable", 503)
        self._validate_schema(database)

    def _validate_schema(self, database: sqlite3.Connection) -> None:
        info = database.execute("PRAGMA table_info(sessions)").fetchall()
        actual = [(str(row[1]), str(row[2]).upper()) for row in info]
        expected = [(name, kind) for name, kind in _SCHEMA]
        if actual != expected:
            raise DemoError("session_store_unavailable", 503)

    def _validate_rows(self, database: sqlite3.Connection) -> None:
        rows = database.execute(
            "SELECT token_digest, session_id, created_at, expires_at FROM sessions"
        ).fetchall()
        for row in rows:
            self._validate_row(row)

    @staticmethod
    def _validate_row(row: tuple[Any, ...]) -> None:
        if len(row) != 4:
            raise DemoError("session_store_unavailable", 503)
        digest, session_id, created_at, expires_at = row
        if not isinstance(digest, str) or not _TOKEN_DIGEST.fullmatch(digest):
            raise DemoError("session_store_unavailable", 503)
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise DemoError("session_store_unavailable", 503)
        if isinstance(created_at, bool) or not isinstance(created_at, int):
            raise DemoError("session_store_unavailable", 503)
        if isinstance(expires_at, bool) or not isinstance(expires_at, int) or expires_at < created_at:
            raise DemoError("session_store_unavailable", 503)

    def _session_from_row(self, row: tuple[Any, ...]) -> DemoSession:
        self._validate_row(row)
        return DemoSession(str(row[1]), int(row[3]))

    def _now(self) -> int:
        value = self.clock()
        if isinstance(value, bool):
            raise ValueError("clock must return a number")
        return int(value)

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _require_started(self) -> None:
        if not self._started:
            raise DemoError("session_store_unavailable", 503)

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise DemoError("session_store_unavailable", 503)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    def _sandbox_path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise DemoError("invalid_session", 401)
        if self.sandbox_root.is_symlink() or not self.sandbox_root.is_dir():
            raise DemoError("session_store_unavailable", 503)
        candidate = self.sandbox_root / session_id
        if candidate.parent != self.sandbox_root:
            raise DemoError("session_store_unavailable", 503)
        return candidate

    @staticmethod
    def _validated_session_id(session: DemoSession) -> str:
        session_id = getattr(session, "session_id", None)
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise DemoError("invalid_session", 401)
        return session_id

    @staticmethod
    def _remove_sandbox(candidate: Path) -> None:
        if not candidate.exists() and not candidate.is_symlink():
            return
        if candidate.is_symlink():
            candidate.unlink()
        elif candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()


class DemoRuntime:
    """Serialize access to one additional guest Marketplace worker."""

    def __init__(
        self,
        sessions: DemoSessions,
        bridge_factory: Callable[..., Any],
        *,
        lock_timeout: float = 2,
        call_timeout: float = 50,
    ):
        self.sessions = sessions
        self.bridge_factory = bridge_factory
        self.lock_timeout = float(lock_timeout)
        self.call_timeout = float(call_timeout)
        if self.lock_timeout <= 0 or self.call_timeout <= 0:
            raise ValueError("runtime timeouts must be positive")
        self._lock = asyncio.Lock()
        self._worker: Any | None = None
        self._worker_session: DemoSession | None = None

    async def start_session(self, token: str | None) -> tuple[DemoSession, str | None]:
        """Restore a valid cookie or create one after safely cleaning expiry."""

        current = self.sessions.resolve(token)
        if current is not None:
            return current, None
        await self._acquire()
        try:
            # The cookie can become valid/invalid while waiting for the worker
            # lock, so resolve it again after acquiring the lock.
            current = self.sessions.resolve(token)
            if current is not None:
                return current, None
            for expired in self.sessions.expired():
                if self._worker_session is not None and self._worker_session.session_id == expired.session_id:
                    await self._close_worker_locked()
                self.sessions.discard_expired(expired)
            return self.sessions.create()
        finally:
            self._lock.release()

    async def call(self, token: str, method: str, arguments: dict | None = None) -> dict:
        """Run one operation for the authenticated session."""

        if self.sessions.resolve(token) is None:
            raise DemoError("invalid_session", 401)
        await self._acquire()
        try:
            session = self.sessions.resolve(token)
            if session is None:
                raise DemoError("invalid_session", 401)
            await self._ensure_worker_locked(session)
            try:
                return await self._request(self._worker, method, arguments)
            except asyncio.CancelledError:
                await self._close_worker_locked()
                raise
            except Exception as exc:
                await self._close_worker_locked()
                raise DemoError("worker_unavailable", 503) from exc
        finally:
            self._lock.release()

    async def close(self) -> None:
        await self._lock.acquire()
        try:
            await self._close_worker_locked()
        finally:
            self._lock.release()

    async def _acquire(self) -> None:
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.lock_timeout)
        except asyncio.TimeoutError as exc:
            raise DemoError("operation_in_progress", 429) from exc

    async def _ensure_worker_locked(self, session: DemoSession) -> None:
        if self._worker is not None and self._worker_session == session:
            return
        await self._close_worker_locked()
        bridge = None
        try:
            bridge = self.bridge_factory(
                self.sessions.directory(session),
                worker_module="agentonomy_commerce.worker",
                worker_args=("0",),
            )
            snapshot = await self._request(bridge, "snapshot", None)
            if not isinstance(snapshot, dict) or "_error" in snapshot:
                raise RuntimeError("guest worker did not initialize")
        except asyncio.CancelledError:
            if bridge is not None:
                await self._close_bridge(bridge)
            raise
        except Exception as exc:
            if bridge is not None:
                await self._close_bridge(bridge)
            raise DemoError("worker_unavailable", 503) from exc
        self._worker = bridge
        self._worker_session = session

    async def _request(self, bridge: Any, method: str, arguments: dict | None) -> dict:
        if bridge is None:
            raise RuntimeError("guest worker is unavailable")
        return await asyncio.wait_for(
            asyncio.to_thread(bridge.request, method, arguments),
            timeout=self.call_timeout,
        )

    async def _close_worker_locked(self) -> None:
        bridge = self._worker
        self._worker = None
        self._worker_session = None
        if bridge is not None:
            await self._close_bridge(bridge)

    @staticmethod
    async def _close_bridge(bridge: Any) -> None:
        """Wait for close even if cancellation arrives during cleanup."""

        close_task = asyncio.create_task(asyncio.to_thread(DemoRuntime._close_bridge_sync, bridge))
        cancelled = False
        while True:
            try:
                await asyncio.shield(close_task)
                break
            except asyncio.CancelledError:
                # Keep the owning lock until the process has actually been
                # closed. Propagate cancellation after this loop so a tenant
                # switch cannot continue by constructing the next worker.
                cancelled = True
                continue
            except Exception:
                break
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    def _close_bridge_sync(bridge: Any) -> None:
        """Close a bridge and force its owned process down on close failure."""

        close_error = None
        try:
            bridge.close()
        except BaseException as exc:  # pragma: no cover - concrete bridges usually close cleanly
            close_error = exc
        process = getattr(bridge, "process", None)
        if process is not None:
            try:
                running = process.poll() is None
            except BaseException:
                running = False
            if running:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except BaseException:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except BaseException:
                        pass
        # A bridge without a process still received its close() call.  For a
        # process bridge the termination attempt above completes ownership
        # cleanup before the runtime releases its operation lock.
        del close_error
