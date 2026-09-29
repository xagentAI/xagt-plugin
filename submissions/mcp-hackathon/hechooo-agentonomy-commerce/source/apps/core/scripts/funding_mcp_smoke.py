import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.config import AppConfig  # noqa: E402


def _content_to_dict(result) -> dict:
    text = getattr(result.content[0], "text", "{}")
    return json.loads(text)


async def main() -> None:
    config = AppConfig.from_env()
    async with streamablehttp_client(config.funding_mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            health = _content_to_dict(await session.call_tool("funding_service_health"))
            status = _content_to_dict(
                await session.call_tool(
                    "get_funding_status",
                    arguments={"user_id": "funding-mcp-smoke-user", "venue": "polymarket"},
                )
            )

    assert health["status"] == "ok"
    assert tool_names == {"funding_service_health", "get_funding_status"}
    assert all(item["legacy"] is True for item in status["spending_authorizations"])

    print(
        json.dumps(
            {
                "status": "ok",
                "tools": sorted(tool_names),
                "legacy_authorizations": len(status["spending_authorizations"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
