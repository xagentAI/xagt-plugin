from __future__ import annotations

import asyncio

from yai_core.types import AgentEvent, EventType

_LABELS = {
    EventType.STRATEGY_SELECTED: "策略",
    EventType.PLAN_CREATED: "计划",
    EventType.MODEL_MESSAGE: "回复",
    EventType.TOOL_CALL: "调用工具",
    EventType.TOOL_RESULT: "工具结果",
    EventType.PERMISSION_ASKED: "权限确认",
    EventType.CLARIFY_REQUESTED: "需要澄清",
    EventType.ERROR: "错误",
}


class CliChannel:
    """终端通道：把 Observer 事件流打印成人可读的过程。"""

    async def emit(self, event: AgentEvent) -> None:
        label = _LABELS.get(event.type, event.type.value)
        if event.type == EventType.TOOL_CALL:
            print(f"  [{label}] {event.data['tool']}({event.data['arguments']})")
        elif event.type == EventType.STRATEGY_SELECTED:
            print(f"  [{label}] {event.data['strategy']}")
        elif event.type == EventType.MODEL_MESSAGE:
            print(f"  [{label}] {event.data.get('text', '')}")
        else:
            print(f"  [{label}] {event.data}")

    async def ask(self, question: str) -> str:
        return await asyncio.to_thread(input, f"  [澄清] {question} > ")

    async def confirm(self, tool_name: str, arguments: dict) -> bool:
        answer = await asyncio.to_thread(
            input, f"  [确认] 允许执行 {tool_name}({arguments})? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes", "是")
