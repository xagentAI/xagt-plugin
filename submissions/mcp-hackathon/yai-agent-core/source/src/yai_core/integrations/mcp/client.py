"""MCP Client 桥接层：外部 MCP Server 工具 → ToolRegistry 里的 ToolSpec。

设计要点（对应内核红线）：
1. 顶层不 import mcp：内核本体零第三方硬依赖，mcp 是可选依赖（pyproject 的
   [mcp] extra），只在 connect() 内部懒加载；没装时给出可操作的报错。
2. 工具同构：MCP 工具被转换成 ToolSpec(source="mcp")，handler 是一个异步闭包。
   Router / Loop / Executor 完全感知不到工具在本机还是远端 MCP Server 上——
   它们只面对统一的 ToolSpec，这就是"Native 与 MCP 统一"的落点。
3. 结果归一：MCP CallToolResult 的 content 文本块 / structured_content /
   is_error 三种形态在这里被翻译成 Executor 熟悉的"返回值或抛异常"。
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from typing import Any

from yai_core.tools.schema import EMPTY_OBJECT_SCHEMA, sanitize_schema
from yai_core.types import ToolSpec

# 兼容别名：本模块下方代码沿用旧名 _EMPTY_SCHEMA，保持零改动。
_EMPTY_SCHEMA = EMPTY_OBJECT_SCHEMA


@dataclass
class McpServerConfig:
    """一个 MCP Server 的连接配置，url / command / server 三选一。

    - url：Streamable HTTP（如 https://example.com/mcp），部署形态最常用；
    - command(+args/env)：拉起本地 stdio 子进程作为 MCP Server；
    - server：已构造好的 MCPServer 实例，内存直连（主要给离线测试用）；
    - prefix：工具名前缀（如 "demo__"），多个 Server 工具重名时去重；默认不加。
    """

    alias: str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    prefix: str = ""
    server: Any | None = None


def config_from_env(
    *,
    alias: str = "remote",
    url_env: str = "MCP_SERVER_URL",
    command_env: str = "MCP_SERVER_COMMAND",
    env: dict[str, str] | None = None,
) -> McpServerConfig | None:
    """从环境变量构造 MCP Server 配置；两个变量都没设置时返回 None。

    - <url_env>：Streamable HTTP URL，部署形态最常用（如线上挂公共 MCP Server）；
    - <command_env>：stdio 启动命令（空格分词，Windows 按系统规则切分）。
    让"是否接外部 MCP、接哪个"成为部署期配置，代码不用改。
    """
    environ = os.environ if env is None else env
    url = environ.get(url_env)
    if url:
        return McpServerConfig(alias=alias, url=url)
    command_line = environ.get(command_env)
    if command_line:
        parts = shlex.split(command_line, posix=(os.name != "nt"))
        if parts:
            return McpServerConfig(alias=alias, command=parts[0], args=parts[1:])
    return None


def _flatten_call_result(result: Any) -> Any:
    """把 MCP CallToolResult 翻译成工具返回值（可被 json.dumps 序列化）。

    顺序：is_error → 抛异常（交给 ToolExecutor 走失败回灌，模型能看到错误）；
    否则优先 content 里的文本块（MCP 面向 LLM 的规范输出）；
    没有文本再回退 structured_content；都没有返回空字符串。
    """
    content = getattr(result, "content", []) or []
    if getattr(result, "is_error", False):
        texts = [b.text for b in content if getattr(b, "text", None)]
        raise RuntimeError("; ".join(texts) or "MCP 工具返回错误")
    texts = [b.text for b in content if getattr(b, "text", None)]
    if texts:
        return "\n".join(texts)
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return ""


class McpToolBridge:
    """一个 MCP Server 连接 ↔ 注册到 ToolRegistry 的一组 ToolSpec。

    用法::

        bridge = McpToolBridge(McpServerConfig(alias="demo", url="https://x/mcp"))
        specs = await bridge.connect()   # 建连 + list_tools + 生成 ToolSpec
        core.register_tools(specs)
        ...
        await bridge.aclose()

    也支持 async with 自动关连接。
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._client: Any = None
        self._specs: list[ToolSpec] = []

    async def __aenter__(self) -> McpToolBridge:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def connect(self) -> list[ToolSpec]:
        # 懒加载：只有真正使用 MCP 集成时才要求安装 mcp 包。
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise ImportError(
                "MCP 集成需要可选依赖：uv sync --extra mcp（或 pip install 'yai-agent-core[mcp]'）"
            ) from exc

        self._client = Client(self._build_target(StdioServerParameters))
        await self._client.__aenter__()
        listed = await self._client.list_tools()
        self._specs = [self._to_spec(tool) for tool in listed.tools]
        return self._specs

    def _build_target(self, stdio_params_cls: Any) -> Any:
        """把配置翻译成 mcp.Client 接受的三种 target：URL / stdio 参数 / Server 实例。"""
        c = self.config
        chosen = sum(x is not None for x in (c.url, c.command, c.server))
        if chosen != 1:
            raise ValueError("McpServerConfig 必须且只能提供 url / command / server 之一")
        if c.url is not None:
            return c.url
        if c.server is not None:
            return c.server
        return stdio_params_cls(command=c.command, args=c.args, env=c.env)

    def _to_spec(self, tool: Any) -> ToolSpec:
        """一个 MCP Tool 描述 → 一个统一 ToolSpec。"""
        remote_name = tool.name
        local_name = f"{self.config.prefix}{remote_name}"
        schema = sanitize_schema(getattr(tool, "input_schema", None)) or dict(_EMPTY_SCHEMA)

        async def handler(**kwargs: Any) -> Any:
            # 闭包按值捕获 remote_name：本地注册名可能带前缀，远端只认工具原名。
            result = await self._client.call_tool(remote_name, kwargs)
            return _flatten_call_result(result)

        return ToolSpec(
            name=local_name,
            description=getattr(tool, "description", "") or remote_name,
            input_schema=schema,
            handler=handler,
            source="mcp",
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    @property
    def specs(self) -> list[ToolSpec]:
        """connect 之后可用：本次从该 Server 注册的工具规格（副本）。"""
        return list(self._specs)


async def attach_mcp_tools(registry: Any, config: McpServerConfig) -> McpToolBridge:
    """便捷函数：连接 MCP Server 并把工具直接注册进 ToolRegistry，返回 bridge 供关闭。"""
    bridge = McpToolBridge(config)
    specs = await bridge.connect()
    registry.register_many(specs)
    return bridge
