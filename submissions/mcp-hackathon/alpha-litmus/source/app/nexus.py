"""Bounded, read-only access to the four documented Nexus evidence tools."""
import asyncio
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import httpx

BASE = "https://nexus.olaxbt.xyz/api/mcp"
MAX_BYTES = 2_000_000
MAX_DEPTH = 32
MAX_ROWS = 10_000
MAX_NUMBER = 1e15
SURFACES = ("signal", "metrics", "equity", "trades")
TIMEOUT = httpx.Timeout(connect=5, read=15, write=5, pool=5)
_CREDENTIAL = re.compile(r"nxk_|sk[-_]|bearer|api[-_]?key|secret|password|token|authorization", re.I)
_SYMBOL = re.compile(r"[A-Z0-9]{1,16}/[A-Z0-9]{1,16}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_PERCENT = re.compile(r"-?[0-9]{1,12}(?:\.[0-9]{1,10})?%")


def nexus_api_key() -> str:
    """Load the Nexus key from env or a bounded Docker-secret file.

    The file path is operator configuration, never caller input. Multiline,
    oversized, missing, linked, or undecodable files fail closed.
    """
    direct = os.getenv("NEXUS_API_KEY", "")
    if direct:
        return direct if "\n" not in direct and "\r" not in direct and len(direct) <= 512 else ""
    raw_path = os.getenv("NEXUS_API_KEY_FILE", "")
    if not raw_path:
        return ""
    path = Path(raw_path)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512:
            return ""
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""
    if not value or len(value) > 512 or "\n" in value or "\r" in value:
        return ""
    return value


def nexus_key_configured() -> bool:
    return bool(nexus_api_key())


def number(value: object) -> float | None:
    """Only finite JSON numbers within conservative computational bounds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not -MAX_NUMBER <= value <= MAX_NUMBER:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _validate(value: object, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("NEXUS_SCHEMA_ERROR")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("NEXUS_SCHEMA_ERROR")
            _validate(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate(child, depth + 1)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if number(value) is None:
            raise ValueError("NEXUS_SCHEMA_ERROR")
    elif value is not None and not isinstance(value, (str, bool)):
        raise ValueError("NEXUS_SCHEMA_ERROR")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("NEXUS_SCHEMA_ERROR")
        result[name] = value
    return result


def unpack(payload: object) -> dict[str, Any]:
    """Decode supported MCP envelopes; callers must sanitize before reporting."""
    for _ in range(MAX_DEPTH):
        _validate(payload)
        if not isinstance(payload, dict) or payload.get("isError") or payload.get("error"):
            raise ValueError("NEXUS_SCHEMA_ERROR")
        for field in ("structuredContent", "data", "result"):
            if field in payload:
                payload = payload[field]
                break
        else:
            if "content" not in payload:
                return payload
            content = payload["content"]
            # The production Nexus gateway returns its tool result directly as
            # an object in `content`. Standard MCP clients commonly return the
            # one-item text-content list below. Accept both documented shapes;
            # the same depth, duplicate-key and allowlist sanitization gates
            # still apply before any value reaches a report.
            if isinstance(content, dict):
                payload = content
                continue
            if not isinstance(content, list) or len(content) != 1:
                raise ValueError("NEXUS_SCHEMA_ERROR")
            item = content[0]
            if not isinstance(item, dict) or item.get("type") != "text":
                raise ValueError("NEXUS_SCHEMA_ERROR")
            text = item.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
                raise ValueError("NEXUS_SCHEMA_ERROR")
            try:
                payload = json.loads(text, object_pairs_hook=_unique_object)
            except (ValueError, RecursionError) as exc:
                raise ValueError("NEXUS_SCHEMA_ERROR") from exc
    raise ValueError("NEXUS_SCHEMA_ERROR")


def sanitize(label: str, data: object, key: str = "") -> dict[str, Any]:
    """Pure allowlist sanitizer; live ingestion explicitly supplies its secret."""
    if not isinstance(data, dict):
        raise ValueError("NEXUS_SCHEMA_ERROR")

    def safe(value: object) -> bool:
        text = str(value)
        return not (key and key.casefold() in text.casefold()) and not _CREDENTIAL.search(text)

    def fields(source: dict[str, Any], schema: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, kind in schema.items():
            value = source.get(name)
            if not isinstance(value, (str, int, float)) or not safe(value):
                continue
            numeric = number(value)
            if kind == "number" and numeric is not None:
                result[name] = value
            elif kind == "count" and numeric is not None and numeric >= 0 and numeric.is_integer():
                result[name] = int(numeric)
            elif kind == "percent" and isinstance(value, str) and _PERCENT.fullmatch(value):
                result[name] = value
            elif kind == "symbol" and isinstance(value, str) and _SYMBOL.fullmatch(value):
                result[name] = value
            elif kind == "id" and isinstance(value, str) and _ID.fullmatch(value):
                result[name] = value
            elif kind == "intent" and value in ("BUY", "SELL", "HOLD"):
                result[name] = value
            elif kind == "status" and value in ("QUALIFIED_FOR_OKX_LISTING", "NOT_QUALIFIED"):
                result[name] = value
        return result

    if label == "signal":
        return fields(data, {"symbol": "symbol", "trade_intent": "intent", "timestamp": "number"})
    if label == "metrics":
        return fields(data, {
            "sharpe_ratio": "number", "trading_period_days": "number",
            "estimated_aum_usdt": "number", "profit_factor": "number",
            "max_drawdown": "percent", "total_return_pct": "number",
            "win_rate_pct": "number", "trade_count": "count", "status": "status",
        })
    if label not in ("equity", "trades"):
        raise ValueError("NEXUS_SCHEMA_ERROR")
    result = fields(data, {"run_id": "id"})
    collection = "points" if label == "equity" else "trades"
    rows = data.get(collection)
    if rows is not None:
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise ValueError("NEXUS_SCHEMA_ERROR")
        schema = {"t": "number", "equity": "number"} if label == "equity" else {"symbol": "symbol", "pnl": "number"}
        # Preserve invalid rows as empty records, never silently shrink a sample.
        result[collection] = [fields(row, schema) if isinstance(row, dict) else {} for row in rows]
    return result


async def read_nexus(symbol: str) -> dict[str, Any]:
    key = nexus_api_key()
    reason = "NEXUS_NOT_CONFIGURED" if not key else "NEXUS_INVALID_SYMBOL"
    if not key or sanitize("signal", {"symbol": symbol}, key).get("symbol") != symbol:
        return {label: {"status": "unavailable", "reason": reason} for label in SURFACES}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
        async def fetch(label: str) -> tuple[str, dict[str, Any]]:
            tool = "get_strategy_" + label
            try:
                async with client.stream(
                    "POST", BASE + "/tools/call", headers={"X-API-KEY": key, "Accept-Encoding": "identity"},
                    json={"name": tool, "arguments": {"symbol": symbol} if label == "signal" else {}},
                ) as response:
                    if response.status_code != 200:
                        return label, {"status": "unavailable", "reason": "NEXUS_HTTP_ERROR"}
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ValueError("NEXUS_SCHEMA_ERROR")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
                        raise ValueError("NEXUS_SCHEMA_ERROR")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise ValueError("NEXUS_SCHEMA_ERROR")
                        body.extend(chunk)
                data = sanitize(label, unpack(json.loads(body, object_pairs_hook=_unique_object)), key)
                if not data:
                    raise ValueError("NEXUS_SCHEMA_ERROR")
                return label, {
                    "status": "received", "tool": tool,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                    "data": data,
                }
            except httpx.TimeoutException:
                return label, {"status": "unavailable", "reason": "NEXUS_TIMEOUT"}
            except (httpx.HTTPError, ValueError, TypeError, RecursionError, OverflowError):
                return label, {"status": "unavailable", "reason": "NEXUS_TRANSPORT_OR_SCHEMA_ERROR"}

        return dict(await asyncio.gather(*(fetch(label) for label in SURFACES)))
