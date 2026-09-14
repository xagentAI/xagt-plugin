"""AgentCore 门面：宿主接入的唯一入口。

    from yai_core import AgentCore
    core = AgentCore.auto(my_app)          # 内省宿主能力，自动注册工具
    result = await core.run("整理本周笔记")  # 自适应选策略/工具/模型
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from yai_core.channels import CollectChannel
from yai_core.discovery import discover
from yai_core.kernel import AdaptiveRouter, AgentLoop
from yai_core.memory import InMemoryStore
from yai_core.policy import AllowlistPolicy
from yai_core.spi import Channel, MemoryStore, ModelProvider, PermissionPolicy
from yai_core.tools import ToolExecutor, ToolRegistry
from yai_core.types import AgentEvent, RunResult, ToolSpec


class AgentCore:
    def __init__(
        self,
        model: ModelProvider,
        *,
        channel: Channel | None = None,
        memory: MemoryStore | None = None,
        policy: PermissionPolicy | None = None,
        router: AdaptiveRouter | None = None,
        auto_approve_tools: bool = True,
        llm_router: bool = False,
    ) -> None:
        self.model = model
        self.registry = ToolRegistry()
        self.channel = channel or CollectChannel()
        self.memory = memory or InMemoryStore()
        self.policy = policy or AllowlistPolicy(mode="allow_all" if auto_approve_tools else "auto")
        # llm_router=True 时把模型注入路由器：先 LLM 分类、失败回退规则；
        # 默认关闭，保持零额外模型调用、离线测试完全确定。
        if router is not None:
            self.router = router
        else:
            self.router = AdaptiveRouter(model=model if llm_router else None)
        self.executor = ToolExecutor(self.registry, self.policy, self.channel)
        self._loop = AgentLoop(
            model=self.model,
            registry=self.registry,
            executor=self.executor,
            channel=self.channel,
            memory=self.memory,
            router=self.router,
        )

    # ---------- 接入 ----------

    @classmethod
    def auto(cls, host: object, model: ModelProvider, **kwargs: object) -> AgentCore:
        """内省宿主模块/对象，自动发现并注册全部公开能力。"""
        core = cls(model, **kwargs)  # type: ignore[arg-type]
        core.register_tools(discover(host))
        return core

    def register_tools(self, specs: list[ToolSpec]) -> None:
        self.registry.register_many(specs)

    def list_tools(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description, "source": s.source}
            for s in self.registry.all()
        ]

    # ---------- 运行 ----------

    async def astream(self, task: str) -> AsyncIterator[AgentEvent]:
        async for event in self._loop.astream(task):
            await self.channel.emit(event)
            yield event

    async def run(self, task: str) -> RunResult:
        events: list[AgentEvent] = []
        final_text = ""
        strategy = None
        async for event in self.astream(task):
            events.append(event)
            data = event.data
            if "strategy" in data:
                from yai_core.types import Strategy

                strategy = Strategy(data["strategy"])
            if event.type.value == "done":
                final_text = data.get("final_text", "")
        return RunResult(
            strategy=strategy or self.router.classify(task, self.registry),
            events=events,
            final_text=final_text,
        )
