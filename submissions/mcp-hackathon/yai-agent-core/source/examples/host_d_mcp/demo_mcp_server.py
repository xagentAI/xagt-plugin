"""host_d 配套的本地 stdio MCP Server（演示用，零网络、零账号）。

被 run.py 以子进程方式拉起；也可以手动运行观察：
    .venv/Scripts/python.exe examples/host_d_mcp/demo_mcp_server.py
（stdio 服务通过标准输入输出通信，直接运行会安静等待客户端，属正常现象。）
"""

from __future__ import annotations

from mcp.server import MCPServer

mcp = MCPServer("YAI-DemoTools")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@mcp.tool()
def weather(city: str) -> str:
    """Get a demo weather report for a city (mock data, not real)."""
    return f"{city} 今天晴，26℃，东北风 2 级（演示数据，非真实天气）。"


if __name__ == "__main__":
    # MCPServer.run() 默认 stdio 传输：把进程的 stdin/stdout 变成 MCP 通道。
    mcp.run()
