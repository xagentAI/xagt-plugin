from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from mcp import types

from apps.node.clink_node.agent_access_mcp import AgentScopedMcpProxy
from apps.node.clink_node.application import assemble_node
from apps.node.clink_node.config import (
    AgentAccessSettings,
    EventBackend,
    EventSettings,
    InteractionMode,
    InteractionSettings,
    ModuleMode,
    ModuleSettings,
    NodeSettings,
    Profile,
    SecretBackend,
    SecretSettings,
    StorageBackend,
    StorageSettings,
)
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.secrets import MemorySecretStore
from apps.node.clink_node.storage.postgres import PostgresNodeRepository


CONTROL_NAME = "agent-access-control-token"
KEY_NAME = "agent-access-token-key"
CONTROL = b"control-token-that-is-only-for-java-management"
TOKEN_KEY = b"runtime-token-key-that-is-only-for-agent-access-32"


class TrackingSecretStore(MemorySecretStore):
    def __init__(self, values: dict[str, bytes]) -> None:
        super().__init__(values)
        self.read_names: list[str] = []
        self.set_names: list[str] = []

    def get(self, name: str) -> bytes | None:
        self.read_names.append(name)
        return super().get(name)

    def set(self, name: str, value: bytes) -> None:
        self.set_names.append(name)
        super().set(name, value)


class ReadOnlyDownstream:
    def __init__(self, _url: str) -> None:
        pass

    async def list_tools(self) -> list[types.Tool]:
        return [
            types.Tool(
                name="search_clink_services",
                description="Read-only fake service search.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict,
    ) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")],
            structuredContent={"name": name, "arguments": arguments},
        )


def _settings(tmp_path: Path, *, enabled: bool) -> NodeSettings:
    defaults = NodeSettings.defaults(
        Profile.SERVER,
        paths=NodePaths.from_home(tmp_path / ".clink"),
    )
    modules = dict(defaults.modules)
    modules["prediction-markets"] = replace(
        modules["prediction-markets"],
        mode=ModuleMode.DISABLED,
    )
    return replace(
        defaults,
        storage=StorageSettings(
            backend=StorageBackend.POSTGRES,
            postgres_url=f"sqlite+pysqlite:///{tmp_path / 'node.sqlite3'}",
        ),
        events=EventSettings(backend=EventBackend.MEMORY),
        secrets=SecretSettings(backend=SecretBackend.KEYCHAIN),
        interaction=InteractionSettings(
            mode=InteractionMode.SELF_HOSTED,
            public_base_url="https://node.example",
        ),
        modules=modules,
        agent_access=AgentAccessSettings(
            enabled=enabled,
            issuer="wallet-app",
            mcp_public_url="https://agents.example/mcp",
        ),
    )


def _repository(settings: NodeSettings) -> PostgresNodeRepository:
    return PostgresNodeRepository(
        settings.storage.postgres_url or "",
    )


def _store(
    *,
    control: bytes | None = CONTROL,
    token_key: bytes | None = TOKEN_KEY,
    **extra: bytes,
) -> TrackingSecretStore:
    values = dict(extra)
    if control is not None:
        values[CONTROL_NAME] = control
    if token_key is not None:
        values[KEY_NAME] = token_key
    return TrackingSecretStore(values)


def _set_hosted_registry_environment(
    monkeypatch: pytest.MonkeyPatch,
    registry_file: str,
    *,
    facilitator_mode: str = "hosted",
) -> None:
    monkeypatch.setenv("CLINK_FACILITATOR_MODE", facilitator_mode)
    monkeypatch.setenv(
        "CLINK_HOSTED_WALLET_CREDENTIALS_FILE",
        registry_file,
    )


def _cleanup(assembly) -> None:
    for closer in reversed(assembly.resource_closers):
        closer()
    assembly.release_lifecycle_locks()


