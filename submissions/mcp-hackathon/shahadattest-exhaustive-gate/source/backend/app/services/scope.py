"""Scope canonicalization + deterministic hashing."""
import hashlib
import json
from typing import Any


def canonicalize(scope: dict[str, Any]) -> str:
    return json.dumps(scope or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def scope_hash(scope: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(scope).encode("utf-8")).hexdigest()
