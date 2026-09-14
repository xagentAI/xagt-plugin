"""SqliteStore 测试：契约对等（与 InMemoryStore 跑同一组断言）+ 持久化专项。

全程离线：内存库与 tmp_path 文件库，零网络、零 Key。
"""

import asyncio
import sqlite3

import pytest

from yai_core import AgentCore, ChatMessage, ModelResponse
from yai_core.memory import InMemoryStore, SqliteStore


def run(coro):
    """同步测试里跑一个协程的小工具（仓库既有风格，不引入 pytest-asyncio）。"""
    return asyncio.run(coro)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    """同一组对等用例分别跑 InMemoryStore 与 SqliteStore。"""
    if request.param == "memory":
        yield InMemoryStore()
    else:
        s = SqliteStore(tmp_path / "t.db")
        yield s
        s.close()


# ---------- A 组：契约对等（两种实现必须行为一致） ----------

def test_empty_history(store) -> None:
    assert store.history() == []


def test_append_history_order_and_fields(store) -> None:
    run(store.append_history(ChatMessage(role="user", content="第一条")))
    run(store.append_history(ChatMessage(role="assistant", content="第二条")))
    hist = store.history()
    assert [m.role for m in hist] == ["user", "assistant"]
    assert [m.content for m in hist] == ["第一条", "第二条"]


def test_kv_put_get_overwrite_and_missing(store) -> None:
    assert run(store.get("k")) is None
    run(store.put("k", "v1"))
    assert run(store.get("k")) == "v1"
    run(store.put("k", "v2"))
    assert run(store.get("k")) == "v2"


def test_clear_empties_history_and_kv(store) -> None:
    run(store.append_history(ChatMessage(role="user", content="x")))
    run(store.put("k", "v"))
    run(store.clear())
    assert store.history() == []
    assert run(store.get("k")) is None


def test_tool_calls_roundtrip_including_empty_list(store) -> None:
    with_calls = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[{"id": "1", "name": "t", "arguments": {"a": 1}}],
    )
    run(store.append_history(with_calls))
    assert store.history()[0].tool_calls == with_calls.tool_calls

    # 空列表必须原样往返（存 "[]"），不能被折叠成 None。
    run(store.append_history(ChatMessage(role="assistant", content="", tool_calls=[])))
    assert store.history()[1].tool_calls == []


def test_optional_fields_roundtrip(store) -> None:
    run(
        store.append_history(
            ChatMessage(role="tool", content="结果", tool_call_id="c1", name="t")
        )
    )
    m = store.history()[0]
    assert m.tool_call_id == "c1"
    assert m.name == "t"

    run(store.append_history(ChatMessage(role="user", content="")))
    missing = store.history()[1]
    assert missing.tool_call_id is None
    assert missing.name is None


# ---------- B 组：SqliteStore 专项 ----------

def test_persistence_across_instances(tmp_path) -> None:
    db = tmp_path / "p.db"
    first = SqliteStore(db)
    run(first.append_history(ChatMessage(role="user", content="持久的我")))
    run(first.put("k", "v"))
    first.close()

    second = SqliteStore(db)  # 重新打开同一文件，数据必须还在
    try:
        assert second.history()[0].content == "持久的我"
        assert run(second.get("k")) == "v"
    finally:
        second.close()


def test_scope_isolation_and_scoped_clear(tmp_path) -> None:
    db = tmp_path / "s.db"
    a = SqliteStore(db, scope="a")
    b = SqliteStore(db, scope="b")
    try:
        run(a.append_history(ChatMessage(role="user", content="A 的消息")))
        run(b.put("kb", "vb"))

        assert len(a.history()) == 1
        assert b.history() == []
        assert run(a.get("kb")) is None
        assert run(b.get("kb")) == "vb"

        run(a.clear())  # 只清 scope=a
        assert a.history() == []
        assert b.history() == []
        assert run(b.get("kb")) == "vb"  # b 的 KV 不受影响
    finally:
        a.close()
        b.close()


def test_memory_databases_are_independent() -> None:
    a = SqliteStore(":memory:")
    b = SqliteStore(":memory:")
    try:
        run(a.append_history(ChatMessage(role="user", content="只在 A")))
        assert len(a.history()) == 1
        assert b.history() == []
    finally:
        a.close()
        b.close()


def test_reinit_same_file_is_idempotent(tmp_path) -> None:
    db = tmp_path / "r.db"
    first = SqliteStore(db)
    run(first.put("k", "v"))
    first.close()

    second = SqliteStore(db)
    third = SqliteStore(db)  # 同文件重复构造：不报错、不丢数据
    try:
        assert run(second.get("k")) == "v"
        assert run(third.get("k")) == "v"
    finally:
        second.close()
        third.close()


def test_from_env_states(tmp_path) -> None:
    assert SqliteStore.from_env(env={}) is None
    assert SqliteStore.from_env(env={"YAI_DB_PATH": "   "}) is None

    store = SqliteStore.from_env(env={"YAI_DB_PATH": str(tmp_path / "env.db")})
    assert store is not None
    try:
        run(store.put("k", "v"))
        assert run(store.get("k")) == "v"
    finally:
        store.close()


def test_parent_dir_created(tmp_path) -> None:
    nested = tmp_path / "nested" / "deep" / "m.db"
    store = SqliteStore(nested)
    try:
        assert nested.parent.exists()
    finally:
        store.close()


def test_schema_version_baseline_and_future_guard(tmp_path) -> None:
    db = tmp_path / "v.db"
    store = SqliteStore(db)
    store.close()

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.execute("PRAGMA user_version = 2")  # 模拟"未来版本"数据库
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="schema 版本"):
        SqliteStore(db)


def test_operations_after_close_raise(tmp_path) -> None:
    store = SqliteStore(tmp_path / "c.db")
    store.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        store.history()


# ---------- C 组：Loop 集成（证明消费点零改动） ----------

class _OneShotModel:
    def __init__(self, content: str) -> None:
        self.content = content

    async def achat(self, messages, tools=None, *, tier="standard"):
        return ModelResponse(content=self.content)


class _CapturingModel:
    """记录第二轮真正发给模型的消息（dict 形态），用于断言历史回放。"""

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.seen.extend(messages)
        return ModelResponse(content="第二轮答复")


def test_loop_replays_persisted_history(tmp_path) -> None:
    store = SqliteStore(tmp_path / "loop.db")

    first = AgentCore(_OneShotModel("第一轮答复"), memory=store)
    r1 = asyncio.run(first.run("你好"))
    assert r1.final_text == "第一轮答复"

    second_model = _CapturingModel()
    second = AgentCore(second_model, memory=store)  # 复用同一个 store
    r2 = asyncio.run(second.run("在吗"))

    contents = [m["content"] for m in second_model.seen]
    # 第二轮上下文里必须能看到上一轮的 user 与 assistant（持久记忆的端到端证据）
    assert "你好" in contents
    assert "第一轮答复" in contents
    assert "在吗" in contents
    assert r2.final_text == "第二轮答复"
    store.close()
