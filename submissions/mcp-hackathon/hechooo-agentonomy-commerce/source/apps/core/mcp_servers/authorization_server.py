import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.authorization_service.schemas import (  # noqa: E402
    AuthorizationCheckResult,
    BudgetAuthorization,
    CheckAuthorizationRequest,
    CreateAuthorizationRequest,
    SpendAuthorizationRequest,
)
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Authorization MCP Server",
    instructions="Expose Clink budget authorization tools for agent payments.",
    host=CONFIG.authorization_mcp_host,
    port=CONFIG.authorization_mcp_port,
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
        raise RuntimeError(f"authorization service request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"authorization service request failed: {exc}") from exc


@MCP_SERVER.tool()
def create_budget_authorization(
    user_id: str,
    agent_id: str,
    max_amount_usdc: str,
    expires_in_minutes: int = 30,
) -> BudgetAuthorization:
    """Create a Clink budget authorization for an agent."""
    request = CreateAuthorizationRequest(
        user_id=user_id,
        agent_id=agent_id,
        max_amount_usdc=max_amount_usdc,
        expires_in_minutes=expires_in_minutes,
    )
    response = _request_json(f"{CONFIG.authorization_service_url}/authorizations", request.model_dump())
    return BudgetAuthorization(**response)


@MCP_SERVER.tool()
def check_budget_authorization(authorization_id: str, amount_usdc: str) -> AuthorizationCheckResult:
    """Check whether a payment amount fits inside an existing budget authorization."""
    request = CheckAuthorizationRequest(amount_usdc=amount_usdc)
    response = _request_json(
        f"{CONFIG.authorization_service_url}/authorizations/{authorization_id}/check",
        request.model_dump(),
    )
    return AuthorizationCheckResult(**response)


@MCP_SERVER.tool()
def spend_budget_authorization(
    authorization_id: str,
    amount_usdc: str,
    payment_id: str | None = None,
) -> AuthorizationCheckResult:
    """Record budget spend after a payment session is created."""
    request = SpendAuthorizationRequest(amount_usdc=amount_usdc, payment_id=payment_id)
    response = _request_json(
        f"{CONFIG.authorization_service_url}/authorizations/{authorization_id}/spend",
        request.model_dump(),
    )
    return AuthorizationCheckResult(**response)


@MCP_SERVER.tool()
def get_budget_authorization(authorization_id: str) -> BudgetAuthorization:
    """Fetch a budget authorization."""
    response = _request_json(f"{CONFIG.authorization_service_url}/authorizations/{authorization_id}")
    return BudgetAuthorization(**response)


@MCP_SERVER.tool()
def revoke_budget_authorization(authorization_id: str) -> BudgetAuthorization:
    """Revoke a budget authorization."""
    response = _request_json(f"{CONFIG.authorization_service_url}/authorizations/{authorization_id}/revoke", {})
    return BudgetAuthorization(**response)


@MCP_SERVER.tool()
def authorization_service_health() -> dict:
    """Check whether the backing authorization service is available."""
    return _request_json(f"{CONFIG.authorization_service_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
