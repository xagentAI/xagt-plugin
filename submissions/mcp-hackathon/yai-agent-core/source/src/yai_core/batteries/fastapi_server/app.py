"""FastAPI Battery：把内嵌 Core 暴露为在线 API。

内置 X-Agent AI MCP Hackathon 要求的两个验证端点：
- GET /health                                 -> {"status":"ok","commit":"<40位>"}
- GET /.well-known/xagent-verification.json   -> {"schemaVersion":1,"slug":...,"commit":...}

注意：本模块属于可选 Battery，允许依赖 fastapi/pydantic；yai_core 内核仍零硬依赖。
"""

from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - 仅在缺少可选依赖时触发
    raise ImportError(
        "FastAPI Battery 需要可选依赖：uv pip install -e '.[server]'"
    ) from exc

from yai_core.batteries.fastapi_server.ratelimit import (
    RateLimitConfig,
    SlidingWindowLimiter,
    client_ip,
)

# 限流只拦这一条 POST：三个 GET 端点（health / verification / tools）是
# X-Agent 评审硬门槛路径，任何超限状态下都必须无条件 200。
_LIMITED_METHOD = "POST"
_LIMITED_PATHS = frozenset({"/v1/agent/run"})


class RunRequest(BaseModel):
    task: str


def create_app(
    core: Any, lifespan: Any = None, *, rate_limit: RateLimitConfig | None = None
) -> FastAPI:
    app = FastAPI(title="YAI Agent Core API", version="0.1.0", lifespan=lifespan)
    commit = os.getenv("YAI_GIT_COMMIT", "dev")
    slug = os.getenv("YAI_PROJECT_SLUG", "yai-agent-core")

    # 评审期限流（opt-out via env）：None -> 从环境变量读默认策略；
    # enabled=False 时不注册中间件，零开销、零行为变化。
    config = rate_limit if rate_limit is not None else RateLimitConfig.from_env()
    if config.enabled:
        limiter = SlidingWindowLimiter(config)

        @app.middleware("http")
        async def _rate_limit_middleware(request, call_next):
            if request.method == _LIMITED_METHOD and request.url.path in _LIMITED_PATHS:
                key = client_ip(
                    request.headers.get("x-forwarded-for"),
                    request.client.host if request.client else None,
                )
                allowed, retry_after = limiter.check(key)
                if not allowed:
                    # 被限请求在中间件层直接返回：不进 core.run，一分模型钱都不花。
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "rate_limited",
                            "detail": "请求过于频繁，请稍后重试",
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
            return await call_next(request)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "commit": commit}

    @app.get("/.well-known/xagent-verification.json")
    async def verification() -> dict:
        return {"schemaVersion": 1, "slug": slug, "commit": commit}

    @app.get("/v1/tools")
    async def list_tools() -> list[dict]:
        return core.list_tools()

    @app.post("/v1/agent/run")
    async def run_agent(req: RunRequest) -> dict:
        result = await core.run(req.task)
        return {
            "strategy": result.strategy.value,
            "final_text": result.final_text,
            "events": [
                {"type": e.type.value, "data": _jsonable(e.data)} for e in result.events
            ],
        }

    return app


def _jsonable(data: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v if isinstance(v, str | int | float | bool | list | dict | None) else str(v)
    return out
