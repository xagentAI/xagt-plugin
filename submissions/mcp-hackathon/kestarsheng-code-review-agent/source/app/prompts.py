# -*- coding: utf-8 -*-
"""Prompt templates for the dual-engine code review system."""

SYSTEM_PROMPT = """\
你是一名资深软件架构师与代码评审专家，擅长从正确性、安全性、性能、\
可维护性和最佳实践五个维度评审代码。你输出的评审结论必须基于代码事实，\
不得臆造。请以严格的 JSON 格式输出评审报告，不要输出任何 JSON 以外的内容。
"""

SYSTEM_PROMPT_WITH_RULES = """\
你是一名资深软件架构师与代码评审专家。你正在与一个规则引擎协同工作——\
规则引擎已通过静态模式匹配发现了若干已知问题（见下方"规则引擎预检结果"）。\
你的任务是：
1. 确认或否定规则引擎的发现（若规则误报请在 issues 中说明）
2. 发现规则引擎无法检测的语义问题（逻辑错误、架构缺陷、业务逻辑等）
3. 从正确性、安全性、性能、可维护性、最佳实践五个维度综合评审

你输出的评审结论必须基于代码事实，不得臆造。\
请以严格的 JSON 格式输出评审报告，不要输出任何 JSON 以外的内容。
"""

JSON_SCHEMA_EXAMPLE = """\
评审报告 JSON 结构如下：
{
  "summary": "一段 2-4 句的总体评价，指出最关键的问题与整体质量",
  "score": 0到100的整数（综合评分）,
  "grade": "由 score 派生，90-100 为 A，75-89 为 B，60-74 为 C，60 以下为 D",
  "dimension_scores": {
    "correctness": 0到100的整数，评估逻辑正确性、边界条件、错误处理,
    "security": 0到100的整数，评估安全漏洞风险（注入、泄露、RCE等）,
    "performance": 0到100的整数，评估时间/空间复杂度、资源使用效率,
    "maintainability": 0到100的整数，评估可读性、模块化、耦合度,
    "best_practice": 0到100的整数，评估是否符合语言/框架最佳实践
  },
  "issues": [
    {
      "severity": "critical 或 major 或 minor 或 info",
      "category": "correctness 或 security 或 performance 或 maintainability 或 best_practice 或 ai_pattern",
      "line": 问题所在的大致行号(1-based)，无法确定时填 null,
      "title": "一句话问题标题",
      "description": "问题详细描述，说明为什么是问题、可能后果",
      "suggestion": "具体可行的修复建议说明",
      "fix_code": "修复后的完整代码片段，可直接替换问题行；若无法生成具体代码则填 null"
    }
  ],
  "strengths": ["代码优点列表，至少 1 条"],
  "improvements": ["改进方向列表，至少 1 条"]
}

规则：
1. issues 中必须至少包含一条真正存在的问题；若确实没有问题，severity 用 info 说明代码状态优秀。
2. 不要编造代码中不存在的问题。security 类别优先于其他类别报告。
3. 建议要具体、可执行。fix_code 必须是可直接替换问题行的完整代码片段，包含修复后的代码，不要包含原始问题代码。
4. 若规则引擎预检结果中存在误报，请在 issues 中用 severity=info 说明"规则引擎 XX 为误报"。
5. dimension_scores 中每个维度的评分必须与 issues 中对应类别的问题严重程度一致：
   - 该维度无问题：85-100
   - 仅有 minor/info 级别问题：70-84
   - 有 major 级别问题：50-69
   - 有 critical 级别问题：0-49
6. score 应为 dimension_scores 五个维度的加权平均（security 和 correctness 权重更高）。
"""

DIFF_SYSTEM_PROMPT = """\
你是一名资深代码评审专家，正在评审一个代码变更（diff）。\
请重点关注变更部分的风险：是否引入安全漏洞、是否破坏现有逻辑、\
是否有性能退化、变更是否完整（如新增分支但未处理所有路径）。\
请以严格的 JSON 格式输出评审报告，不要输出任何 JSON 以外的内容。
"""


def build_user_prompt(language: str, context: str, code: str) -> str:
    parts = [f"语言：{language or '未知'}"]
    if context:
        parts.append(f"任务上下文：{context}")
    parts.append("待评审代码：")
    parts.append("```" + language + "\n" + code + "\n```")
    parts.append(JSON_SCHEMA_EXAMPLE)
    return "\n".join(parts)


