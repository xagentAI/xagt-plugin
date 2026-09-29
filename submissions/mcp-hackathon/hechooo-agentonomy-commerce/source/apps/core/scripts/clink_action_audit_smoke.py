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
    action = await _call_tool(
        config.action_mcp_url,
        "create_action_intent",
        {
            "user_id": "action-audit-smoke-user",
            "agent_id": "agent_001",
            "action_type": "service_purchase",
            "amount_usdc": "0.01",
            "target": "0x2222222222222222222222222222222222222222",
            "description": "Smoke test service purchase intent",
        },
    )
    audit_created = await _call_tool(
        config.audit_mcp_url,
        "write_audit_event",
        {
            "event_type": "action_intent_created",
            "source_service": "clink_action_audit_smoke",
            "action_id": action["action_id"],
            "user_id": action["user_id"],
            "agent_id": action["agent_id"],
            "payload": {"action_type": action["action_type"], "amount_usdc": action["amount_usdc"]},
        },
    )
    authorization = await _call_tool(
        config.authorization_mcp_url,
        "create_budget_authorization",
        {
            "user_id": action["user_id"],
            "agent_id": action["agent_id"],
            "max_amount_usdc": "0.1",
            "expires_in_minutes": 30,
        },
    )
    policy = await _call_tool(
        config.policy_mcp_url,
        "evaluate_action_policy",
        {
            "action_id": action["action_id"],
            "user_id": action["user_id"],
            "agent_id": action["agent_id"],
            "action_type": action["action_type"],
            "amount_usdc": action["amount_usdc"],
            "authorization_id": authorization["authorization_id"],
            "risk_level": "low",
            "risk_score": 12,
            "risk_action": "approve",
        },
    )
    updated = await _call_tool(
        config.action_mcp_url,
        "update_action_intent",
        {
            "action_id": action["action_id"],
            "state": "policy_checked" if policy["approved"] else "blocked",
            "policy_decision_id": policy["policy_decision_id"],
        },
    )
    audit_policy = await _call_tool(
        config.audit_mcp_url,
        "write_audit_event",
        {
            "event_type": "policy_evaluated",
            "source_service": "clink_action_audit_smoke",
            "action_id": action["action_id"],
            "user_id": action["user_id"],
            "agent_id": action["agent_id"],
            "policy_decision_id": policy["policy_decision_id"],
            "payload": {"approved": policy["approved"], "reason_code": policy["reason_code"]},
        },
    )
    trail = await _call_tool(
        config.audit_mcp_url,
        "get_audit_trail",
        {
            "action_id": action["action_id"],
        },
    )
    payload = {
        "action": action,
        "audit_created": audit_created,
        "authorization": authorization,
        "policy": policy,
        "updated_action": updated,
        "audit_policy": audit_policy,
        "trail": trail,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
