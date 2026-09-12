# -*- coding: utf-8 -*-
"""Dual-engine code review: rule-based static analysis + LLM semantic review.

The rule engine runs first (fast, deterministic, no API cost), detecting
known anti-patterns. The LLM then reviews the code with awareness of rule
findings, adding semantic analysis and confirming/denying rule hits.

Results are merged with source attribution:
- "rule": found by rule engine only
- "llm": found by LLM only
- "confirmed": both engines agree (highest confidence)
"""
import json
import logging
import re
from typing import Any

from openai import OpenAI

from .config import get_settings
from .diff_parser import diff_summary, parse_diff
from .prompts import (
    DIFF_SYSTEM_PROMPT,
    FILES_SYSTEM_PROMPT,
    SUGGEST_FIX_SYSTEM_PROMPT,
    SYSTEM_PROMPT_WITH_RULES,
    build_diff_prompt,
    build_files_prompt,
    build_suggest_fix_prompt,
    build_user_prompt,
    build_user_prompt_with_rules,
)
from .rules_engine import merge_findings, run_rules

logger = logging.getLogger(__name__)

_SEVERITY_PENALTY = {"critical": 35, "major": 18, "minor": 8, "info": 3}
_DIMENSION_CATEGORIES = {
    "correctness": ["correctness"],
    "security": ["security"],
    "performance": ["performance"],
    "maintainability": ["maintainability"],
    "best_practice": ["best_practice", "ai_pattern"],
}


def _compute_dimension_scores(
    llm_scores: dict[str, int] | None,
    merged_issues: list[dict],
) -> dict[str, int]:
    """Compute final dimension scores by combining LLM scores with rule penalties.

    LLM provides a semantic baseline; rule-engine findings apply penalties
    based on severity. This ensures deterministic rules always affect the
    score even if the LLM misses them.
    """
    defaults = {
        "correctness": 85,
        "security": 85,
        "performance": 85,
        "maintainability": 85,
        "best_practice": 85,
    }
    if llm_scores:
        for k in defaults:
            if k in llm_scores:
                defaults[k] = max(0, min(100, int(llm_scores[k])))

    for issue in merged_issues:
        cat = issue.get("category", "")
        sev = issue.get("severity", "info")
        penalty = _SEVERITY_PENALTY.get(sev, 3)

        for dim, cats in _DIMENSION_CATEGORIES.items():
            if cat in cats:
                defaults[dim] = max(0, defaults[dim] - penalty)

    return defaults


def _compute_overall_score(dimensions: dict[str, int]) -> int:
    """Weighted average: security & correctness weighted higher."""
    weights = {
        "correctness": 0.25,
        "security": 0.30,
        "performance": 0.15,
        "maintainability": 0.15,
        "best_practice": 0.15,
    }
    total = sum(dimensions[k] * w for k, w in weights.items())
    return round(total)


