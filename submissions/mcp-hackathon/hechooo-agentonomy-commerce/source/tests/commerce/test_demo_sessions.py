import asyncio
import hashlib
import sqlite3
import threading
import time
from pathlib import Path

import pytest


def _store(tmp_path, **changes):
    from agentonomy_commerce.demo_sessions import DemoSessions

    values = dict(state_dir=tmp_path)
    values.update(changes)
    store = DemoSessions(**values)
    store.start()
    return store


def test_new_credentials_are_hashed_and_restart_resolves(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoSessions

    first = _store(tmp_path)
    session, token = first.create()
    assert len(session.session_id) == 32
    assert session.session_id == session.session_id.lower()
    assert token
    db = tmp_path / "public-demo" / "sessions.sqlite3"
    raw = db.read_bytes()
    assert token.encode() not in raw
    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT token_digest, session_id, created_at, expires_at FROM sessions"
        ).fetchone()
    assert row[0] == hashlib.sha256(token.encode()).hexdigest()
    assert row[1] == session.session_id
    assert len(row) == 4

    second = DemoSessions(tmp_path)
    second.start()
    assert second.resolve(token) == session


def test_unknown_tampered_and_expired_tokens_do_not_resolve(tmp_path):
    now = [1000.0]
    store = _store(tmp_path, clock=lambda: now[0], ttl_seconds=10)
    session, token = store.create()
    assert store.resolve(token) == session
    assert store.resolve(token + "tampered") is None
    now[0] += 10
    assert store.resolve(token) is None
    assert store.expired() == [session]


def test_creation_limit_and_stored_session_capacity(tmp_path):
    now = [1000.0]
    store = _store(tmp_path, clock=lambda: now[0], max_sessions=2, creations_per_minute=2)
    first, _ = store.create()
    second, _ = store.create()
    from agentonomy_commerce.demo_sessions import DemoError

    with pytest.raises(DemoError) as capacity:
        store.create()
    assert capacity.value.status == 429
    assert capacity.value.code in {"session_capacity", "session_rate_limited"}
    now[0] += 61
    with pytest.raises(DemoError) as still_full:
        store.create()
    assert still_full.value.code == "session_capacity"
    assert {entry.session_id for entry in store.expired()} == set()
    assert first != second


def test_expiry_cleanup_does_not_bypass_creation_rate_limit(tmp_path):
    now = [1000.0]
    store = _store(tmp_path, clock=lambda: now[0], ttl_seconds=1, creations_per_minute=10)
    for _ in range(10):
        store.create()
    now[0] += 1
    for expired in store.expired():
        store.discard_expired(expired)
    from agentonomy_commerce.demo_sessions import DemoError

    with pytest.raises(DemoError) as failed:
        store.create()
    assert failed.value.code == "session_rate_limited"


def test_directory_isolated_and_expiry_cleanup_cannot_escape_sandbox_root(tmp_path):
    now = [1000.0]
    store = _store(tmp_path, clock=lambda: now[0], ttl_seconds=1)
    session, token = store.create()
    del token
    directory = store.directory(session)
    directory.mkdir(mode=0o700)
    (directory / "marker").write_text("guest", encoding="utf-8")
    baseline = tmp_path / "baseline.sqlite3"
    baseline.write_text("must remain", encoding="utf-8")
    now[0] += 1
    store.discard_expired(session)
    assert not directory.exists()
    assert baseline.read_text(encoding="utf-8") == "must remain"
    assert store.resolve(None) is None


def test_valid_session_is_not_discarded(tmp_path):
    store = _store(tmp_path)
    session, token = store.create()
    directory = store.directory(session)
    directory.mkdir(mode=0o700)
    store.discard_expired(session)
    assert store.resolve(token) == session
    assert directory.exists()


def test_missing_existing_ledger_fails_closed(tmp_path):
    store = _store(tmp_path)
    store.db_path.unlink()
    from agentonomy_commerce.demo_sessions import DemoError, DemoSessions

    with pytest.raises(DemoError) as failed:
        DemoSessions(tmp_path).start()
    assert failed.value.code == "session_store_unavailable"


def test_existing_sandbox_symlink_is_rejected(tmp_path):
    store = _store(tmp_path)
    session, _ = store.create()
    outside = tmp_path / "outside"
    outside.mkdir()
    store.directory(session).symlink_to(outside, target_is_directory=True)
    from agentonomy_commerce.demo_sessions import DemoError

    with pytest.raises(DemoError) as failed:
        store.directory(session)
    assert failed.value.code == "session_store_unavailable"
    assert not (outside / "unexpected").exists()


class FakeBridge:
    instances = []

    def __init__(self, state_dir, **kwargs):
        self.state_dir = Path(state_dir)
        self.kwargs = kwargs
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method, arguments=None):
        self.calls.append((method, arguments))
        if method == "snapshot":
            return {"ready": True}
        return {"method": method, "arguments": arguments}

    def close(self):
        self.closed = True


