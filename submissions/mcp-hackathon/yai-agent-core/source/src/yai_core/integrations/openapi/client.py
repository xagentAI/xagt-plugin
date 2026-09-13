"""执行阶段：OpenAPI 工具桥。

一个 OpenAPI 描述 = 一个桥：connect() 载入/展开/发现并注册 ToolSpec，
每个工具是一个闭包 handler，负责鉴权、填路径、拼 query、发 body、归一响应。
httpx 只在 connect() 内懒加载；测试通过 transport= 注入 httpx.MockTransport，全程离线。
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from yai_core.integrations.openapi.discovery import OperationPlan, plan_operations
from yai_core.integrations.openapi.spec import (
    OpenApiSpecConfig,
    load_spec,
    resolve_base_url,
    resolve_refs,
)
from yai_core.types import ToolSpec

_SUPPORTED_SECURITY = {"http", "apiKey"}


class OpenApiToolBridge:
    """发现并执行一个 OpenAPI 描述暴露的 REST 操作。"""

    def __init__(self, config: OpenApiSpecConfig, *, transport: Any = None) -> None:
        self.config = config
        self._transport = transport  # 测试注入 httpx.MockTransport；生产为 None
        self._client: Any = None
        self._specs: list[ToolSpec] = []
        self._notes: list[str] = []
        self._spec: dict | None = None
        self._plans: list[OperationPlan] = []
        self._base_url: str | None = None
        self._security_schemes: dict[str, dict] = {}

    @property
    def specs(self) -> list[ToolSpec]:
        return list(self._specs)

    @property
    def notes(self) -> list[str]:
        return list(self._notes)

    async def connect(self) -> list[ToolSpec]:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "OpenAPI 集成需要可选依赖：uv sync --extra openapi"
                "（或 pip install 'yai-agent-core[openapi]'）"
            ) from exc

        raw = load_spec(self.config, transport=self._transport)
        spec, ref_notes = resolve_refs(raw)
        self._notes.extend(ref_notes)
        plans, plan_notes = plan_operations(spec, self.config)
        self._notes.extend(plan_notes)

        self._spec = spec
        self._plans = plans
        self._base_url = resolve_base_url(self.config, spec)
        self._security_schemes = (
            (spec.get("components") or {}).get("securitySchemes") or {}
        )
        self._audit_security(plans)

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            transport=self._transport,
            headers=dict(self.config.extra_headers),
        )
        self._specs = [self._plan_to_spec(plan) for plan in plans]
        return self.specs

    def _audit_security(self, plans: list[OperationPlan]) -> None:
        """注册期审计：oauth2/basic/mutualTLS 暂不支持，记 note 但不阻断发现。"""
        seen: set[str] = set()
        for plan in plans:
            for requirement in plan.security:
                for scheme_name in requirement:
                    scheme = self._security_schemes.get(scheme_name)
                    if scheme is None:
                        continue
                    kind = scheme.get("type")
                    if kind not in _SUPPORTED_SECURITY and scheme_name not in seen:
                        seen.add(scheme_name)
                        self._notes.append(
                            f"鉴权方案 {scheme_name}（{kind}）暂不支持，"
                            "相关工具将按匿名请求发送"
                        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> OpenApiToolBridge:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---------- 执行期小步骤（每个都可独立推理） ----------

    def _token_from_env(self) -> str | None:
        env_name = self.config.auth_token_env
        if not env_name:
            return None
        raw = (os.environ.get(env_name) or "").strip()
        return raw or None

    async def _auth_for(self, plan: OperationPlan) -> tuple[dict, dict]:
        """按 security 要求挑第一个能满足的方案；都不满足且不允许匿名 → 调用期报错。"""
        headers: dict[str, str] = {}
        query: dict[str, str] = {}
        requirements = plan.security or []
        allows_anonymous = any(not requirement for requirement in requirements)
        for requirement in requirements:
            for scheme_name, _scopes in requirement.items():
                scheme = self._security_schemes.get(scheme_name)
                if scheme is None:
                    continue
                kind = scheme.get("type")
                if kind == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
                    token = self._token_from_env()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                        return headers, query
                elif kind == "apiKey":
                    token = self._token_from_env()
                    if token:
                        where = scheme.get("in")
                        key_name = scheme.get("name", "X-Api-Key")
                        if where == "header":
                            headers[key_name] = token
                        elif where == "query":
                            query[key_name] = token
                        return headers, query
        if requirements and not allows_anonymous:
            raise RuntimeError(
                f"工具 {plan.name} 需要鉴权，但环境变量 {self.config.auth_token_env} 未设置令牌"
            )
        return headers, query

    def _build_path(self, plan: OperationPlan, kwargs: dict) -> str:
        path = plan.path_template
        for name in plan.path_params:
            if name not in kwargs:
                raise RuntimeError(f"调用 {plan.name} 缺少路径参数：{name}")
            # safe=""：路径段里的 / 也要编码，避免参数值破坏路径结构。
            path = path.replace("{" + name + "}", quote(str(kwargs[name]), safe=""))
        return path

    def _build_query(self, plan: OperationPlan, kwargs: dict) -> dict:
        query: dict[str, Any] = {}
        for name in plan.query_params:
            if name in kwargs and kwargs[name] is not None:
                value = kwargs[name]
                if isinstance(value, bool):
                    value = "true" if value else "false"  # httpx 默认会渲染成 True/False
                query[name] = value  # list 值由 httpx 展开成重复键
        return query

    def _build_body(self, plan: OperationPlan, kwargs: dict) -> Any:
        if not plan.body_fields:
            return None
        if plan.body_wrapped:
            return kwargs.get("body")
        return {name: kwargs[name] for name in plan.body_fields if name in kwargs}

    def _plan_to_spec(self, plan: OperationPlan) -> ToolSpec:
        async def handler(**kwargs: Any) -> Any:
            if self._client is None:
                raise RuntimeError("OpenApiToolBridge 尚未 connect()")
            if not self._base_url:
                raise RuntimeError(
                    "spec 未声明 servers[0].url 且未配置 base_url_override，无法调用工具"
                )
            auth_headers, auth_query = await self._auth_for(plan)
            path = self._build_path(plan, kwargs)
            query = self._build_query(plan, kwargs)
            query.update(auth_query)
            body = self._build_body(plan, kwargs)

            url = self._base_url.rstrip("/") + path
            request_headers = dict(auth_headers)
            if body is not None:
                request_headers.setdefault("Content-Type", "application/json")

            resp = await self._client.request(
                plan.method,
                url,
                params=query or None,
                json=body if body is not None else None,
                headers=request_headers,
            )
            if resp.status_code == 204:
                return ""
            if resp.status_code < 200 or resp.status_code >= 300:
                # 非 2xx 走工具错误通道（Executor 捕获 RuntimeError → tool_result 失败事件）。
                raise RuntimeError(
                    f"HTTP {resp.status_code} from {plan.method} {path}: {resp.text[:500]}"
                )
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type.lower():
                return resp.json()
            text = resp.text
            if len(text) > self.config.max_result_chars:
                return text[: self.config.max_result_chars] + "…[truncated]"
            return text

        return ToolSpec(
            name=plan.name,
            description=plan.description,
            input_schema=plan.input_schema,
            handler=handler,
            # 来源可枚举，与 types.ToolSpec.source 的 Literal 契约对齐；alias 只用于日志/notes。
            source="openapi",
        )


async def attach_openapi_tools(
    registry: Any, config: OpenApiSpecConfig, *, transport: Any = None
) -> OpenApiToolBridge:
    """发现并把工具注册进 registry，返回桥（宿主在停机时 await bridge.aclose()）。"""
    bridge = OpenApiToolBridge(config, transport=transport)
    specs = await bridge.connect()
    for spec in specs:
        registry.register(spec)
    return bridge
