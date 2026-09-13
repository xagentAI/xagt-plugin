"""Agent Loop：按 Adaptive Router 选定的策略执行任务。

- direct: 一次模型调用直接回答
- react:  推理 <-> 工具调用循环，直到模型不再调用工具
- plan:   先生成步骤计划，再带计划进入 react 循环
- clarify: 通过 Channel 反问后重新路由
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from yai_core.kernel.context import Context
from yai_core.kernel.router import AdaptiveRouter
from yai_core.spi import Channel, MemoryStore, ModelProvider
from yai_core.tools.executor import ToolExecutor
from yai_core.tools.registry import ToolRegistry
from yai_core.types import (
    AgentEvent,
    ChatMessage,
    EventType,
    Strategy,
)

_SYSTEM_TEMPLATE = """你是运行在宿主软件内部的 AI 助手。\
你只能通过"工具"操作宿主的能力，不要编造工具不存在的数据。\
当任务完成时，直接给出可交付的最终结果。

宿主当前提供的能力：
{tools}
"""


class AgentLoop:
    def __init__(
        self,
        model: ModelProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        channel: Channel,
        memory: MemoryStore,
        router: AdaptiveRouter | None = None,
        *,
        max_iters: int = 6,
    ) -> None:
        self.model = model
        self.registry = registry
        self.executor = executor
        self.channel = channel
        self.memory = memory
        self.router = router or AdaptiveRouter()
        self.max_iters = max_iters

    async def astream(self, task: str) -> AsyncIterator[AgentEvent]:
        decision = await self.router.aclassify(task, self.registry)
        strategy = decision.strategy
        # 决策来源（llm/rules）、理由与模型档位随事件流出：每次自适应决策都可审计。
        yield AgentEvent(
            EventType.STRATEGY_SELECTED,
            {
                "strategy": strategy.value,
                "source": decision.source,
                "reason": decision.reason,
                "tier": decision.tier,
            },
        )

        if strategy == Strategy.CLARIFY:
            yield AgentEvent(EventType.CLARIFY_REQUESTED, {"question": task})
            answer = await self.channel.ask(task)
            async for ev in self.astream(answer):
                yield ev
            return

        ctx = Context(_SYSTEM_TEMPLATE.format(tools=self.registry.describe()))
        for msg in self.memory.history():
            ctx.add(msg)
        ctx.add(ChatMessage(role="user", content=task))

        if strategy == Strategy.PLAN:
            async for ev in self._make_plan(ctx, task, tier=decision.tier):
                yield ev
            # 计划只是"助手说过的话"，必须再推一把，模型才会进入工具执行；
            # 否则真实模型会把计划本身当成最终答复（离线脚本模型曾掩盖此问题）。
            ctx.add(
                ChatMessage(
                    role="user",
                    content="请按上面的计划逐步调用工具执行，拿到全部结果后给出最终汇报。",
                )
            )

        final_text = ""
        async for ev in self._react_cycle(ctx, use_tools=strategy != Strategy.DIRECT):
            yield ev
            if ev.type == EventType.MODEL_MESSAGE:
                final_text = ev.data.get("text", final_text)

        await self.memory.append_history(ChatMessage(role="user", content=task))
        await self.memory.append_history(ChatMessage(role="assistant", content=final_text))
        yield AgentEvent(EventType.DONE, {"strategy": strategy.value, "final_text": final_text})

    async def _make_plan(
        self, ctx: Context, task: str, *, tier: str = "strong"
    ) -> AsyncIterator[AgentEvent]:
        prompt = (
            "把下面的任务拆成 2-5 个可执行步骤，每行一个步骤，用 1. 2. 3. 编号，"
            "只输出步骤本身：\n" + task
        )
        ctx.add(ChatMessage(role="user", content=prompt))
        # 档位由路由器建议（LLM 路由可给 standard/strong），规则路由的 plan 默认 strong。
        resp = await self.model.achat(ctx.llm_messages(), tools=None, tier=tier)
        steps = [s.strip() for s in re.findall(r"\d+[.、)]\s*(.+)", resp.content)]
        if not steps:
            steps = [task]
        plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
        ctx.add(ChatMessage(role="assistant", content=plan_text))
        yield AgentEvent(EventType.PLAN_CREATED, {"steps": steps})

    async def _react_cycle(
        self, ctx: Context, *, use_tools: bool
    ) -> AsyncIterator[AgentEvent]:
        tools_schema = self.registry.llm_schemas() if use_tools else None
        for _ in range(self.max_iters):
            try:
                resp = await self.model.achat(ctx.llm_messages(), tools=tools_schema)
            except Exception as exc:  # noqa: BLE001
                yield AgentEvent(EventType.ERROR, {"error": f"{type(exc).__name__}: {exc}"})
                return

            if not resp.tool_calls:
                text = resp.content.strip()
                ctx.add(ChatMessage(role="assistant", content=text))
                yield AgentEvent(EventType.MODEL_MESSAGE, {"text": text})
                return

            ctx.add(
                ChatMessage(
                    role="assistant",
                    content=resp.content,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(
                                tc.arguments, ensure_ascii=False
                            )},
                        }
                        for tc in resp.tool_calls
                    ],
                )
            )
            for call in resp.tool_calls:
                tool_events, ok, result_text = await self.executor.execute(
                    call.name, call.arguments
                )
                for tool_event in tool_events:
                    yield tool_event
                ctx.add(
                    ChatMessage(
                        role="tool",
                        content=result_text,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        # 达到迭代上限：要求模型基于已有观察收尾
        ctx.add(
            ChatMessage(
                role="user",
                content="已达到工具调用上限，请基于已有结果直接给出最终答案。",
            )
        )
        resp = await self.model.achat(ctx.llm_messages(), tools=None)
        yield AgentEvent(EventType.MODEL_MESSAGE, {"text": resp.content.strip()})
