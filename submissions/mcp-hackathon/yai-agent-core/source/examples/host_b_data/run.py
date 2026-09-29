"""宿主 B 演示：同一份 Core、零修改，自动适配销售数据应用。

运行：.venv/Scripts/python.exe examples/host_b_data/run.py [可选任务文本]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/

from runner_common import bootstrap, build_model, load_dotenv, stream  # noqa: E402

bootstrap()

from host_b_data import capabilities  # noqa: E402
from yai_core import AgentCore  # noqa: E402

DEFAULT_TASK = "先筛选硬件品类，然后统计销售额并整理成报告"


async def main() -> None:
    load_dotenv()
    model, backend = build_model()
    core = AgentCore.auto(capabilities, model)
    task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
    await stream(core, task, backend)


if __name__ == "__main__":
    asyncio.run(main())
