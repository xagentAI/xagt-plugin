# -*- coding: utf-8 -*-
"""Consumer-aware impact analysis and transitive propagation.

Beyond the plain diff (which mirrors mature tooling), this module answers two
questions that classic diff tools do not:

1. **Consumer-aware compatibility** — given a ``consumer_profile`` describing
   which paths / schemas / fields a specific caller actually uses, which
   findings actually hit that caller (and which can be safely ignored)?
2. **Transitive propagation** — when a referenced component schema changes,
   which operations are affected (a change to ``Pet.age`` can break every
   endpoint that returns a ``Pet``)?

All logic is deterministic and LLM-free.
"""
from __future__ import annotations

import re

from .diff_core import DiffError, detect_changes, normalize_format
from .models import FORMAT_GRAPHQL, FORMAT_JSON_SCHEMA, FORMAT_OPENAPI

_METHOD_RE = re.compile(
    r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE)\s+(/\S+?)"
    r"(?:\.|\s|$)"
)
_COMPONENT_SCHEMA_RE = re.compile(r"#/components/schemas/([A-Za-z0-9_\-]+)")
_GRAPHQL_TYPE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?=:|\.|$)")
_JSON_POINTER_RE = re.compile(r"#/(?:[A-Za-z0-9_\-]+/)")
_SCHEMA_REF_RE = re.compile(r"\$ref['\"]?\s*:\s*['\"]?#/components/schemas/([A-Za-z0-9_\-]+)")


def _parse_location(loc: str) -> dict:
    """Split a finding location into machine-consumable tokens."""
    loc = loc or ""
    tokens = {
        "methods": [],
        "paths": [],
        "component_schemas": [],
        "type_refs": [],
        "json_pointers": [],
    }
    m = _METHOD_RE.match(loc)
    if m:
        tokens["methods"].append(m.group(1))
        tokens["paths"].append(m.group(2))
    tokens["component_schemas"] = _COMPONENT_SCHEMA_RE.findall(loc)
    t = _GRAPHQL_TYPE_RE.match(loc)
    if t and not tokens["component_schemas"]:
        tokens["type_refs"].append(t.group(1))
    tokens["json_pointers"] = _JSON_POINTER_RE.findall(loc)
    return tokens


def _path_eq(a: str, b: str) -> bool:
    a = (a or "").strip().rstrip("/")
    b = (b or "").strip().rstrip("/")
    return a == b or a.lstrip("/") == b.lstrip("/")


def _profile_path_match(profile_paths: list[str], finding_paths: list[str]) -> bool:
    for p in profile_paths or []:
        for fp in finding_paths:
            if _path_eq(p, fp):
                return True
    return False


def matches_profile(finding, profile: dict) -> tuple[bool, str]:
    """Return (hit, reason) whether a finding affects the given consumer."""
    if not profile:
        return True, "no profile (full impact)"
    loc = finding.location or ""
    tokens = _parse_location(loc)

    if profile.get("paths"):
        if _profile_path_match(profile["paths"], tokens["paths"]):
            return True, "path match"
    if profile.get("schemas"):
        for s in profile["schemas"]:
            if s in tokens["component_schemas"] or s in tokens["type_refs"]:
                return True, f"schema '{s}'"
    if profile.get("fields"):
        for f in profile["fields"]:
            f = f.strip()
            if loc.startswith(f) or f in tokens["json_pointers"]:
                return True, f"field '{f}'"
    return False, ""


# --------------------------------------------------------------------------- #
# Transitive propagation (OpenAPI reference graph)
# --------------------------------------------------------------------------- #
def _collect_refs(schema, doc: dict, out: set) -> None:
    """Collect every #/components/schemas/X referenced by a schema subtree."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            out.add(name)
        for v in schema.values():
            _collect_refs(v, doc, out)
    elif isinstance(schema, list):
        for v in schema:
            _collect_refs(v, doc, out)


def _operation_refs(doc: dict, path: str, method: str) -> set:
    """All component schemas referenced by one operation's I/O."""
    refs: set = set()
    item = (doc.get("paths") or {}).get(path) or {}
    op = item.get(method) or {}
    for schema_holder in _iter_operation_schemas(op):
        _collect_refs(schema_holder, doc, refs)
    return refs


def _iter_operation_schemas(op: dict):
    yield op.get("requestBody") if isinstance(op.get("requestBody"), dict) else None
    for p in op.get("parameters") or []:
        if isinstance(p, dict):
            yield p.get("schema")
            yield p.get("content")
    for resp in (op.get("responses") or {}).values():
        if isinstance(resp, dict):
            yield resp.get("content")
            yield resp.get("schema")


