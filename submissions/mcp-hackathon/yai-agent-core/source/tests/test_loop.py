"""端到端测试：用脚本化假模型离线验证 react 循环，不需要 API Key。"""

import asyncio

from yai_core import AgentCore, ModelResponse, ToolCallRequest, build_spec


class ScriptedModel:
    """按预设顺序返回响应的假模型，用于离线测试。"""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def achat(self, messages, tools=None, *, tier="standard"):
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


NOTES = {"周报": ["周一完成 Core 骨架", "周三跑通工具调用"], "其他": ["买菜"]}


def search_notes(keyword: str) -> list:
    """搜索宿主笔记库。"""
    return NOTES.get(keyword, [])


def test_react_loop_calls_tool_and_finishes() -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="search_notes",
                                            arguments={"keyword": "周报"})],
            ),
            ModelResponse(content="本周周报包含 2 条记录：Core 骨架、工具调用。"),
        ]
    )
    core = AgentCore(model)
    core.register_tools([build_spec(search_notes)])

    result = asyncio.run(core.run("搜索笔记里关于周报的内容并总结"))

    event_types = [e.type.value for e in result.events]
    assert "strategy_selected" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert event_types[-1] == "done"
    assert "周报" in result.final_text
    assert model.calls == 2


def test_plan_strategy_still_executes_tools() -> None:
    """回归：plan 拆完步骤后必须真正进入工具循环，不能把计划当最终答复。"""

    def search_notes(keyword: str) -> list:
        """搜索宿主笔记库。"""
        return ["X-Agent 0919 截止"] if keyword == "比赛" else []

    model = ScriptedModel(
        [
            ModelResponse(content="1. 搜索比赛笔记\n2. 统计总数并汇报"),  # 规划轮（无 tools）
            ModelResponse(
                content="",
                tool_calls=[ToolCallRequest(id="p1", name="search_notes",
                                            arguments={"keyword": "比赛"})],
            ),
            ModelResponse(content="找到 1 条比赛相关笔记。"),
        ]
    )
    core = AgentCore(model)
    core.register_tools([build_spec(search_notes)])

    result = asyncio.run(core.run("先搜索比赛笔记，然后汇报"))

    assert result.strategy.value == "plan"
    event_types = [e.type.value for e in result.events]
    assert "plan_created" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "比赛" in result.final_text


def test_direct_answer_without_tools() -> None:
    model = ScriptedModel([ModelResponse(content="你好，我是内嵌助手。")])
    core = AgentCore(model)
    result = asyncio.run(core.run("你好"))
    assert result.strategy.value == "direct"
    assert result.final_text.startswith("你好")


def test_llm_router_decision_flows_through_loop() -> None:
    """开启 llm_router 后：分类来源/理由/档位进事件，plan 用分类建议的 strong 档。"""

    class ClassifierThenPlan(ScriptedModel):
        async def achat(self, messages, tools=None, *, tier="standard"):
            self.tiers.append(tier)
            self.calls += 1
            # 第 1 次调用是路由分类（系统提示含"路由器"）
            if self.calls == 1:
                return ModelResponse(
                    content='{"strategy": "plan", "tier": "strong",'
                    ' "reason": "先拆解再执行"}'
                )
            # 第 2 次是规划轮
            if self.calls == 2:
                return ModelResponse(content="1. 搜索比赛笔记\n2. 汇报结果")
            # 之后走父类的脚本队列（工具调用 + 最终答复）
            return self._responses[min(self.calls - 1, len(self._responses) - 1)]

        def __init__(self, responses) -> None:
            super().__init__(responses)
            self.tiers = []

    model = ClassifierThenPlan(
        [
            ModelResponse(
                content="",
                tool_calls=[ToolCallRequest(id="p1", name="search_notes",
                                            arguments={"keyword": "比赛"})],
            ),
            ModelResponse(content="找到 1 条比赛笔记。"),
        ]
    )
    core = AgentCore(model, llm_router=True)
    core.register_tools([build_spec(search_notes)])

    result = asyncio.run(core.run("先搜索比赛笔记，然后汇报"))

    selected = next(e for e in result.events if e.type.value == "strategy_selected")
    assert selected.data["source"] == "llm"
    assert selected.data["strategy"] == "plan"
    assert selected.data["tier"] == "strong"
    # 分类用 standard（轻量快），规划轮按建议用 strong，工具循环回 standard
    assert model.tiers[0] == "standard"
    assert model.tiers[1] == "strong"
    assert result.final_text.startswith("找到")
