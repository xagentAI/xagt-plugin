from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import anyio
import pytest
from mcp import types

from clink_node.opc_client import OpcClient, OpcClientError
from clink_node.opc_onboarding import OpcOnboardingBridge


INSTALLATION_ID = "opc_" + "a" * 40
PAIRING_URL = "https://account.agentonomy.example/account/opc/pairing-secret"
TOKEN = "agentonomy_opc_v1_do-not-leak"
NOW = 1_800_000_000


class FakeClient:
    def __init__(self, statuses: list[object] | None = None) -> None:
        self.state = SimpleNamespace(installation_id=INSTALLATION_ID)
        self.statuses = list(statuses or [])
        self.status_calls = 0
        self.connect_calls = 0
        self.open_account_link_calls = 0
        self.list_calls = 0
        self.business_calls: list[tuple[str, dict]] = []
        self.pairing = {
            "installation_id": INSTALLATION_ID,
            "pairing_id": "opc_pair_" + "b" * 40,
            "verification_uri": PAIRING_URL,
            "expires_at": NOW + 600,
            "status": "pending",
        }
        self.business_tools = [
            types.Tool(
                name="get_clink_account_readiness",
                description="Read account readiness.",
                inputSchema={
                    "type": "object",
                    "properties": {"user_id": {"type": "string"}},
                    "required": ["user_id"],
                    "additionalProperties": False,
                },
            )
        ]
        self.business_result = types.CallToolResult(
            content=[types.TextContent(type="text", text='{"ok":true}')],
            structuredContent={"ok": True},
        )
        self.list_error: BaseException | None = None
        self.call_error: BaseException | None = None

    def status(self) -> dict:
        self.status_calls += 1
        if not self.statuses:
            return {"installation_id": INSTALLATION_ID, "status": "unpaired"}
        value = self.statuses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def connect(self) -> dict:
        self.connect_calls += 1
        return self.pairing

    def open_account_link(self) -> dict:
        self.open_account_link_calls += 1
        return {**self.pairing, "status": "active"}

    async def list_tools(self):
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return self.business_tools

    async def call_tool(self, name: str, arguments: dict):
        self.business_calls.append((name, arguments))
        if self.call_error is not None:
            raise self.call_error
        return self.business_result


def result_value(result: types.CallToolResult) -> dict:
    assert isinstance(result.structuredContent, dict)
    return result.structuredContent


def test_fixed_catalogue_is_offline_and_strict() -> None:
    client = FakeClient()
    bridge = OpcOnboardingBridge(client)

    tools = asyncio.run(bridge.list_tools())

    assert [tool.name for tool in tools] == [
        "get_clink_connection_status",
        "connect_clink_wallet",
        "list_clink_business_tools",
        "call_clink_business_tool",
    ]
    assert client.status_calls == 0
    assert client.list_calls == 0
    assert all(isinstance(tool, types.Tool) for tool in tools)
    for tool in tools:
        assert tool.inputSchema["type"] == "object"
        assert tool.inputSchema["additionalProperties"] is False
    call_definition = tools[-1]
    assert call_definition.inputSchema["required"] == ["name", "arguments"]
    assert call_definition.inputSchema["properties"]["arguments"]["type"] == "object"
    assert call_definition.annotations is not None
    assert call_definition.annotations.readOnlyHint is False


