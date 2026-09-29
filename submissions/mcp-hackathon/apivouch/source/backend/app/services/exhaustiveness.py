from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import GIT_COMMIT, MAX_PROOF_PAGES, MAX_PROOF_RECORDS
from app.services.http_client import safe_request
from app.services.tester import prepare_request

_MISSING = object()
_ITEM_PATHS = ("items", "results", "records", "data")
_NEXT_PATHS = ("next_cursor", "nextCursor", "next_page_token", "nextPageToken", "pagination.next_cursor")
_MORE_PATHS = ("has_more", "hasMore", "pagination.has_more")
_TOTAL_PATHS = ("total", "total_count", "totalCount", "pagination.total")
_SNAPSHOT_PATHS = ("snapshot_id", "snapshotId", "snapshot", "pagination.snapshot_id", "meta.snapshot_id")
_CURSOR_PARAMS = ("cursor", "page_token", "pageToken", "after", "next_cursor")
_PAGE_PARAMS = ("page", "page_number", "pageNumber")
_OFFSET_PARAMS = ("offset", "skip")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _at_path(value: Any, path: str | None) -> Any:
    if not path:
        return _MISSING
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _first_path(value: Any, explicit: str | None, candidates: tuple[str, ...]) -> tuple[Any, str | None]:
    if explicit:
        return _at_path(value, explicit), explicit
    for path in candidates:
        result = _at_path(value, path)
        if result is not _MISSING:
            return result, path
    return _MISSING, None


def _extract_items(payload: Any, explicit_path: str | None) -> tuple[list[Any] | None, str | None]:
    if isinstance(payload, list) and not explicit_path:
        return payload, "$"
    result, path = _first_path(payload, explicit_path, _ITEM_PATHS)
    return (result, path) if isinstance(result, list) else (None, path)


def _pagination_strategy(endpoint: dict[str, Any], pagination: dict[str, Any]) -> tuple[str, str | None]:
    mode = pagination.get("mode", "auto")
    parameter = pagination.get("request_token_parameter")
    query_names = [str(item.get("name")) for item in endpoint.get("parameters") or [] if item.get("in") == "query" and item.get("name")]
    if mode != "auto":
        if mode == "single":
            return mode, None
        defaults = {"cursor": "cursor", "page": "page", "offset": "offset"}
        return mode, parameter or defaults[mode]
    if parameter:
        lowered = parameter.lower()
        if "offset" in lowered or lowered == "skip":
            return "offset", parameter
        if "page" in lowered and "token" not in lowered:
            return "page", parameter
        return "cursor", parameter
    for names, detected_mode in ((_CURSOR_PARAMS, "cursor"), (_PAGE_PARAMS, "page"), (_OFFSET_PARAMS, "offset")):
        match = next((name for name in query_names if name in names), None)
        if match:
            return detected_mode, match
    return "single", None


def _problem(code: str, message: str, next_action: str) -> dict[str, str]:
    return {"code": code, "message": message, "next_action": next_action}


