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
    async with streamablehttp_client(config.action_mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            action = _content_to_dict(
                await session.call_tool(
                    "create_action_intent",
                    arguments={
                        "user_id": "approval-mcp-smoke-user",
                        "agent_id": "hermes",
                        "action_type": "market_trade",
                        "amount_usdc": "1",
                        "target": "polymarket:691547",
                        "description": "MCP approval smoke live trade intent",
                    },
                )
            )
            approval = _content_to_dict(
                await session.call_tool(
                    "request_action_approval",
                    arguments={
                        "action_id": action["action_id"],
                        "approval_type": "live_trade_confirmation",
                        "requested_by": "hermes",
                        "message": "Approve Hermes to submit this 1 USDC live order.",
                        "expires_in_minutes": 10,
                    },
                )
            )
            submitted = _content_to_dict(
                await session.call_tool(
                    "submit_action_approval",
                    arguments={
                        "approval_id": approval["approval_id"],
                        "decision": "approved",
                        "approved_by": "approval-mcp-smoke-user",
                        "wallet_address": "0x20b7f4884ebd1992ee7a6257d33c1bc2e5a70f0b",
                        "signature": "0xsigned-demo",
                    },
                )
            )
            final_action = _content_to_dict(await session.call_tool("get_action_intent", arguments={"action_id": action["action_id"]}))

    assert approval["state"] == "requested"
    assert submitted["state"] == "approved"
    assert final_action["state"] == "user_approved"
    assert final_action["approval_id"] == approval["approval_id"]

    print(
        json.dumps(
            {
                "status": "ok",
                "action_id": action["action_id"],
                "approval_id": approval["approval_id"],
                "final_state": final_action["state"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
