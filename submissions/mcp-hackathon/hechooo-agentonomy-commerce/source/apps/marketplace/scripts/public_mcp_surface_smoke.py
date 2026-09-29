from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.config import AppConfig
from mcp_servers.marketplace_server import MCP_SERVER


EXPECTED_TOOL_NAMES = {
    "search_clink_services",
    "get_clink_service_details",
    "compare_clink_service_quotes",
    "create_clink_purchase_preview",
    "execute_clink_purchase",
    "get_clink_purchase",
    "clink_marketplace_health",
}


def health_result_is_degraded(*, is_error: bool, texts: list[str]) -> bool:
    combined = " ".join(texts).lower()
    return is_error and "503" in combined and "degraded" in combined


async def contract_tool_names() -> set[str]:
    return {tool.name for tool in await MCP_SERVER.list_tools()}


async def live_smoke() -> dict[str, object]:
    config = AppConfig.from_env()
    async with streamablehttp_client(config.mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            if names != EXPECTED_TOOL_NAMES:
                raise AssertionError(f"unexpected MCP surface: {sorted(names)}")
            result = await session.call_tool("clink_marketplace_health", {})
            texts = [
                str(getattr(item, "text", ""))
                for item in result.content
            ]
            if result.isError and not health_result_is_degraded(
                is_error=True,
                texts=texts,
            ):
                raise AssertionError(f"marketplace health tool failed: {texts}")
            return {
                "status": "ok",
                "transport": "connected",
                "health": "degraded" if result.isError else "ready",
                "tools": sorted(names),
            }


async def main() -> None:
    contract_names = await contract_tool_names()
    if contract_names != EXPECTED_TOOL_NAMES:
        raise AssertionError(
            f"unexpected local MCP contract: {sorted(contract_names)}"
        )
    if "--live" in sys.argv:
        result = await live_smoke()
    else:
        result = {
            "status": "ok",
            "transport": "contract_only",
            "tools": sorted(contract_names),
        }
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