class ReviewError(Exception):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response (tolerates fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ReviewError("模型未返回有效 JSON")
        return json.loads(match.group(0))


def _call_llm(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call the configured LLM and return parsed JSON."""
    settings = get_settings()
    if not settings.llm_api_key:
        raise ReviewError("LLM API Key 未配置（环境变量 LLM_API_KEY）")

    client = OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )

    try:
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed")
        raise ReviewError(f"LLM 调用失败: {exc}") from exc

    content = resp.choices[0].message.content or "{}"
    data = _extract_json(content)

    if not isinstance(data, dict) or "issues" not in data:
        raise ReviewError("模型返回结构不完整，缺少 issues 字段")
    return data


def review_code(code: str, language: str = "", context: str = "") -> dict[str, Any]:
    """Run dual-engine review: rules first, then LLM with rule context.

    Returns a structured report with merged findings and engine metadata.
    """
    # ── Phase 1: Rule engine (fast, local, no API cost) ──
    rule_findings = run_rules(code, language)
    rule_dicts = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity,
            "category": f.category,
            "line": f.line,
            "title": f.title,
            "description": f.description,
            "suggestion": f.suggestion,
            "fix_code": f.fix_code,
            "confidence": f.confidence,
        }
        for f in rule_findings
    ]
    logger.info("Rule engine found %d issues", len(rule_findings))

    # ── Phase 2: LLM review with rule context ──
    user_prompt = build_user_prompt_with_rules(language, context, code, rule_dicts)
    llm_data = _call_llm(SYSTEM_PROMPT_WITH_RULES, user_prompt)
    llm_issues = llm_data.get("issues", [])

    # ── Phase 3: Merge and attribute ──
    merged_issues = merge_findings(rule_findings, llm_issues, code)

    rule_count = sum(1 for i in merged_issues if i.get("source") == "rule")
    llm_count = sum(1 for i in merged_issues if i.get("source") == "llm")
    confirmed_count = sum(1 for i in merged_issues if i.get("source") == "confirmed")

    # ── Phase 4: Dimension scores ──
    llm_dim_scores = llm_data.get("dimension_scores")
    dimension_scores = _compute_dimension_scores(llm_dim_scores, merged_issues)
    overall_score = _compute_overall_score(dimension_scores)
    grade = (
        "A" if overall_score >= 90
        else "B" if overall_score >= 75
        else "C" if overall_score >= 60
        else "D"
    )

    report = {
        "summary": llm_data.get("summary", ""),
        "score": overall_score,
        "grade": grade,
        "dimension_scores": dimension_scores,
        "issues": merged_issues,
        "strengths": llm_data.get("strengths", []),
        "improvements": llm_data.get("improvements", []),
        "engine_info": {
            "rule_count": rule_count,
            "llm_count": llm_count,
            "confirmed_count": confirmed_count,
            "total_rules_run": len(rule_findings),
            "engines": ["rule", "llm"],
        },
    }
    return report


def review_diff(diff: str, language: str = "", context: str = "") -> dict[str, Any]:
    """Review a unified diff: parse, reconstruct changed code, dual-engine review."""
    parsed = parse_diff(diff)
    if not parsed.reconstructed_code.strip():
        return {
            "summary": "变更不包含实质性代码修改（仅删除或空白变更）。",
            "score": 100,
            "grade": "A",
            "dimension_scores": {
                "correctness": 100,
                "security": 100,
                "performance": 100,
                "maintainability": 100,
                "best_practice": 100,
            },
            "issues": [],
            "strengths": ["变更无引入新代码的风险"],
            "improvements": [],
            "engine_info": {
                "rule_count": 0,
                "llm_count": 0,
                "confirmed_count": 0,
                "total_rules_run": 0,
                "engines": ["rule", "llm"],
            },
            "diff_meta": {
                "files_changed": parsed.files_changed,
                "added_lines": parsed.added_lines,
                "removed_lines": parsed.removed_lines,
                "hunks": len(parsed.hunks),
            },
        }

    meta = diff_summary(parsed)
    rule_findings = run_rules(parsed.reconstructed_code, language)
    rule_dicts = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity,
            "category": f.category,
            "line": f.line,
            "title": f.title,
            "description": f.description,
            "suggestion": f.suggestion,
            "fix_code": f.fix_code,
            "confidence": f.confidence,
        }
        for f in rule_findings
    ]

    user_prompt = build_diff_prompt(language, context, diff, meta)
    llm_data = _call_llm(DIFF_SYSTEM_PROMPT, user_prompt)
    llm_issues = llm_data.get("issues", [])
    merged_issues = merge_findings(rule_findings, llm_issues, parsed.reconstructed_code)

    rule_count = sum(1 for i in merged_issues if i.get("source") == "rule")
    llm_count = sum(1 for i in merged_issues if i.get("source") == "llm")
    confirmed_count = sum(1 for i in merged_issues if i.get("source") == "confirmed")

    llm_dim_scores = llm_data.get("dimension_scores")
    dimension_scores = _compute_dimension_scores(llm_dim_scores, merged_issues)
    overall_score = _compute_overall_score(dimension_scores)
    grade = (
        "A" if overall_score >= 90
        else "B" if overall_score >= 75
        else "C" if overall_score >= 60
        else "D"
    )

    report = {
        "summary": llm_data.get("summary", ""),
        "score": overall_score,
        "grade": grade,
        "dimension_scores": dimension_scores,
        "issues": merged_issues,
        "strengths": llm_data.get("strengths", []),
        "improvements": llm_data.get("improvements", []),
        "engine_info": {
            "rule_count": rule_count,
            "llm_count": llm_count,
            "confirmed_count": confirmed_count,
            "total_rules_run": len(rule_findings),
            "engines": ["rule", "llm"],
        },
        "diff_meta": {
            "files_changed": parsed.files_changed,
            "added_lines": parsed.added_lines,
            "removed_lines": parsed.removed_lines,
            "hunks": len(parsed.hunks),
        },
    }
    return report


def _build_report(
    llm_data: dict[str, Any],
    merged_issues: list[dict],
    total_rules_run: int,
) -> dict[str, Any]:
    """Build a standard review report from LLM data and merged issues."""
    rule_count = sum(1 for i in merged_issues if i.get("source") == "rule")
    llm_count = sum(1 for i in merged_issues if i.get("source") == "llm")
    confirmed_count = sum(1 for i in merged_issues if i.get("source") == "confirmed")

    llm_dim_scores = llm_data.get("dimension_scores")
    dimension_scores = _compute_dimension_scores(llm_dim_scores, merged_issues)
    overall_score = _compute_overall_score(dimension_scores)
    grade = (
        "A" if overall_score >= 90
        else "B" if overall_score >= 75
        else "C" if overall_score >= 60
        else "D"
    )

    return {
        "summary": llm_data.get("summary", ""),
        "score": overall_score,
        "grade": grade,
        "dimension_scores": dimension_scores,
        "issues": merged_issues,
        "strengths": llm_data.get("strengths", []),
        "improvements": llm_data.get("improvements", []),
        "engine_info": {
            "rule_count": rule_count,
            "llm_count": llm_count,
            "confirmed_count": confirmed_count,
            "total_rules_run": total_rules_run,
            "engines": ["rule", "llm"],
        },
    }


def review_files(
    files: list[dict[str, str]],
    context: str = "",
) -> dict[str, Any]:
    """Review multiple files: per-file rule scan + holistic LLM review.

    Args:
        files: list of {filename, content, language} dicts.
        context: optional project/task context.

    Returns:
        dict with file_reports (per-file) and overall_report (holistic).
    """
    all_rule_findings: list = []
    rule_summary_parts: list[str] = []
    file_reports: list[dict] = []

    for f in files:
        filename = f["filename"]
        content = f["content"]
        lang = f.get("language", "")

        file_findings = run_rules(content, lang)
        all_rule_findings.extend(file_findings)

        if file_findings:
            for finding in file_findings:
                rule_summary_parts.append(
                    f"  [{filename}] {finding.rule_id} {finding.severity}/"
                    f"{finding.category} 行{finding.line}: {finding.title}"
                )

        file_merged = merge_findings(file_findings, [], content)
        file_report = _build_report(
            {"summary": f"规则引擎扫描 {filename}，发现 {len(file_findings)} 个问题。",
             "strengths": [], "improvements": []},
            file_merged,
            len(file_findings),
        )
        file_reports.append({
            "filename": filename,
            "language": lang,
            "report": file_report,
        })

    rule_summary = "\n".join(rule_summary_parts) if rule_summary_parts else ""

    files_for_prompt = [
        {"filename": f["filename"], "language": f.get("language", ""),
         "content": f["content"]}
        for f in files
    ]
    user_prompt = build_files_prompt(context, files_for_prompt, rule_summary)
    llm_data = _call_llm(FILES_SYSTEM_PROMPT, user_prompt)
    llm_issues = llm_data.get("issues", [])

    all_code = "\n\n".join(f["content"] for f in files)
    overall_merged = merge_findings(all_rule_findings, llm_issues, all_code)
    overall_report = _build_report(llm_data, overall_merged, len(all_rule_findings))

    return {
        "file_reports": file_reports,
        "overall_report": overall_report,
    }


def suggest_fix_for_code(
    code: str,
    language: str = "",
    context: str = "",
) -> dict[str, Any]:
    """Generate a complete fix for code with known issues (LLM).

    Runs the rule engine first to surface deterministic findings, then asks
    the LLM to produce a fully corrected version of the code.
    """
    rule_findings = run_rules(code, language)
    issues = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity,
            "category": f.category,
            "line": f.line,
            "title": f.title,
            "description": f.description,
            "suggestion": f.suggestion,
        }
        for f in rule_findings
    ]

    user_prompt = build_suggest_fix_prompt(language, context, code, issues)
    llm_data = _call_llm(SUGGEST_FIX_SYSTEM_PROMPT, user_prompt)

    result = {
        "fixed_code": llm_data.get("fixed_code"),
        "explanation": llm_data.get("explanation", ""),
        "changes": llm_data.get("changes", []),
        "found_issues": len(issues),
    }
    if not result["fixed_code"] and not issues:
        result.update(
            {
                "fixed_code": code,
                "explanation": "未检测到问题，代码保持原样。",
                "changes": [],
            }
        )
    return result


def explain_issue(rule_id: str) -> dict[str, Any]:
    """Explain a rule-engine rule in detail (no LLM needed).

    Returns the rule definition, applicability, and guidance.
    """
    from .rules_engine import RULES

    for rule in RULES:
        if rule.id.lower() == rule_id.strip().lower():
            return {
                "rule_id": rule.id,
                "language": rule.language,
                "severity": rule.severity,
                "category": rule.category,
                "confidence": rule.confidence,
                "title": rule.title,
                "description": rule.description,
                "suggestion": rule.suggestion,
                "ok": True,
            }
    return {"ok": False, "error": f"未找到规则 {rule_id}", "rule_id": rule_id}


_BRIEF_ISSUE_KEYS = ("severity", "category", "line", "title", "source", "rule_id", "confidence")


def _build_brief_report(
    report: dict[str, Any],
    max_issues: int = 5,
) -> dict[str, Any]:
    """Build a compact version of a review report for MCP budget usage.

    Keeps the headline (summary, scores, engine stats) plus a trimmed issue
    list without verbose description/suggestion/fix_code fields, so agents
    can decide whether to dig deeper without burning context tokens.
    """
    issues = report.get("issues", [])
    kept = issues[:max_issues]
    brief = {
        "summary": report.get("summary", ""),
        "score": report.get("score", 0),
        "grade": report.get("grade", "C"),
        "dimension_scores": report.get("dimension_scores", {}),
        "issue_count": len(issues),
        "truncated": len(issues) > max_issues,
        "issues": [
            {k: i.get(k) for k in _BRIEF_ISSUE_KEYS if k in i}
            for i in kept
        ],
        "engine_info": report.get("engine_info", {}),
    }
    strengths = report.get("strengths", [])
    improvements = report.get("improvements", [])
    if strengths:
        brief["strengths"] = strengths[:3]
    if improvements:
        brief["improvements"] = improvements[:3]
    return brief