def test_enabled_assembly_uses_real_credentials_for_authenticated_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, enabled=True)
    _set_hosted_registry_environment(
        monkeypatch,
        str(tmp_path / "hosted-wallets.json"),
    )
    store = _store()
    monkeypatch.setattr(
        "apps.node.clink_node.application.StreamableHttpMcpClient",
        ReadOnlyDownstream,
    )

    repository = _repository(settings)
    assembly = assemble_node(
        settings,
        secret_store=store,
        repository=repository,
    )
    try:
        assert isinstance(assembly.mcp_proxy, AgentScopedMcpProxy)
        assert assembly.context.agent_access_service is not None
        assert assembly.context.agent_control_token == CONTROL.decode()

        async def scenario() -> None:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=assembly.api_application),
                base_url="http://127.0.0.1",
            ) as client:
                control_headers = {
                    "Authorization": "Bearer " + CONTROL.decode()
                }
                registered = await client.post(
                    "/v1/c/agents",
                    headers=control_headers,
                    json={
                        "subject_id": "wallet-user-1",
                        "external_agent_id": "java-agent-1",
                    },
                )
                assert registered.status_code == 201, registered.text
                agent_id = registered.json()["agent_id"]
                issued = await client.post(
                    f"/v1/c/agents/{agent_id}/runtime-credentials",
                    headers=control_headers,
                    json={
                        "runtime_id": "runtime-1",
                        "request_id": "request-1",
                        "scope": "read",
                    },
                )
                assert issued.status_code == 201, issued.text
                access_token = issued.json()["access_token"]

            mcp_headers = {
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
                "Authorization": "Bearer " + access_token,
            }
            async with assembly.mcp_application.router.lifespan_context(
                assembly.mcp_application
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(
                        app=assembly.mcp_application
                    ),
                    base_url="http://127.0.0.1",
                ) as client:
                    listed = await client.post(
                        "/mcp",
                        headers=mcp_headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/list",
                        },
                    )
                    assert listed.status_code == 200, listed.text
                    listed_tools = listed.json()["result"]["tools"]
                    names = {tool["name"] for tool in listed_tools}
                    assert "search_clink_services" in names
                    assert "create_core_account_setup_link" not in names
                    for tool in listed_tools:
                        assert "user_id" not in tool["inputSchema"].get(
                            "properties", {}
                        )

                    called = await client.post(
                        "/mcp",
                        headers=mcp_headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "search_clink_services",
                                "arguments": {},
                            },
                        },
                    )
                    assert called.status_code == 200, called.text
                    assert (
                        called.json()["result"]["structuredContent"]["name"]
                        == "search_clink_services"
                    )

        asyncio.run(scenario())
    finally:
        _cleanup(assembly)
        repository.engine.dispose()


@pytest.mark.parametrize(
    ("control", "token_key", "extra", "message"),
    (
        (None, TOKEN_KEY, {}, "not configured"),
        (b"short", TOKEN_KEY, {}, "invalid"),
        (CONTROL, b"k" * 31, {}, "invalid"),
        (CONTROL, CONTROL, {}, "distinct"),
        (
            CONTROL,
            TOKEN_KEY,
            {"core-internal-api-token": CONTROL},
            "reuse",
        ),
    ),
)
def test_enabled_assembly_rejects_missing_weak_or_reused_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control: bytes | None,
    token_key: bytes | None,
    extra: dict[str, bytes],
    message: str,
) -> None:
    settings = _settings(tmp_path, enabled=True)
    _set_hosted_registry_environment(
        monkeypatch,
        str(tmp_path / "hosted-wallets.json"),
    )
    store = _store(control=control, token_key=token_key, **extra)
    repository = _repository(settings)
    with pytest.raises(RuntimeError, match="[Aa]gent access"):
        try:
            assemble_node(
                settings,
                secret_store=store,
                repository=repository,
            )
        finally:
            repository.engine.dispose()
    assert CONTROL_NAME not in store.set_names
    assert KEY_NAME not in store.set_names


def test_enabled_assembly_requires_hosted_mode_and_absolute_registry_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, enabled=True)
    cases = (
        (None, str(tmp_path / "hosted-wallets.json"), "Hosted"),
        ("native", str(tmp_path / "hosted-wallets.json"), "Hosted"),
        ("hosted", "hosted-wallets.json", "absolute"),
        ("hosted", "", "absolute"),
    )
    for mode, registry_file, message in cases:
        with pytest.raises(RuntimeError, match=message):
            if mode is None:
                monkeypatch.delenv("CLINK_FACILITATOR_MODE", raising=False)
            else:
                monkeypatch.setenv("CLINK_FACILITATOR_MODE", mode)
            monkeypatch.setenv(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILE",
                registry_file,
            )
            repository = _repository(settings)
            try:
                assemble_node(
                    settings,
                    secret_store=_store(),
                    repository=repository,
                )
            finally:
                repository.engine.dispose()


def test_disabled_assembly_does_not_read_or_generate_agent_credentials(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, enabled=False)
    store = _store(control=None, token_key=None)
    repository = _repository(settings)
    assembly = assemble_node(
        settings,
        secret_store=store,
        repository=repository,
    )
    try:
        assert assembly.context.agent_access_service is None
        assert assembly.context.agent_control_token == ""
        assert CONTROL_NAME not in store.read_names
        assert KEY_NAME not in store.read_names
        assert CONTROL_NAME not in store.set_names
        assert KEY_NAME not in store.set_names
    finally:
        _cleanup(assembly)
        repository.engine.dispose()
