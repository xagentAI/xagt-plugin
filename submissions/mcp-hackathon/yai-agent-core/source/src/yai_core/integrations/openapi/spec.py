"""OpenAPI 描述载入、版本校验与内部 $ref 展开。

顶层只 import 标准库；httpx / pyyaml 一律函数内懒加载（内核零硬依赖红线）。
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_READ_ONLY_METHODS = frozenset({"get", "head"})
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


@dataclass
class OpenApiSpecConfig:
    """一个 OpenAPI 描述的接入配置。url / path / spec 三选一。"""

    alias: str = "rest"
    url: str | None = None
    path: str | Path | None = None
    spec: dict | None = None
    prefix: str = ""
    base_url_override: str | None = None
    auth_token_env: str | None = "OPENAPI_AUTH_TOKEN"
    extra_headers: dict[str, str] = field(default_factory=dict)
    read_only: bool = False
    max_operations: int = 40
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    timeout: float = 15.0
    max_spec_bytes: int = 2 * 1024 * 1024
    max_result_chars: int = 16_000


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def config_from_env(
    *,
    alias: str = "rest",
    url_env: str = "OPENAPI_SPEC_URL",
    path_env: str = "OPENAPI_SPEC_PATH",
    token_env: str = "OPENAPI_AUTH_TOKEN",
    base_url_env: str = "OPENAPI_BASE_URL",
    read_only_env: str = "OPENAPI_READ_ONLY",
    env: dict[str, str] | None = None,
) -> OpenApiSpecConfig | None:
    """从环境变量构造配置；URL 与 PATH 都没配时返回 None（装配方据此跳过）。"""
    environ = os.environ if env is None else env
    url = (environ.get(url_env) or "").strip() or None
    raw_path = (environ.get(path_env) or "").strip() or None
    if url is None and raw_path is None:
        return None
    base = (environ.get(base_url_env) or "").strip() or None
    # 只记录变量名，不判断令牌是否存在：缺令牌由调用期报错，且报错要点名这个变量。
    return OpenApiSpecConfig(
        alias=alias,
        url=url,
        path=Path(raw_path) if raw_path else None,
        base_url_override=base,
        auth_token_env=token_env,
        read_only=_truthy(environ.get(read_only_env)),
    )


def _load_from_path(path: Path, max_bytes: int) -> dict:
    p = Path(path).expanduser()
    data = p.read_bytes()
    if len(data) > max_bytes:
        raise ValueError(f"OpenAPI 描述超过 {max_bytes} 字节上限：{p}")
    suffix = p.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # 懒加载：只有 YAML 描述才需要 pyyaml
        except ImportError as exc:
            raise ImportError(
                "解析 YAML 形式的 OpenAPI 描述需要可选依赖：uv sync --extra openapi"
            ) from exc
        loaded = yaml.safe_load(data.decode("utf-8"))
    else:
        loaded = json.loads(data.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("OpenAPI 描述根节点必须是对象")
    return loaded


def _load_from_url(config: OpenApiSpecConfig, transport: Any) -> dict:
    try:
        import httpx  # 懒加载
    except ImportError as exc:
        raise ImportError(
            "OpenAPI 集成需要可选依赖：uv sync --extra openapi"
            "（或 pip install 'yai-agent-core[openapi]'）"
        ) from exc
    # transport 仅供测试注入 httpx.MockTransport；生产为 None，走真实网络。
    with httpx.Client(timeout=config.timeout, transport=transport) as client:
        resp = client.get(config.url)  # type: ignore[arg-type]
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(f"拉取 OpenAPI 描述失败：HTTP {resp.status_code}")
        if len(resp.content) > config.max_spec_bytes:
            raise ValueError(f"OpenAPI 描述超过 {config.max_spec_bytes} 字节上限")
        ctype = resp.headers.get("content-type", "")
        if "yaml" in ctype or str(config.url).endswith((".yaml", ".yml")):
            try:
                import yaml
            except ImportError as exc:
                raise ImportError(
                    "解析 YAML 形式的 OpenAPI 描述需要可选依赖：uv sync --extra openapi"
                ) from exc
            loaded = yaml.safe_load(resp.text)
        else:
            loaded = resp.json()
    if not isinstance(loaded, dict):
        raise ValueError("OpenAPI 描述根节点必须是对象")
    return loaded


def load_spec(config: OpenApiSpecConfig, *, transport: Any = None) -> dict:
    """三选一载入（dict / 文件 / URL）并校验是 OpenAPI 3；非法输入给可操作错误。"""
    if config.spec is not None:
        raw = config.spec
    elif config.path is not None:
        raw = _load_from_path(config.path, config.max_spec_bytes)
    elif config.url is not None:
        raw = _load_from_url(config, transport)
    else:
        raise ValueError("OpenApiSpecConfig 必须提供 url / path / spec 之一")
    if not isinstance(raw, dict):
        raise ValueError("OpenAPI 描述根节点必须是对象")
    if "openapi" not in raw:
        if str(raw.get("swagger", "")).startswith("2"):
            raise ValueError("不支持 Swagger 2.0，请先转换为 OpenAPI 3（3.0.x / 3.1.x）")
        raise ValueError("缺少 openapi 版本字段，不是合法的 OpenAPI 3 描述")
    if not str(raw["openapi"]).startswith("3."):
        raise ValueError(f"仅支持 OpenAPI 3.x，收到版本：{raw['openapi']}")
    return raw


def _resolve_pointer(root: dict, pointer: str) -> Any:
    """按 JSON Pointer（#/a/b/1）在根节点里取目标。"""
    cur: Any = root
    for part in pointer.lstrip("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")  # Pointer 转义
        cur = cur[part]
    return cur


def resolve_refs(spec: dict) -> tuple[dict, list[str]]:
    """内联展开文档内部 $ref，返回（深拷贝后的新 spec, notes）。

    - 内部 $ref（#/...）：递归内联；正在展开的引用链上再次命中 = 循环，保留 $ref 原样并记 note；
    - 外部 $ref（http/另一文件）：不解析，原样保留并记 note（v0.2 不跨文档抓取）。
    """
    notes: list[str] = []
    root = copy.deepcopy(spec)

    def walk(node: Any, stack: frozenset[str]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                if not ref.startswith("#"):
                    note = f"外部 $ref 不解析，原样保留：{ref}"
                    if note not in notes:
                        notes.append(note)
                    return {"$ref": ref}
                if ref in stack:
                    note = f"检测到循环 $ref：{ref}，该处保留原样"
                    if note not in notes:
                        notes.append(note)
                    return {"$ref": ref}
                target = _resolve_pointer(root, ref)
                resolved = walk(target, stack | {ref})
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                if isinstance(resolved, dict) and siblings:
                    # 3.1 允许 $ref 与兄弟键共存：内联目标后用兄弟键覆盖同名字段。
                    return {**resolved, **{k: walk(v, stack) for k, v in siblings.items()}}
                return resolved
            return {k: walk(v, stack) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, stack) for v in node]
        return node

    return walk(root, frozenset()), notes


def resolve_base_url(config: OpenApiSpecConfig, spec: dict) -> str | None:
    """base_url 优先级：显式 override > servers[0].url；相对 server 地址按 spec URL 解析。"""
    if config.base_url_override:
        return config.base_url_override
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        url = servers[0]["url"]
        if config.url and not url.startswith("http"):
            return urljoin(config.url, url)
        return url
    return None