def test_status_transitions_on_the_same_bridge_and_active_requires_readiness_query() -> None:
    client = FakeClient(
        [
            {"installation_id": INSTALLATION_ID, "status": "pending"},
            {"installation_id": INSTALLATION_ID, "status": "active"},
        ]
    )
    bridge = OpcOnboardingBridge(client)

    pending = result_value(
        asyncio.run(bridge.call_tool("get_clink_connection_status", {}))
    )
    active = result_value(
        asyncio.run(bridge.call_tool("get_clink_connection_status", {}))
    )

    assert pending["status"] == "pending"
    assert active["status"] == "active"
    assert active["payment_ready"] is False
    assert active["payment_ready_checked"] is False
    assert "get_clink_account_readiness" in active["next_action"]
    assert client.status_calls == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpcClientError("not found", status_code=404), "unpaired"),
        (OpcClientError("server unavailable", status_code=503), "unavailable"),
        (OpcClientError("transport failed"), "unavailable"),
    ],
)
def test_status_uses_request_scoped_http_status_without_guessing_unpaired(
    error: OpcClientError, expected: str
) -> None:
    bridge = OpcOnboardingBridge(FakeClient([error]))

    result = asyncio.run(bridge.call_tool("get_clink_connection_status", {}))

    assert result_value(result)["status"] == expected
    assert result_value(result)["payment_ready"] is False


@pytest.mark.parametrize("status", ["active", "revoked"])
def test_connect_handles_active_as_management_but_does_not_reconnect_revoked(
    status: str,
) -> None:
    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": status}])
    bridge = OpcOnboardingBridge(client, browser_opener=lambda _url: True)

    result = asyncio.run(bridge.call_tool("connect_clink_wallet", {}))

    value = result_value(result)
    assert value["status"] == status
    assert client.connect_calls == 0
    assert client.open_account_link_calls == (1 if status == "active" else 0)
    assert value["browser_opened"] is (status == "active")
    assert "verification_uri" not in value
    assert "pairing_id" not in value


@pytest.mark.parametrize("status", ["active", "revoked"])
def test_connect_refreshes_authoritative_status_before_cached_pairing(status: str) -> None:
    client = FakeClient(
        [
            {"installation_id": INSTALLATION_ID, "status": "pending"},
            {"installation_id": INSTALLATION_ID, "status": status},
        ]
    )
    opened: list[str] = []
    bridge = OpcOnboardingBridge(
        client,
        browser_opener=lambda url: opened.append(url) or True,
    )

    first = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )
    second = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )

    assert first["status"] == "pending"
    assert second["status"] == status
    assert second["browser_opened"] is (status == "active")
    assert second["expiry"] == (NOW + 600 if status == "active" else None)
    assert client.connect_calls == 1
    assert client.open_account_link_calls == (1 if status == "active" else 0)
    assert len(opened) == (2 if status == "active" else 1)


def test_active_connect_uses_a_fresh_management_link_on_each_explicit_call() -> None:
    client = FakeClient(
        [
            {"installation_id": INSTALLATION_ID, "status": "active"},
            {"installation_id": INSTALLATION_ID, "status": "active"},
        ]
    )
    client.pairing = {
        **client.pairing,
        "status": "active",
        "verification_uri": PAIRING_URL.replace("pairing-secret", "management-secret"),
    }
    opened: list[str] = []
    bridge = OpcOnboardingBridge(
        client,
        browser_opener=lambda url: opened.append(url) or True,
    )
    # A pending link left by an earlier flow must not be reused for an active
    # management invocation.
    bridge._pairing = {
        "verification_uri": PAIRING_URL,
        "expires_at": NOW + 600,
        "status": "pending",
    }

    first = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )
    second = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )

    assert first["status"] == second["status"] == "active"
    assert first["browser_opened"] is second["browser_opened"] is True
    assert client.open_account_link_calls == 2
    assert client.connect_calls == 0
    assert opened == [client.pairing["verification_uri"]] * 2
    for result in (first, second):
        assert "verification_uri" not in result
        assert "pairing_id" not in result
        assert PAIRING_URL not in json.dumps(result)


