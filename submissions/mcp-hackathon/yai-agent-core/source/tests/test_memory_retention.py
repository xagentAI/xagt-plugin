"""历史保留策略测试：纯函数边界 + 两种 Store 参数化对等 + SQLite 专项。

全程离线：内存库 / tmp_path 文件库 / 注入假时钟，零网络、零 Key、零 sleep。
"""

from __future__ import annotations

import asyncio
import warnings
from datetime import UTC, datetime, timedelta

import pytest

from yai_core.memory import InMemoryStore, SqliteStore, retention_from_env
from yai_core.memory.retention import count_cut, ttl_cut
from yai_core.types import ChatMessage


def run(coro):
    """同步测试里跑一个协程的小工具（仓库既有风格，不引入 pytest-asyncio）。"""
    return asyncio.run(coro)


class FakeClock:
    """可手动推进的时钟：测试推进时间而不是 sleep 等真实窗口。"""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def append_roles(store, roles: list[str]) -> None:
    """按简写角色序列追加消息；a_tc=带 tool_calls 的 assistant，tool=其工具结果。"""
    for idx, role in enumerate(roles):
        if role == "a_tc":
            message = ChatMessage(
                role="assistant",
                content="",
                tool_calls=[{"id": f"c{idx}", "name": "t", "arguments": {}}],
            )
        elif role == "tool":
            message = ChatMessage(
                role="tool", content="结果", tool_call_id=f"c{idx - 1}"
            )
        else:
            message = ChatMessage(
                role={"u": "user", "a": "assistant"}[role],
                content=f"{role}{idx}",
            )
        run(store.append_history(message))


def assert_well_formed(messages: list[ChatMessage]) -> None:
    """工具调用对完整性：无孤儿 tool、无被截断的 tool_calls 助手消息。"""
    for i, message in enumerate(messages):
        if message.role == "tool":
            prev = messages[i - 1]
            assert prev.role == "assistant" and prev.tool_calls, f"孤儿 tool 消息 @ {i}"
        if message.role == "assistant" and message.tool_calls:
            assert i + len(message.tool_calls) < len(messages), f"截断的 tool_calls @ {i}"
            for _j in range(len(message.tool_calls)):
                assert messages[i + 1 + _j].role == "tool"


def install_deleted_counter(store) -> dict[str, int]:
    """累计 append 触发的内部裁剪删除条数（两种实现挂钩点不同）。"""
    total = {"n": 0}
    orig_prune = store.prune

    def counting_prune() -> int:
        result = orig_prune()
        total["n"] += result
        return result

    store.prune = counting_prune
    orig_locked = getattr(store, "_prune_locked", None)
    if orig_locked is not None:

        def counting_locked() -> int:
            result = orig_locked()
            total["n"] += result
            return result

        store._prune_locked = counting_locked
    return total


@pytest.fixture(params=["memory", "sqlite"])
def make_store(request, tmp_path):
    """同一组对等用例分别构造 InMemoryStore 与 SqliteStore（每个用例独立 db 文件）。"""
    opened: list = []

    def _make(**kwargs):
        if request.param == "memory":
            store = InMemoryStore(**kwargs)
        else:
            store = SqliteStore(tmp_path / f"ret_{len(opened)}.db", **kwargs)
        opened.append(store)
        return store

    yield _make

    for store in opened:
        close = getattr(store, "close", None)
        if close is not None:
            close()


# ---------- A 组：纯函数边界（不依赖任何 Store） ----------

def test_count_cut_round_alignment() -> None:
    three_rounds = ["user", "assistant"] * 3
    assert count_cut(three_rounds, 2) == 4
    assert count_cut(three_rounds, 3) == 4  # 候选落在 assistant 上，后移到下一轮首
    assert count_cut(three_rounds, 6) is None  # 恰好不裁
    assert count_cut(three_rounds, None) is None
    # 单轮（即使自身超限）不裁，至少保留最后一轮
    assert count_cut(["user", "assistant", "assistant", "assistant", "assistant"], 2) is None
    # 历史开头的非 user 消息归"第 0 轮"，随第一轮一起删
    assert count_cut(["assistant", "user", "assistant", "user", "assistant"], 2) == 3
    assert count_cut(["user", "assistant"], 2) is None
    assert count_cut([], 5) is None


