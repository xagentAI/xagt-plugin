import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.action_service.schemas import (  # noqa: E402
    ActionApproval,
    AgentActionIntent,
    CreateActionIntentRequest,
    RequestActionApprovalRequest,
    SubmitActionApprovalRequest,
    UpdateActionIntentRequest,
)
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Action MCP Server",
    instructions="Expose Clink Core AgentActionIntent lifecycle tools.",
    host=CONFIG.action_mcp_host,
    port=CONFIG.action_mcp_port,
    stateless_http=True,
    json_response=True,
)


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    method = "GET"
    headers = {"Authorization": f"Bearer {CONFIG.clink_internal_api_token}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"action service request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"action service request failed: {exc}") from exc


@MCP_SERVER.tool()
def create_action_intent(
    user_id: str,
    agent_id: str,
    action_type: str = "service_purchase",
    amount_usdc: str | None = None,
    target: str | None = None,
    merchant_id: str | None = None,
    authorization_id: str | None = None,
    description: str | None = None,
    metadata: dict | None = None,
) -> AgentActionIntent:
    """Create an AgentActionIntent before policy, payment, or execution."""
    request = CreateActionIntentRequest(
        user_id=user_id,
        agent_id=agent_id,
        action_type=action_type,
        amount_usdc=amount_usdc,
        target=target,
        merchant_id=merchant_id,
        authorization_id=authorization_id,
        description=description,
        metadata=metadata or {},
    )
    response = _request_json(f"{CONFIG.action_service_url}/actions", request.model_dump())
    return AgentActionIntent(**response)


@MCP_SERVER.tool()
def update_action_intent(
    action_id: str,
    state: str | None = None,
    policy_decision_id: str | None = None,
    payment_id: str | None = None,
    order_id: str | None = None,
    receipt_id: str | None = None,
    tx_hash: str | None = None,
    error: str | None = None,
    metadata: dict | None = None,
) -> AgentActionIntent:
    """Update an AgentActionIntent as policy/execution progresses."""
    request = UpdateActionIntentRequest(
        state=state,
        policy_decision_id=policy_decision_id,
        payment_id=payment_id,
        order_id=order_id,
        receipt_id=receipt_id,
        tx_hash=tx_hash,
        error=error,
        metadata=metadata or {},
    )
    response = _request_json(f"{CONFIG.action_service_url}/actions/{action_id}/update", request.model_dump())
    return AgentActionIntent(**response)


@MCP_SERVER.tool()
def get_action_intent(action_id: str) -> AgentActionIntent:
    """Fetch an AgentActionIntent by id."""
    response = _request_json(f"{CONFIG.action_service_url}/actions/{action_id}")
    return AgentActionIntent(**response)


@MCP_SERVER.tool()
def request_action_approval(
    action_id: str,
    approval_type: str = "human_confirmation",
    requested_by: str | None = None,
    message: str | None = None,
    approval_url: str | None = None,
    expires_in_minutes: int = 15,
    metadata: dict | None = None,
) -> ActionApproval:
    """Create a human approval request for an action and move it to approval_requested."""
    request = RequestActionApprovalRequest(
        approval_type=approval_type,
        requested_by=requested_by,
        message=message,
        approval_url=approval_url,
        expires_in_minutes=expires_in_minutes,
        metadata=metadata or {},
    )
    response = _request_json(f"{CONFIG.action_service_url}/actions/{action_id}/approval-requests", request.model_dump())
    return ActionApproval(**response)


@MCP_SERVER.tool()
def submit_action_approval(
    approval_id: str,
    decision: str,
    approved_by: str,
    wallet_address: str | None = None,
    signature: str | None = None,
    note: str | None = None,
    metadata: dict | None = None,
) -> ActionApproval:
    """Submit a user approval or rejection for an action approval request."""
    request = SubmitActionApprovalRequest(
        decision=decision,
        approved_by=approved_by,
        wallet_address=wallet_address,
        signature=signature,
        note=note,
        metadata=metadata or {},
    )
    response = _request_json(f"{CONFIG.action_service_url}/action-approvals/{approval_id}/submit", request.model_dump())
    return ActionApproval(**response)


@MCP_SERVER.tool()
def get_action_approval(approval_id: str) -> ActionApproval:
    """Fetch an ActionApproval by id."""
    response = _request_json(f"{CONFIG.action_service_url}/action-approvals/{approval_id}")
    return ActionApproval(**response)


@MCP_SERVER.tool()
def action_service_health() -> dict:
    """Check whether the backing action service is available."""
    return _request_json(f"{CONFIG.action_service_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
