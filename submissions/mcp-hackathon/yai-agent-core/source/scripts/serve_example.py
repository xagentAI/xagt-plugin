"""在线 API 启动示例（X-Agent 部署形态）。

本地直跑（宿主机统一用 8001，容器内才是 8000）：
    uv run uvicorn scripts.serve_example:app --host 127.0.0.1 --port 8001
容器化：
    docker compose up --build   # 容器内监听 8000，宿主机映射 8001:8000
环境变量（写在项目根 .env 即可，脚本启动时自动加载）：
    OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL   真实模型（缺省走离线演示模型）
    YAI_GIT_COMMIT=<40位 commit>  YAI_PROJECT_SLUG=<slug>   X-Agent 验证端点
    commit 解析顺序：YAI_GIT_COMMIT → 平台注入（如 RENDER_GIT_COMMIT）→ 当前 git HEAD → dev
    （只接受完整 40 位哈希，镜像默认值 dev 等占位会被跳过）
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path

_SHA40 = re.compile(r"[0-9a-f]{40}")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from host_a_notes import capabilities  # noqa: E402
from runner_common import build_model, load_dotenv  # noqa: E402
from yai_core import AgentCore  # noqa: E402
from yai_core.batteries.fastapi_server import RateLimitConfig, create_app  # noqa: E402
from yai_core.integrations.openapi import attach_openapi_tools  # noqa: E402
from yai_core.integrations.openapi import (  # noqa: E402
    config_from_env as openapi_config_from_env,
)
from yai_core.memory import InMemoryStore, SqliteStore, retention_from_env  # noqa: E402


def _git_commit() -> str:
    """读取当前 git HEAD 的完整 40 位 commit；非 git 环境回退 dev。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "dev"


def _valid_sha(value: str | None) -> str | None:
    """只接受完整 40 位小写哈希；dev、空串、短 SHA 等占位值一律视为无效。"""
    if value and _SHA40.fullmatch(value.strip()):
        return value.strip()
    return None


load_dotenv()
# commit 解析链：YAI_GIT_COMMIT（构建期固化）→ 平台注入（Render 为 RENDER_GIT_COMMIT）
# → 当前 git HEAD（本地联调）→ dev。
# 注意镜像 ENV 里烤着默认值 dev（非合法哈希），必须跳过它，平台注入的真实 SHA 才能生效。
os.environ["YAI_GIT_COMMIT"] = (
    _valid_sha(os.environ.get("YAI_GIT_COMMIT"))
    or _valid_sha(os.environ.get("RENDER_GIT_COMMIT"))
    or _git_commit()
)

_model, _backend = build_model()
print(f"serve_example 后端：{_backend}")
print(f"验证端点 commit：{os.environ['YAI_GIT_COMMIT']}")

# llm_router=True：先让模型做一次轻量分类（strategy/tier/reason），
# 分类失败/超时自动回退确定性规则，事件流里带 source=llm|rules 可审计。
# 持久化记忆 opt-in：设置 YAI_DB_PATH 才落 SQLite；不设置时用进程内内存。
# 历史保留策略 opt-in：YAI_HISTORY_MAX_MESSAGES / YAI_HISTORY_TTL_SECONDS；
# env 只在这一层解析一次（非法值只 warning 一次），两种 Store 对等生效。
_retention = retention_from_env()
_sqlite_store = SqliteStore.from_env(retention=_retention)
if _sqlite_store is not None:
    _store = _sqlite_store
else:
    _store = InMemoryStore(max_messages=_retention[0], ttl_seconds=_retention[1])
if _retention != (None, None):
    print(
        f"历史保留策略：max_messages={_retention[0]}，ttl_seconds={_retention[1]}"
        "（opt-in，按轮对齐裁剪；SQLite 构造时已自动 prune 一次）"
    )
core = AgentCore.auto(capabilities, _model, llm_router=True, memory=_store)


@contextlib.asynccontextmanager
async def app_lifespan(_app):
    """启停生命周期：挂载外部 MCP；停机时断开连接并关闭记忆存储。

    MCP 与 OpenAPI 两个集成相互独立：缺 extra / 外部服务不可达 / 描述拉取失败
    都只告警、不阻断启动。本地 native 工具与验证端点必须始终可用。
    """
    bridges = []
    try:
        # MCP 与 OpenAPI 各自独立：任一集成缺依赖 / 挂载失败都只告警，不影响另一个与本地工具。
        try:
            from yai_core.integrations.mcp import attach_mcp_tools, config_from_env
        except ImportError as exc:  # 没装 [mcp] extra 是合法部署形态
            print(f"[serve_example] 未安装 [mcp] extra，跳过 MCP 挂载：{exc}")
        else:
            cfg = config_from_env(alias="remote")
            if cfg is not None:
                try:
                    bridge = await attach_mcp_tools(core.registry, cfg)
                    bridges.append(bridge)
                    names = [s.name for s in bridge.specs]
                    print(f"MCP 已挂载（{cfg.alias}）：{names}")
                except Exception as exc:  # noqa: BLE001 - 外部依赖不可用是运行时常态
                    print(f"[警告] 外部 MCP 挂载失败，仅提供本地工具：{type(exc).__name__}: {exc}")

        # OpenAPI 发现（opt-in）：配置 OPENAPI_SPEC_URL/PATH 才挂载。
        # 在线演示服务强制只读：只注册 GET/HEAD，写操作绝不暴露到公网演示端点。
        openapi_config = openapi_config_from_env(alias="rest")
        if openapi_config is not None:
            openapi_config.read_only = True
            try:
                openapi_bridge = await attach_openapi_tools(core.registry, openapi_config)
                bridges.append(openapi_bridge)
                print(
                    f"[serve_example] OpenAPI 已挂载：{openapi_config.url or openapi_config.path}，"
                    f"工具 {len(openapi_bridge.specs)} 个（read_only=True）"
                )
                for note in openapi_bridge.notes:
                    print(f"  note: {note}")
            except ImportError as exc:
                print(f"[serve_example] 未安装 [openapi] extra，跳过 OpenAPI 挂载：{exc}")
            except Exception as exc:  # OpenAPI 故障不拖垮本地服务
                print(f"[serve_example] OpenAPI 挂载失败，降级跳过：{exc}")
        yield
    finally:
        for bridge in bridges:
            with contextlib.suppress(Exception):
                await bridge.aclose()
        # close() 不是 MemoryStore 契约方法：探测式调用，InMemoryStore 没有就跳过。
        close_store = getattr(_store, "close", None)
        if close_store is not None:
            close_store()


# 评审期限流（默认开启）：显式 from_env 并打印一行策略，便于部署核对。
_rate_limit = RateLimitConfig.from_env()
print(
    f"限流策略：enabled={_rate_limit.enabled}，"
    f"per_minute={_rate_limit.per_minute}，window_seconds={_rate_limit.window_seconds}"
    "（仅 POST /v1/agent/run；GET 验证端点不受限）"
)
app = create_app(core, lifespan=app_lifespan, rate_limit=_rate_limit)
