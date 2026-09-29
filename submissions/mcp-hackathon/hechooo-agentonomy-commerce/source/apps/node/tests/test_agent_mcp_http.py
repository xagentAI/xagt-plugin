import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from mcp import types

from apps.node.clink_node.agent_access import AgentAccessService
from apps.node.clink_node.mcp_gateway import create_mcp_application
from apps.node.clink_node.storage.agent_access import AgentAccessRepository
from apps.node.clink_node.storage.postgres import PostgresNodeRepository


class Access:
    def __init__(self):
        self.revoked = False

    def authenticate(self, token):
        if token not in {"runtime-alice", "runtime-bob"} or self.revoked:
            raise ValueError("invalid runtime credential")
        return SimpleNamespace(user_id=token.removeprefix("runtime-"), scope="read")


class ScopedProxy:
    async def list_tools(self, *, principal=None):
        assert principal is not None
        return [types.Tool(name="who_am_i", inputSchema={"type": "object", "properties": {}})]

    async def call_tool(self, name, arguments, *, principal=None):
        assert principal is not None
        await asyncio.sleep(0)  # Force interleaving of distinct request identities.
        return {"user_id": principal.user_id}


def test_mcp_authentication_covers_handshake_and_keeps_request_principals_separate():
    async def scenario():
        access = Access()
        app = create_mcp_application(ScopedProxy(), access_service=access)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "who_am_i", "arguments": {}}}
                headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
                assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 401
                assert (await client.post("/mcp", json=payload, headers={**headers, "Authorization": "Bearer java-control"})).status_code == 401
                async def invoke(user):
                    response = await client.post("/mcp", json=payload, headers={**headers, "Authorization": "Bearer runtime-" + user})
                    assert response.status_code == 200, response.text
                    assert response.json()["result"]["structuredContent"]["user_id"] == user
                await asyncio.gather(invoke("alice"), invoke("bob"))
                access.revoked = True
                assert (await client.post("/mcp", json=payload, headers={**headers, "Authorization": "Bearer runtime-alice"})).status_code == 401
    asyncio.run(scenario())


def test_mcp_rejects_oversized_bodies_and_ambiguous_authorization():
    async def scenario():
        app = create_mcp_application(ScopedProxy(), access_service=Access())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                response = await client.post("/mcp", content=b"x" * 65537, headers={"Authorization": "Bearer runtime-alice"})
                assert response.status_code == 413
                response = await client.post("/mcp", content=b"{}", headers=[("Authorization", "Bearer runtime-alice"), ("Authorization", "Bearer runtime-bob")])
                assert response.status_code == 401
    asyncio.run(scenario())


def test_second_dispatch_authentication_failure_is_sanitized():
    class FailsAfterAdmission(Access):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def authenticate(self, token):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("synthetic-db-secret-from-second-auth")
            return super().authenticate(token)

    async def scenario():
        for method in ("tools/list", "tools/call"):
            app = create_mcp_application(ScopedProxy(), access_service=FailsAfterAdmission())
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
                    if method == "tools/call":
                        payload["params"] = {"name": "who_am_i", "arguments": {}}
                    response = await client.post("/mcp", json=payload, headers={
                        "Authorization": "Bearer runtime-alice", "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-03-26",
                    })
                    assert "synthetic-db-secret-from-second-auth" not in response.text
                    assert "alice" not in response.text
    asyncio.run(scenario())


def test_runtime_revoke_rejects_new_mcp_admission(tmp_path):
    repository = PostgresNodeRepository(
        f"sqlite+pysqlite:///{tmp_path / 'node.sqlite3'}"
    )
    repository.migrate()
    now = [datetime.now(UTC)]
    access = AgentAccessService(
        AgentAccessRepository(repository.engine),
        issuer="wallet-app",
        token_key=b"t" * 32,
        clock=lambda: now[0],
    )
    binding = access.register(
        subject_id="wallet-user-1",
        external_agent_id="agent-1",
    )
    credential = access.issue_credential(
        agent_id=binding.agent_id,
        runtime_id="runtime-a",
        request_id="request-a",
        scope="read",
    )
    app = create_mcp_application(ScopedProxy(), access_service=access)

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1",
            ) as client:
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                    "Authorization": "Bearer " + credential.access_token,
                }
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "who_am_i",
                        "arguments": {},
                    },
                }
                assert (
                    await client.post(
                        "/mcp",
                        json=payload,
                        headers=headers,
                    )
                ).status_code == 200
                access.revoke_runtime(
                    agent_id=binding.agent_id,
                    runtime_id="runtime-a",
                )
                assert (
                    await client.post(
                        "/mcp",
                        json=payload,
                        headers=headers,
                    )
                ).status_code == 401

    asyncio.run(scenario())
