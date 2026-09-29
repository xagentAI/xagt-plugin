from __future__ import annotations

import inspect
import json
from typing import Any

from yai_core.spi import Channel, PermissionDecision, PermissionPolicy
from yai_core.tools.registry import ToolRegistry
from yai_core.types import AgentEvent, EventType


class ToolExecutor:
    """Tool Bus：权限检查 -> 执行（同步/异步 handler 均可）-> 结构化结果。

    执行过程中产生的 Observer 事件由 execute 返回，
    由 AgentLoop 统一 yield（保证事件流只有一条路径）。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        channel: Channel,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.channel = channel

    async def execute(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[list[AgentEvent], bool, str]:
        """返回 (过程事件列表, 是否成功, 文本结果)，永不向 Agent Loop 抛异常。"""
        events: list[AgentEvent] = []
        if not self.registry.has(name):
            return events, False, f"工具 {name!r} 不存在"

        decision = await self.policy.check(name, arguments)
        if decision == PermissionDecision.ASK:
            events.append(
                AgentEvent(EventType.PERMISSION_ASKED, {"tool": name, "arguments": arguments})
            )
            approved = await self.channel.confirm(name, arguments)
            if not approved:
                return events, False, f"用户/宿主拒绝执行工具 {name}"
        if decision == PermissionDecision.DENY:
            return events, False, f"权限策略拒绝执行工具 {name}"

        events.append(AgentEvent(EventType.TOOL_CALL, {"tool": name, "arguments": arguments}))
        spec = self.registry.get(name)
        try:
            result = spec.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
            text = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 - 工具错误必须回灌给模型而不是崩溃
            events.append(
                AgentEvent(EventType.TOOL_RESULT, {"tool": name, "ok": False,
                                                   "error": str(exc)})
            )
            return events, False, f"工具 {name} 执行出错: {type(exc).__name__}: {exc}"

        events.append(
            AgentEvent(EventType.TOOL_RESULT, {"tool": name, "ok": True, "preview": text[:200]})
        )
        return events, True, text
