"""权限策略契约：高风险工具调用必须可被宿主拦截/确认。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@runtime_checkable
class PermissionPolicy(Protocol):
    async def check(self, tool_name: str, arguments: dict[str, Any]) -> PermissionDecision: ...