def test_overlapping_active_connect_calls_share_one_management_open() -> None:
    class ConcurrentManagementClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([{"installation_id": INSTALLATION_ID, "status": "active"}])
            self.open_started = threading.Event()
            self.open_release = threading.Event()

        def open_account_link(self) -> dict:
            self.open_account_link_calls += 1
            self.open_started.set()
            self.open_release.wait(timeout=1)
            return {**self.pairing, "status": "active"}

    client = ConcurrentManagementClient()
    opened: list[str] = []
    bridge = OpcOnboardingBridge(
        client,
        browser_opener=lambda url: opened.append(url) or True,
    )

    async def connect_twice():
        async with anyio.create_task_group() as task_group:
            first_result: dict[str, object] = {}
            second_result: dict[str, object] = {}

            async def first() -> None:
                nonlocal first_result
                first_result = result_value(
                    await bridge.call_tool("connect_clink_wallet", {})
                )

            async def second() -> None:
                nonlocal second_result
                second_result = result_value(
                    await bridge.call_tool("connect_clink_wallet", {})
                )

            task_group.start_soon(first)
            await anyio.to_thread.run_sync(client.open_started.wait)
            task_group.start_soon(second)
            client.open_release.set()
        return first_result, second_result

    first, second = anyio.run(connect_twice)

    assert first == second
    assert first["status"] == "active"
    assert first["browser_opened"] is True
    assert client.open_account_link_calls == 1
    assert opened == [client.pairing["verification_uri"]]


def test_active_management_browser_failure_never_returns_link_and_directs_to_local_account(
) -> None:
    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": "active"}])
    bridge = OpcOnboardingBridge(client, browser_opener=lambda _url: False)

    result = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )

    assert result["status"] == "active"
    assert result["browser_opened"] is False
    assert "opc account --no-open" in result["instructions"]
    assert PAIRING_URL not in json.dumps(result)
    assert TOKEN not in json.dumps(result)


def test_connect_reuses_unexpired_pairing_and_never_returns_url_or_browser_error(
) -> None:
    client = FakeClient(
        [
            OpcClientError("not found", status_code=404),
            OpcClientError("not found", status_code=404),
        ]
    )
    opened: list[str] = []

    def browser_opener(url: str) -> bool:
        opened.append(url)
        return False

    bridge = OpcOnboardingBridge(client, browser_opener=browser_opener)
    first = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )
    second = result_value(
        asyncio.run(bridge.call_tool("connect_clink_wallet", {}))
    )

    assert first["status"] == second["status"] == "pending"
    assert first["expiry"] == second["expiry"] == NOW + 600
    assert first["browser_opened"] is False
    assert second["browser_opened"] is False
    assert client.connect_calls == 1
    assert opened == [PAIRING_URL, PAIRING_URL]
    encoded = json.dumps([first, second])
    assert PAIRING_URL not in encoded
    assert TOKEN not in encoded
    assert "headless" in first["instructions"].lower()


def test_overlapping_connect_calls_share_one_pairing_and_browser_open() -> None:
    class ConcurrentClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([
                OpcClientError("not found", status_code=404),
                OpcClientError("not found", status_code=404),
            ])
            self._connect_lock = threading.Lock()
            self._second_connect = threading.Event()

        def connect(self) -> dict:
            with self._connect_lock:
                self.connect_calls += 1
                count = self.connect_calls
            if count == 1:
                # If the bridge does not single-flight the lifecycle, the
                # second worker reaches connect and releases this wait.
                self._second_connect.wait(timeout=0.5)
            elif count == 2:
                self._second_connect.set()
            return self.pairing

    client = ConcurrentClient()
    opened: list[str] = []
    bridge = OpcOnboardingBridge(
        client,
        browser_opener=lambda url: opened.append(url) or True,
    )

    async def connect_twice():
        return await asyncio.gather(
            bridge.call_tool("connect_clink_wallet", {}),
            bridge.call_tool("connect_clink_wallet", {}),
        )

    results = asyncio.run(connect_twice())

    assert [result_value(result)["status"] for result in results] == [
        "pending",
        "pending",
    ]
    assert client.connect_calls == 1
    assert opened == [PAIRING_URL]


