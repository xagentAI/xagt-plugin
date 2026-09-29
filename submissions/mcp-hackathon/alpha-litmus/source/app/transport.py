"""Shared bounded transport policy.

Public deployments must place REST behind an authenticating, rate-limiting TLS
reverse proxy before setting ALPHALITMUS_ENABLE_NEXUS=true. The switch is not
authentication. Admission is per process; configure worker counts accordingly.
At most eight requests retain intake buffers, with a ten-second total body
deadline. GET /health never reads or waits on uploads and bypasses both gates.
Declared health bodies are rejected; undeclared bytes are not read or buffered.
"""

import json
import math
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from typing import Any, Literal, TypeVar

import anyio
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.contracts import ChallengeRequest, ReleaseGateResult, Report, StrictModel
from app.lab import challenge
from app.nexus import read_nexus
from app.recorded_nexus import RecordedNexusReplay
from app.live_nexus import LiveNexusResult
from app.release_gate import project
from app.nexus_compute import (
    NexusComputeError, WindowEvidence, WindowExperimentReport, WindowExperimentRequest, run_window_experiment,
)

MAX_BODY_BYTES = 4_000_000
MAX_DEPTH = 32
MAX_CONCURRENT = 2
MAX_INTAKE = 8
BODY_TIMEOUT_SECONDS = 10
T = TypeVar("T")


class TransportError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class Admission:
    def __init__(self, capacity: int = MAX_CONCURRENT) -> None:
        self._slots = BoundedSemaphore(capacity)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if not self._slots.acquire(blocking=False):
            raise TransportError(429, "CAPACITY_EXCEEDED")
        try:
            yield
        finally:
            self._slots.release()


admission = Admission()
intake_admission = Admission(MAX_INTAKE)


async def compute(function: Callable[[], T]) -> T:
    async with admission.slot():
        # Do not abandon a running thread on cancellation and release its slot early.
        return await anyio.to_thread.run_sync(function, abandon_on_cancel=False)


def validate_json(value: object) -> None:
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise TransportError(400, "INVALID_JSON")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TransportError(400, "INVALID_JSON")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise TransportError(400, "INVALID_JSON")
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise TransportError(400, "INVALID_JSON")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TransportError(400, "INVALID_JSON")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise TransportError(400, "INVALID_JSON")


