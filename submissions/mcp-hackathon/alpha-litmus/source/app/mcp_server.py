"""Strict MCP stdio server with opt-in backtest compute, never trading."""

from collections.abc import Sequence
import sys
from typing import Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.message import SessionMessage
from mcp.types import ContentBlock, JSONRPCMessage, Tool, ToolAnnotations
from pydantic import ValidationError

from app.certificates import verify_report
from app.contracts import ChallengeRequest, ReleaseGateResult, Report, StrictModel, Verification
from app.demo import fixture
from app.lab import challenge
from app.nexus_compute import WindowExperimentReport, WindowExperimentRequest
from app.provenance import validate_startup
from app.transport import (
    ChallengeArguments,
    DemoArguments,
    MAX_BODY_BYTES,
    TransportError,
    VerifyArguments,
    WindowExperimentArguments,
    bound_arguments,
    compute,
    decode_json,
    run_challenge,
    run_live_nexus_candidate,
    run_recorded_replay,
    run_release_gate,
    run_window_compute,
)


class ReplayRecordedArguments(StrictModel):
    pass


class LiveNexusArguments(StrictModel):
    pass


ARGUMENTS: dict[str, type[StrictModel]] = {
    "evaluate_strategy_release": ChallengeArguments,
    "challenge_nexus_strategy": ChallengeArguments,
    "find_failure_boundary": ChallengeArguments,
    "verify_failure_certificate": VerifyArguments,
    "get_demo_fixture": DemoArguments,
    "run_nexus_window_stability": WindowExperimentArguments,
    "replay_recorded_nexus_evidence": ReplayRecordedArguments,
    "evaluate_live_nexus_candidate": LiveNexusArguments,
}


class StrictMCP(FastMCP[None]):
    async def run_stdio_async(self) -> None:
        """Bound raw frames before SDK decoding can discard duplicate JSON keys."""
        validate_startup()
        incoming, reader = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        writer, outgoing = anyio.create_memory_object_stream[SessionMessage](0)

        async def read_frames() -> None:
            async with incoming:
                while True:
                    line = await anyio.to_thread.run_sync(
                        lambda: sys.stdin.buffer.readline(MAX_BODY_BYTES + 1),
                        abandon_on_cancel=True,
                    )
                    if not line:
                        return
                    try:
                        decode_json(line)
                        message = JSONRPCMessage.model_validate_json(line)
                    except Exception:
                        # Invalid frames have no trustworthy request ID; close safely.
                        return
                    await incoming.send(SessionMessage(message))

        async def write_frames() -> None:
            async with outgoing:
                async for message in outgoing:
                    data = message.message.model_dump_json(by_alias=True, exclude_none=True)

                    def write() -> None:
                        sys.stdout.buffer.write((data + "\n").encode("utf-8"))
                        sys.stdout.buffer.flush()

                    await anyio.to_thread.run_sync(write)

        async with anyio.create_task_group() as group:
            group.start_soon(read_frames)
            group.start_soon(write_frames)
            await self._mcp_server.run(reader, writer, self._mcp_server.create_initialization_options())
            group.cancel_scope.cancel()

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema = ARGUMENTS[tool.name].model_json_schema()
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        # Validate before FastMCP's coercion and extra-field-ignoring argument model.
        try:
            bound_arguments(arguments)
            model = ARGUMENTS.get(name)
            if model is None:
                raise ToolError("UNKNOWN_TOOL")
            model.model_validate(arguments, strict=True)
            return await super().call_tool(name, arguments)
        except (ValidationError, TransportError) as exc:
            code = exc.code if isinstance(exc, TransportError) else "INVALID_ARGUMENTS"
            raise ToolError(code) from None
        except ToolError as exc:
            # FastMCP wraps execution exceptions; retain only our public codes.
            if isinstance(exc.__cause__, TransportError):
                raise ToolError(exc.__cause__.code) from None
            raise ToolError("TOOL_FAILED") from None
        except Exception:
            raise ToolError("TOOL_FAILED") from None


mcp = StrictMCP("AlphaLitmus", log_level="CRITICAL")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
async def evaluate_strategy_release(request: ChallengeRequest) -> ReleaseGateResult:
    """Primary release gate: bounded fragility check before deploy, enable, or scale.

    Returns BLOCK_DEPLOYMENT, INSUFFICIENT_EVIDENCE, or SURVIVED_BOUNDED_TESTS.
    Never approves deployment, never executes trades, never financial advice.
    """
    return await run_release_gate(request)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
async def challenge_nexus_strategy(request: ChallengeRequest) -> Report:
    """Challenge a reference dataset or Nexus evidence; never execute trades."""
    return await run_challenge(request)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
async def find_failure_boundary(request: ChallengeRequest) -> Report:
    """Return the full report with the bounded, per-dimension failure frontier."""
    return await run_challenge(request)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def verify_failure_certificate(report: Report) -> Verification:
    """Recompute integrity and policy, without claiming authenticity."""
    return await compute(lambda: verify_report(report))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def get_demo_fixture(scenario: Literal["mixed", "shock"] = "mixed") -> Report:
    """Challenge a seeded synthetic fixture and return its report, not profit evidence."""
    return await compute(lambda: challenge(ChallengeRequest(research=fixture(scenario))))


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True,
))
async def run_nexus_window_stability(request: WindowExperimentRequest) -> WindowExperimentReport:
    """Start bounded Nexus backtest compute, never trading or orders.

    Requires confirm_compute=true, ALPHALITMUS_ENABLE_NEXUS_BACKTEST=true and
    NEXUS_API_KEY. Separate from read-only Nexus evidence access.
    """
    return await run_window_compute(request)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def replay_recorded_nexus_evidence() -> dict[str, Any]:
    """Replay recorded historical Nexus evidence; never live, never trading.

    Recorded historical Nexus snapshot for SKLab AlphaLitmus Candidate v1 —
    not a live market call and not evidence of future profitability.
    """
    result = await run_recorded_replay()
    return result.model_dump(mode="json")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
async def evaluate_live_nexus_candidate() -> dict[str, Any]:
    """Evaluate fixed Candidate v1 against fresh read-only Nexus evidence.

    May serve a disclosed cache entry up to 60 seconds old. Never backtests,
    trades, accepts caller-selected identity, or falls back to recorded data.
    """
    result = await run_live_nexus_candidate()
    return result.model_dump(mode="json")


if __name__ == "__main__":
    mcp.run(transport="stdio")
