from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import mcp_servers.prediction_markets_server as server


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _snapshot_payload() -> dict:
    return {
        "summary": {
            "portfolio_value_usd": "0.00",
            "current_value_usd": "0.00",
            "capital_deployed_usd": "0.00",
            "realized_pnl_usd": "0.00",
            "unrealized_pnl_usd": "0.00",
            "total_pnl_usd": "0.00",
            "total_pnl_pct": "0.00",
            "open_positions": 0,
            "pending_confirmations": 0,
            "submitted_executions": 0,
            "win_rate_pct": "0.00",
            "last_updated_at": "2026-08-21T00:00:00Z",
        }
    }


def main() -> None:
    signature = inspect.signature(
        server.get_prediction_market_portfolio_snapshot
    )
    assert list(signature.parameters) == []

    tool = server.MCP_SERVER._tool_manager.get_tool(
        "get_prediction_market_portfolio_snapshot"
    )
    assert tool is not None
    assert "user_id" not in tool.parameters.get("properties", {})
    assert not tool.parameters.get("required")

    original_request_json = server._request_json
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request_json(
        base_url: str,
        path: str,
        payload: dict | None = None,
    ) -> dict:
        calls.append((base_url, path, payload))
        return _snapshot_payload()

    try:
        server._request_json = fake_request_json
        snapshot = server.get_prediction_market_portfolio_snapshot()
    finally:
        server._request_json = original_request_json

    assert snapshot.summary.portfolio_value_usd == "0.00"
    assert calls == [
        (
            server.CONFIG.portfolio_url,
            "/portfolio/snapshot",
            None,
        )
    ]

    internal_token = "portfolio-internal-secret-marker"
    original_token = server.CONFIG.prediction_markets_internal_api_token
    original_urlopen = server.urllib.request.urlopen
    requests = []

    def fake_urlopen(request, timeout: int):
        assert timeout == 30
        requests.append(request)
        return _JsonResponse({"status": "ok"})

    try:
        server.urllib.request.urlopen = fake_urlopen
        server.CONFIG.prediction_markets_internal_api_token = internal_token
        server._request_json(
            server.CONFIG.portfolio_url,
            "/portfolio/snapshot",
        )
        server._request_json(server.CONFIG.router_url, "/healthz")

        assert requests[0].get_header("Authorization") is None
        assert internal_token not in requests[0].full_url
        assert requests[1].get_header("Authorization") is None

        requests.clear()
        server.CONFIG.prediction_markets_internal_api_token = ""
        server._request_json(
            server.CONFIG.portfolio_url,
            "/portfolio/snapshot",
        )
        assert len(requests) == 1
        assert requests[0].get_header("Authorization") is None
    finally:
        server.CONFIG.prediction_markets_internal_api_token = original_token
        server.urllib.request.urlopen = original_urlopen

    print(json.dumps({"status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
