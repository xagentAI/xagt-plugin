from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client


class McpClient(Protocol):
    async def list_tools(self) -> list[types.Tool]: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult: ...


class DownstreamMcpFailure(RuntimeError):
    def __init__(
        self,
        module: str,
        tool_name: str,
        detail: str,
    ) -> None:
        self.module = module
        self.tool_name = tool_name
        self.detail = detail
        self.retry_safe = False
        super().__init__(
            json.dumps(
                {
                    "error": "downstream_tool_failed",
                    "module": module,
                    "tool": tool_name,
                    "detail": detail,
                    "retry_safe": False,
                },
                separators=(",", ":"),
            )
        )


NativeHandler = Callable[
    [dict[str, Any]],
    Awaitable[dict[str, Any] | types.CallToolResult],
]


@dataclass(frozen=True)
class NativeTool:
    definition: types.Tool
    handler: NativeHandler


class StreamableHttpMcpClient:
    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 20,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.timeout_seconds = timeout_seconds

    async def list_tools(self) -> list[types.Tool]:
        async with self._session() as session:
            result = await session.list_tools()
            return list(result.tools)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        async with self._session() as session:
            return await session.call_tool(name, arguments)

    def _session(self):
        return _McpSession(
            self.url,
            self.headers,
            self.timeout_seconds,
        )


class _McpSession:
    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> None:
        self.url = url
        self.headers = headers
        self.timeout_seconds = timeout_seconds
        self.stack: AsyncExitStack | None = None

    async def __aenter__(self) -> ClientSession:
        stack = AsyncExitStack()
        self.stack = stack
        try:
            client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout_seconds,
            )
            await stack.enter_async_context(client)
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(self.url, http_client=client)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            return session
        except BaseException as original:
            self.stack = None
            try:
                await stack.aclose()
            except BaseException as cleanup_error:
                original.add_note(
                    f"AsyncExitStack cleanup failed: {type(cleanup_error).__name__}"
                )
            raise

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self.stack is not None:
            await self.stack.aclose()


class McpToolProxy:
    def __init__(
        self,
        downstreams: dict[str, McpClient],
        *,
        native_tools: dict[str, NativeTool] | None = None,
    ) -> None:
        self.downstreams = downstreams
        self.native_tools = native_tools or _placeholder_native_tools()
        self._owners: dict[str, str] = {}

    async def list_tools(self) -> list[types.Tool]:
        tools = [
            native.definition for native in self.native_tools.values()
        ]
        owners = {name: "node" for name in self.native_tools}
        for module, client in self.downstreams.items():
            for tool in await client.list_tools():
                if tool.name in owners:
                    if owners[tool.name] == "node":
                        continue
                    raise ValueError(
                        f"duplicate MCP tool {tool.name!r} from "
                        f"{owners[tool.name]} and {module}"
                    )
                owners[tool.name] = module
                tools.append(tool)
        self._owners = owners
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | types.CallToolResult:
        native = self.native_tools.get(name)
        if native is not None:
            return await native.handler(arguments)
        module = self._owners.get(name)
        if module is None:
            await self.list_tools()
            module = self._owners.get(name)
        if module is None or module == "node":
            raise KeyError(f"unknown Clink Node tool: {name}")
        try:
            return await self.downstreams[module].call_tool(
                name,
                arguments,
            )
        except Exception as exc:
            if isinstance(exc, DownstreamMcpFailure):
                raise
            raise DownstreamMcpFailure(
                module,
                name,
                f"{type(exc).__name__}: {exc}",
            ) from exc


def _placeholder_native_tools() -> dict[str, NativeTool]:
    async def unavailable(arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        return {
            "status": "not_configured",
            "reason": "Clink Node runtime context is not attached",
        }

    definitions = {
        "clink_node_status": (
            "Read unified Clink Node and module readiness.",
            {"type": "object", "properties": {}},
        ),
        "create_core_account_setup_link": (
            "Create the single Core Account wallet and mandate setup link.",
            {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        ),
        "get_clink_account_readiness": (
            "Read wallet, mandate and chain allowance readiness from Core.",
            {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        ),
        "get_clink_balances": (
            (
                "Read actual wallet and Polymarket USDC balances separately "
                "from the Agent spending authorization budget."
            ),
            {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        ),
        "list_clink_capabilities": (
            "List all capabilities exposed by this Clink Node.",
            {"type": "object", "properties": {}},
        ),
    }
    return {
        name: NativeTool(
            types.Tool(
                name=name,
                description=description,
                inputSchema=schema,
            ),
            unavailable,
        )
        for name, (description, schema) in definitions.items()
    }
