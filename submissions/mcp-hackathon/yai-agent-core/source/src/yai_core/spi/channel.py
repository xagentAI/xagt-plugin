"""通道契约：Core 不假设 UI 形态（CLI / Web / Flutter 都实现同一接口）。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from yai_core.types import AgentEvent


@runtime_checkable
class Channel(Protocol):
    async def emit(self, event: AgentEvent) -> None:
        """接收 Observer 事件流（思考过程、工具状态、错误等）。"""
        ...

    async def ask(self, question: str) -> str:
        """策略为 clarify 时，向宿主/用户反问并取回回答。"""
        ...

    async def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """权限策略为 ask 时，请求宿主确认是否执行该工具。"""
        ...
