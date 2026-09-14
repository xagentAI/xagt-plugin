from __future__ import annotations

from collections.abc import Iterable

from yai_core.spi import PermissionDecision


class AllowlistPolicy:
    """默认权限策略。

    - mode="auto": 白名单内工具自动放行，其余询问
    - mode="allow_all": 全部自动放行（本地演示/测试用）
    - mode="deny_all": 除白名单外全部拒绝
    """

    def __init__(
        self,
        allowed: Iterable[str] = (),
        *,
        mode: str = "auto",
    ) -> None:
        self.allowed = set(allowed)
        self.mode = mode

    async def check(self, tool_name: str, arguments: dict) -> PermissionDecision:
        if tool_name in self.allowed:
            return PermissionDecision.ALLOW
        if self.mode == "allow_all":
            return PermissionDecision.ALLOW
        if self.mode == "deny_all":
            return PermissionDecision.DENY
        return PermissionDecision.ASK
