"""OpenAPI 发现集成：把任意符合 OpenAPI 3 的 REST API 自动注册为 Core 工具。

与 MCP 桥同构：懒加载 httpx/pyyaml（[openapi] 可选依赖），发现结果统一成
ToolSpec(source="openapi")，Router / Loop / Executor 感知不到工具来自 REST
（alias 仅用于日志与 notes）。
"""

from yai_core.integrations.openapi.client import (
    OpenApiToolBridge,
    attach_openapi_tools,
)
from yai_core.integrations.openapi.discovery import OperationPlan, plan_operations
from yai_core.integrations.openapi.spec import (
    OpenApiSpecConfig,
    config_from_env,
    load_spec,
    resolve_refs,
)

__all__ = [
    "OpenApiSpecConfig",
    "OpenApiToolBridge",
    "OperationPlan",
    "attach_openapi_tools",
    "config_from_env",
    "load_spec",
    "plan_operations",
    "resolve_refs",
]
