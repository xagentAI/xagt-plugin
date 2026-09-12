# -*- coding: utf-8 -*-
"""FastMCP server exposing code review capabilities as reusable MCP tools.

Tools:
- review_code:    dual-engine review of a source code snippet   [LLM]
- review_diff:    dual-engine review of a unified diff / PR     [LLM]
- review_files:   dual-engine review of multiple files          [LLM]
- detect_security: fast rule-only security scan (instant, free)
- list_rules:     list all built-in rule engine rules (instant)
- explain_issue:  explain a rule in detail (instant, free)
- suggest_fix:    generate corrected code for known issues      [LLM]

Usage guidance for agents:
1. Start cheap: use detect_security / list_rules / explain_issue first
   (no LLM cost, millisecond latency).
2. For a full analysis call review_code / review_diff / review_files with
   detail="brief" (default) to save context tokens; use detail="full" when
   the user needs every fix suggestion.
3. When the user wants the problem fixed, call suggest_fix with the code.

Run via stdio (default) for Claude Code / Codex / Cursor, or mount
`mcp` onto a FastAPI app for remote streamable HTTP transport
(see app.main: `app.mount("/mcp", mcp.http_app())`).
"""
import json

from fastmcp import FastMCP

from .config import PROJECT_SLUG
from .reviewer import (
    ReviewError,
    _build_brief_report,
    explain_issue,
    review_code,
    review_diff,
    review_files,
    suggest_fix_for_code,
)
from .rules_engine import RULES, run_rules

mcp = FastMCP(
    PROJECT_SLUG,
    instructions=(
        "Dual-engine code review assistant. Rule engine + LLM semantic review "
        "with cross-validation. Free instant tools (no LLM call): "
        "detect_security, list_rules, explain_issue. LLM tools: review_code, "
        "review_diff, review_files (use detail='brief' to save context unless "
        "the user needs full details), suggest_fix. Workflow: quick scan with "
        "detect_security first, then deep review, then explain_issue/suggest_fix "
        "as needed."
    ),
)


def _wrap_review(report: dict, detail: str, extra: dict | None = None) -> str:
    """Serialize a review report, applying brief/full detail control."""
    out = {"ok": True}
    if extra:
        out.update(extra)
    if detail == "full":
        report_with_meta = dict(report)
        report_with_meta["detail"] = "full"
        out["report"] = report_with_meta
    else:
        brief = _build_brief_report(report)
        brief["detail"] = "brief"
        out["report"] = brief
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def review_code_tool(
    code: str,
    language: str = "",
    context: str = "",
    detail: str = "brief",
) -> str:
    """Review a source code snippet with dual-engine analysis (rules + LLM).

    Use this when you have a piece of code (not a diff) you want reviewed
    for security, correctness, performance, maintainability issues.

    Args:
        code: source code to review.
        language: programming language hint (python, java, js, go, ...).
        context: optional description of what the code is supposed to do.
        detail: "brief" (default, trimmed issues to save context) or "full"
            (complete report with every description/suggestion/fix_code).

    Returns:
        JSON string with summary, score, grade, dimension scores, issues
        (source-attributed) and engine stats.
    """
    try:
        report = review_code(code=code, language=language, context=context)
    except ReviewError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return _wrap_review(report, detail)


@mcp.tool()
def review_diff_tool(
    diff: str,
    language: str = "",
    context: str = "",
    detail: str = "brief",
) -> str:
    """Review a unified diff (git diff / PR change) for change-level risks.

    Use this when the user shares a diff or asks you to check a PR / commit
    change, not full source files.

    Args:
        diff: unified diff text.
        language: programming language hint.
        context: optional description of the change purpose.
        detail: "brief" (default) or "full".

    Returns:
        JSON string with diff metadata (files_changed, added/deleted lines)
        and a structured review report.
    """
    try:
        result = review_diff(diff=diff, language=language, context=context)
    except ReviewError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    diff_meta = result.pop("diff_meta", {})
    return _wrap_review(result, detail, extra={"diff_meta": diff_meta})


@mcp.tool()
def review_files_tool(
    files: list[dict],
    context: str = "",
    detail: str = "brief",
) -> str:
    """Review multiple files (entire module/project change) with dual-engine analysis.

    Use this when reviewing a whole set of files at once, e.g. before committing
    or when several files changed together. Detects per-file rule hits plus
    cross-file architecture problems.

    Args:
        files: array of file objects, each {"filename": str, "content": str,
            "language": str (optional)}.
        context: optional project/task context description.
        detail: "brief" (default) or "full".

    Returns:
        JSON string with per-file reports and an overall cross-file report.
    """
    try:
        result = review_files(files=files, context=context)
    except ReviewError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    if detail == "full":
        out = result
    else:
        overall = result.get("overall_report", {})
        out = {
            "file_count": len(result.get("file_reports", [])),
            "overall_report": _build_brief_report(overall, max_issues=8),
        }
    out["detail"] = detail
    return json.dumps({"ok": True, "result": out}, ensure_ascii=False)


@mcp.tool()
def explain_issue(rule_id: str) -> str:
    """Explain a rule-engine rule in detail (no LLM call, instant, free).

    Use this to understand why a rule fired or to explain a finding to the
    user. Args: rule_id, e.g. PY-S001, JS-S002, AI-H003.

    Returns:
        JSON string with rule definition, severity, category and guidance.
    """
    result = explain_issue(rule_id)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def suggest_fix(
    code: str,
    language: str = "",
    context: str = "",
) -> str:
    """Generate a full corrected version of code with known issues (LLM).

    Use this when the user wants the code actually fixed, not just reviewed.
    Rules engine runs first to surface deterministic findings, then the LLM
    produces a complete fixed_code block that can replace the original.

    Args:
        code: source code to fix.
        language: programming language hint (python, java, js, go, ...).
        context: optional description of what the code is supposed to do.

    Returns:
        JSON string with fixed_code, explanation, and list of changes.
    """
    try:
        result = suggest_fix_for_code(code=code, language=language, context=context)
    except ReviewError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "result": result}, ensure_ascii=False)


@mcp.tool()
def detect_security(code: str, language: str = "") -> str:
    """Fast rule-only security scan — no LLM call, returns instantly.

    Use this for a quick cheap security check while coding; call review_code
    for deeper semantic analysis.

    Args:
        code: source code to scan.
        language: programming language hint.

    Returns:
        JSON string with detected security issues and their rule IDs.
    """
    findings = run_rules(code, language)
    security_findings = [
        f for f in findings if f.category in ("security", "ai_pattern")
    ]
    return json.dumps(
        {
            "ok": True,
            "total_findings": len(security_findings),
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "category": f.category,
                    "line": f.line,
                    "title": f.title,
                    "description": f.description,
                    "suggestion": f.suggestion,
                    "confidence": f.confidence,
                }
                for f in security_findings
            ],
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_rules() -> str:
    """List all built-in rule engine rules with their metadata (instant, free).

    Returns:
        JSON string with all rules (id, language, severity, category, title).
    """
    return json.dumps(
        {
            "total": len(RULES),
            "rules": [
                {
                    "id": r.id,
                    "language": r.language,
                    "severity": r.severity,
                    "category": r.category,
                    "confidence": r.confidence,
                    "title": r.title,
                }
                for r in RULES
            ],
        },
        ensure_ascii=False,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()