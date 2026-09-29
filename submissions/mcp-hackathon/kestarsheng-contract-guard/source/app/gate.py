# -*- coding: utf-8 -*-
"""CI gate evaluation: turn a diff (optionally consumer-filtered) into a
pass/block decision for merge pipelines.

The engine stays 100% deterministic -- the gate makes exactly the same
decision every time it is asked. Policy options:

- ``allow_breaking`` (default False): block if any breaking finding applies.
- ``max_severity`` (e.g. "major"): block only findings whose severity is
  stricter than the threshold ("critical" > "major" > "minor" > "info").
- ``consumer_profile``: evaluate only findings that hit a specific caller's
  subset first, so a change is only blocked when it breaks *this* consumer.
"""
from __future__ import annotations

from .diff_core import detect_changes
from .impact import scan_consumer_impact

SEVERITY_RANK = {"info": 0, "minor": 1, "major": 2, "critical": 3}

_POLICY_HINTS = {
    "endpoint_removed": "Restore the endpoint or keep a deprecation window",
    "required_field_added": "Make the new field optional in v2",
    "constraint_tightened": "Relax the constraint or bump to a major version",
    "type_changed": "Add a new field instead of changing the existing type",
    "field_removed": "Keep the field as deprecated rather than removing it",
    "enum_value_removed": "Restore the enum value or add an escape hatch",
    "property_removed": "Keep the property as optional",
}


def evaluate_gate(
    old_spec: str,
    new_spec: str,
    fmt: str,
    *,
    allow_breaking: bool | None = None,
    max_severity: str | None = None,
    consumer_profile: dict | None = None,
) -> dict:
    """Evaluate the gate policy over the diff.

    Returns an "ok" report (without error key) ready for JSON serialization.
    Raises DiffError on invalid format/spec (callers map that to HTTP 400).
    """
    consumer_aware = bool(consumer_profile)
    if consumer_aware:
        scan = scan_consumer_impact(
            old_spec, new_spec, fmt, consumer_profile, use_llm=False
        )
        findings = list(scan["hits"])
        total_changes = scan["total_changes"]
        breaking_count = scan["consumer_breaking_count"]
        summary_prefix = scan["summary"]
    else:
        report = detect_changes(old_spec, new_spec, fmt)
        findings = [f.as_dict() for f in report.findings]
        total_changes = report.total_changes
        breaking_count = report.breaking_count
        summary_prefix = report.summary

    policy = {
        "allow_breaking": allow_breaking,
        "max_severity": max_severity,
        "consumer_profile": consumer_profile,
    }

    effective_allow = allow_breaking is True
    threshold = (
        SEVERITY_RANK.get(max_severity, 2) if max_severity is not None else None
    )
    blocked = []
    for f in findings:
        if not f["breaking"]:
            continue
        if effective_allow:
            continue
        if threshold is not None and SEVERITY_RANK.get(f["severity"], 0) <= threshold:
            continue
        blocked.append(
            {
                "change_type": f["change_type"],
                "severity": f["severity"],
                "location": f["location"],
                "summary": f["summary"],
                "id": f["id"],
                "hint": _POLICY_HINTS.get(f["change_type"], ""),
            }
        )

    passed = not blocked
    if passed:
        summary = f"Gate passed: no change exceeds the policy."
    else:
        worst = max(SEVERITY_RANK.get(b["severity"], 0) for b in blocked)
        summary = (
            f"Gate blocked: {len(blocked)} finding(s) exceed the policy "
            f"(worst severity: {_rank_to_severity(worst)}). "
            f"Address the blocked findings, or relax the gate policy."
        )

    return {
        "format": fmt,
        "passed": passed,
        "blocked_by": blocked,
        "policy": policy,
        "consumer_aware": consumer_aware,
        "breaking_count": breaking_count,
        "total_changes": total_changes,
        "summary": summary,
        "diff_summary": summary_prefix,
    }


def _rank_to_severity(rank: int) -> str:
    for name, value in SEVERITY_RANK.items():
        if value == rank:
            return name
    return "info"