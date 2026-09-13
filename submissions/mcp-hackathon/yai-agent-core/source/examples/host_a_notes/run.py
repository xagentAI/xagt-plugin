"""宿主 A 演示：同一个 Core 自动适配笔记应用。

运行：.venv/Scripts/python.exe examples/host_a_notes/run.py [可选任务文本]
有 OPENAI_API_KEY（.env）时走真实模型，否则走离线脚本模型。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/

from runner_common import bootstrap, build_model, load_dotenv, stream  # noqa: E402

bootstrap()

from host_a_notes import capabilities  # noqa: E402
from yai_core import AgentCore  # noqa: E402

DEFAULT_TASK = "列出我的全部笔记"


async def main() -> None:
    load_dotenv()
    model, backend = build_model()
    core = AgentCore.auto(capabilities, model)
    task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
    await stream(core, task, backend)


if __name__ == "__main__":
    asyncio.run(main())
