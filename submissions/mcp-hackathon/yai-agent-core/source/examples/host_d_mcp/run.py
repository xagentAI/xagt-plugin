"""宿主 D 演示：Core 通过 MCP Client 接入外部 MCP Server 的工具。

默认以 stdio 子进程方式拉起同目录 demo_mcp_server.py（离线可跑）；
也可以用环境变量改接任意 MCP Server：
    MCP_SERVER_URL=http://127.0.0.1:8000/mcp   # Streamable HTTP
    MCP_SERVER_COMMAND="uv run server.py"       # stdio 命令（空格分词）

运行：.venv/Scripts/python.exe examples/host_d_mcp/run.py [可选任务文本]
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/

from runner_common import bootstrap, build_model, load_dotenv, stream  # noqa: E402

bootstrap()

from yai_core import AgentCore, build_spec  # noqa: E402

DEFAULT_TASK = "用 MCP 工具算一下 17 加 25，再查一下湛江的天气，最后用一句话汇总"


def host_label() -> str:
    """host_d 自己的本地工具：演示 Native 与 MCP 工具在同一注册表共存。"""
    return "host_d（本地宿主）在线"


def build_config():
    """按环境变量构造 McpServerConfig；缺省回落到自带的本地 stdio 演示 Server。"""
    from yai_core.integrations.mcp import McpServerConfig

    url = os.getenv("MCP_SERVER_URL")
    if url:
        return McpServerConfig(alias="remote", url=url)
    command_line = os.getenv("MCP_SERVER_COMMAND")
    if command_line:
        parts = shlex.split(command_line, posix=(os.name != "nt"))
        return McpServerConfig(alias="stdio", command=parts[0], args=parts[1:])
    demo_server = Path(__file__).with_name("demo_mcp_server.py")
    return McpServerConfig(
        alias="demo-stdio",
        command=sys.executable,
        args=[str(demo_server)],
    )


async def main() -> None:
    load_dotenv()
    model, backend = build_model()
    core = AgentCore(model)
    core.register_tools([build_spec(host_label)])

    try:
        from yai_core.integrations.mcp import attach_mcp_tools
    except ImportError as exc:
        print(f"[缺少依赖] {exc}")
        return

    bridge = await attach_mcp_tools(core.registry, build_config())
    try:
        task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
        await stream(core, task, backend)
    finally:
        await bridge.aclose()  # 断开 stdio 子进程 / HTTP 连接，不留后台进程


if __name__ == "__main__":
    asyncio.run(main())