def test_cancelled_connect_owner_releases_singleflight_waiters() -> None:
    class BlockingStatusClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([
                OpcClientError("not found", status_code=404),
                OpcClientError("not found", status_code=404),
            ])
            self.status_started = threading.Event()
            self.status_release = threading.Event()

        def status(self) -> dict:
            self.status_started.set()
            self.status_release.wait(timeout=1)
            return super().status()

    client = BlockingStatusClient()
    bridge = OpcOnboardingBridge(client, browser_opener=lambda _url: True)

    async def cancel_then_connect():
        owner_scope: dict[str, anyio.CancelScope] = {}
        owner_done = anyio.Event()

        async def owner() -> None:
            with anyio.CancelScope() as scope:
                owner_scope["scope"] = scope
                await bridge.call_tool("connect_clink_wallet", {})
            owner_done.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(owner)
            await anyio.to_thread.run_sync(client.status_started.wait)
            owner_scope["scope"].cancel()
            client.status_release.set()
            with anyio.fail_after(1):
                await owner_done.wait()
            with anyio.fail_after(1):
                result = await bridge.call_tool("connect_clink_wallet", {})
            task_group.cancel_scope.cancel()
            return result

    result = anyio.run(cancel_then_connect)

    assert result_value(result)["status"] == "pending"
    assert client.connect_calls == 1


def test_business_listing_is_actual_and_maps_authorization_and_service_errors() -> None:
    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": "active"}])
    bridge = OpcOnboardingBridge(client)
    listed = result_value(
        asyncio.run(bridge.call_tool("list_clink_business_tools", {}))
    )
    assert listed["tools"][0]["name"] == "get_clink_account_readiness"
    assert listed["tools"][0]["inputSchema"]["required"] == ["user_id"]

    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": "active"}])
    client.list_error = OpcClientError("consent required", status_code=400)
    auth = result_value(
        asyncio.run(OpcOnboardingBridge(client).call_tool("list_clink_business_tools", {}))
    )
    assert auth["error"] == "WALLET_AUTHORIZATION_REQUIRED"
    assert "consent required" not in json.dumps(auth).lower()

    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": "active"}])
    client.list_error = OpcClientError("revoked", status_code=400)
    client.statuses = [{"installation_id": INSTALLATION_ID, "status": "revoked"}]
    revoked = result_value(
        asyncio.run(OpcOnboardingBridge(client).call_tool("list_clink_business_tools", {}))
    )
    assert revoked["error"] == "DEVICE_REVOKED"

    client = FakeClient([{"installation_id": INSTALLATION_ID, "status": "active"}])
    client.list_error = RuntimeError("private remote body")
    unavailable = result_value(
        asyncio.run(OpcOnboardingBridge(client).call_tool("list_clink_business_tools", {}))
    )
    assert unavailable["error"] == "CLINK_UNAVAILABLE"
    assert "private remote body" not in json.dumps(unavailable)


def test_business_listing_refreshes_revocation_after_authorization_failure() -> None:
    client = FakeClient(
        [
            {"installation_id": INSTALLATION_ID, "status": "active"},
            {"installation_id": INSTALLATION_ID, "status": "revoked"},
        ]
    )
    client.list_error = OpcClientError("authorization expired", status_code=401)

    result = asyncio.run(
        OpcOnboardingBridge(client).call_tool("list_clink_business_tools", {})
    )

    value = result_value(result)
    assert value["error"] == "DEVICE_REVOKED"
    assert value["status"] == "revoked"
    assert client.status_calls == 2


def test_business_call_rejects_local_shape_and_onboarding_names() -> None:
    client = FakeClient()
    bridge = OpcOnboardingBridge(client)

    for call_arguments in (
        {"name": "get_clink_connection_status", "arguments": {}},
        {"name": "remote_business", "arguments": []},
        {"name": "remote_business"},
    ):
        result = asyncio.run(bridge.call_tool("call_clink_business_tool", {
            **call_arguments,
        }))
        assert result.isError
        assert client.business_calls == []


