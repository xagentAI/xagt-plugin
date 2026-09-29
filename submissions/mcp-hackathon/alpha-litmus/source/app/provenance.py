"""Process-stable build claims, not proof that a Git object actually exists."""

import os
import re
from functools import lru_cache
from typing import TypedDict


class CommitState(TypedDict):
    commit: str
    commit_reviewable: bool


@lru_cache(maxsize=1)
def _snapshot() -> tuple[str, bool]:
    value = os.getenv("ALPHALITMUS_COMMIT", "")
    valid = re.fullmatch(r"[0-9a-f]{40}", value) is not None and value != "0" * 40
    return (value if valid else "local-dev", valid)


def commit_state() -> CommitState:
    """Return a syntax-only SHA claim or the sole fallback local-dev/False.

    Reviewability does not verify Git object existence or authenticity.
    """
    commit, reviewable = _snapshot()
    return {"commit": commit, "commit_reviewable": reviewable}


def validate_startup() -> None:
    state = commit_state()
    if os.getenv("ALPHALITMUS_ENV") == "production" and not state["commit_reviewable"]:
        raise RuntimeError("Production requires a nonzero lowercase 40-character build commit")