def test_ttl_cut_round_alignment() -> None:
    roles = ["user", "assistant"] * 3
    assert ttl_cut(roles, [True] * 4 + [False] * 2) == 4
    assert ttl_cut(roles, [True] * 2 + [False] * 4) == 2  # 恰好整轮过期
    assert ttl_cut(roles, [True] + [False] * 5) is None  # 只过期到首轮中间，不裁
    assert ttl_cut(roles, [False] * 6) is None
    assert ttl_cut(roles, [True] * 6) == 6  # 全部过期：整库清空（空历史合法）
    # 前导非 user 消息（第 0 轮）全部过期时随全库清空
    assert ttl_cut(["assistant", "user", "assistant"], [True] * 3) == 3


def test_retention_from_env_states() -> None:
    assert retention_from_env({}) == (None, None)
    assert retention_from_env({"YAI_HISTORY_MAX_MESSAGES": "200"}) == (200, None)
    assert retention_from_env({"YAI_HISTORY_TTL_SECONDS": "604800"}) == (None, 604800)
    # 空白等同未设置，静默
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert retention_from_env({"YAI_HISTORY_MAX_MESSAGES": "  "}) == (None, None)
        assert caught == []
    # 0 / 负数 / 非整数：回退 None 且每项各一条 warning
    for bad in ("0", "-3", "abc"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert retention_from_env(
                {"YAI_HISTORY_MAX_MESSAGES": bad, "YAI_HISTORY_TTL_SECONDS": bad}
            ) == (None, None)
            assert len(caught) == 2


# ---------- B 组：两种 Store 参数化对等 ----------

def test_default_keeps_everything(make_store) -> None:
    store = make_store()
    append_roles(store, ["u", "a"] * 25)
    assert len(store.history()) == 50


def test_count_trim_keeps_last_round_and_reports_deleted(make_store) -> None:
    store = make_store(max_messages=2)
    deleted = install_deleted_counter(store)
    append_roles(store, ["u", "a", "u", "a", "u", "a"])
    assert [m.role for m in store.history()] == ["user", "assistant"]
    assert deleted["n"] == 4  # 增量裁剪累计删掉 4 条
    assert_well_formed(store.history())


def test_exact_boundary_no_delete(make_store) -> None:
    store = make_store(max_messages=6)
    append_roles(store, ["u", "a"] * 3)
    assert len(store.history()) == 6
    assert store.prune() == 0


def test_single_round_over_limit_not_trimmed(make_store) -> None:
    store = make_store(max_messages=2)
    append_roles(store, ["u", "a", "a", "a", "a"])
    assert len(store.history()) == 5
    assert store.prune() == 0


def test_tool_pairs_never_split(make_store) -> None:
    # 朴素按条硬删会在第 3/4 条切开工具对；轮对齐后必须完整
    store = make_store(max_messages=3)
    append_roles(store, ["u", "a_tc", "tool", "u", "a"])
    assert_well_formed(store.history())

    store = make_store(max_messages=4)
    append_roles(store, ["u", "a_tc", "tool", "u", "a_tc", "tool", "u", "a"])
    assert_well_formed(store.history())
    assert [m.role for m in store.history()] == ["user", "assistant"]


def test_ttl_drops_expired_round_keeps_recent(make_store) -> None:
    # 基准取真实 UTC 当前时刻并抹掉微秒：SQLite 落库为秒级 UTC 文本，必须同基准
    clock = FakeClock(datetime.now(UTC).replace(microsecond=0))
    store = make_store(ttl_seconds=60, clock=clock)
    append_roles(store, ["u", "a"])
    clock.advance(seconds=120)
    append_roles(store, ["u", "a"])
    assert [m.role for m in store.history()] == ["user", "assistant"]
    assert_well_formed(store.history())


def test_ttl_equal_cutoff_is_retained(make_store) -> None:
    clock = FakeClock(datetime.now(UTC).replace(microsecond=0))
    store = make_store(ttl_seconds=60, clock=clock)
    append_roles(store, ["u", "a"])
    clock.advance(seconds=60)  # cutoff 恰好等于消息时间戳：严格 < 语义下保留
    assert store.prune() == 0
    assert len(store.history()) == 2


def test_ttl_all_expired_clears_store(make_store) -> None:
    clock = FakeClock(datetime.now(UTC).replace(microsecond=0))
    store = make_store(ttl_seconds=60, clock=clock)
    append_roles(store, ["u", "a"])
    clock.advance(seconds=61)  # 唯一一轮也全部过期 -> 整库清空
    assert store.prune() == 2
    assert store.history() == []


def test_prune_idempotent(make_store) -> None:
    store = make_store(max_messages=2)
    append_roles(store, ["u", "a"] * 3)
    first = store.prune()
    assert first == 0  # append 时已裁完，显式再裁无东西可删
    assert store.prune() == 0


def test_clear_resets_history_and_timestamps(make_store) -> None:
    store = make_store(max_messages=2)
    append_roles(store, ["u", "a"])
    run(store.clear())
    assert store.history() == []
    # 清空后重新写入，裁剪逻辑仍正常（时间戳列表没有残留）
    append_roles(store, ["u", "a", "u", "a", "u", "a"])
    assert [m.role for m in store.history()] == ["user", "assistant"]


# ---------- C 组：SqliteStore 专项 ----------

def test_scope_isolation_under_retention(tmp_path) -> None:
    db = tmp_path / "scope.db"
    a = SqliteStore(db, scope="a", max_messages=2)
    b = SqliteStore(db, scope="b", max_messages=2)
    try:
        append_roles(a, ["u", "a", "u", "a", "u", "a"])
        append_roles(b, ["u", "a"])
        assert [m.role for m in a.history()] == ["user", "assistant"]
        assert len(b.history()) == 2  # A 的裁剪不动 B
    finally:
        a.close()
        b.close()


def test_startup_prune_on_construction(tmp_path) -> None:
    db = tmp_path / "startup.db"
    old = SqliteStore(db)  # 旧实例：未配置保留策略
    append_roles(old, ["u", "a"])
    old.close()
    # 新实例：把时钟拨到 30 天后并配置 1 小时 TTL，构造期 prune 应清空过期历史
    future = FakeClock(datetime.now(UTC).replace(microsecond=0) + timedelta(days=30))
    fresh = SqliteStore(db, ttl_seconds=3600, clock=future)
    try:
        assert fresh.history() == []
    finally:
        fresh.close()


def test_close_then_prune_raises(tmp_path) -> None:
    store = SqliteStore(tmp_path / "closed.db", max_messages=2)
    store.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        store.prune()


def test_from_env_passes_retention(tmp_path) -> None:
    store = SqliteStore.from_env(
        env={
            "YAI_DB_PATH": str(tmp_path / "env.db"),
            "YAI_HISTORY_MAX_MESSAGES": "2",
            "YAI_HISTORY_TTL_SECONDS": "60",
        }
    )
    assert store is not None
    try:
        assert store._max_messages == 2
        assert store._ttl_seconds == 60
    finally:
        store.close()


def test_from_env_explicit_retention_tuple(tmp_path) -> None:
    # 无路径仍返回 None（即使显式传了 retention）
    assert SqliteStore.from_env(env={}, retention=(4, None)) is None
    store = SqliteStore.from_env(
        env={"YAI_DB_PATH": str(tmp_path / "env2.db")}, retention=(4, None)
    )
    assert store is not None
    try:
        assert store._max_messages == 4
        assert store._ttl_seconds is None
    finally:
        store.close()
