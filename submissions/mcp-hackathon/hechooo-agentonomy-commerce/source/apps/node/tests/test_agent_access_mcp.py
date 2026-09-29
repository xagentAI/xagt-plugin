import asyncio
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from mcp import types

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.agent_access_mcp import AgentScopedMcpProxy


TRANSFER_DESTINATION = "0x" + "1" * 40
TRANSFER_NETWORK = "eip155:137"


def transfer_id_for(user_id, agent_id, request_id):
    canonical = json.dumps(
        [user_id, agent_id, request_id],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "transfer_" + hashlib.sha256(canonical).hexdigest()[:48]


def transfer_response(*, transfer_id, request_id, to_address=TRANSFER_DESTINATION,
                      amount_usdc="2", status="pending", tx_hash=None,
                      receipt_id=None):
    return {
        "transfer_id": transfer_id,
        "request_id": request_id,
        "status": status,
        "network": TRANSFER_NETWORK,
        "asset": "USDC",
        "token_address": "0x" + "2" * 40,
        "to_address": to_address,
        "amount_usdc": amount_usdc,
        "amount_atomic": str(int(Decimal(amount_usdc) * 1_000_000)),
        "reservation_id": "reserve_" + "a" * 40,
        "tx_hash": tx_hash,
        "receipt_id": receipt_id,
        "reason_code": None,
        "next_action": "query_transfer",
    }


def principal(user="c_alice", scope="payments", opc_installation_id=None):
    return SimpleNamespace(
        user_id=user,
        agent_id="agent_" + user,
        runtime_id="run1",
        scope=scope,
        opc_installation_id=opc_installation_id,
    )


class Proxy:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [types.Tool(name=name, inputSchema={"type": "object", "properties": {
            "user_id": {"type": "string"}, "agent_id": {"type": "string"},
            "opc_installation_id": {"type": "string"},
            "offering_id": {"type": "string"}, "service_input": {"type": "object"},
            "preview_id": {"type": "string"}, "user_confirmed": {"type": "boolean"},
            "spending_authorization_id": {"type": "string"}, "transaction_hash": {"type": "string"},
        }, "required": []}) for name in (
            "create_clink_purchase_preview", "execute_clink_purchase", "get_clink_purchase",
            "create_core_account_setup_link", "revoke_polymarket_account_binding", "unreviewed_new_tool",
            "fund_polymarket_from_spending_authorization",
        )]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "create_clink_purchase_preview":
            return types.CallToolResult(content=[], structuredContent={
                "preview_id": "preview_" + arguments["user_id"], "user_id": arguments["user_id"],
            })
        return types.CallToolResult(content=[], structuredContent={"status": "action_required"})


class Market:
    def get_purchase_preview(self, *, user_id, preview_id):
        if preview_id != "preview_" + user_id:
            raise DownstreamError("marketplace", 404, "owned object not found")
        return {"preview_id": preview_id, "user_id": user_id, "execution_mode": "clink_allowance"}


class ReadyCore:
    def hosted_wallet_readiness(self, user_id):
        return {"user_id": user_id, "ready": True, "credential_routing": "per_wallet"}


def call(
    proxy,
    name,
    args,
    user="c_alice",
    scope="payments",
    opc_installation_id=None,
):
    return asyncio.run(
        proxy.call_tool(
            name,
            args,
            principal=principal(user, scope, opc_installation_id),
        )
    )


def test_tool_listing_is_default_deny_scoped_and_hides_authority_fields():
    proxy = AgentScopedMcpProxy(Proxy(), SimpleNamespace(marketplace=Market()))
    listed = asyncio.run(proxy.list_tools(principal=principal()))
    assert "create_core_account_setup_link" not in {t.name for t in listed}
    assert "unreviewed_new_tool" not in {t.name for t in listed}
    for tool in listed:
        assert not {
            "user_id",
            "agent_id",
            "opc_installation_id",
            "spending_authorization_id",
            "transaction_hash",
        } & tool.inputSchema["properties"].keys()
    read_only = asyncio.run(proxy.list_tools(principal=principal(scope="read")))
    assert "execute_clink_purchase" not in {t.name for t in read_only}


def test_identity_injection_and_foreign_id_denial_precede_mutations():
    downstream = Proxy()
    proxy = AgentScopedMcpProxy(downstream, SimpleNamespace(marketplace=Market(), core=ReadyCore()))
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_bob", "user_confirmed": True})
    assert result.isError and downstream.calls == []
    result = call(proxy, "create_clink_purchase_preview", {"user_id": "c_bob", "offering_id": "offering_a", "service_input": {}})
    assert result.isError and downstream.calls == []
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice", "transaction_hash": "untrusted"})
    assert result.isError and downstream.calls == []
    call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice", "user_confirmed": True})
    assert downstream.calls == [("execute_clink_purchase", {"preview_id": "preview_c_alice", "user_confirmed": True})]


def test_opc_installation_is_hidden_and_server_injected_only_for_opc_payments():
    installation = "opc_" + "a" * 40
    downstream = Proxy()
    proxy = AgentScopedMcpProxy(
        downstream,
        SimpleNamespace(marketplace=Market(), core=ReadyCore()),
    )

    create = {
        "offering_id": "offering_a",
        "service_input": {},
    }
    result = call(
        proxy,
        "create_clink_purchase_preview",
        create,
        opc_installation_id=installation,
    )
    assert not result.isError
    assert downstream.calls[-1][1] == {
        **create,
        "user_id": "c_alice",
        "opc_installation_id": installation,
    }

    call(
        proxy,
        "execute_clink_purchase",
        {"preview_id": "preview_c_alice", "user_confirmed": True},
        opc_installation_id=installation,
    )
    assert downstream.calls[-1][1]["opc_installation_id"] == installation

    call(
        proxy,
        "fund_polymarket_from_spending_authorization",
        {"request_id": "opc-funding", "amount_usdc": "0.01", "user_confirmed": True},
        opc_installation_id=installation,
    )
    assert downstream.calls[-1][1]["opc_installation_id"] == installation

    call(proxy, "create_clink_purchase_preview", create)
    assert "opc_installation_id" not in downstream.calls[-1][1]


def test_read_scope_and_missing_principal_cannot_execute():
    downstream = Proxy()
    proxy = AgentScopedMcpProxy(downstream, SimpleNamespace(marketplace=Market()))
    assert call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice"}, scope="read").isError
    assert asyncio.run(proxy.call_tool("execute_clink_purchase", {}, principal=None)).isError
    assert downstream.calls == []


def test_polymarket_id_is_server_namespaced_stable_across_runtime_restart():
    downstream = Proxy()
    proxy = AgentScopedMcpProxy(downstream, SimpleNamespace(marketplace=Market(), core=ReadyCore()))
    args = {"request_id": "task-1-payment", "amount_usdc": "0.01", "user_confirmed": True}
    call(proxy, "fund_polymarket_from_spending_authorization", args)
    call(proxy, "fund_polymarket_from_spending_authorization", args)
    call(proxy, "fund_polymarket_from_spending_authorization", args, user="c_bob")
    first, second, third = [args for _, args in downstream.calls]
    assert first == second
    assert first["confirmation_id"] != third["confirmation_id"]
    assert first["user_id"] == "c_alice" and third["user_id"] == "c_bob"
    assert first["amount_usdc"] == "0.010000"
    assert "request_id" not in first
    assert first["resource"] == "clink://polymarket/funding"


def test_downstream_errors_do_not_echo_internal_credentials():
    class Broken(Proxy):
        async def call_tool(self, *_):
            raise DownstreamError("core", 503, "secret-internal-token")
    proxy = AgentScopedMcpProxy(Broken(), SimpleNamespace(marketplace=Market(), core=ReadyCore()))
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice"})
    assert result.isError
    assert "secret-internal-token" not in result.model_dump_json()


def test_new_preview_is_re_read_and_checked_before_exposure():
    class Foreign(Proxy):
        async def call_tool(self, name, arguments):
            return types.CallToolResult(content=[], structuredContent={"preview_id": "preview_c_bob", "user_id": "c_bob"})
    proxy = AgentScopedMcpProxy(Foreign(), SimpleNamespace(marketplace=Market()))
    result = call(proxy, "create_clink_purchase_preview", {"offering_id": "offer1", "service_input": {}})
    assert result.isError
    assert "c_bob" not in result.model_dump_json()
    safe = AgentScopedMcpProxy(Proxy(), SimpleNamespace(marketplace=Market()))
    result = call(safe, "create_clink_purchase_preview", {"offering_id": "offer1", "service_input": {}})
    assert result.structuredContent["preview_id"] == "preview_c_alice"


def test_discovery_failure_does_not_disable_owned_payment_status_or_expose_secrets():
    class Broken(Proxy):
        async def list_tools(self):
            raise RuntimeError("private-internal-key")
    proxy = AgentScopedMcpProxy(Broken(), SimpleNamespace(marketplace=Market()))
    listed = asyncio.run(proxy.list_tools(principal=principal()))
    assert "get_agentonomy_payment" in {item.name for item in listed}
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice"})
    assert result.isError
    assert "private-internal-key" not in result.model_dump_json()


def test_payment_cannot_use_a_single_wallet_or_unready_core():
    class LegacyCore:
        def hosted_wallet_readiness(self, user_id):
            return {"user_id": user_id, "ready": True, "credential_routing": "single_wallet"}
    downstream = Proxy()
    proxy = AgentScopedMcpProxy(downstream, SimpleNamespace(marketplace=Market(), core=LegacyCore()))
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice"})
    assert result.structuredContent["status"] == "action_required"
    assert downstream.calls == []


@pytest.mark.parametrize("change", [
    {"user_id": "c_bob"}, {"preview_id": "preview_c_bob"},
    {"purchase_id": "purchase_c_bob"},
])
def test_execution_response_must_match_owned_preview_before_any_result_is_exposed(change):
    class Foreign(Proxy):
        async def call_tool(self, name, arguments):
            purchase = {"user_id": "c_alice", "preview_id": "preview_c_alice", "purchase_id": "purchase_c_alice"}
            return types.CallToolResult(content=[], structuredContent={
                "purchase": {**purchase, **change}, "service_result": {"private": "foreign-result"},
            })

    proxy = AgentScopedMcpProxy(Foreign(), SimpleNamespace(marketplace=Market(), core=ReadyCore()))
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice", "user_confirmed": True})
    assert result.isError
    assert "foreign-result" not in result.model_dump_json()
    assert "c_bob" not in result.model_dump_json()


def test_execution_returns_only_owned_purchase_and_delivery_read_back():
    class Executed(Proxy):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return types.CallToolResult(content=[], structuredContent={
                "purchase": {"user_id": "c_alice", "preview_id": "preview_c_alice", "purchase_id": "purchase_c_alice"},
                "service_result": {"private": "unverified-result"},
            })

    class OwnedMarket(Market):
        def get_purchase(self, *, user_id, purchase_id):
            assert (user_id, purchase_id) == ("c_alice", "purchase_c_alice")
            return {"user_id": user_id, "preview_id": "preview_c_alice", "purchase_id": purchase_id,
                    "state": "delivered", "service_result": {"data": "owned-result"}}

    downstream = Executed()
    proxy = AgentScopedMcpProxy(downstream, SimpleNamespace(marketplace=OwnedMarket(), core=ReadyCore()))
    result = call(proxy, "execute_clink_purchase", {"preview_id": "preview_c_alice", "user_confirmed": True})
    assert not result.isError
    assert result.structuredContent["service_result"] == {"data": "owned-result"}
    assert result.structuredContent["purchase"]["state"] == "delivered"
    assert "service_result" not in result.structuredContent["purchase"]
    assert "unverified-result" not in result.model_dump_json()
    assert len(downstream.calls) == 1
