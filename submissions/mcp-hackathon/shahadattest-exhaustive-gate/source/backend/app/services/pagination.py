"""Cursor/offset/page-number chain validation. Pure + deterministic."""
from typing import Any


def check_chain(observations: list[dict[str, Any]], pagination_type: str) -> list[dict[str, str]]:
    """Return list of pagination problems (codes). Empty == chain OK so far."""
    problems: list[dict[str, str]] = []
    if not observations:
        return problems
    seen_pages: set[Any] = set()
    seen_cursors_out: set[str] = set()
    prev_out: str | None = None
    prev_page: int | None = None
    for i, ob in enumerate(observations):
        pg = ob.get("page_number")
        if pg is not None:
            if pg in seen_pages:
                problems.append({"code": "MISSING_PAGE", "message": f"Duplicate page number {pg} (possible retry/loop)."})
            seen_pages.add(pg)
            if prev_page is not None and pg != prev_page + 1 and pagination_type in ("page", "offset"):
                problems.append({"code": "MISSING_PAGE", "message": f"Page gap: {prev_page} -> {pg}."})
            prev_page = pg if isinstance(pg, int) else prev_page
        cin, cout = ob.get("cursor_in"), ob.get("cursor_out")
        if pagination_type == "cursor" and i > 0:
            if cin != prev_out and not (cin is None and prev_out is None):
                problems.append({"code": "CURSOR_CHAIN_BROKEN", "message": f"Observation {i}: cursor_in {cin!r} != previous cursor_out {prev_out!r}."})
        if cout is not None:
            if cout in seen_cursors_out:
                problems.append({"code": "CURSOR_LOOP", "message": f"Cursor {cout!r} already emitted (loop)."})
            seen_cursors_out.add(cout)
            if pagination_type == "cursor" and cin is not None and cout == cin:
                problems.append({"code": "CURSOR_LOOP", "message": f"Cursor did not advance ({cin!r})."})
        prev_out = cout
    return problems


def is_exhausted(observations: list[dict[str, Any]]) -> bool:
    if not observations:
        return False
    return observations[-1].get("has_more") is False
