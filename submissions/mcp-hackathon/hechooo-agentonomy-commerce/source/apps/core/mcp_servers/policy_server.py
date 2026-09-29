import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.policy_service.schemas import EvaluateActionPolicyRequest, PolicyDecision  # noqa: E402
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Policy MCP Server",
    instructions="Expose Clink Core action policy evaluation tools.",
    host=CONFIG.policy_mcp_host,
    port=CONFIG.policy_mcp_port,
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
        raise RuntimeError(f"policy service request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"policy service request failed: {exc}") from exc


@MCP_SERVER.tool()
def evaluate_action_policy(
    user_id: str,
    agent_id: str,
    amount_usdc: str,
    action_id: str | None = None,
    action_type: str = "service_purchase",
    authorization_id: str | None = None,
    merchant_id: str | None = None,
    target_address: str | None = None,
    chain: str = "base",
    risk_level: str | None = None,
    risk_score: int | None = None,
    risk_action: str | None = None,
    user_confirmed: bool = False,
    requires_confirmation: bool = True,
    live_mode: bool = False,
    metadata: dict | None = None,
) -> PolicyDecision:
    """Evaluate whether an agent action can proceed under Clink Core policy."""
    request = EvaluateActionPolicyRequest(
        action_id=action_id,
        user_id=user_id,
        agent_id=agent_id,
        action_type=action_type,
        amount_usdc=amount_usdc,
        authorization_id=authorization_id,
        merchant_id=merchant_id,
        target_address=target_address,
        chain=chain,
        risk_level=risk_level,
        risk_score=risk_score,
        risk_action=risk_action,
        user_confirmed=user_confirmed,
        requires_confirmation=requires_confirmation,
        live_mode=live_mode,
        metadata=metadata or {},
    )
    response = _request_json(f"{CONFIG.policy_service_url}/policies/evaluate", request.model_dump())
    return PolicyDecision(**response)


@MCP_SERVER.tool()
def get_policy_decision(policy_decision_id: str) -> PolicyDecision:
    """Fetch a stored policy decision."""
    response = _request_json(f"{CONFIG.policy_service_url}/policies/{policy_decision_id}")
    return PolicyDecision(**response)


@MCP_SERVER.tool()
def policy_service_health() -> dict:
    """Check whether the backing policy service is available."""
    return _request_json(f"{CONFIG.policy_service_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
