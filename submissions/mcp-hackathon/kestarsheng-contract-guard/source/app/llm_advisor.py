# -*- coding: utf-8 -*-
"""Optional LLM advisory layer.

When an LLM API key is configured, this module asks the model to produce a
concise consumer-impact assessment over the confirmed breaking changes. The
result is appended as a single ``source == "advisory"`` finding. When no key
is configured or the call fails, it returns an empty list — the deterministic
engine output remains complete and usable on its own.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

import httpx

from .config import get_settings
from .models import Finding, FORMAT_GRAPHQL, FORMAT_JSON_SCHEMA, FORMAT_OPENAPI

_ADVISORY_MODEL_FALLBACK = "deepseek-chat"


def assess(findings: Iterable[Finding], fmt: str) -> list[Finding]:
    """Return advisory findings (impact assessment). Empty on any failure."""
    settings = get_settings()
    if not settings.llm_api_key:
        return []

    breaking = [f for f in findings if f.breaking]
    if not breaking:
        return []

    prompt = _build_prompt(breaking, fmt)
    try:
        text = _call_llm(prompt, settings)
    except Exception:  # noqa: BLE001 - advisory must never break the request
        return []

    parsed = _parse_json(text)
    impact = (parsed or {}).get("impact_summary") or text.strip()
    priority = (parsed or {}).get("top_priority") or ""

    body = impact
    if priority:
        body += f"\n\nTop priority: {priority}"

    return [Finding(
        change_type="impact_assessment",
        breaking=False,
        severity="info",
        location="(overall)",
        summary=body[:2000],
        source="advisory",
        format=fmt,
        id=f"{fmt}:impact_assessment:(overall)",
    )]


def _build_prompt(breaking: list[Finding], fmt: str) -> str:
    lines = [f"Format: {fmt}", "Confirmed breaking changes:"]
    for f in breaking[:40]:
        lines.append(f"- [{f.severity}] {f.location}: {f.summary}")
    if len(breaking) > 40:
        lines.append(f"... and {len(breaking) - 40} more")
    changes_block = "\n".join(lines)
    return (
        "You are an API compatibility analyst. Below are confirmed breaking "
        "changes produced by a deterministic diff engine. Write a concise "
        "consumer-impact assessment (2-4 sentences) and identify the single "
        "most urgent change to address first.\n\n"
        f"{changes_block}\n\n"
        'Return ONLY a JSON object: {"impact_summary": "...", "top_priority": "..."}'
    )


def _call_llm(prompt: str, settings) -> str:
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model or _ADVISORY_MODEL_FALLBACK,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None