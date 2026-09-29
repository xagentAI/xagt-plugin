import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.audit_service.schemas import AuditEvent, AuditTrail, WriteAuditEventRequest  # noqa: E402
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Audit MCP Server",
    instructions="Expose Clink Core append-only audit trail tools.",
    host=CONFIG.audit_mcp_host,
    port=CONFIG.audit_mcp_port,
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
        raise RuntimeError(f"audit service request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"audit service request failed: {exc}") from exc


@MCP_SERVER.tool()
def write_audit_event(
    event_type: str,
    source_service: str,
    action_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    policy_decision_id: str | None = None,
    payment_id: str | None = None,
    order_id: str | None = None,
    receipt_id: str | None = None,
    tx_hash: str | None = None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> AuditEvent:
    """Append an audit event for an agent action."""
    request = WriteAuditEventRequest(
        idempotency_key=idempotency_key,
        event_type=event_type,
        source_service=source_service,
        action_id=action_id,
        user_id=user_id,
        agent_id=agent_id,
        policy_decision_id=policy_decision_id,
        payment_id=payment_id,
        order_id=order_id,
        receipt_id=receipt_id,
        tx_hash=tx_hash,
        payload=payload or {},
    )
    response = _request_json(f"{CONFIG.audit_service_url}/audit/events", request.model_dump())
    return AuditEvent(**response)


@MCP_SERVER.tool()
def get_audit_event(event_id: str) -> AuditEvent:
    """Fetch a single audit event by id."""
    response = _request_json(f"{CONFIG.audit_service_url}/audit/events/{event_id}")
    return AuditEvent(**response)


@MCP_SERVER.tool()
def get_audit_trail(
    action_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> AuditTrail:
    """Fetch audit events filtered by action, user, or agent."""
    query = urllib.parse.urlencode(
        {key: value for key, value in {"action_id": action_id, "user_id": user_id, "agent_id": agent_id}.items() if value}
    )
    url = f"{CONFIG.audit_service_url}/audit/trail"
    if query:
        url = f"{url}?{query}"
    response = _request_json(url)
    return AuditTrail(**response)


@MCP_SERVER.tool()
def audit_service_health() -> dict:
    """Check whether the backing audit service is available."""
    return _request_json(f"{CONFIG.audit_service_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
