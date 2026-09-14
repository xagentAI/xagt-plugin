# -*- coding: utf-8 -*-
"""Semantic version bump suggestion and changelog generation.

Given a DiffReport, derives the appropriate SemVer bump (major / minor / patch)
and generates a human-readable markdown changelog.
"""
from __future__ import annotations

from .models import DiffReport, Finding, SEVERITY_ORDER


def suggest_version_bump(report: DiffReport, current_version: str = "") -> dict:
    """Derive the SemVer bump level from a diff report.

    Rules:
    - Any critical or major breaking change -> major bump
    - Any minor non-breaking change -> minor bump
    - Only info-level changes -> patch bump
    - No changes -> none
    """
    counts = report.counts or {}
    has_critical_breaking = report.breaking_count > 0 and counts.get("critical", 0) > 0
    has_major_breaking = report.breaking_count > 0 and counts.get("major", 0) > 0
    has_minor = counts.get("minor", 0) > 0
    has_info = counts.get("info", 0) > 0

    if has_critical_breaking or has_major_breaking:
        bump = "major"
        reason = f"{report.breaking_count} breaking change(s) detected"
    elif has_minor:
        bump = "minor"
        reason = f"{counts['minor']} minor change(s) detected (non-breaking but noteworthy)"
    elif has_info:
        bump = "patch"
        reason = f"{counts['info']} additive change(s) detected"
    else:
        bump = "none"
        reason = "No changes detected"

    new_version = _bump_version(current_version, bump) if current_version else None

    return {
        "bump": bump,
        "reason": reason,
        "current_version": current_version or None,
        "suggested_version": new_version,
        "breaking_count": report.breaking_count,
        "total_changes": report.total_changes,
    }


def _bump_version(version: str, bump: str) -> str | None:
    try:
        parts = version.strip().lstrip("v").split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


def generate_changelog(report: DiffReport, old_version: str = "", new_version: str = "") -> str:
    """Generate a markdown changelog from a diff report."""
    lines: list[str] = []

    header_ver = ""
    if old_version and new_version:
        header_ver = f" ({old_version} -> {new_version})"
    elif old_version:
        bump_info = suggest_version_bump(report, old_version)
        if bump_info["suggested_version"]:
            header_ver = f" ({old_version} -> {bump_info['suggested_version']})"

    lines.append(f"## API Contract Changes{header_ver}")
    lines.append("")
    lines.append(report.summary)
    lines.append("")

    if report.total_changes == 0:
        lines.append("No changes detected.")
        return "\n".join(lines)

    grouped: dict[str, list[Finding]] = {sev: [] for sev in SEVERITY_ORDER}
    for f in report.findings:
        if f.source != "confirmed":
            continue
        grouped.setdefault(f.severity, []).append(f)

    severity_labels = {
        "critical": "Breaking Changes (Critical)",
        "major": "Breaking Changes (Major)",
        "minor": "Minor Changes",
        "info": "Additive Changes",
    }

    for sev in SEVERITY_ORDER:
        items = grouped.get(sev, [])
        if not items:
            continue
        lines.append(f"### {severity_labels.get(sev, sev)}")
        lines.append("")
        for f in items:
            icon = ":rotating_light:" if f.breaking else ":sparkles:"
            lines.append(f"- {icon} **{f.change_type}** — {f.summary} (`{f.location}`)")
            if f.suggestion:
                lines.append(f"  - Suggestion: {f.suggestion}")
        lines.append("")

    advisory = [f for f in report.findings if f.source == "advisory"]
    if advisory:
        lines.append("### Advisory (LLM Impact Assessment)")
        lines.append("")
        for f in advisory:
            lines.append(f"- {f.summary}")
        lines.append("")

    return "\n".join(lines)