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

from services.funding_service.schemas import (  # noqa: E402
    FundingStatus,
)
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
MCP_SERVER = FastMCP(
    "Funding MCP Server",
    instructions="Expose Clink spending-cap funding tools. Per-transfer signing links are not part of the production flow.",
    host=CONFIG.funding_mcp_host,
    port=CONFIG.funding_mcp_port,
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
        raise RuntimeError(f"funding service request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"funding service request failed: {exc}") from exc


@MCP_SERVER.tool()
def get_funding_status(user_id: str | None = None, venue: str | None = None) -> FundingStatus:
    """Read spending authorizations, receipts, and available budget by venue."""
    query = urllib.parse.urlencode({key: value for key, value in {"user_id": user_id, "venue": venue}.items() if value})
    suffix = f"?{query}" if query else ""
    response = _request_json(f"{CONFIG.funding_service_url}/funding/status{suffix}")
    return FundingStatus(**response)


@MCP_SERVER.tool()
def funding_service_health() -> dict:
    """Check whether the backing funding service is available."""
    return _request_json(f"{CONFIG.funding_service_url}/healthz")


def main() -> None:
    MCP_SERVER.run(transport="streamable-http")


if __name__ == "__main__":
    main()