def build_user_prompt_with_rules(
    language: str,
    context: str,
    code: str,
    rule_findings: list[dict],
) -> str:
    """Build prompt that includes rule engine pre-check results for LLM."""
    parts = [f"语言：{language or '未知'}"]
    if context:
        parts.append(f"任务上下文：{context}")

    if rule_findings:
        parts.append("规则引擎预检结果：")
        for f in rule_findings:
            parts.append(
                f"  [{f['rule_id']}] {f['severity']}/{f['category']} "
                f"行{f.get('line', '?')}: {f['title']}"
            )
        parts.append("")
    else:
        parts.append("规则引擎预检结果：未发现已知模式问题。\n")

    parts.append("待评审代码：")
    parts.append("```" + language + "\n" + code + "\n```")
    parts.append(JSON_SCHEMA_EXAMPLE)
    return "\n".join(parts)


def build_diff_prompt(language: str, context: str, diff: str, diff_meta: str) -> str:
    """Build prompt for diff-level review."""
    parts = [f"语言：{language or '未知'}"]
    if context:
        parts.append(f"任务上下文：{context}")
    parts.append(f"变更概要：{diff_meta}")
    parts.append("待评审 diff：")
    parts.append("```diff\n" + diff + "\n```")
    parts.append(JSON_SCHEMA_EXAMPLE)
    return "\n".join(parts)


FILES_SYSTEM_PROMPT = """\
你是一名资深软件架构师与代码评审专家，正在评审一个项目的多个文件。\
你的任务是从全局视角评审代码质量：不仅关注单个文件内部的问题，\
还要关注跨文件的架构问题（如循环依赖、接口不一致、重复逻辑等）。

请以严格的 JSON 格式输出评审报告，不要输出任何 JSON 以外的内容。\
报告中的 issues 应涵盖所有文件的问题，line 字段使用问题所在文件内的行号，\
在 title 中标注文件名前缀，如 "[utils.py] 第3行存在..."。
"""


def build_files_prompt(
    context: str,
    files: list[dict],
    rule_summary: str,
) -> str:
    """Build prompt for multi-file review.

    Args:
        context: optional project/task context.
        files: list of {filename, language, content} dicts.
        rule_summary: pre-check summary from rule engine.
    """
    parts = []
    if context:
        parts.append(f"项目上下文：{context}")
    parts.append(f"共 {len(files)} 个文件待评审：\n")

    for f in files:
        parts.append(f"--- 文件: {f['filename']} (语言: {f.get('language', '未知')}) ---")
        parts.append(f"```{f.get('language', '')}\n{f['content']}\n```")
        parts.append("")

    if rule_summary:
        parts.append("规则引擎预检结果：")
        parts.append(rule_summary)
    else:
        parts.append("规则引擎预检结果：未发现已知模式问题。")

    parts.append("")
    parts.append(JSON_SCHEMA_EXAMPLE)
    return "\n".join(parts)


SUGGEST_FIX_SYSTEM_PROMPT = """\
你是一名资深代码修复专家。你的任务是为存在问题的代码生成修复方案。\
请以严格的 JSON 格式输出，不要输出任何 JSON 以外的内容。
"""

SUGGEST_FIX_SCHEMA_EXAMPLE = """\
修复方案 JSON 结构如下：
{
  "fixed_code": "修复后的完整代码，可直接替换原始代码；若无法修复则填 null",
  "explanation": "2-4 句说明修改了什么、为什么这样修改、解决了什么问题",
  "changes": ["修改点列表，每条描述一处具体修改"]
}

规则：
1. fixed_code 必须完整、可直接运行，不含注释掉的原始代码。
2. 若问题是缺失上下文导致无法准确修复，explanation 说明需要补充哪些信息，fixed_code 填 null。
"""


def build_suggest_fix_prompt(
    language: str,
    context: str,
    code: str,
    issues: list[dict],
) -> str:
    """Build prompt for generating a fix for known issues in code."""
    parts = [f"语言：{language or '未知'}"]
    if context:
        parts.append(f"任务上下文：{context}")
    parts.append("存在问题：")
    for i in issues:
        parts.append(
            f"  - [{i.get('rule_id') or i.get('source', 'llm')}] "
            f"{i.get('severity')}/{i.get('category')} "
            f"行{i.get('line', '?')}: {i.get('title')}"
        )
        if i.get("description"):
            parts.append(f"    描述：{i['description']}")
    parts.append("")
    parts.append("原始代码：")
    parts.append("```" + language + "\n" + code + "\n```")
    parts.append("")
    parts.append(SUGGEST_FIX_SCHEMA_EXAMPLE)
    return "\n".join(parts)