def decode_json(body: bytes) -> object:
    if len(body) > MAX_BODY_BYTES:
        raise TransportError(413, "BODY_TOO_LARGE")
    try:
        value: object = json.loads(body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
        validate_json(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise TransportError(400, "INVALID_JSON") from exc


def bound_arguments(value: object) -> None:
    validate_json(value)
    try:
        body = json.dumps(value, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise TransportError(400, "INVALID_JSON") from exc
    if len(body) > MAX_BODY_BYTES:
        raise TransportError(413, "BODY_TOO_LARGE")


class JSONBoundary:
    """Buffer at most 4 MB, including chunked bodies, before framework parsing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            headers = dict(scope.get("headers", []))
            length = headers.get(b"content-length")
            if length is not None and (not length.isdigit() or len(length) > 10):
                raise TransportError(400, "INVALID_REQUEST")
            if length is not None and int(length) > MAX_BODY_BYTES:
                raise TransportError(413, "BODY_TOO_LARGE")
            if scope["method"] == "GET" and scope["path"] == "/health":
                if (length is not None and int(length)) or b"transfer-encoding" in headers:
                    raise TransportError(400, "BODY_NOT_ALLOWED")
                await self.app(scope, receive, send)
                return
            # Hold admission through dispatch so retained buffers stay bounded too.
            async with intake_admission.slot():
                await self._receive_and_dispatch(scope, receive, send, headers)
        except TransportError as exc:
            await JSONResponse({"detail": exc.code}, status_code=exc.status)(scope, receive, send)

    async def _receive_and_dispatch(self, scope: Scope, receive: Receive, send: Send,
                                    headers: dict[bytes, bytes]) -> None:
        body = bytearray()
        try:
            with anyio.fail_after(BODY_TIMEOUT_SECONDS):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        raise TransportError(413, "BODY_TOO_LARGE")
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError as exc:
            raise TransportError(408, "BODY_TIMEOUT") from exc
        if body:
            if headers.get(b"content-encoding", b"identity").lower() != b"identity":
                raise TransportError(415, "UNSUPPORTED_ENCODING")
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            if content_type != b"application/json" and not content_type.endswith(b"+json"):
                raise TransportError(415, "JSON_REQUIRED")
            decode_json(bytes(body))

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class ValidateRequest(StrictModel):
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$")


class DemoArguments(StrictModel):
    scenario: Literal["mixed", "shock"] = "mixed"


class ChallengeArguments(StrictModel):
    request: ChallengeRequest


class VerifyArguments(StrictModel):
    report: Report


class WindowExperimentArguments(StrictModel):
    request: WindowExperimentRequest


def nexus_enabled() -> bool:
    return os.getenv("ALPHALITMUS_ENABLE_NEXUS") == "true"


async def nexus_evidence(symbol: str) -> dict[str, Any]:
    if not nexus_enabled():
        reason = "NEXUS_DISABLED" if os.getenv("NEXUS_API_KEY") else "NEXUS_NOT_CONFIGURED"
        return {name: {"status": "unavailable", "reason": reason}
                for name in ("signal", "metrics", "equity", "trades")}
    return await read_nexus(symbol)


async def run_challenge(request: ChallengeRequest) -> Report:
    async with admission.slot():
        evidence = await nexus_evidence(request.symbol) if request.mode == "nexus" else None
        return await anyio.to_thread.run_sync(lambda: challenge(request, evidence), abandon_on_cancel=False)


async def run_release_gate(request: ChallengeRequest) -> ReleaseGateResult:
    """Run the existing analysis engine, then apply the pure release-gate projection.

    Single-admission path shared by REST and MCP so both use the same engine
    and decision mapping with no parallel implementation.
    """
    async with admission.slot():
        evidence = await nexus_evidence(request.symbol) if request.mode == "nexus" else None

        def _evaluate() -> ReleaseGateResult:
            return project(challenge(request, evidence))

        return await anyio.to_thread.run_sync(_evaluate, abandon_on_cancel=False)


async def run_recorded_replay() -> RecordedNexusReplay:
    """Shared recorded-evidence replay path for REST and MCP.

    Calls the same verified replay function with no network access and no
    caller-selected snapshot. Fails closed with bounded public codes.
    """
    from app.recorded_nexus import RecordedEvidenceError, replay_recorded_nexus_evidence

    async with admission.slot():
        def _replay() -> RecordedNexusReplay:
            return replay_recorded_nexus_evidence()

        try:
            return await anyio.to_thread.run_sync(_replay, abandon_on_cancel=False)
        except RecordedEvidenceError as exc:
            if exc.code == "RECORDED_EVIDENCE_UNAVAILABLE":
                raise TransportError(503, exc.code) from None
            if exc.code == "RECORDED_EVIDENCE_INTEGRITY_FAILED":
                raise TransportError(500, exc.code) from None
            raise TransportError(500, "RECORDED_EVIDENCE_INVALID") from None


async def run_live_nexus_candidate() -> LiveNexusResult:
    """Shared fixed-strategy live path with no recorded fallback."""
    from app.live_nexus import LiveNexusError, run_live_nexus_candidate as run_live

    async with admission.slot():
        try:
            return await run_live()
        except LiveNexusError as exc:
            status = {
                "LIVE_NEXUS_DISABLED": 503,
                "LIVE_NEXUS_RATE_LIMITED": 429,
                "LIVE_NEXUS_CIRCUIT_OPEN": 503,
                "LIVE_NEXUS_UNAVAILABLE": 502,
                "LIVE_NEXUS_INVALID": 502,
            }.get(exc.code, 502)
            raise TransportError(status, exc.code) from None


async def run_window_compute(request: WindowExperimentRequest) -> WindowExperimentReport:
    async with admission.slot():
        try:
            return await run_window_experiment(request)
        except NexusComputeError as exc:
            if exc.code in ("NEXUS_COMPUTE_DISABLED", "NEXUS_NOT_CONFIGURED"):
                return WindowExperimentReport(
                    baseline_n_bars=request.windows[-1],
                    windows=[WindowEvidence(n_bars=n, reason=exc.code) for n in reversed(request.windows)],
                )
            status, code = {
                "NEXUS_INVALID_REQUEST": (422, "NEXUS_INVALID_REQUEST"),
                "NEXUS_COMPUTE_BUSY": (429, "NEXUS_COMPUTE_BUSY"),
                "NEXUS_TIMEOUT": (504, "NEXUS_TIMEOUT"),
            }.get(exc.code, (502, "NEXUS_COMPUTE_FAILED"))
            raise TransportError(status, code) from None
