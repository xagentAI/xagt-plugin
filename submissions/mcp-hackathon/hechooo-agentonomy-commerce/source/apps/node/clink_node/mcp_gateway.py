from __future__ import annotations

import asyncio
from typing import Any

from mcp import types
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import (
    StreamableHTTPSessionManager,
)
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.middleware import Middleware

from .agent_access_http import RuntimeMcpAuthMiddleware, bearer_token
from .api import NodeApiContext
from .mcp_proxy import McpToolProxy, NativeTool
from .projections import build_account_summary, build_activity_summary, build_balance_summary


def build_native_tools(context: NodeApiContext) -> dict[str, NativeTool]:
    async def node_status(arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        modules = {
            item.name: {
                "mode": item.mode,
                "status": item.status,
                "detail": item.detail,
            }
            for item in context.repository.list_modules()
        }
        ready = all(
            item["status"] in {"ready", "external", "disabled"}
            for item in modules.values()
        )
        return {
            "status": "ready" if ready else "not_ready",
            "profile": context.settings.profile.value,
            "modules": modules,
        }

    async def account_link(arguments: dict[str, Any]) -> dict[str, Any]:
        return context.core.create_account_session(arguments["user_id"])

    async def account_readiness(
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return build_account_summary(
            context.core,
            context.prediction_markets,
            arguments["user_id"],
        )

    async def activity(arguments: dict[str, Any]) -> dict[str, Any]:
        return build_activity_summary(
            context.core,
            arguments["user_id"],
            int(arguments.get("limit", 12)),
        )

    async def balances(arguments: dict[str, Any]) -> dict[str, Any]:
        return build_balance_summary(context.core, context.prediction_markets, arguments["user_id"])

    async def capabilities(arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        items = [
            *context.marketplace.capabilities(),
            *context.prediction_markets.capabilities(),
        ]
        return {"count": len(items), "capabilities": items}

    empty_schema = {"type": "object", "properties": {}}
    user_schema = {
        "type": "object",
        "properties": {"user_id": {"type": "string", "minLength": 1}},
        "required": ["user_id"],
        "additionalProperties": False,
    }
    activity_schema = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "minLength": 1},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 12,
            },
        },
        "required": ["user_id"],
        "additionalProperties": False,
    }
    return {
        "clink_node_status": NativeTool(
            types.Tool(
                name="clink_node_status",
                description="Read unified Clink Node and module readiness.",
                inputSchema=empty_schema,
            ),
            node_status,
        ),
        "create_core_account_setup_link": NativeTool(
            types.Tool(
                name="create_core_account_setup_link",
                description=(
                    "Create the single Core Account wallet and mandate "
                    "setup link. Do not use shell or private service APIs."
                ),
                inputSchema=user_schema,
            ),
            account_link,
        ),
        "get_clink_account_readiness": NativeTool(
            types.Tool(
                name="get_clink_account_readiness",
                description=(
                    "Read the unified wallet, spending mandate, Marketplace "
                    "and Polymarket account readiness projection."
                ),
                inputSchema=user_schema,
            ),
            account_readiness,
        ),
        "get_clink_activity": NativeTool(
            types.Tool(
                name="get_clink_activity",
                description=(
                    "Read the user's recent, redacted Core decisions and "
                    "account activity. This tool never executes an action."
                ),
                inputSchema=activity_schema,
            ),
            activity,
        ),
        "get_clink_balances": NativeTool(
            types.Tool(
                name="get_clink_balances",
                description=(
                    "Read actual USDC balances for the bound wallet and "
                    "Polymarket account, separately from the Agent spending "
                    "authorization budget. This tool never moves funds."
                ),
                inputSchema=user_schema,
            ),
            balances,
        ),
        "list_clink_capabilities": NativeTool(
            types.Tool(
                name="list_clink_capabilities",
                description="List product capabilities exposed by this Node.",
                inputSchema=empty_schema,
            ),
            capabilities,
        ),
    }


def create_mcp_server(proxy: McpToolProxy, *, access_service: Any = None) -> Server:
    server = Server(
        "Clink Node",
        version="0.1.0",
        instructions=(
            "Agentonomy is the authenticated payment entry point for this runtime. "
            "Identity is server-bound; never supply or select another user. Core owns "
            "wallet identity, mandate, risk, budget and settlement. Wallet setup and "
            "permission changes are user actions in the wallet app, not Agent tools. "
            "A submitted transaction is not settled. Preserve operation_id and request_id "
            "across runtime restarts. If execution outcome is unknown, read the existing "
            "payment; do not create another intent, change its key or recharge for failed delivery."
        ) if access_service is not None else (
            "Clink Node is the only Agent-facing entry point. Core owns "
            "identity, mandate, policy, risk, funding and audit. Never retry "
            "a failed execution or funding tool unless the user starts a "
            "new operation."
        ),
    )

    async def authenticated_principal():
        try:
            return await asyncio.to_thread(
                access_service.authenticate, bearer_token(server.request_context.request.scope)
            )
        except Exception:
            # MCP serializes callback exception text. Never expose database,
            # SecretStore or transport details from this second admission check.
            raise ValueError("Runtime authentication unavailable") from None

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        if access_service is not None:
            principal = await authenticated_principal()
            return await proxy.list_tools(principal=principal)
        return await proxy.list_tools()

    @server.call_tool(validate_input=True)
    async def call_tool(
        name: str,
        arguments: dict[str, Any],
    ):
        if access_service is not None:
            # Use the actual transport request metadata, not an ambient ContextVar
            # that can be lost when the MCP manager creates server tasks.
            principal = await authenticated_principal()
            return await proxy.call_tool(name, arguments, principal=principal)
        return await proxy.call_tool(name, arguments)

    return server


def create_mcp_application(proxy: McpToolProxy, *, access_service: Any = None) -> Starlette:
    server = create_mcp_server(proxy, access_service=access_service)
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
    )
    endpoint = StreamableHTTPASGIApp(manager)
    return Starlette(
        routes=[Route("/mcp", endpoint=endpoint)],
        lifespan=lambda app: manager.run(),
        middleware=[Middleware(RuntimeMcpAuthMiddleware, access_service=access_service)] if access_service is not None else [],
    )
