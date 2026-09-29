from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.config import AppConfig

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Clink Marketplace",
    instructions=(
        "Discover, compare, preview and purchase registry-verified or Clink-verified services. "
        "Always expose the trust tier when recommending a service. Clink Core remains "
        "the only authorization, risk, funding and audit control plane. Quote payment "
        "capability is provisional; the newly created preview is authoritative. When a "
        "preview reports requires_purchase_signature=false, execute it without asking for "
        "a checkout signature or creating a second preview."
    ),
    host=CONFIG.mcp_host,
    port=CONFIG.mcp_port,
    stateless_http=True,
    json_response=True,
)


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    method = "GET"
    headers: dict[str, str] = {"Accept": "application/json"}
    if CONFIG.internal_api_token:
        headers["Authorization"] = f"Bearer {CONFIG.internal_api_token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Clink Marketplace registry returned HTTP {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Clink Marketplace registry request failed: {exc}") from exc


@MCP_SERVER.tool()
def search_clink_services(
    query: str,
    network: str | None = None,
    max_price_usd: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search fresh services and return their explicit Registry or Clink trust tier."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return _request_json(
        f"{CONFIG.registry_url}/catalog/search",
        {
            "query": query,
            "network": network,
            "max_price_usd": max_price_usd,
            "limit": limit,
        },
    )


@MCP_SERVER.tool()
def get_clink_service_details(offering_id: str) -> dict[str, Any]:
    """Fetch one purchasable service, provider identity, and verification tier."""
    safe_id = urllib.parse.quote(offering_id, safe="")
    return _request_json(f"{CONFIG.registry_url}/catalog/offerings/{safe_id}")


@MCP_SERVER.tool()
def compare_clink_service_quotes(query: str, network: str | None = None, max_price_usd: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Compare offers using trust tier, price, SLA and explainable Clink reputation."""
    return _request_json(f"{CONFIG.registry_url}/quotes/compare", {"query":query,"network":network,"max_price_usd":max_price_usd,"limit":limit})


@MCP_SERVER.tool()
def create_clink_purchase_preview(user_id: str, offering_id: str, service_input: dict[str, Any], payment_index: int = 0, network: str | None = None, max_price_usd: str | None = None, opc_installation_id: str | None = None) -> dict[str, Any]:
    """Lock one quote and return the authoritative automatic-payment capability."""
    payload = {"user_id":user_id,"offering_id":offering_id,"service_input":service_input,"payment_index":payment_index,"network":network,"max_price_usd":max_price_usd}
    if opc_installation_id is not None:
        payload["opc_installation_id"] = opc_installation_id
    return _request_json(f"{CONFIG.registry_url}/purchases/previews", payload)


@MCP_SERVER.tool()
def execute_clink_purchase(preview_id: str, user_confirmed: bool = False, spending_authorization_id: str | None = None, transaction_hash: str | None = None, payment_response: dict[str, Any] | None = None, opc_installation_id: str | None = None) -> dict[str, Any]:
    """Execute once; automatic Core rails need no checkout or per-purchase signature."""
    safe_id=urllib.parse.quote(preview_id,safe="")
    payload = {"user_confirmed":user_confirmed,"spending_authorization_id":spending_authorization_id,"transaction_hash":transaction_hash,"payment_response":payment_response}
    if opc_installation_id is not None:
        payload["opc_installation_id"] = opc_installation_id
    return _request_json(f"{CONFIG.registry_url}/purchases/{safe_id}/execute", payload)


@MCP_SERVER.tool()
def get_clink_purchase(purchase_id: str) -> dict[str, Any]:
    """Fetch one purchase state and its Core audit references."""
    safe_id=urllib.parse.quote(purchase_id,safe="")
    return _request_json(f"{CONFIG.registry_url}/purchases/{safe_id}")


@MCP_SERVER.tool()
def clink_marketplace_health() -> dict[str, Any]:
    """Check the marketplace registry and return catalog statistics."""
    return _request_json(f"{CONFIG.registry_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
