from __future__ import annotations

from yai_core.types import AgentEvent


class CollectChannel:
    """收集全部事件的通道：测试、API Battery、批处理使用。"""

    def __init__(self, *, auto_confirm: bool = True, default_answer: str = "") -> None:
        self.events: list[AgentEvent] = []
        self.auto_confirm = auto_confirm
        self.default_answer = default_answer

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    async def ask(self, question: str) -> str:
        return self.default_answer

    async def confirm(self, tool_name: str, arguments: dict) -> bool:
        return self.auto_confirm
