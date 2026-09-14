# -*- coding: utf-8 -*-
"""SARIF 2.1.0 export for GitHub Code Scanning integration.

Converts a DiffReport into the Static Analysis Results Interchange Format
(SARIF) so results can be uploaded via `github/codeql-action/upload-sarif`.
"""
from __future__ import annotations

import hashlib

from .models import DiffReport, Finding, SEVERITY_ORDER

_SEVERITY_TO_SARIF_LEVEL = {
    "critical": "error",
    "major": "error",
    "minor": "warning",
    "info": "note",
}


def export_sarif(report: DiffReport) -> dict:
    """Convert a DiffReport to a SARIF 2.1.0 document."""
    rules = _build_rules(report)
    results = [_build_result(f, idx) for idx, f in enumerate(report.findings) if f.source == "confirmed"]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "Contract Guard",
                    "version": "1.0.0",
                    "semanticVersion": "1.0.0",
                    "informationUri": "https://github.com/kestarsheng/contract-guard",
                    "rules": rules,
                },
            },
            "results": results,
            "invocations": [{
                "executionSuccessful": True,
                "commandLine": f"contract-guard diff --format {report.format}",
            }],
        }],
    }


def _build_rules(report: DiffReport) -> list:
    seen: set[str] = set()
    rules: list = []
    for f in report.findings:
        if f.change_type in seen:
            continue
        seen.add(f.change_type)
        level = _SEVERITY_TO_SARIF_LEVEL.get(f.severity, "warning")
        rules.append({
            "id": f.change_type,
            "name": f.change_type.replace("_", " ").title(),
            "shortDescription": {
                "text": f.change_type.replace("_", " "),
            },
            "fullDescription": {
                "text": f.summary if f.summary else f.change_type,
            },
            "defaultConfiguration": {"level": level},
            "properties": {
                "breaking": f.breaking,
                "severity": f.severity,
                "tags": ["breaking"] if f.breaking else ["non-breaking"],
            },
        })
    return rules


def _build_result(finding: Finding, idx: int) -> dict:
    level = _SEVERITY_TO_SARIF_LEVEL.get(finding.severity, "warning")
    loc_hash = hashlib.sha256(finding.id.encode("utf-8")).hexdigest()[:16]

    return {
        "ruleId": finding.change_type,
        "ruleIndex": idx,
        "level": level,
        "message": {
            "text": finding.summary,
        },
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {
                    "uri": "contract-diff",
                },
            },
            "logicalLocations": [{
                "name": finding.location,
            }],
        }],
        "partialFingerprints": {
            "primaryLocationLineHash": loc_hash,
        },
        "properties": {
            "breaking": finding.breaking,
            "severity": finding.severity,
            "source": finding.source,
            "format": finding.format,
            "previous": finding.previous,
            "current": finding.current,
            "suggestion": finding.suggestion,
        },
    }