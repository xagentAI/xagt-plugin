"""Deterministic verdict engine. No LLM. Pure function of session state + claim."""
import hashlib
import json
from typing import Any

from app.services.obligations import REASONS, obligations_for
from app.services.pagination import check_chain, is_exhausted
from app.services.scope import scope_hash


def _reason(code: str, severity: str = "blocking") -> dict[str, Any]:
    meta = REASONS.get(code, {"message": code, "action": "DO_NOT_MAKE_EXHAUSTIVE_CLAIM"})
    return {"code": code, "message": meta["message"], "severity": severity,
            "recommended_next_action": meta["action"]}


def verify(session: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    ctype = str(claim.get("type", "")).upper()
    observations: list[dict] = session.get("observations", [])
    failures: list[dict] = session.get("failures", [])
    pagination_type = session.get("pagination_type", "cursor")
    strategy = session.get("snapshot_strategy", "STRICT")
    base_scope_hash = session.get("scope_hash", "")

    blocking: list[dict] = []
    warnings: list[dict] = []
    obligations = obligations_for(ctype)
    obligation_status: dict[str, str] = {}

    # --- scope stability
    scope_ok = True
    for ob in observations:
        if ob.get("scope_hash") and ob["scope_hash"] != base_scope_hash:
            scope_ok = False
    if not scope_ok:
        blocking.append(_reason("SCOPE_MISMATCH"))
    obligation_status["SCOPE_STABLE"] = "satisfied" if scope_ok else "failed"

    # --- failures
    rate_limited = any(f.get("kind") == "rate_limit" for f in failures)
    if rate_limited:
        blocking.append(_reason("RATE_LIMIT_INTERRUPTION"))
    if failures:
        blocking.append(_reason("UNRESOLVED_FAILURE"))
    obligation_status["NO_UNRESOLVED_FAILURES"] = "satisfied" if not failures else "failed"

    # --- pagination chain
    chain_problems = check_chain(observations, pagination_type)
    for p in chain_problems:
        blocking.append(_reason(p["code"]))
    obligation_status["NO_CURSOR_GAPS"] = "satisfied" if not chain_problems else "failed"

    # --- exhaustion
    exhausted = is_exhausted(observations)
    if not exhausted:
        blocking.append(_reason("PAGINATION_NOT_EXHAUSTED"))
    obligation_status["RESULT_SET_COMPLETE"] = "satisfied" if exhausted else "failed"

    # --- snapshot
    snaps = [ob.get("snapshot_id") for ob in observations if ob.get("snapshot_id")]
    snapshot_status = "UNKNOWN"
    if snaps:
        snapshot_status = "STABLE" if len(set(snaps)) == 1 else "CHANGED"
    if snapshot_status == "CHANGED":
        if strategy == "STRICT":
            blocking.append(_reason("SNAPSHOT_CHANGED"))
        # BEST_EFFORT -> handled below as CONDITIONAL
    elif snapshot_status == "UNKNOWN":
        warnings.append(_reason("UNKNOWN_SNAPSHOT_STATE", "info"))
    obligation_status["SNAPSHOT_ACCEPTABLE"] = "satisfied" if snapshot_status in ("STABLE", "UNKNOWN") else ("conditional" if strategy == "BEST_EFFORT" else "failed")

    pages_seen = len(observations)
    records_seen = sum(int(ob.get("records_seen", 0)) for ob in observations)

    # --- claim-specific checks (only meaningful if structurally complete)
    certified_value: Any = None
    if ctype == "EXACT_COUNT":
        claimed = claim.get("value")
        auth_totals = [ob.get("authoritative_total") for ob in observations if ob.get("authoritative_total") is not None]
        if exhausted and not failures and scope_ok:
            if auth_totals and len(set(auth_totals)) == 1 and auth_totals[0] == records_seen:
                certified_value = records_seen
            elif not auth_totals:
                certified_value = records_seen
            if claimed is not None and int(claimed) != int(records_seen):
                blocking.append(_reason("CLAIM_VALUE_MISMATCH"))
                certified_value = None
        obligation_status["COUNT_CONSISTENT"] = "satisfied" if certified_value is not None or not exhausted else "failed"
    elif ctype == "NONE":
        if exhausted and records_seen > 0:
            blocking.append(_reason("CLAIM_VALUE_MISMATCH"))
        elif exhausted:
            certified_value = 0
        obligation_status["NO_MATCHES_OBSERVED"] = "satisfied" if records_seen == 0 else "failed"
    elif ctype == "ALL":
        if exhausted:
            certified_value = records_seen
    elif ctype in ("MIN", "MAX"):
        field = claim.get("field")
        cand = claim.get("candidate_id")
        items = [it for ob in observations for it in (ob.get("items") or [])]
        if not field:
            blocking.append(_reason("MISSING_REQUIRED_FIELD"))
        elif exhausted and items and all(isinstance(it, dict) and field in it and isinstance(it[field], (int, float)) for it in items):
            extreme = min(it[field] for it in items) if ctype == "MIN" else max(it[field] for it in items)
            holders = [it.get("id") for it in items if it[field] == extreme]
            if cand is not None and cand not in holders:
                blocking.append(_reason("CLAIM_VALUE_MISMATCH"))
            else:
                certified_value = {"field": field, "value": extreme, "holder_ids": holders}
        elif exhausted:
            blocking.append(_reason("MISSING_REQUIRED_FIELD"))
        obligation_status["TARGET_FIELD_AVAILABLE_FOR_ALL_CANDIDATES"] = "satisfied" if certified_value is not None else "failed"
        obligation_status["COMPARISON_DOMAIN_VALID"] = "satisfied" if certified_value is not None else ("failed" if exhausted else "pending")

    if ctype not in ("NONE", "ALL", "EXACT_COUNT", "MIN", "MAX"):
        return {"verdict": "UNPROVEN", "claim_type": ctype, "obligations": obligations,
                "obligation_status": obligation_status,
                "blocking_reasons": [_reason("CLAIM_VALUE_MISMATCH")],
                "required_next_actions": ["DO_NOT_MAKE_EXHAUSTIVE_CLAIM"],
                "evidence_summary": {"pages_seen": pages_seen, "records_seen": records_seen,
                                     "continuation_available": not exhausted, "snapshot_status": snapshot_status}}

    if blocking:
        verdict = "UNPROVEN"
    elif snapshot_status == "CHANGED" and strategy == "BEST_EFFORT":
        verdict = "CONDITIONAL"
    else:
        verdict = "PROVEN"

    actions = sorted({r["recommended_next_action"] for r in blocking}) or ([] if verdict == "PROVEN" else ["DO_NOT_MAKE_EXHAUSTIVE_CLAIM"])
    return {"verdict": verdict, "claim_type": ctype, "obligations": obligations,
            "obligation_status": obligation_status, "blocking_reasons": blocking,
            "required_next_actions": actions,
            "certified_value": certified_value, "records_examined": records_seen,
            "pages_examined": pages_seen,
            "evidence_summary": {"pages_seen": pages_seen, "records_seen": records_seen,
                                 "continuation_available": not exhausted, "snapshot_status": snapshot_status}}
