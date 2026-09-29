"""FastAPI Battery 端点测试：离线脚本模型 + TestClient，不需要 API Key 与网络。"""

from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from yai_core import AgentCore, ModelResponse, build_spec
from yai_core.batteries.fastapi_server import create_app


class ScriptedModel:
    def __init__(self, text: str) -> None:
        self._text = text

    async def achat(self, messages, tools=None, *, tier="standard"):
        return ModelResponse(content=self._text)


def list_notes() -> list:
    """列出全部笔记。"""
    return [{"id": 1, "title": "Core 骨架"}]


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    monkeypatch.setenv("YAI_PROJECT_SLUG", "yai-test")
    core = AgentCore(ScriptedModel("你好，我是内嵌助手。"))
    core.register_tools([build_spec(list_notes)])
    return TestClient(create_app(core))


def test_health(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["commit"]) == 40  # X-Agent 硬门槛：40 位 commit


def test_xagent_verification(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/.well-known/xagent-verification.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"schemaVersion": 1, "slug": "yai-test", "commit": "0" * 40}


def test_tools_endpoint_lists_discovered_capabilities(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/v1/tools")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "list_notes" in names


def test_agent_run_endpoint_returns_events_and_text(monkeypatch) -> None:
    resp = _client(monkeypatch).post("/v1/agent/run", json={"task": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy"] == "direct"
    assert body["final_text"].startswith("你好")
    event_types = [e["type"] for e in body["events"]]
    assert "strategy_selected" in event_types
    assert event_types[-1] == "done"


def test_lifespan_attaches_mcp_tools(monkeypatch) -> None:
    """lifespan 挂载的外部 MCP 工具要出现在 /v1/tools（线上部署形态的离线回放）。"""
    pytest.importorskip("mcp")
    from mcp.server import MCPServer

    from yai_core.integrations.mcp import McpServerConfig, attach_mcp_tools

    monkeypatch.setenv("YAI_GIT_COMMIT", "0" * 40)
    monkeypatch.setenv("YAI_PROJECT_SLUG", "yai-test")

    server = MCPServer("TestWiki")

    @server.tool()
    def ask_question(repoName: str, question: str) -> str:
        """Ask a question about a repository."""
        return f"wiki answer for {repoName}: {question}"

    core = AgentCore(ScriptedModel("ok"))
    core.register_tools([build_spec(list_notes)])

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        bridge = await attach_mcp_tools(
            core.registry, McpServerConfig(alias="wiki", server=server)
        )
        try:
            yield
        finally:
            await bridge.aclose()

    with TestClient(create_app(core, lifespan=lifespan)) as client:
        tools = {t["name"]: t for t in client.get("/v1/tools").json()}
        assert "list_notes" in tools  # native 工具仍在
        assert tools["ask_question"]["source"] == "mcp"  # MCP 工具同构挂载
