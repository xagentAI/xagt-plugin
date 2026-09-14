"""MCP Client 桥接层测试：内存直连 MCPServer，全程不起子进程、不触网。

未安装 mcp 可选依赖时整文件自动跳过（内核本体仍保持零依赖可测）。
"""

import ast
import json
import pathlib

import pytest

pytest.importorskip("mcp")  # 没装 [mcp] extra 的环境（如最小 CI）跳过本文件

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from yai_core.channels import CollectChannel  # noqa: E402
from yai_core.integrations.mcp import (  # noqa: E402
    McpServerConfig,
    McpToolBridge,
    attach_mcp_tools,
    config_from_env,
    sanitize_schema,
)
from yai_core.policy import AllowlistPolicy  # noqa: E402
from yai_core.tools import ToolExecutor, ToolRegistry  # noqa: E402


class Book(BaseModel):
    title: str
    year: int


def build_server() -> MCPServer:
    """构造内存 MCP Server：一个文本工具、一个结构化工具、一个必错工具。"""
    server = MCPServer("TestShop")

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the text."""
        return f"echo: {text}"

    @server.tool()
    def make_book(title: str, year: int = 2026) -> Book:
        """Make a structured book."""
        return Book(title=title, year=year)

    @server.tool()
    def boom() -> str:
        """Always fails."""
        raise ToolError("boom-message")

    return server


def test_connect_registers_mcp_tools() -> None:
    import asyncio

    async def scenario() -> None:
        bridge = McpToolBridge(McpServerConfig(alias="t", server=build_server()))
        specs = await bridge.connect()
        assert {s.name for s in specs} == {"echo", "make_book", "boom"}
        assert all(s.source == "mcp" for s in specs)
        # SDK 自动生成的 schema 带 title 私有键，必须被清洗掉
        echo = next(s for s in specs if s.name == "echo")
        assert "title" not in echo.input_schema
        assert echo.input_schema["required"] == ["text"]
        registry = ToolRegistry()
        registry.register_many(specs)
        assert registry.has("echo")
        await bridge.aclose()

    asyncio.run(scenario())


def test_prefix_namespacing_keeps_remote_name() -> None:
    """本地名加前缀防重名，但闭包内部仍调用远端原名。"""
    import asyncio

    async def scenario() -> None:
        cfg = McpServerConfig(alias="t", server=build_server(), prefix="demo__")
        async with McpToolBridge(cfg) as bridge:
            registry = ToolRegistry()
            registry.register_many(bridge.specs)
            assert registry.has("demo__echo")
            spec = registry.get("demo__echo")
            text = await spec.handler(text="hi")
            assert text == "echo: hi"

    asyncio.run(scenario())


def test_handler_text_and_structured_results() -> None:
    import asyncio

    async def scenario() -> None:
        async with McpToolBridge(McpServerConfig(alias="t", server=build_server())) as b:
            specs = {s.name: s for s in b.specs}
            assert await specs["echo"].handler(text="hi") == "echo: hi"
            book_text = await specs["make_book"].handler(title="Dune", year=1965)
            assert "Dune" in book_text and "1965" in book_text

    asyncio.run(scenario())


def test_error_tool_raises_for_executor() -> None:
    """MCP is_error 结果必须翻译成异常，由 Executor 统一走失败回灌。"""
    import asyncio

    async def scenario() -> None:
        async with McpToolBridge(McpServerConfig(alias="t", server=build_server())) as b:
            boom = next(s for s in b.specs if s.name == "boom")
            with pytest.raises(RuntimeError, match="boom-message"):
                await boom.handler()

    asyncio.run(scenario())


def test_executor_runs_mcp_tools_end_to_end() -> None:
    """MCP 工具经过 ToolExecutor 与 Native 工具行为一致（含权限/事件/错误）。"""
    import asyncio

    async def scenario() -> None:
        registry = ToolRegistry()
        bridge = await attach_mcp_tools(
            registry, McpServerConfig(alias="t", server=build_server())
        )
        executor = ToolExecutor(registry, AllowlistPolicy(mode="allow_all"), CollectChannel())

        events, ok, text = await executor.execute("echo", {"text": "hi"})
        assert ok is True
        # Executor 对一切返回值统一 json.dumps，字符串结果即 JSON 字符串
        assert json.loads(text) == "echo: hi"
        assert events[0].data["tool"] == "echo"

        events2, ok2, text2 = await executor.execute("boom", {})
        assert ok2 is False
        assert "boom-message" in text2
        assert events2[-1].data["ok"] is False

        await bridge.aclose()

    asyncio.run(scenario())


def test_config_requires_exactly_one_target() -> None:
    import asyncio

    async def scenario() -> None:
        with pytest.raises(ValueError, match="之一"):
            await McpToolBridge(McpServerConfig(alias="t")).connect()
        with pytest.raises(ValueError, match="之一"):
            await McpToolBridge(
                McpServerConfig(alias="t", url="http://x/mcp", server=build_server())
            ).connect()

    asyncio.run(scenario())


def test_sanitize_schema() -> None:
    raw = {
        "title": "echoArguments",
        "type": "object",
        "properties": {"text": {"title": "Text", "type": "string"}},
        "required": ["text"],
    }
    clean = sanitize_schema(raw)
    assert "title" not in clean and "title" not in clean["properties"]["text"]
    assert clean["type"] == "object"
    assert sanitize_schema({}) == {"type": "object", "properties": {}}
    assert sanitize_schema(["a", 1]) == ["a", 1]


def test_config_from_env() -> None:
    """部署期通过环境变量决定接哪个 MCP Server；未配置时返回 None（不报错）。"""
    assert config_from_env(env={}) is None

    url_cfg = config_from_env(alias="deepwiki", env={"MCP_SERVER_URL": "https://x/mcp"})
    assert url_cfg is not None and url_cfg.url == "https://x/mcp" and url_cfg.alias == "deepwiki"

    cmd_cfg = config_from_env(env={"MCP_SERVER_COMMAND": "python server.py --stdio"})
    assert cmd_cfg is not None and cmd_cfg.command == "python"
    assert cmd_cfg.args == ["server.py", "--stdio"]


def test_no_toplevel_mcp_import_keeps_kernel_dependency_free() -> None:
    """红线：client.py 顶层不允许 import mcp，mcp 只能在函数体内懒加载。"""
    client_path = pathlib.Path(__file__).parents[1] / "src" / "yai_core" / (
        "integrations/mcp/client.py"
    )
    tree = ast.parse(client_path.read_text(encoding="utf-8"))
    for node in tree.body:  # 只检查模块顶层语句
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("mcp") for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith("mcp")
