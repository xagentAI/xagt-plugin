from __future__ import annotations

from collections.abc import Iterable

from yai_core.types import ToolSpec


class ToolRegistry:
    """统一工具注册表：Native / OpenAPI / MCP 工具在此同构。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具 {spec.name!r} 已注册，名称必须唯一")
        self._tools[spec.name] = spec

    def register_many(self, specs: Iterable[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"未知工具 {name!r}，当前可用：{list(self._tools)}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def llm_schemas(self) -> list[dict]:
        return [spec.llm_schema() for spec in self._tools.values()]

    def describe(self) -> str:
        """给系统提示词用的工具清单文本。"""
        if not self._tools:
            return "（当前宿主没有提供任何工具）"
        return "\n".join(f"- {s.name}: {s.description}" for s in self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
