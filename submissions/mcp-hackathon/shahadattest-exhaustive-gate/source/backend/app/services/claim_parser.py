"""Deterministic NL claim parser (regex first; LLM optional later)."""
import re
from typing import Any


def parse_claim(text: str) -> dict[str, Any]:
    t = text.strip().lower()
    m = re.search(r"there are no (.+)", t)
    if m or t.startswith("no ") or "no matching" in t or "not found" in t:
        return {"type": "NONE", "resource": _resource(t), "scope": _scope_hint(t)}
    m = re.search(r"these are all (.+)|here are all (.+)|every matching (.+)", t)
    if m or (t.startswith("all ") or " are all " in t):
        return {"type": "ALL", "resource": _resource(t), "scope": {}}
    m = re.search(r"exactly (\d+)", t)
    if m:
        return {"type": "EXACT_COUNT", "resource": _resource(t), "scope": _scope_hint(t), "value": int(m.group(1))}
    if "cheapest" in t or "lowest" in t or "shortest" in t or "minimum" in t:
        return {"type": "MIN", "resource": _resource(t), "field": _field_hint(t)}
    if "highest" in t or "most expensive" in t or "largest" in t or "maximum" in t or "highest-value" in t:
        return {"type": "MAX", "resource": _resource(t), "field": _field_hint(t)}
    return {"type": "UNKNOWN", "resource": _resource(t), "scope": {}}


def _resource(t: str) -> str:
    for w in ("invoice", "customer", "product", "ticket", "order", "event", "record"):
        if w in t:
            return w
    return "record"


def _scope_hint(t: str) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    for w in ("unpaid", "overdue", "open", "active", "paid"):
        if w in t:
            scope["status"] = w
    return scope


def _field_hint(t: str) -> str:
    if "price" in t or "cheapest" in t or "expensive" in t:
        return "price"
    if "value" in t:
        return "value"
    if "balance" in t:
        return "balance"
    return "value"