def test_uncertain_business_call_is_dispatched_once_and_never_replayable() -> None:
    client = FakeClient()
    client.call_error = RuntimeError("private remote body")
    bridge = OpcOnboardingBridge(client)

    result = asyncio.run(
        bridge.call_tool(
            "call_clink_business_tool",
            {"name": "execute_clink_purchase", "arguments": {"request_id": "one"}},
        )
    )

    value = result_value(result)
    assert result.isError
    assert value["error"] == "outcome_unknown"
    assert value["retry_safe"] is False
    assert "private remote body" not in json.dumps(value)
    assert client.business_calls == [
        ("execute_clink_purchase", {"request_id": "one"})
    ]


def test_business_call_projects_a_known_remote_rejection_without_raw_details() -> None:
    client = FakeClient()
    client.business_result = types.CallToolResult(
        content=[types.TextContent(type="text", text="private remote detail")],
        structuredContent={
            "error": "tool_not_allowed",
            "status": "rejected",
            "retry_safe": False,
            "detail": "private remote detail",
        },
        isError=True,
    )
    bridge = OpcOnboardingBridge(client)

    result = asyncio.run(
        bridge.call_tool(
            "call_clink_business_tool",
            {"name": "get_clink_account_readiness", "arguments": {}},
        )
    )

    value = result_value(result)
    assert result.isError
    assert value == {
        "error": "tool_not_allowed",
        "status": "rejected",
        "retry_safe": False,
    }
    assert "private remote detail" not in result.model_dump_json()


def test_stdio_mcp_disables_sdk_validation_before_bridge_argument_checks(monkeypatch) -> None:
    from mcp.server import stdio
    from mcp.server.lowlevel import Server

    captured: dict[str, object] = {}
    original_call_tool = Server.call_tool

    def call_tool(self, *, validate_input=True):
        captured["validate_input"] = validate_input
        return original_call_tool(self, validate_input=validate_input)

    async def run(self, *_args, **_kwargs):
        handler = self.request_handlers[types.CallToolRequest]
        request = types.CallToolRequest(
            params=types.CallToolRequestParams(
                name="call_clink_business_tool",
                arguments={
                    "name": "call_clink_business_tool",
                    "arguments": "synthetic-private-token",
                },
            )
        )
        captured["result"] = (await handler(request)).root

    class EmptyStdio:
        async def __aenter__(self):
            return None, None

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(Server, "call_tool", call_tool)
    monkeypatch.setattr(Server, "run", run)
    monkeypatch.setattr(stdio, "stdio_server", lambda: EmptyStdio())

    asyncio.run(OpcClient.serve_stdio(SimpleNamespace()))

    assert captured["validate_input"] is False
    result = captured["result"]
    assert isinstance(result, types.CallToolResult)
    assert result.structuredContent == {
        "error": "INVALID_ARGUMENTS",
        "status": "rejected",
        "retry_safe": False,
    }
    assert "synthetic-private-token" not in result.model_dump_json()


def test_real_mcp_memory_handshake_exposes_fixed_surface() -> None:
    from mcp.client.session import ClientSession
    from mcp.server.lowlevel import Server
    from mcp.shared.memory import create_client_server_memory_streams

    bridge = OpcOnboardingBridge(FakeClient())
    server = Server("Agentonomy OPC bridge", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return await bridge.list_tools()

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        return await bridge.call_tool(name, arguments)

    async def handshake() -> None:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    server.run,
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
                try:
                    async with ClientSession(client_read, client_write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        assert [tool.name for tool in result.tools] == [
                            "get_clink_connection_status",
                            "connect_clink_wallet",
                            "list_clink_business_tools",
                            "call_clink_business_tool",
                        ]
                        malformed = await session.call_tool(
                            "call_clink_business_tool",
                            {
                                "name": "call_clink_business_tool",
                                "arguments": "synthetic-private-token",
                            },
                        )
                        assert malformed.isError
                        assert malformed.structuredContent == {
                            "error": "INVALID_ARGUMENTS",
                            "status": "rejected",
                            "retry_safe": False,
                        }
                        assert "synthetic-private-token" not in malformed.model_dump_json()
                finally:
                    task_group.cancel_scope.cancel()

    import anyio

    asyncio.run(handshake())
