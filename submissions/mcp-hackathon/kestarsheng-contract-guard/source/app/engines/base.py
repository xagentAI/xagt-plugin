# -*- coding: utf-8 -*-
"""Shared helpers for the deterministic diff engines."""
from __future__ import annotations

import json
from typing import Any

from ..models import Finding, SEVERITY_ORDER


def severity_rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(SEVERITY_ORDER)


def render(value: Any, limit: int = 120) -> str:
    """Render an arbitrary value to a short, human-readable string."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + "…"
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [render(v, 30) for v in value[:8]]
        suffix = ", …" if len(value) > 8 else ""
        return "[" + ", ".join(parts) + suffix + "]"
    if isinstance(value, dict):
        if "$ref" in value:
            return value["$ref"]
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:limit]
    return str(value)[:limit]


def find_severity(location: str) -> None:  # pragma: no cover - reserved
    return None


def make_finding(
    change_type: str,
    breaking: bool,
    severity: str,
    location: str,
    summary: str,
    previous: Any = None,
    current: Any = None,
    suggestion: str = "",
    fmt: str = "",
) -> Finding:
    """Build a deterministic (confirmed) finding with a stable id."""
    return Finding(
        change_type=change_type,
        breaking=breaking,
        severity=severity,
        location=location,
        summary=summary,
        previous=render(previous) if previous is not None else None,
        current=render(current) if current is not None else None,
        suggestion=suggestion,
        source="confirmed",
        format=fmt,
        id=f"{fmt}:{change_type}:{location}",
    )