"""Context._compact 轮边界丢弃专项：压缩不得拆散 assistant(tool_calls)/tool 对。"""

from __future__ import annotations

from yai_core.kernel.context import Context
from yai_core.types import ChatMessage


def _tool_round(marker: str, big: int) -> list[ChatMessage]:
    """构造一轮含工具调用的历史：user(大) -> assistant(tool_calls) -> tool(大)。"""
    return [
        ChatMessage(role="user", content=marker * big),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": marker, "name": "t", "arguments": {}}],
        ),
        ChatMessage(role="tool", content=marker * big, tool_call_id=marker),
    ]


def test_compact_drops_whole_round_and_keeps_system() -> None:
    ctx = Context("系统提示", max_chars=10)
    ctx.messages.extend(_tool_round("旧", 50))
    ctx.messages.extend(
        [
            ChatMessage(role="user", content="新任务"),
            ChatMessage(role="assistant", content="完成"),
        ]
    )
    ctx._compact()
    assert [m.role for m in ctx.messages] == ["system", "user", "assistant"]
    assert ctx.messages[0].content == "系统提示"
    assert ctx.messages[1].content == "新任务"


def test_compact_within_budget_unchanged() -> None:
    ctx = Context("系统提示", max_chars=24000)
    ctx.messages.extend(_tool_round("x", 10))
    before = list(ctx.messages)
    ctx._compact()
    assert ctx.messages == before


def test_compact_keeps_last_round_even_if_over_budget() -> None:
    ctx = Context("系统提示", max_chars=10)
    ctx.messages.extend(_tool_round("大", 50))  # 只有一轮且超预算
    ctx._compact()
    # 宁可超预算也不裁：system + 完整工具轮（4 条）
    assert [m.role for m in ctx.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


def test_compact_triggered_via_add_path() -> None:
    ctx = Context("系统提示", max_chars=10)
    ctx.messages.extend(_tool_round("旧", 50))
    # 公共 add 路径追加新一轮时触发压缩，旧工具轮整轮消失、新轮完整
    ctx.add(ChatMessage(role="user", content="新"))
    ctx.add(ChatMessage(role="assistant", content="好"))
    roles = [m.role for m in ctx.messages]
    assert roles[0] == "system"
    assert "tool" not in roles  # 旧工具轮被整轮删掉，没有孤儿 tool 残留
    assert roles[-2:] == ["user", "assistant"]
