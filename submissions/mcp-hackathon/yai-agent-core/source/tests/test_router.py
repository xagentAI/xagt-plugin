import asyncio

import pytest

from yai_core import AdaptiveRouter, ModelResponse, Strategy, ToolRegistry, build_spec


def _registry_with_tools() -> ToolRegistry:
    reg = ToolRegistry()

    def search_notes(keyword: str) -> list:
        """搜索笔记。"""
        return []

    reg.register(build_spec(search_notes))
    return reg


class ScriptedClassifier:
    """测试用分类模型：返回预设内容，可记录调用并可模拟异常/超时。"""

    def __init__(self, content: str = "", *, raises: Exception | None = None,
                 sleep: float = 0.0) -> None:
        self._content = content
        self._raises = raises
        self._sleep = sleep
        self.calls = 0
        self.tiers: list[str] = []

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.calls += 1
        self.tiers.append(tier)
        if self._raises is not None:
            raise self._raises
        if self._sleep:
            await asyncio.sleep(self._sleep)
        return ModelResponse(content=self._content)


def test_no_tools_goes_direct() -> None:
    router = AdaptiveRouter()
    assert router.classify("你好", ToolRegistry()) == Strategy.DIRECT


def test_action_goes_react() -> None:
    router = AdaptiveRouter()
    assert router.classify("搜索笔记里关于周报的内容", _registry_with_tools()) == Strategy.REACT


def test_multistep_goes_plan() -> None:
    router = AdaptiveRouter()
    task = "先搜索订单，然后统计数量并整理成报告"
    assert router.classify(task, _registry_with_tools()) == Strategy.PLAN


def test_vague_goes_clarify() -> None:
    router = AdaptiveRouter()
    assert router.classify("随便", _registry_with_tools()) == Strategy.CLARIFY


def test_explicit_mcp_intent_goes_react() -> None:
    # 显式要求用（MCP）工具提问，即使没有"查/搜"等动词也必须进工具循环，
    # 否则 direct 路径不传 tools，模型只能把工具调用写成文本（v0.2 实测回归）。
    router = AdaptiveRouter()
    task = "用 MCP 工具问一下 GitHub 仓库 python-sdk：Client 怎么初始化？"
    assert router.classify(task, _registry_with_tools()) == Strategy.REACT


def test_explicit_mcp_intent_case_insensitive() -> None:
    router = AdaptiveRouter()
    assert router.classify("调用 mcp 工具查询天气", _registry_with_tools()) == Strategy.REACT


def test_mcp_multistep_goes_plan() -> None:
    router = AdaptiveRouter()
    task = "先用 MCP 工具问一下这个仓库的结构，然后整理成一句话总结"
    assert router.classify(task, _registry_with_tools()) == Strategy.PLAN


# ---------- aclassify：LLM 分类 + 规则兜底 ----------

def test_aclassify_without_model_uses_rules() -> None:
    router = AdaptiveRouter()
    decision = asyncio.run(router.aclassify("搜索笔记", _registry_with_tools()))
    assert decision.source == "rules"
    assert decision.strategy == Strategy.REACT


def test_aclassify_llm_valid_decision() -> None:
    model = ScriptedClassifier(
        '{"strategy": "react", "tier": "standard", "reason": "需要调用搜索工具"}'
    )
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("帮我看看笔记里有啥", _registry_with_tools()))
    assert decision.source == "llm"
    assert decision.strategy == Strategy.REACT
    assert decision.tier == "standard"
    assert "搜索工具" in decision.reason
    assert model.calls == 1  # 只做一次轻量分类调用


def test_aclassify_llm_tolerates_fences_and_prose() -> None:
    model = ScriptedClassifier('好的，结果如下：\n```json\n{"strategy": "plan", '
                               '"tier": "strong", "reason": "多步任务"}\n```')
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("先查再汇总", _registry_with_tools()))
    assert decision.strategy == Strategy.PLAN and decision.tier == "strong"


def test_aclassify_llm_garbage_falls_back_to_rules() -> None:
    model = ScriptedClassifier("我不太确定你在说什么")
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("搜索笔记里的周报", _registry_with_tools()))
    assert decision.source == "rules"  # 解析失败 -> 规则兜底
    assert decision.strategy == Strategy.REACT
    assert "回退" in decision.reason


def test_aclassify_llm_exception_falls_back_to_rules() -> None:
    model = ScriptedClassifier(raises=RuntimeError("network down"))
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("搜索笔记", _registry_with_tools()))
    assert decision.source == "rules" and decision.strategy == Strategy.REACT


def test_aclassify_llm_timeout_falls_back_to_rules() -> None:
    model = ScriptedClassifier('{"strategy": "react"}', sleep=0.3)
    router = AdaptiveRouter(model=model, classify_timeout=0.05)
    decision = asyncio.run(router.aclassify("搜索笔记", _registry_with_tools()))
    assert decision.source == "rules" and decision.strategy == Strategy.REACT


def test_aclassify_llm_invalid_strategy_falls_back() -> None:
    model = ScriptedClassifier('{"strategy": "fly-to-moon", "reason": "瞎编"}')
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("搜索笔记", _registry_with_tools()))
    assert decision.source == "rules"


def test_aclassify_no_tools_skips_model_call() -> None:
    # 能力边界优先：宿主没工具时，连分类模型都不该调用。
    model = ScriptedClassifier('{"strategy": "react"}')
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("搜索一下", ToolRegistry()))
    assert decision.strategy == Strategy.DIRECT and model.calls == 0


def test_aclassify_empty_task_skips_model_call() -> None:
    model = ScriptedClassifier('{"strategy": "clarify"}')
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("   ", _registry_with_tools()))
    assert decision.strategy == Strategy.CLARIFY and model.calls == 0


def test_rules_plan_defaults_to_strong_tier() -> None:
    router = AdaptiveRouter()
    decision = asyncio.run(
        router.aclassify("先搜索订单，然后统计数量并整理成报告", _registry_with_tools())
    )
    assert decision.strategy == Strategy.PLAN and decision.tier == "strong"


@pytest.mark.parametrize("bad_tier", ["ultra", "", 3])
def test_aclassify_bad_tier_normalizes(bad_tier) -> None:
    model = ScriptedClassifier(f'{{"strategy": "react", "tier": "{bad_tier}"}}')
    router = AdaptiveRouter(model=model)
    decision = asyncio.run(router.aclassify("查笔记", _registry_with_tools()))
    assert decision.tier == "standard"
