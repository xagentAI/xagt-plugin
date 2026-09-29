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
    async with streamablehttp_client(config.authorization_mcp_url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            health = await session.call_tool("authorization_service_health")
            created = await session.call_tool(
                "create_budget_authorization",
                arguments={
                    "user_id": "demo-user",
                    "agent_id": "agent_001",
                    "max_amount_usdc": "0.1",
                    "expires_in_minutes": 30,
                },
            )
            authorization = _content_to_dict(created)
            approved = await session.call_tool(
                "check_budget_authorization",
                arguments={
                    "authorization_id": authorization["authorization_id"],
                    "amount_usdc": "0.00001",
                },
            )
            blocked = await session.call_tool(
                "check_budget_authorization",
                arguments={
                    "authorization_id": authorization["authorization_id"],
                    "amount_usdc": "1",
                },
            )
            payload = {
                "health": _content_to_dict(health),
                "created": authorization,
                "approved_check": _content_to_dict(approved),
                "blocked_check": _content_to_dict(blocked),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
