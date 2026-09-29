# -*- coding: utf-8 -*-
"""SARIF 2.1.0 export of rule-engine findings.

SARIF (Static Analysis Results Interchange Format) is the OASIS standard
consumed by VS Code (Sarif Viewer), GitHub Code Scanning and many CI tools.
This module converts deterministic findings into a standards-compliant
document so the results can drop straight into a developer's IDE / pipeline.
"""
from __future__ import annotations

from typing import Any

from .rules_engine import RULES, merge_findings, run_rules

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_NAME = "Code Review Agent"

_LEVEL_MAP = {
    "critical": "error",
    "major": "error",
    "minor": "warning",
    "info": "note",
}


def _rule_definitions() -> list[dict]:
    rules = []
    for r in RULES:
        rules.append({
            "id": r.id,
            "name": r.title.replace(" ", "_"),
            "shortDescription": {"text": r.title},
            "fullDescription": {"text": r.description},
            "help": {"text": f"{r.description}\n\nSuggestion: {r.suggestion}"},
            "helpUri": (
                "https://github.com/kestarsheng/code-review-agent"
                f"/blob/main/README.md#{r.id.lower()}"
            ),
            "properties": {
                "category": r.category,
                "severity": r.severity,
                "confidence": r.confidence,
                "language": r.language,
            },
            "defaultConfiguration": {"level": _LEVEL_MAP.get(r.severity, "warning")},
        })
    return rules


def _rule_level(severity: str) -> str:
    return _LEVEL_MAP.get(severity, "warning")


def build_sarif(
    issues: list[dict],
    uri: str = "snippet.py",
    language: str = "",
) -> dict[str, Any]:
    """Build a SARIF 2.1.0 document from merged issue dicts.

    Args:
        issues: merged findings (from merge_findings / report["issues"]).
        uri: artifact path to attach findings to (e.g. 'src/main.py').
        language: detected language, stored for reference.

    Returns:
        SARIF-compliant document.
    """
    results = []
    for issue in issues:
        level = _rule_level(issue.get("severity", "info"))
        message = issue.get("title") or issue.get("description") or "issue"
        if issue.get("description") and issue.get("description") != message:
            message = f"{message} — {issue['description']}"
        result: dict[str, Any] = {
            "ruleId": issue.get("rule_id") or f"LLM-{issue.get('category', 'issue')}",
            "level": level,
            "message": {"text": message},
            "properties": {
                "category": issue.get("category", ""),
                "source": issue.get("source", ""),
                "confidence": issue.get("confidence", 0.0),
                "language": language,
            },
        }
        if issue.get("fix_code"):
            result["fixes"] = [
                {
                    "artifactChanges": [],
                    "description": {"text": "Suggested fix"},
                }
            ]
            result["properties"]["fix_code"] = issue["fix_code"]
        if issue.get("line"):
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": issue["line"]},
                    }
                }
            ]
        results.append(result)

    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": "https://github.com/kestarsheng/code-review-agent",
                        "version": "2.1.0",
                        "rules": _rule_definitions(),
                    }
                },
                "results": results,
            }
        ],
    }


def sarif_from_code(
    code: str,
    language: str = "",
    uri: str = "snippet.py",
) -> dict[str, Any]:
    """One-shot: run deterministic engines (rules + AST) and export SARIF.

    No LLM, no API cost — ready for CI integration.
    """
    from .reviewer import _run_all_engines

    findings, detected = _run_all_engines(code, language)
    merged = merge_findings(list(findings), [], code)
    return build_sarif(merged, uri=uri or "snippet.py", language=detected or language)