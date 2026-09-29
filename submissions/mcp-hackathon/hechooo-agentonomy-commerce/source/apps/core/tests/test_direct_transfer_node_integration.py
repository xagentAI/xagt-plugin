"""Offline Node -> internal HTTP -> real Core -> simulated Hosted/Watcher."""
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from test_direct_transfer_hosted import hosted_context
from test_direct_transfer_service import DEST, NETWORK


def test_node_transfer_reaches_real_core_settlement_without_second_payment(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "node"))
    from clink_node.adapters.core import CoreHttpAdapter
    from clink_node.agent_access_mcp import AgentScopedMcpProxy
    service, funding, repo, hosted = hosted_context(tmp_path, monkeypatch, recover_state="finalized")
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL", funding.config.funding_database_url)
    from services.funding_service import app as funding_app
    funding.config.clink_internal_api_token = "offline-internal-test-token"
    monkeypatch.setattr(funding_app, "APP_CONFIG", funding.config)
    monkeypatch.setattr(funding_app, "SERVICE", funding)
    monkeypatch.setattr(funding_app, "DirectTransferService", lambda _: service)
    monkeypatch.setattr(funding, "get_hosted_wallet_readiness", lambda user: {
        "user_id": user, "ready": True, "credential_routing": "per_wallet",
    })
    paths = []
    with TestClient(funding_app.create_app()) as core_http:
        def transport(request):
            assert request.headers["authorization"] == "Bearer offline-internal-test-token"
            paths.append((request.method, request.url.path))
            response = core_http.request(request.method, str(request.url),
                headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, json=response.json())

        adapter = CoreHttpAdapter(account_url="http://testserver", action_url="http://testserver",
            policy_url="http://testserver", audit_url="http://testserver", funding_url="http://testserver",
            internal_token="offline-internal-test-token", transport=httpx.MockTransport(transport))

        class NoDownstreams:
            async def list_tools(self):
                return []

            async def call_tool(self, *_args):
                raise AssertionError("direct transfer must use Core, not a business downstream")

        proxy = AgentScopedMcpProxy(NoDownstreams(), SimpleNamespace(core=adapter))
        owner = SimpleNamespace(user_id="u", agent_id="hermes", scope="payments", opc_installation_id=None)
        reader = SimpleNamespace(user_id="u", agent_id="hermes", scope="read", opc_installation_id=None)
        other = SimpleNamespace(user_id="other", agent_id="hermes", scope="read", opc_installation_id=None)
        args = {"request_id": "node-e2e-1", "to_address": DEST, "network": NETWORK, "amount_usdc": "2"}
        def call(name, args, principal):
            return asyncio.run(proxy.call_tool(name, args, principal=principal))

        assert call("create_clink_transfer", args, reader).isError
        first = call("create_clink_transfer", args, owner)
        assert not first.isError, first.structuredContent
        assert first.structuredContent["status"] == "pending"
        query = {"transfer_id": first.structuredContent["transfer_id"]}
        assert call("get_clink_transfer", query, other).isError
        final = call("get_clink_transfer", query, reader)
        assert not final.isError, final.structuredContent
        assert final.structuredContent["status"] == "succeeded"
        assert final.structuredContent["receipt_id"] and final.structuredContent["tx_hash"]
        assert repo.spending_grant("grant_1").used_amount_usdc == Decimal("2")
        assert repo.spending_grant("grant_1").reserved_amount_usdc == 0
        replay = call("create_clink_transfer", args, owner)
        assert replay.structuredContent == final.structuredContent
        assert len(hosted.submit_calls) == 1
        assert sum(method == "POST" for method, _ in paths) == 2  # original + idempotent replay
        assert "offline-internal-test-token" not in json.dumps(final.structuredContent)
