"""YAI Agent Core —— 进程内嵌入式自适应 Agent 内核。

宿主软件只声明能力，Core 自动发现、自适应规划与执行。
"""

from yai_core.core import AgentCore
from yai_core.discovery import build_spec, discover
from yai_core.kernel import AdaptiveRouter, AgentLoop, Context, RouteDecision
from yai_core.llm.openai_compat import OpenAICompatProvider
from yai_core.tools import ToolExecutor, ToolRegistry
from yai_core.types import (
    AgentEvent,
    ChatMessage,
    EventType,
    ModelResponse,
    RunResult,
    Strategy,
    ToolCallRequest,
    ToolSpec,
)

__version__ = "0.1.0"

__all__ = [
    "AgentCore",
    "AdaptiveRouter",
    "RouteDecision",
    "AgentLoop",
    "Context",
    "ToolRegistry",
    "ToolExecutor",
    "OpenAICompatProvider",
    "build_spec",
    "discover",
    "AgentEvent",
    "ChatMessage",
    "EventType",
    "ModelResponse",
    "RunResult",
    "Strategy",
    "ToolCallRequest",
    "ToolSpec",
    "__version__",
]
