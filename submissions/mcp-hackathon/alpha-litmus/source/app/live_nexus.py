"""Bounded live Nexus pulse for the fixed Candidate v1 strategy.

This module performs four read-only calls, never backtests, trades, orders,
wallet actions, or caller-selected strategy/symbol access. It fails closed and
never substitutes recorded evidence for unavailable live evidence.
"""

from __future__ import annotations

import asyncio
import copy
from collections import deque
from datetime import datetime, timezone
import os
import time
from typing import Any, Final, Literal

import anyio
from pydantic import Field

from app.certificates import verify_report
from app.contracts import ChallengeRequest, ReleaseGateResult, StrictModel
from app.lab import challenge
from app.nexus import SURFACES, nexus_key_configured, read_nexus
from app.release_gate import project

STRATEGY_NAME: Final[Literal["SKLab AlphaLitmus Candidate v1"]] = "SKLab AlphaLitmus Candidate v1"
STRATEGY_ID: Final[Literal["str_b840280ce037"]] = "str_b840280ce037"
SYMBOL: Final[Literal["BTC/USDT"]] = "BTC/USDT"
SOURCE: Final[Literal["OlaXBT Nexus MCP"]] = "OlaXBT Nexus MCP"
CACHE_TTL_SECONDS: Final[Literal[60]] = 60
REQUEST_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW: Final[Literal[30]] = 30
MIN_REFRESH_INTERVAL_SECONDS = 10
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 120

PUBLIC_CODES = frozenset(
    {
        "LIVE_NEXUS_DISABLED",
        "LIVE_NEXUS_RATE_LIMITED",
        "LIVE_NEXUS_CIRCUIT_OPEN",
        "LIVE_NEXUS_UNAVAILABLE",
        "LIVE_NEXUS_INVALID",
    }
)


class LiveNexusError(Exception):
    def __init__(self, code: str) -> None:
        safe = code if code in PUBLIC_CODES else "LIVE_NEXUS_INVALID"
        super().__init__(safe)
        self.code = safe


class LiveNexusResult(StrictModel):
    live_schema_version: Literal["alphalitmus-live-nexus-1"] = "alphalitmus-live-nexus-1"
    strategy_name: Literal["SKLab AlphaLitmus Candidate v1"] = STRATEGY_NAME
    strategy_id: Literal["str_b840280ce037"] = STRATEGY_ID
    symbol: Literal["BTC/USDT"] = SYMBOL
    source: Literal["OlaXBT Nexus MCP"] = SOURCE
    served_at: str
    upstream_fetched_at: str
    surface_fetched_at: dict[str, str]
    freshness_seconds: dict[str, float]
    cache_status: Literal["miss", "hit"]
    cache_age_seconds: float = Field(ge=0, le=CACHE_TTL_SECONDS)
    cache_ttl_seconds: Literal[60] = CACHE_TTL_SECONDS
    upstream_latency_ms: float = Field(ge=0, le=120_000)
    request_limit_per_minute_per_process: Literal[30] = MAX_REQUESTS_PER_WINDOW
    evidence_surfaces: list[str]
    live: Literal[True] = True
    historical: Literal[False] = False
    no_execution: Literal[True] = True
    profitability_claimed: Literal[False] = False
    recorded_fallback_used: Literal[False] = False
    disclosure: str
    release_gate: ReleaseGateResult