def test_runtime_reuses_worker_and_closes_on_tenant_switch(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoRuntime

    FakeBridge.instances.clear()
    store = _store(tmp_path)
    runtime = DemoRuntime(store, FakeBridge)

    async def scenario():
        first, token_a = await runtime.start_session(None)
        assert token_a
        assert await runtime.call(token_a, "budget") == {
            "method": "budget", "arguments": None
        }
        second, token_b = await runtime.start_session(None)
        assert token_b and second != first
        await runtime.call(token_b, "search", {"query": "csv"})
        assert len(FakeBridge.instances) == 2
        assert FakeBridge.instances[0].closed
        assert FakeBridge.instances[1].state_dir == store.directory(second)
        assert await runtime.call(token_a, "snapshot") == {"ready": True}
        assert FakeBridge.instances[1].closed
        assert len(FakeBridge.instances) == 3
        await runtime.close()

    asyncio.run(scenario())
    assert FakeBridge.instances[-1].closed


def test_runtime_serializes_calls_and_rechecks_auth_after_lock(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoError, DemoRuntime

    class BlockingBridge(FakeBridge):
        entered = threading.Event()
        release = threading.Event()

        def request(self, method, arguments=None):
            if method == "slow":
                self.__class__.entered.set()
                while not self.__class__.release.wait(0.005):
                    time.sleep(0.005)
            return super().request(method, arguments)

    store = _store(tmp_path)
    runtime = DemoRuntime(store, BlockingBridge, lock_timeout=0.01, call_timeout=1)

    async def scenario():
        _, token = await runtime.start_session(None)
        first = asyncio.create_task(runtime.call(token, "slow"))
        assert await asyncio.to_thread(BlockingBridge.entered.wait, 1)
        with pytest.raises(DemoError) as busy:
            await runtime.call(token, "second")
        assert busy.value.code == "operation_in_progress"
        BlockingBridge.release.set()
        await first
        await runtime.close()

    asyncio.run(scenario())


def test_runtime_timeout_closes_worker_without_resetting_persisted_session(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoError, DemoRuntime

    class TimeoutBridge(FakeBridge):
        def request(self, method, arguments=None):
            if method == "slow":
                time.sleep(0.1)
            return super().request(method, arguments)

    store = _store(tmp_path)
    runtime = DemoRuntime(store, TimeoutBridge, call_timeout=0.01)

    async def scenario():
        session, token = await runtime.start_session(None)
        with pytest.raises(DemoError) as failed:
            await runtime.call(token, "slow")
        assert failed.value.code == "worker_unavailable"
        assert TimeoutBridge.instances[-1].closed
        assert store.resolve(token) == session
        await runtime.close()

    asyncio.run(scenario())


def test_runtime_cancellation_closes_worker_before_releasing_lock(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoRuntime

    class CancellableBridge(FakeBridge):
        entered = threading.Event()
        release = threading.Event()

        def request(self, method, arguments=None):
            if method == "slow":
                self.__class__.entered.set()
                self.__class__.release.wait(2)
            return super().request(method, arguments)

        def close(self):
            self.__class__.release.set()
            super().close()

    CancellableBridge.instances.clear()
    store = _store(tmp_path)
    runtime = DemoRuntime(store, CancellableBridge, call_timeout=5)

    async def scenario():
        _, token = await runtime.start_session(None)
        pending = asyncio.create_task(runtime.call(token, "slow"))
        assert await asyncio.to_thread(CancellableBridge.entered.wait, 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert CancellableBridge.instances[-1].closed
        await runtime.call(token, "snapshot")
        await runtime.close()

    asyncio.run(scenario())


def test_switch_cancellation_is_deferred_until_old_worker_closes(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoRuntime

    class SwitchCloseBridge(FakeBridge):
        close_started = threading.Event()
        release_close = threading.Event()

        def close(self):
            self.__class__.close_started.set()
            self.__class__.release_close.wait(2)
            super().close()

    SwitchCloseBridge.instances.clear()
    SwitchCloseBridge.close_started.clear()
    SwitchCloseBridge.release_close.clear()
    store = _store(tmp_path)
    runtime = DemoRuntime(store, SwitchCloseBridge)

    async def scenario():
        _, token_a = await runtime.start_session(None)
        await runtime.call(token_a, "snapshot")
        _, token_b = await runtime.start_session(None)
        pending = asyncio.create_task(runtime.call(token_b, "search"))
        assert await asyncio.to_thread(SwitchCloseBridge.close_started.wait, 1)
        pending.cancel()
        await asyncio.sleep(0.02)
        assert not pending.done()
        SwitchCloseBridge.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert len(SwitchCloseBridge.instances) == 1
        assert SwitchCloseBridge.instances[0].closed
        await runtime.close()

    asyncio.run(scenario())


def test_worker_factory_uses_guest_module_and_ephemeral_merchant_port(tmp_path):
    from agentonomy_commerce.demo_sessions import DemoRuntime

    calls = []

    class FactoryBridge(FakeBridge):
        pass

    def factory(state_dir, **kwargs):
        calls.append((Path(state_dir), kwargs))
        return FactoryBridge(state_dir, **kwargs)

    store = _store(tmp_path)
    runtime = DemoRuntime(store, factory)

    async def scenario():
        _, token = await runtime.start_session(None)
        await runtime.call(token, "snapshot")
        await runtime.close()

    asyncio.run(scenario())
    assert calls[0][1] == {
        "worker_module": "agentonomy_commerce.worker",
        "worker_args": ("0",),
    }
