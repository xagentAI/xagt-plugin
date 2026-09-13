"""可选集成层：把外部生态能力接入内核，全部懒加载、零硬依赖。

- integrations.mcp：MCP Client，把外部 MCP Server 的工具注册进 ToolRegistry。
- integrations.openapi：OpenAPI 发现，把任意 OpenAPI 3 REST API 自动注册为工具。
"""