def _evaluate_claim(items: list[Any], claim: dict[str, Any], complete: bool, blockers: list[dict[str, str]]) -> tuple[str, Any]:
    claim_type = claim["claim_type"]
    certified: Any = None
    if claim_type == "ALL":
        certified = {"records": len(items)}
    elif claim_type == "NONE":
        certified = len(items) == 0
        if items:
            blockers.append(_problem("CLAIM_FALSE", f"The server returned {len(items)} record(s), not none.", "Narrow the scope or revise the claim."))
    elif claim_type == "EXACT_COUNT":
        expected = claim.get("expected_count")
        if expected is None:
            blockers.append(_problem("EXPECTED_COUNT_REQUIRED", "EXACT_COUNT requires expected_count.", "Provide the count to verify."))
        else:
            certified = len(items)
            if len(items) != expected:
                blockers.append(_problem("CLAIM_FALSE", f"Expected {expected} records but the server returned {len(items)}.", "Revise the claim or inspect the upstream dataset."))
    else:
        field = claim.get("field")
        if not field:
            blockers.append(_problem("FIELD_REQUIRED", f"{claim_type} requires a numeric field.", "Provide the dotted field path to compare."))
        else:
            comparable: list[tuple[float, Any]] = []
            for item in items:
                value = _at_path(item, field)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    blockers.append(_problem("NON_NUMERIC_FIELD", f"Every record must contain numeric field '{field}'.", "Fix the field path or the upstream data."))
                    break
                comparable.append((float(value), item))
            if comparable:
                extreme_value = (min if claim_type == "MIN" else max)(pair[0] for pair in comparable)
                chosen = next(pair for pair in comparable if pair[0] == extreme_value)
                chosen_id = _at_path(chosen[1], claim.get("id_field") or "id")
                candidate_id = claim.get("candidate_id")
                if candidate_id is not None:
                    candidate = next((pair for pair in comparable if _at_path(pair[1], claim.get("id_field") or "id") == candidate_id), None)
                    if candidate is None:
                        blockers.append(_problem("CANDIDATE_NOT_FOUND", f"Candidate {candidate_id!r} was not present in the exhaustive result set.", "Check the candidate ID and query scope."))
                    elif candidate[0] != extreme_value:
                        blockers.append(_problem("CLAIM_FALSE", f"Candidate {candidate_id!r} is not the {claim_type.lower()} record.", "Use the certified candidate or revise the claim."))
                    else:
                        chosen_id = candidate_id
                certified = {"value": extreme_value, "candidate_id": None if chosen_id is _MISSING else chosen_id}
            elif not blockers:
                blockers.append(_problem("EMPTY_SET", f"{claim_type} is undefined for an empty result set.", "Use NONE or query a non-empty scope."))
    if not complete and not any(item["code"] == "COLLECTION_INCOMPLETE" for item in blockers):
        blockers.append(_problem("COLLECTION_INCOMPLETE", "The full result set was not traversed.", "Fix pagination metadata or increase a bounded collection limit."))
    return ("UNPROVEN" if blockers else "PROVEN"), certified


def _failure(claim: dict[str, Any], code: str, message: str, next_action: str) -> dict[str, Any]:
    return {
        "success": False,
        "verdict": "UNPROVEN",
        "claim": {key: value for key, value in claim.items() if key != "arguments"},
        "certified_value": None,
        "blocking_reasons": [_problem(code, message, next_action)],
        "warnings": [],
        "evidence": {"source": "server-collected", "complete": False, "pages_examined": 0, "records_examined": 0},
        "certificate": None,
    }


