"""模型提供者契约：Core 不绑定任何模型厂商。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from yai_core.types import ModelResponse


@runtime_checkable
class ModelProvider(Protocol):
    """任何实现该协议的对象都可作为 Core 的模型后端。

    - OpenAI 兼容实现见 ``yai_core.llm.openai_compat``
    - 测试/离线演示可使用脚本化假模型
    """

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        """单轮对话。

        Args:
            messages: OpenAI 线格式消息字典列表（由 Context.llm_messages() 产出）。
            tools: OpenAI 形状的工具描述列表；None 表示本轮不提供工具。
            tier: "standard" / "strong"，供模型路由（便宜模型 vs 强模型）。
        """
        ...
