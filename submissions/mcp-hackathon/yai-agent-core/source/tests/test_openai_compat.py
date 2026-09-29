"""OpenAICompatProvider 协议层测试：用假 openai 模块离线验证 DeepSeek 同款链路。

不发任何网络请求，验证四件事：
1. 第一次请求携带 OpenAI function-calling 的 tools 描述；
2. provider 能把 SDK 返回的 tool_calls 解析成 ToolCallRequest；
3. 宿主函数被真正执行；
4. 第二次请求把结果以 role="tool" + tool_call_id 回灌（DeepSeek/OpenAI 硬性协议）。
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from yai_core import AgentCore, OpenAICompatProvider, build_spec

# ---------- 假 openai SDK ----------

class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeCompletions:
    def __init__(self, script: list[_FakeMessage], captured: list[dict[str, Any]]) -> None:
        self._script = script
        self._captured = captured
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        self._captured.append(kwargs)
        message = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return types.SimpleNamespace(choices=[_FakeChoice(message)])


class _FakeAsyncOpenAI:
    script: list[_FakeMessage] = []
    captured: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(_FakeAsyncOpenAI.script, _FakeAsyncOpenAI.captured)
        )


def _install_fake_openai(
    monkeypatch, script: list[_FakeMessage], captured: list[dict[str, Any]]
) -> None:
    _FakeAsyncOpenAI.script = script
    _FakeAsyncOpenAI.captured = captured
    fake_module = types.ModuleType("openai")
    fake_module.AsyncOpenAI = _FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_module)


# ---------- 宿主能力（普通函数） ----------

def count_notes() -> int:
    """统计笔记总数。"""
    return 3


def test_tool_call_roundtrip_and_tool_message_feedback(monkeypatch) -> None:
    script = [
        # 第一轮：模型决定调 count_notes
        _FakeMessage(None, [_FakeToolCall("call_1", "count_notes", "{}")]),
        # 第二轮：模型拿到工具结果后收尾
        _FakeMessage("你一共有 3 条笔记。", None),
    ]
    captured: list[dict[str, Any]] = []
    _install_fake_openai(monkeypatch, script, captured)

    provider = OpenAICompatProvider(api_key="test-key", base_url="http://localhost:1234")
    core = AgentCore(provider)
    core.register_tools([build_spec(count_notes)])

    result = asyncio.run(core.run("统计一下笔记数量"))

    event_types = [e.type.value for e in result.events]
    assert result.strategy.value == "react"
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "3 条" in result.final_text

    # 第一次请求必须带 tools 清单，且形状是 OpenAI function-calling 规范
    first_request = captured[0]
    assert first_request["tools"][0]["type"] == "function"
    assert first_request["tools"][0]["function"]["name"] == "count_notes"

    # 第二次请求必须把工具结果以 role=tool 回灌，id 与模型下发的一致
    second_messages = captured[1]["messages"]
    tool_messages = [m for m in second_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[0]["content"] == "3"


def test_plain_answer_sends_no_tools(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    _install_fake_openai(monkeypatch, [_FakeMessage("你好，我是内嵌助手。", None)], captured)

    provider = OpenAICompatProvider(api_key="test-key", base_url="http://localhost:1234")
    core = AgentCore(provider)
    result = asyncio.run(core.run("你好"))

    assert result.strategy.value == "direct"
    assert result.final_text.startswith("你好")
    # direct 策略不应下发 tools
    assert "tools" not in captured[0]
