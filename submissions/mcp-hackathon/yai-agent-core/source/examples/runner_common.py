"""三个示例宿主共用的运行脚手架：路径引导、.env 加载、模型选择、事件流打印。

各宿主的 run.py 只负责声明自己的 capabilities 与默认任务，不重复这些样板。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bootstrap() -> None:
    """把 src/ 与 examples/ 放进 sys.path，使脚本可直接运行、无需安装。"""
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "examples"))


def load_dotenv() -> None:
    """极简 .env 加载器：只认 KEY=VALUE，不覆盖已存在的环境变量，内核保持零依赖。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_model():
    """有 Key 走 OpenAI 兼容真实模型（DeepSeek 等），否则回退离线脚本模型。"""
    if os.getenv("OPENAI_API_KEY"):
        from yai_core import OpenAICompatProvider

        model = OpenAICompatProvider()
        label = f"真实模型 {os.getenv('OPENAI_BASE_URL', '(SDK默认)')} :: {model.model}"
        return model, label
    from demo_model import OfflineScriptedModel

    return OfflineScriptedModel(), "离线脚本模型（未检测到 OPENAI_API_KEY）"


async def stream(core, task: str, backend: str) -> None:
    """跑任务并把 Observer 事件流按人类可读方式打印出来。"""
    from yai_core import EventType

    print("=" * 60)
    print("后端：", backend)
    print("自动发现的工具：", [t["name"] for t in core.list_tools()])
    print("任务：", task)
    print("-" * 60)

    async for event in core.astream(task):
        if event.type == EventType.STRATEGY_SELECTED:
            print(f"[路由] 选定策略：{event.data['strategy']}")
        elif event.type == EventType.PLAN_CREATED:
            print("[计划] 拆出步骤：")
            for i, step in enumerate(event.data["steps"], 1):
                print(f"   {i}. {step}")
        elif event.type == EventType.TOOL_CALL:
            print(f"[工具] 调用 {event.data['tool']}({event.data['arguments']})")
        elif event.type == EventType.TOOL_RESULT:
            preview = event.data.get("preview") or event.data.get("error", "")
            print(f"[观察] 返回：{str(preview)[:120]}")
        elif event.type == EventType.PERMISSION_ASKED:
            print(f"[权限] 请求确认：{event.data['tool']}({event.data['arguments']})")
        elif event.type == EventType.CLARIFY_REQUESTED:
            print(f"[反问] {event.data['question']}")
        elif event.type == EventType.MODEL_MESSAGE:
            print(f"[模型] {event.data['text']}")
        elif event.type == EventType.ERROR:
            print(f"[错误] {event.data['error']}")
        elif event.type == EventType.DONE:
            print("-" * 60)
            print(f"完成（策略 {event.data['strategy']}）")
            print("最终结果：", event.data["final_text"])
