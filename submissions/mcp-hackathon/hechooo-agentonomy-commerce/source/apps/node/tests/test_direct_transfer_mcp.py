import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.node.clink_node.adapters.core import CoreHttpAdapter
from apps.node.clink_node.agent_access_mcp import AgentScopedMcpProxy
from apps.node.clink_node.mcp_gateway import build_native_tools, create_mcp_application
from apps.node.tests.test_agent_access_mcp import principal, transfer_id_for, transfer_response


ARGS = {"request_id": "send-1", "to_address": "0x" + "1" * 40,
        "network": "eip155:137", "amount_usdc": "2"}
ID = transfer_id_for("c_alice", "agent_c_alice", "send-1")
OPC = "opc_" + "a" * 40


class NoBusiness:
    async def list_tools(self):
        return []

    async def call_tool(self, *_args):
        raise AssertionError("must not route direct transfer through business service")


def setup_proxy(*, response=None, ready=True, timeout=False, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer offline-core-secret"
        if request.url.path == "/funding/hosted-wallet-readiness":
            return httpx.Response(200, json={"user_id": "c_alice", "ready": ready,
                "credential_routing": "per_wallet", "reason_code": "HOSTED_ENROLLMENT_REQUIRED"})
        if timeout:
            raise httpx.ReadTimeout("secret upstream URL", request=request)
        body = response if response is not None else transfer_response(transfer_id=ID, request_id="send-1")
        return httpx.Response(status, json=body)

    adapter = CoreHttpAdapter(account_url="http://core.test", action_url="http://core.test",
        policy_url="http://core.test", audit_url="http://core.test", funding_url="http://core.test",
        internal_token="offline-core-secret", transport=httpx.MockTransport(handler))
    return AgentScopedMcpProxy(NoBusiness(), SimpleNamespace(core=adapter)), requests, adapter


def invoke(proxy, name, args, scope="payments", installation=OPC):
    return asyncio.run(proxy.call_tool(name, args, principal=principal(
        scope=scope, opc_installation_id=installation)))


def test_transfer_catalogue_scope_and_anonymous_boundary():
    proxy, _, _ = setup_proxy()
    for scope, expected in [("read", {"get_clink_transfer"}),
                            ("payments", {"get_clink_transfer", "create_clink_transfer"})]:
        tools = asyncio.run(proxy.list_tools(principal=principal(scope=scope)))
        transfers = {t.name: t for t in tools if "transfer" in t.name}
        assert set(transfers) == expected
        for tool in transfers.values():
            assert tool.inputSchema["additionalProperties"] is False
            assert not {"user_id", "agent_id", "opc_installation_id"} & tool.inputSchema["properties"].keys()
    assert asyncio.run(proxy.list_tools()) == []
    assert asyncio.run(proxy.call_tool("create_clink_transfer", ARGS)).isError
    assert invoke(proxy, "create_clink_transfer", ARGS, scope="read").isError
    # Native raw MCP must not gain an unscoped money tool.
    assert not {"create_clink_transfer", "get_clink_transfer"} & set(build_native_tools(SimpleNamespace()))


@pytest.mark.parametrize("patch", [
    {"user_id": "victim"}, {"agent_id": "victim"}, {"opc_installation_id": OPC},
    {"spender": "0x" + "2" * 40}, {"user_confirmed": True},
    {"amount_usdc": 2}, {"amount_usdc": "2e0"}, {"amount_usdc": "0"},
    {"amount_usdc": "0.0000001"}, {"amount_usdc": "2\n"},
    {"request_id": "send-1\n"}, {"network": "eip155:137\n"},
    {"to_address": "0x" + "0" * 40}, {"to_address": "0x" + "1" * 40 + "\n"},
])
def test_transfer_rejects_unsafe_arguments_before_any_request(patch):
    proxy, requests, _ = setup_proxy()
    result = invoke(proxy, "create_clink_transfer", {**ARGS, **patch})
    assert result.isError
    assert result.structuredContent["error"] == "invalid_tool_arguments"
    assert requests == []


def test_transfer_injects_principal_and_projects_core_response():
    body = {**transfer_response(transfer_id=ID, request_id="send-1"), "internal_token": "do-not-echo"}
    proxy, requests, _ = setup_proxy(response=body)
    result = invoke(proxy, "create_clink_transfer", {**ARGS, "amount_usdc": "2.000000"})
    assert not result.isError, result.structuredContent
    assert "internal_token" not in result.structuredContent
    assert len(requests) == 2 and requests[-1].method == "POST"
    assert requests[-1].url.path == "/funding/transfers"
    assert json.loads(requests[-1].content) == {**ARGS, "user_id": "c_alice",
        "agent_id": "agent_c_alice", "opc_installation_id": OPC}
    requests.clear()
    assert not invoke(proxy, "get_clink_transfer", {"transfer_id": ID}, scope="read").isError
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/funding/transfers/" + ID
    assert dict(requests[0].url.params) == {"user_id": "c_alice",
        "agent_id": "agent_c_alice", "opc_installation_id": OPC}


def test_hosted_gate_only_blocks_create_not_read():
    proxy, requests, _ = setup_proxy(ready=False)
    result = invoke(proxy, "create_clink_transfer", ARGS)
    assert result.structuredContent["status"] == "action_required"
    assert result.structuredContent["reason_code"] == "HOSTED_ENROLLMENT_REQUIRED"
    assert result.structuredContent["next_action"] == "contact_service_operator"
    assert all(r.method == "GET" for r in requests)
    requests.clear()
    assert not invoke(proxy, "get_clink_transfer", {"transfer_id": ID}, scope="read").isError
    assert [r.url.path for r in requests] == ["/funding/transfers/" + ID]


@pytest.mark.parametrize("patch", [
    {"transfer_id": "transfer_" + "b" * 48}, {"request_id": "other"},
    {"to_address": "0x" + "3" * 40}, {"network": "eip155:8453"},
    {"amount_usdc": "3"}, {"amount_atomic": "3"}, {"status": "invented"},
    {"status": "succeeded"}, {"asset": "ETH"}, {"reason_code": "https://secret"},
])
def test_invalid_create_response_returns_original_recovery_id_once(patch):
    proxy, requests, _ = setup_proxy(response={**transfer_response(transfer_id=ID, request_id="send-1"), **patch})
    result = invoke(proxy, "create_clink_transfer", ARGS)
    assert result.isError
    assert result.structuredContent == {"error": "invalid_business_response", "status": "unknown",
        "retry_safe": False, "transfer_id": ID, "request_id": "send-1", "next_action": "query_transfer"}
    assert sum(r.method == "POST" for r in requests) == 1


def test_timeout_returns_recovery_id_and_get_never_reposts():
    proxy, requests, _ = setup_proxy(timeout=True)
    result = invoke(proxy, "create_clink_transfer", ARGS)
    assert result.isError and result.structuredContent["transfer_id"] == ID
    assert result.structuredContent["error"] == "service_unavailable"
    assert "secret" not in json.dumps(result.structuredContent)
    assert invoke(proxy, "get_clink_transfer", {"transfer_id": ID}, scope="read").isError
    assert sum(r.method == "POST" for r in requests) == 1


@pytest.mark.parametrize("bad_id", ["../other", ID + "\n", "http://evil", ID + "?user_id=victim"])
def test_adapter_rejects_unsafe_path_before_network(bad_id):
    _, requests, adapter = setup_proxy()
    with pytest.raises(ValueError):
        adapter.get_direct_transfer(user_id="c_alice", agent_id="agent_c_alice", transfer_id=bad_id)
    assert requests == []


def test_query_by_original_request_id_is_owner_bound_and_read_only():
    proxy, requests, _ = setup_proxy(ready=False)
    result = invoke(proxy, "get_clink_transfer", {"request_id": "send-1"}, scope="read")
    assert not result.isError, result.structuredContent
    assert result.structuredContent["transfer_id"] == ID
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/funding/transfers/" + ID
    assert requests[0].url.params["opc_installation_id"] == OPC


def test_query_by_request_id_rejects_mismatched_response_request():
    proxy, requests, _ = setup_proxy(response=transfer_response(transfer_id=ID, request_id="other"))
    result = invoke(proxy, "get_clink_transfer", {"request_id": "send-1"}, scope="read")
    assert result.isError and result.structuredContent["error"] == "invalid_business_response"
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.parametrize("args", [{}, {"transfer_id": ID, "request_id": "send-1"},
                                  {"request_id": "send-1\n"}])
def test_query_rejects_ambiguous_or_unsafe_recovery_input(args):
    proxy, requests, _ = setup_proxy()
    assert invoke(proxy, "get_clink_transfer", args, scope="read").isError
    assert requests == []


def test_r4_bridge_discovers_transfers_and_recovers_after_unknown_response():
    from apps.node.tests.test_opc_onboarding import FakeClient
    from clink_node.opc_onboarding import OpcOnboardingBridge
    proxy, requests, _ = setup_proxy(timeout=True)
    healthy, get_requests, _ = setup_proxy()

    class BridgeClient(FakeClient):
        async def list_tools(self):
            return await proxy.list_tools(principal=principal(opc_installation_id=OPC))

        async def call_tool(self, name, arguments):
            self.business_calls.append((name, arguments))
            selected = proxy if name == "create_clink_transfer" else healthy
            return await selected.call_tool(name, arguments, principal=principal(opc_installation_id=OPC))

    client = BridgeClient(statuses=[{"installation_id": OPC, "status": "active"}])
    bridge = OpcOnboardingBridge(client)
    listed = asyncio.run(bridge.call_tool("list_clink_business_tools", {}))
    assert "create_clink_transfer" in listed.model_dump_json()
    unknown = asyncio.run(bridge.call_tool("call_clink_business_tool", {
        "name": "create_clink_transfer", "arguments": ARGS}))
    assert unknown.isError and unknown.structuredContent["status"] == "unknown"
    # r4 deliberately strips error metadata; original request_id still allows recovery.
    assert "transfer_id" not in unknown.structuredContent
    recovered = asyncio.run(bridge.call_tool("call_clink_business_tool", {
        "name": "get_clink_transfer", "arguments": {"request_id": "send-1"}}))
    assert not recovered.isError, recovered.structuredContent
    assert recovered.structuredContent["transfer_id"] == ID
    assert sum(r.method == "POST" for r in requests + get_requests) == 1
    assert client.business_calls == [("create_clink_transfer", ARGS),
                                    ("get_clink_transfer", {"request_id": "send-1"})]


def test_transfer_http_mcp_admission_denies_anonymous_read_and_revoked():
    class Auth:
        revoked = False

        def authenticate(self, token):
            if self.revoked or token not in {"synthetic-pay", "synthetic-read"}:
                raise ValueError("unauthorized")
            return principal(scope="payments" if token == "synthetic-pay" else "read", opc_installation_id=OPC)

    async def scenario():
        proxy, requests, _ = setup_proxy()
        auth = Auth()
        app = create_mcp_application(proxy, access_service=auth)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
                body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "create_clink_transfer", "arguments": ARGS}}
                assert (await client.post("/mcp", json=body, headers=headers)).status_code == 401
                response = await client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer synthetic-read"})
                assert response.json()["result"]["isError"] is True
                assert requests == []
                response = await client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer synthetic-pay"})
                assert response.json()["result"]["structuredContent"]["transfer_id"] == ID
                assert sum(r.method == "POST" for r in requests) == 1
                auth.revoked = True
                assert (await client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer synthetic-pay"})).status_code == 401
                assert sum(r.method == "POST" for r in requests) == 1
    asyncio.run(scenario())


def test_redirect_does_not_forward_internal_bearer_or_repost():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("hosted-wallet-readiness"):
            return httpx.Response(200, json={"user_id": "c_alice", "ready": True, "credential_routing": "per_wallet"})
        return httpx.Response(307, headers={"location": "https://untrusted.invalid/funding/transfers"})

    adapter = CoreHttpAdapter(account_url="http://core.test", action_url="http://core.test", policy_url="http://core.test",
        audit_url="http://core.test", funding_url="http://core.test", internal_token="synthetic-secret", transport=httpx.MockTransport(handler))
    proxy = AgentScopedMcpProxy(NoBusiness(), SimpleNamespace(core=adapter))
    result = invoke(proxy, "create_clink_transfer", ARGS)
    assert result.isError and result.structuredContent["transfer_id"] == ID
    assert all(r.url.host == "core.test" for r in requests)
    assert sum(r.method == "POST" for r in requests) == 1


@pytest.mark.parametrize("amount", ["0.000001", "99999999999999.999999"])
def test_decimal_edges_roundtrip_without_float(amount):
    proxy, requests, _ = setup_proxy(response=transfer_response(transfer_id=ID, request_id="send-1", amount_usdc=amount))
    result = invoke(proxy, "create_clink_transfer", {**ARGS, "amount_usdc": amount})
    assert not result.isError
    assert result.structuredContent["amount_usdc"] == amount
    assert json.loads(requests[-1].content)["amount_usdc"] == amount
