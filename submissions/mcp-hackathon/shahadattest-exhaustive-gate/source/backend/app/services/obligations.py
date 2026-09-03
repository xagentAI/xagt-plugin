"""Proof obligations per claim type."""
from typing import Any

OBLIGATIONS: dict[str, list[str]] = {
    "NONE": ["RESULT_SET_COMPLETE", "NO_MATCHES_OBSERVED", "NO_UNRESOLVED_FAILURES", "SCOPE_STABLE", "SNAPSHOT_ACCEPTABLE"],
    "ALL": ["RESULT_SET_COMPLETE", "NO_UNRESOLVED_FAILURES", "SCOPE_STABLE", "SNAPSHOT_ACCEPTABLE"],
    "EXACT_COUNT": ["RESULT_SET_COMPLETE", "NO_UNRESOLVED_FAILURES", "SCOPE_STABLE", "NO_CURSOR_GAPS", "SNAPSHOT_ACCEPTABLE", "COUNT_CONSISTENT"],
    "MIN": ["RESULT_SET_COMPLETE", "NO_UNRESOLVED_FAILURES", "SCOPE_STABLE", "SNAPSHOT_ACCEPTABLE", "TARGET_FIELD_AVAILABLE_FOR_ALL_CANDIDATES", "COMPARISON_DOMAIN_VALID"],
    "MAX": ["RESULT_SET_COMPLETE", "NO_UNRESOLVED_FAILURES", "SCOPE_STABLE", "SNAPSHOT_ACCEPTABLE", "TARGET_FIELD_AVAILABLE_FOR_ALL_CANDIDATES", "COMPARISON_DOMAIN_VALID"],
}

REASONS: dict[str, dict[str, str]] = {
    "PAGINATION_NOT_EXHAUSTED": {"message": "The upstream result set has not been fully traversed.", "action": "FETCH_NEXT_PAGE"},
    "CURSOR_CHAIN_BROKEN": {"message": "Cursor chain is discontinuous; coverage has gaps.", "action": "RESTART_WITH_STABLE_SNAPSHOT"},
    "CURSOR_LOOP": {"message": "A cursor repeated; retrieval is looping.", "action": "RESTART_WITH_STABLE_SNAPSHOT"},
    "MISSING_PAGE": {"message": "Pages are missing, duplicated, or out of order.", "action": "FETCH_MISSING_CANDIDATES"},
    "UNRESOLVED_FAILURE": {"message": "A page failed and was never retried successfully.", "action": "RETRY_FAILED_PAGE"},
    "RATE_LIMIT_INTERRUPTION": {"message": "Rate limiting interrupted retrieval.", "action": "RETRY_FAILED_PAGE"},
    "SCOPE_MISMATCH": {"message": "Filters/scope changed during retrieval.", "action": "NORMALIZE_SCOPE"},
    "SNAPSHOT_CHANGED": {"message": "Dataset snapshot changed during retrieval.", "action": "RESTART_WITH_STABLE_SNAPSHOT"},
    "UNKNOWN_SNAPSHOT_STATE": {"message": "No snapshot information supplied.", "action": "VERIFY_SOURCE_TOTAL"},
    "CLAIM_VALUE_MISMATCH": {"message": "Claimed value contradicts observed evidence.", "action": "DO_NOT_MAKE_EXHAUSTIVE_CLAIM"},
    "MISSING_REQUIRED_FIELD": {"message": "Comparison field missing on some candidates.", "action": "FETCH_MISSING_CANDIDATES"},
    "AUTHORITATIVE_COUNT_MISSING": {"message": "No complete enumeration and no trusted total.", "action": "VERIFY_SOURCE_TOTAL"},
}


def obligations_for(claim_type: str) -> list[str]:
    return list(OBLIGATIONS.get(claim_type.upper(), []))
