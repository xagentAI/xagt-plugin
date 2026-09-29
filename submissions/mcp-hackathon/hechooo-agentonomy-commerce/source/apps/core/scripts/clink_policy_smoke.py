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


async def _call_tool(url: str, tool_name: str, arguments: dict | None = None) -> dict:
    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments or {})
            return _content_to_dict(result)


async def main() -> None:
    config = AppConfig.from_env()
    authorization = await _call_tool(
        config.authorization_mcp_url,
        "create_budget_authorization",
        {
            "user_id": "policy-smoke-user",
            "agent_id": "agent_001",
            "max_amount_usdc": "0.1",
            "expires_in_minutes": 30,
        },
    )
    approved = await _call_tool(
        config.policy_mcp_url,
        "evaluate_action_policy",
        {
            "user_id": "policy-smoke-user",
            "agent_id": "agent_001",
            "action_type": "service_purchase",
            "amount_usdc": "0.01",
            "authorization_id": authorization["authorization_id"],
            "risk_level": "low",
            "risk_score": 12,
            "risk_action": "approve",
            "user_confirmed": False,
        },
    )
    over_budget = await _call_tool(
        config.policy_mcp_url,
        "evaluate_action_policy",
        {
            "user_id": "policy-smoke-user",
            "agent_id": "agent_001",
            "action_type": "service_purchase",
            "amount_usdc": "1",
            "authorization_id": authorization["authorization_id"],
            "risk_level": "low",
            "risk_score": 12,
            "risk_action": "approve",
            "user_confirmed": False,
        },
    )
    needs_confirmation = await _call_tool(
        config.policy_mcp_url,
        "evaluate_action_policy",
        {
            "user_id": "policy-smoke-user",
            "agent_id": "agent_001",
            "action_type": "market_trade",
            "amount_usdc": "0.01",
            "risk_level": "low",
            "risk_score": 12,
            "risk_action": "approve",
            "user_confirmed": False,
            "requires_confirmation": True,
            "live_mode": True,
        },
    )
    payload = {
        "authorization": authorization,
        "approved": approved,
        "over_budget": over_budget,
        "needs_confirmation": needs_confirmation,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
