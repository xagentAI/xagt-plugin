"""OpenAI 兼容模型后端：DeepSeek / 通义千问 / OpenAI / 本地 vLLM 等同一套代码。"""

from __future__ import annotations

import json
import os
from typing import Any

from yai_core.types import ModelResponse, ToolCallRequest


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        strong_model: str | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "使用 OpenAICompatProvider 需要安装可选依赖：uv pip install -e '.[llm]'"
            ) from exc

        self.client = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY", "missing"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
        )
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self.strong_model = strong_model or os.getenv("LLM_STRONG_MODEL") or self.model

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        # messages 由 Context.llm_messages() 产出，已经是 OpenAI 线格式 dict
        kwargs: dict[str, Any] = {
            "model": self.strong_model if tier == "strong" else self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        completion = await self.client.chat.completions.create(**kwargs)
        msg = completion.choices[0].message

        tool_calls: list[ToolCallRequest] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))

        return ModelResponse(content=msg.content or "", tool_calls=tool_calls, raw=completion)
