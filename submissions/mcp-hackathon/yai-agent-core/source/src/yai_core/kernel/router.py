"""Adaptive Router：把任务路由到 direct / react / plan / clarify。

v0.1 使用确定性规则（可测试、零成本、离线可跑）；
v0.2 增加 LLM 分类器（一次轻量模型调用，输出结构化策略 JSON），
     分类失败时自动回退到本规则实现——这就是"模型自适应"的兜底设计。

- classify()：纯规则，同步、零成本、永远可用（最终兜底）；
- aclassify()：优先 LLM 分类（配置了模型时），任何异常/超时/非法输出都回退规则。
  两条路径都返回 RouteDecision（策略 + 决策来源 + 理由 + 模型档位），
  保证"每一次自适应决策都可观测、可解释"。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from yai_core.tools.registry import ToolRegistry
from yai_core.types import Strategy

# 多步骤信号：出现时倾向先规划再执行
_PLAN_HINTS = (
    "然后", "接着", "之后", "再把", "分步", "步骤", "先", "并且", "同时",
    "对比", "整理成", "汇总成", "最终", "一共", "分别",
)
# 行动信号：需要调用工具
_ACTION_HINTS = (
    "查", "找", "搜", "列出", "统计", "计算", "导出", "获取", "读取",
    "记录", "新增", "整理", "分析", "筛选", "生成",
    # 显式的工具/MCP 调用意图（v0.2 接外部 MCP Server 后补齐）
    "问一下", "查询", "调用", "工具", "mcp",
)
# 过于模糊、需要反问
_CLARIFY_HINTS = ("随便", "你看着办", "什么都行", "帮我弄一下")


@dataclass
class RouteDecision:
    """一次路由决策的完整记录：策略、决策来源、理由、建议模型档位。"""

    strategy: Strategy
    source: str  # "llm"：模型分类；"rules"：规则（含 LLM 失败后的兜底）
    reason: str
    tier: str = "standard"  # "standard"（便宜快）/ "strong"（规划等重活）


class AdaptiveRouter:
    def __init__(
        self,
        *,
        min_plan_steps: int = 2,
        model: object | None = None,
        classify_timeout: float = 15.0,
    ) -> None:
        self.min_plan_steps = min_plan_steps
        # model 可选：注入了才启用 LLM 分类；不注入时 aclassify 直接走规则。
        self.model = model
        self.classify_timeout = classify_timeout

    # ---------- 规则路径（同步、永远可用的兜底） ----------

    def classify(self, task: str, registry: ToolRegistry) -> Strategy:
        return self._rules(task, registry).strategy

    def _rules(self, task: str, registry: ToolRegistry) -> RouteDecision:
        text = task.strip()
        if not text:
            return RouteDecision(Strategy.CLARIFY, "rules", "任务为空，需要反问澄清")
        if any(h in text for h in _CLARIFY_HINTS) and len(text) < 12:
            return RouteDecision(Strategy.CLARIFY, "rules", "任务过于模糊，先澄清")
        if len(registry) == 0:
            # 宿主没有任何能力 -> 只能直接回答（能力边界优先于用户意图）
            return RouteDecision(Strategy.DIRECT, "rules", "宿主无任何工具，直接回答")
        # 拉丁字母提示词（如 mcp）大小写不敏感；中文提示词按原文匹配。
        lowered = text.lower()
        wants_action = any(
            (h in lowered) if h.isascii() else (h in text) for h in _ACTION_HINTS
        )
        multi_step = sum(1 for h in _PLAN_HINTS if h in text) >= 1
        if multi_step and wants_action:
            return RouteDecision(
                Strategy.PLAN, "rules", "命中多步骤+行动信号，先规划再执行", "strong"
            )
        if wants_action:
            return RouteDecision(Strategy.REACT, "rules", "命中行动信号，进入工具循环")
        # 有工具但任务像闲聊/问答：直接答（模型仍可在 react 循环里自行决定用工具）
        return RouteDecision(Strategy.DIRECT, "rules", "无需工具的直接问答")

    # ---------- LLM 路径（失败一律回退规则） ----------

    async def aclassify(self, task: str, registry: ToolRegistry) -> RouteDecision:
        text = task.strip()
        # 空任务、未配置模型、宿主无工具：直接走规则，不浪费一次模型调用。
        if not text or self.model is None or len(registry) == 0:
            return self._rules(task, registry)
        try:
            raw = await asyncio.wait_for(
                self._llm_classify(text, registry), timeout=self.classify_timeout
            )
            decision = self._parse(raw, registry)
            return decision
        except Exception as exc:  # noqa: BLE001 - 分类是增强不是依赖，任何失败都兜底
            fallback = self._rules(task, registry)
            fallback.reason = f"LLM 分类失败（{type(exc).__name__}），回退规则：{fallback.reason}"
            return fallback

    async def _llm_classify(self, task: str, registry: ToolRegistry) -> str:
        """一次轻量模型调用，要求只输出路由 JSON。"""
        tools_text = "\n".join(
            f"- {s.name}: {s.description}" for s in registry.all()
        )
        prompt = (
            "你是嵌入式 Agent 的任务路由器。根据任务与宿主可用工具，只输出一个 JSON 对象，"
            "不要输出 JSON 以外的任何内容：\n"
            '{"strategy": "direct|react|plan|clarify", '
            '"tier": "standard|strong", "reason": "不超过30字的中文理由"}\n'
            "策略判定标准：\n"
            "- direct：闲聊、知识问答、写作、解释，不需要调用工具；\n"
            "- react：需要调用工具（查询/搜索/计算/读取/调用 MCP 等），单步即可完成；\n"
            "- plan：明显多步骤、需要先拆解计划再逐步执行；\n"
            "- clarify：任务过于模糊、缺少必要对象，无法执行。\n"
            f"宿主可用工具：\n{tools_text}\n"
            f"任务：{task}"
        )
        messages = [
            {"role": "system", "content": "你是严谨的路由器，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ]
        resp = await self.model.achat(messages, tools=None, tier="standard")
        return resp.content

    def _parse(self, content: str, registry: ToolRegistry) -> RouteDecision:
        """解析模型输出为 RouteDecision；非法/越界输出抛异常交 aclassify 兜底。"""
        text = content.strip()
        # 容忍模型套 ```json 代码块或在 JSON 前后啰嗦：截取第一个 { 到最后一个 }。
        fenced = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if fenced is None:
            raise ValueError("分类输出中没有 JSON 对象")
        data = json.loads(fenced.group(0))
        strategy_value = data.get("strategy")
        if strategy_value not in {s.value for s in Strategy}:
            raise ValueError(f"非法策略值：{strategy_value!r}")
        strategy = Strategy(strategy_value)
        # 能力边界兜底：模型让调工具但宿主没有工具，强制 direct。
        if len(registry) == 0 and strategy in (Strategy.REACT, Strategy.PLAN):
            raise ValueError("宿主无工具却被路由到工具策略")
        tier = data.get("tier", "standard")
        if tier not in ("standard", "strong"):
            tier = "standard"
        reason = str(data.get("reason") or "").strip() or "LLM 分类（模型未给理由）"
        return RouteDecision(strategy, "llm", reason, tier)