def build_reference_graph(doc: dict) -> dict:
    """Map each component schema to the operations that reference it."""
    graph: dict[str, set] = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method in ("parameters",) or not isinstance(op, dict):
                continue
            op_loc = f"{method.upper()} {path}"
            for name in _operation_refs(doc, path, method.lower()):
                graph.setdefault(name, set()).add(op_loc)
    return {k: sorted(v) for k, v in graph.items()}


def _expand_location_schema_roots(loc: str, doc: dict, fmt: str) -> list[str]:
    """Resolve a finding location to the component schemas it belongs to."""
    roots: list[str] = []
    tokens = _parse_location(loc)
    roots.extend(tokens["component_schemas"])
    if fmt == FORMAT_OPENAPI and tokens["methods"] and tokens["paths"]:
        path, method = tokens["paths"][0], tokens["methods"][0].lower()
        roots.extend(sorted(_operation_refs(doc, path, method) - set(roots)))
    return roots


def compute_affected_operations(finding, old_doc: dict, new_doc: dict, fmt: str) -> list[str]:
    """Transitively list the operations affected by a single finding."""
    if fmt != FORMAT_OPENAPI:
        return []
    loc = finding.location or ""
    tokens = _parse_location(loc)
    direct = {
        f"{method} {path}"
        for method, path in zip(tokens["methods"], tokens["paths"])
    }
    graph = build_reference_graph(old_doc)
    affected: set = set()
    for root in _expand_location_schema_roots(loc, old_doc, fmt):
        affected.update(graph.get(root, []))
    affected.update(direct)
    return sorted(affected)


def all_affected_operations(findings, old_doc: dict, new_doc: dict, fmt: str) -> list[str]:
    """Union of affected operations across every finding (full blast radius)."""
    combined: set = set()
    for f in findings:
        combined.update(compute_affected_operations(f, old_doc, new_doc, fmt))
    return sorted(combined)


# --------------------------------------------------------------------------- #
# Top-level orchestration
# --------------------------------------------------------------------------- #
def scan_consumer_impact(
    old_spec: str,
    new_spec: str,
    fmt: str,
    consumer_profile: dict | None = None,
    use_llm: bool = False,
) -> dict:
    """Run the diff, then apply consumer-aware filtering and propagation.

    Returns a JSON-serializable report with ``hits`` (findings that affect the
    consumer), ``misses`` (ignorable ones) and the transitive ``impact``.
    """
    fmt_norm = normalize_format(fmt)
    profile = consumer_profile or {}
    report = detect_changes(old_spec, new_spec, fmt_norm, use_llm=use_llm)

    old_doc = new_doc = {}
    try:
        if fmt_norm == FORMAT_OPENAPI:
            from .engines.openapi import parse_openapi
            old_doc = parse_openapi(old_spec)
            new_doc = parse_openapi(new_spec)
    except Exception:  # pragma: no cover - parse already succeeded in detect_changes
        old_doc = new_doc = {}

    hits, misses = [], []
    for f in report.findings:
        entry = f.as_dict()
        entry["affected_operations"] = compute_affected_operations(
            f, old_doc, new_doc, fmt_norm
        )
        hit, reason = matches_profile(f, profile)
        entry["hit"] = hit
        if reason:
            entry["match_reason"] = reason
        (hits if hit else misses).append(entry)

    consumer_affected = any(e["breaking"] for e in hits)
    return {
        "schema_version": report.schema_version,
        "format": fmt_norm,
        "breaking": report.breaking,
        "total_changes": report.total_changes,
        "consumer_aware": bool(profile),
        "consumer_affected": consumer_affected,
        "consumer_breaking_count": sum(1 for e in hits if e["breaking"]),
        "hit_count": len(hits),
        "miss_count": len(misses),
        "hits": hits,
        "misses": misses,
        "impact": {
            "affected_operations": all_affected_operations(
                report.findings, old_doc, new_doc, fmt_norm
            ),
            "schema_to_operations": build_reference_graph(old_doc) if fmt_norm == FORMAT_OPENAPI else {},
        },
        "summary": (
            f"{report.summary} "
            + (
                f"Consumer affected: {consumer_affected} ({len(hits)} hit / {len(misses)} ignorable)."
                if profile
                else f"Blast radius: {len(all_affected_operations(report.findings, old_doc, new_doc, fmt_norm))} operation(s)."
            )
        ),
    }