async def prove_exhaustive_claim(endpoint: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    """Traverse a read-only collection and evaluate a claim from server-owned evidence."""
    if endpoint.get("method") != "GET":
        return _failure(claim, "UNSAFE_OPERATION", "Exhaustive proofs only run against GET operations.", "Choose a read-only collection operation.")

    pagination = dict(claim.get("pagination") or {})
    max_pages = min(int(pagination.get("max_pages", MAX_PROOF_PAGES)), MAX_PROOF_PAGES)
    max_records = min(int(pagination.get("max_records", MAX_PROOF_RECORDS)), MAX_PROOF_RECORDS)
    mode, token_parameter = _pagination_strategy(endpoint, pagination)
    arguments = dict(claim.get("arguments") or {})
    if token_parameter and token_parameter in arguments:
        return _failure(claim, "PARTIAL_START_FORBIDDEN", f"'{token_parameter}' cannot be supplied by the claimant.", "Remove the pagination token so APIVouch starts from the first page.")

    items: list[Any] = []
    page_digests: list[str] = []
    cursor_chain: list[str] = []
    snapshots: list[Any] = []
    totals: list[int] = []
    warnings: list[dict[str, str]] = []
    blockers: list[dict[str, str]] = []
    complete = False
    record_ids: set[str] = set()
    token: Any = None if mode == "cursor" else (1 if mode == "page" else 0)

    for page_number in range(1, max_pages + 1):
        try:
            prepared = prepare_request(endpoint, arguments)
            if token_parameter and (mode != "cursor" or token is not None):
                prepared["params"][token_parameter] = token
            response = await safe_request("GET", prepared["url"], params=prepared["params"], headers=prepared["headers"])
            if not 200 <= response.status_code < 300:
                blockers.append(_problem("UPSTREAM_HTTP_ERROR", f"Page {page_number} returned HTTP {response.status_code}.", "Restore the upstream operation and retry."))
                break
            payload = response.json()
        except (httpx.HTTPError, HTTPException, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            blockers.append(_problem("COLLECTION_FAILED", f"Page {page_number} could not be collected: {str(exc)[:240]}", "Fix access or response JSON and retry."))
            break

        page_items, items_path = _extract_items(payload, pagination.get("items_path"))
        if page_items is None:
            blockers.append(_problem("ITEMS_NOT_FOUND", f"Page {page_number} has no list at the configured or recognized items path.", "Set pagination.items_path to the response array."))
            break
        page_digest = _digest(payload)
        if page_digest in page_digests:
            blockers.append(_problem("PAGE_REPEATED", f"Page {page_number} repeated a prior response.", "Fix the upstream cursor or pagination configuration."))
            break
        page_digests.append(page_digest)
        for item in page_items:
            identity = _at_path(item, claim.get("id_field") or "id")
            if identity is _MISSING:
                continue
            identity_hash = _digest(identity)
            if identity_hash in record_ids:
                blockers.append(_problem("DUPLICATE_RECORD", f"Record identity {identity!r} appeared more than once.", "Fix unstable or overlapping pagination windows."))
                break
            record_ids.add(identity_hash)
        if blockers:
            break
        items.extend(page_items)

        total, _ = _first_path(payload, pagination.get("total_path"), _TOTAL_PATHS)
        if total is not _MISSING:
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                blockers.append(_problem("INVALID_TOTAL", "The authoritative total must be a non-negative integer.", "Fix total_path or the upstream total."))
                break
            totals.append(total)
        snapshot, _ = _first_path(payload, pagination.get("snapshot_path"), _SNAPSHOT_PATHS)
        if snapshot is not _MISSING:
            snapshots.append(snapshot)
        has_more, _ = _first_path(payload, pagination.get("has_more_path"), _MORE_PATHS)
        next_token, _ = _first_path(payload, pagination.get("next_cursor_path"), _NEXT_PATHS)

        if has_more is not _MISSING and not isinstance(has_more, bool):
            blockers.append(_problem("INVALID_HAS_MORE", "has_more must be a boolean.", "Fix has_more_path or the upstream response."))
            break
        if has_more is False and next_token is not _MISSING and next_token is not None:
            blockers.append(_problem("PAGINATION_SIGNAL_CONFLICT", "has_more is false while a next cursor is present.", "Make the upstream completion signals agree."))
            break
        if has_more is not _MISSING:
            continuation = has_more
        elif next_token is not _MISSING:
            continuation = next_token is not None
        elif totals:
            continuation = len(items) < totals[-1]
        elif token_parameter:
            blockers.append(_problem("COMPLETION_SIGNAL_MISSING", "The paginated response exposes no has_more, next cursor, or authoritative total.", "Add completion metadata or configure its response path."))
            break
        else:
            continuation = False
        if not continuation:
            complete = True
            break
        if not page_items:
            blockers.append(_problem("EMPTY_CONTINUATION_PAGE", "An empty page claims that more results exist.", "Fix the upstream pagination contract."))
            break
        if len(items) >= max_records:
            blockers.append(_problem("RECORD_LIMIT_REACHED", f"Collection reached the server cap of {max_records} records.", "Narrow the query scope or raise the deployment cap."))
            break
        if mode == "single" or not token_parameter:
            blockers.append(_problem("PAGINATION_CONFIGURATION_REQUIRED", "The response has more data but no request token strategy is available.", "Declare a cursor/page/offset parameter or configure pagination.request_token_parameter."))
            break
        if mode == "cursor":
            if next_token is _MISSING or next_token is None:
                blockers.append(_problem("NEXT_CURSOR_MISSING", "The response says more data exists but supplies no next cursor.", "Fix next_cursor_path or the upstream response."))
                break
            hashed_token = _digest(next_token)
            if hashed_token in cursor_chain:
                blockers.append(_problem("CURSOR_REPEATED", "The upstream returned a cursor already used.", "Fix the upstream cursor implementation."))
                break
            cursor_chain.append(hashed_token)
            token = next_token
        elif mode == "page":
            token = int(token) + 1
            cursor_chain.append(_digest(token))
        else:
            token = int(token) + len(page_items)
            cursor_chain.append(_digest(token))

    if len(items) > max_records:
        blockers.append(_problem("RECORD_LIMIT_REACHED", f"Collection exceeded the server cap of {max_records} records.", "Narrow the query scope or raise the deployment cap."))
        complete = False
    if not complete and len(page_digests) >= max_pages and not any(item["code"] == "PAGE_LIMIT_REACHED" for item in blockers):
        blockers.append(_problem("PAGE_LIMIT_REACHED", f"Collection reached the server cap of {max_pages} pages.", "Narrow the query scope or raise the deployment cap."))
    if totals and len(set(totals)) != 1:
        blockers.append(_problem("TOTAL_CHANGED", "The authoritative total changed during traversal.", "Retry against a stable snapshot."))
    if totals and complete and totals[0] != len(items):
        blockers.append(_problem("COUNT_INCONSISTENT", f"The upstream total is {totals[0]} but APIVouch observed {len(items)} records.", "Fix pagination gaps/duplicates or the upstream total."))
    if snapshots and len({_digest(value) for value in snapshots}) != 1:
        blockers.append(_problem("SNAPSHOT_CHANGED", "The dataset snapshot changed during traversal.", "Retry with snapshot-consistent pagination."))

    verdict, certified = _evaluate_claim(items, claim, complete, blockers)
    if verdict == "PROVEN" and not snapshots:
        verdict = "CONDITIONAL"
        warnings.append(_problem("SNAPSHOT_NOT_DECLARED", "Traversal completed, but the API did not expose a stable snapshot identifier.", "Add snapshot/version metadata for a durable proof."))

    evidence = {
        "source": "server-collected",
        "operation_id": endpoint.get("operation_id"),
        "method": "GET",
        "mode": mode,
        "items_path": pagination.get("items_path") or (items_path if page_digests else None),
        "complete": complete,
        "pages_examined": len(page_digests),
        "records_examined": len(items),
        "page_digests": page_digests,
        "cursor_chain_hashes": cursor_chain,
        "snapshot_hash": _digest(snapshots[0]) if snapshots and len({_digest(value) for value in snapshots}) == 1 else None,
        "authoritative_total": totals[0] if totals and len(set(totals)) == 1 else None,
        "request_scope_hash": _digest(arguments),
        "endpoint_fingerprint": _digest({"method": endpoint.get("method"), "base_url": endpoint.get("base_url"), "path": endpoint.get("path"), "parameters": [(item.get("name"), item.get("in")) for item in endpoint.get("parameters") or []]}),
        "limits": {"max_pages": max_pages, "max_records": max_records},
    }
    certificate_payload = {
        "claim": {key: value for key, value in claim.items() if key != "arguments"},
        "certified_value": certified,
        "evidence": evidence,
        "verdict": verdict,
        "review_commit": GIT_COMMIT,
    }
    certificate = None
    if verdict in {"PROVEN", "CONDITIONAL"}:
        evidence_hash = _digest(certificate_payload)
        certificate = {"certificate_id": f"avp_{evidence_hash[:20]}", "evidence_hash": evidence_hash, "review_commit": GIT_COMMIT}
    return {
        "success": True,
        "verdict": verdict,
        "claim": {key: value for key, value in claim.items() if key != "arguments"},
        "certified_value": certified,
        "blocking_reasons": blockers,
        "warnings": warnings,
        "evidence": evidence,
        "certificate": certificate,
    }