_lock = asyncio.Lock()
_requests: deque[float] = deque()
_cache_payload: dict[str, Any] | None = None
_cache_stored_at = 0.0
_last_refresh_attempt: float = -float(MIN_REFRESH_INTERVAL_SECONDS)
_consecutive_failures = 0
_circuit_open_until = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_seconds(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def live_nexus_enabled() -> bool:
    return os.getenv("ALPHALITMUS_ENABLE_LIVE_NEXUS") == "true" and nexus_key_configured()


def reset_live_nexus_state() -> None:
    """Test-only state reset; production never calls this."""
    global _lock, _cache_payload, _cache_stored_at, _last_refresh_attempt
    global _consecutive_failures, _circuit_open_until
    _requests.clear()
    _lock = asyncio.Lock()
    _cache_payload = None
    _cache_stored_at = 0.0
    _last_refresh_attempt = -MIN_REFRESH_INTERVAL_SECONDS
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def _bounded_requests(now: float) -> None:
    while _requests and now - _requests[0] >= REQUEST_WINDOW_SECONDS:
        _requests.popleft()
    if len(_requests) >= MAX_REQUESTS_PER_WINDOW:
        raise LiveNexusError("LIVE_NEXUS_RATE_LIMITED")
    _requests.append(now)


def _cache_result(now: float, served_at: datetime) -> LiveNexusResult | None:
    if _cache_payload is None:
        return None
    age = max(0.0, now - _cache_stored_at)
    if age > CACHE_TTL_SECONDS:
        return None
    payload = copy.deepcopy(_cache_payload)
    payload.update(
        {
            "served_at": _iso_seconds(served_at),
            "cache_status": "hit",
            "cache_age_seconds": min(float(CACHE_TTL_SECONDS), round(age, 3)),
        }
    )
    return LiveNexusResult.model_validate(payload)


def _parse_surface_times(evidence: dict[str, Any], completed: datetime) -> tuple[dict[str, str], dict[str, float]]:
    fetched: dict[str, str] = {}
    freshness: dict[str, float] = {}
    for label in SURFACES:
        envelope = evidence.get(label)
        if not isinstance(envelope, dict) or envelope.get("status") != "received":
            raise LiveNexusError("LIVE_NEXUS_UNAVAILABLE")
        value = envelope.get("fetched_at")
        if not isinstance(value, str):
            raise LiveNexusError("LIVE_NEXUS_INVALID")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise LiveNexusError("LIVE_NEXUS_INVALID") from None
        if parsed.tzinfo != timezone.utc:
            raise LiveNexusError("LIVE_NEXUS_INVALID")
        age = (completed - parsed).total_seconds()
        if age < -5 or age > 120:
            raise LiveNexusError("LIVE_NEXUS_INVALID")
        fetched[label] = value
        freshness[label] = round(max(0.0, age), 3)
    return fetched, freshness


def _note_failure(now: float) -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit_open_until = now + CIRCUIT_OPEN_SECONDS


async def run_live_nexus_candidate() -> LiveNexusResult:
    """Fetch or serve a short-lived verified live result for Candidate v1."""
    global _cache_payload, _cache_stored_at, _last_refresh_attempt
    global _consecutive_failures, _circuit_open_until

    if not live_nexus_enabled():
        raise LiveNexusError("LIVE_NEXUS_DISABLED")
    async with _lock:
        now = _monotonic()
        served_at = _utc_now()
        _bounded_requests(now)
        cached = _cache_result(now, served_at)
        if cached is not None:
            return cached
        if now < _circuit_open_until:
            raise LiveNexusError("LIVE_NEXUS_CIRCUIT_OPEN")
        if now - _last_refresh_attempt < MIN_REFRESH_INTERVAL_SECONDS:
            raise LiveNexusError("LIVE_NEXUS_RATE_LIMITED")
        _last_refresh_attempt = now
        started = _monotonic()
        try:
            evidence = await read_nexus(SYMBOL)
            completed = _utc_now()
            surface_times, freshness = _parse_surface_times(evidence, completed)
            as_of = completed.timestamp()

            def evaluate() -> ReleaseGateResult:
                gate = project(challenge(ChallengeRequest(mode="nexus", symbol=SYMBOL, as_of=as_of), evidence))
                if gate.source_report_verified is not True or not verify_report(gate.report).valid:
                    raise LiveNexusError("LIVE_NEXUS_INVALID")
                return gate

            gate = await anyio.to_thread.run_sync(evaluate, abandon_on_cancel=False)
            latest = max(datetime.fromisoformat(value) for value in surface_times.values())
            latency = max(0.0, (_monotonic() - started) * 1000)
            result = LiveNexusResult(
                served_at=_iso_seconds(completed),
                upstream_fetched_at=latest.isoformat(),
                surface_fetched_at=dict(sorted(surface_times.items())),
                freshness_seconds=dict(sorted(freshness.items())),
                cache_status="miss",
                cache_age_seconds=0.0,
                upstream_latency_ms=round(min(latency, 120_000), 3),
                evidence_surfaces=sorted(surface_times),
                disclosure=(
                    "Live read-only OlaXBT Nexus evidence for fixed Candidate v1; "
                    "not trading authorization, source authentication, or evidence of future profitability."
                ),
                release_gate=gate,
            )
        except asyncio.CancelledError:
            raise
        except LiveNexusError:
            _note_failure(now)
            raise
        except Exception:
            _note_failure(now)
            raise LiveNexusError("LIVE_NEXUS_UNAVAILABLE") from None
        _consecutive_failures = 0
        _circuit_open_until = 0.0
        _cache_stored_at = _monotonic()
        _cache_payload = result.model_dump(mode="python")
        return LiveNexusResult.model_validate(copy.deepcopy(_cache_payload))
