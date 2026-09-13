"""发现阶段：把 OpenAPI paths/operations 翻译成工具执行计划（OperationPlan）。

本模块纯函数、零 IO、零第三方依赖，输出交给 client.py 闭包执行。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from yai_core.integrations.openapi.spec import (
    _HTTP_METHODS,
    _READ_ONLY_METHODS,
    OpenApiSpecConfig,
)
from yai_core.tools.schema import EMPTY_OBJECT_SCHEMA, sanitize_schema


@dataclass
class OperationPlan:
    """一个 REST 操作翻译成工具的中间表示。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    method: str
    path_template: str
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    body_fields: tuple[str, ...]
    body_wrapped: bool
    body_required: bool
    security: list[dict] = field(default_factory=list)


def _camel_to_snake(segment: str) -> str:
    """petId → pet_id；listPets → list_pets（小写边界前插下划线）。"""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", segment).lower()


def _clean_operation_id(operation_id: str) -> str:
    """operationId 合法化：驼峰转蛇形、非法字符变下划线、截断 64 字符。"""
    name = _camel_to_snake(operation_id)
    name = re.sub(r"[^a-z0-9_-]+", "_", name).strip("_")
    return name[:64].strip("_")


def _synthetic_name(method: str, path: str) -> str:
    """没有 operationId 时合成：GET /pets/{petId} → get_pets_pet_id。"""
    parts = [method.lower()]
    for segment in path.strip("/").split("/"):
        if not segment:
            continue
        segment = segment.strip("{}").replace("-", "_")
        parts.append(_camel_to_snake(segment))
    return re.sub(r"[^a-z0-9_]+", "_", "_".join(parts))[:64].strip("_")


def _dedupe_name(name: str, used: set[str], notes: list[str]) -> str:
    """同一 spec 内重名追加 __2/__3（跨来源重名由 ToolRegistry 直接报错，不在这里吞）。"""
    if name not in used:
        used.add(name)
        return name
    suffix = 2
    while f"{name}__{suffix}" in used:
        suffix += 1
    final = f"{name}__{suffix}"
    used.add(final)
    notes.append(f"同一 spec 内工具名冲突，{name} 的第 {suffix - 1} 个重名操作改名为 {final}")
    return final


def _parameter_property(parameter: dict) -> tuple[str, dict, bool]:
    name = parameter["name"]
    schema = sanitize_schema(parameter.get("schema") or {})
    if parameter.get("description") and isinstance(schema, dict):
        schema.setdefault("description", parameter["description"])
    return name, schema, bool(parameter.get("required", False))


def _merge_body(
    properties: dict, required: list[str], body_schema: dict, notes: list[str]
) -> tuple[tuple[str, ...], bool]:
    """requestBody 的 schema 并入入参：object 拍平合并；其他类型包成 {"body": ...}。"""
    body_schema = sanitize_schema(body_schema)
    if isinstance(body_schema, dict) and body_schema.get("type") == "object":
        body_props = body_schema.get("properties") or {}
        for name, sub in body_props.items():
            if name in properties:
                notes.append(f"body 字段与路径/查询参数同名 {name}，body 侧覆盖")
            properties[name] = sub
        for name in body_schema.get("required") or []:
            if name not in required:
                required.append(name)
        return tuple(body_props.keys()), False
    properties["body"] = body_schema
    return ("body",), True


def _path_allowed(path: str, config: OpenApiSpecConfig) -> bool:
    """先 include 白名单（前缀匹配），再 exclude 黑名单。"""
    if config.include_paths and not any(
        path.startswith(prefix) for prefix in config.include_paths
    ):
        return False
    if config.exclude_paths and any(path.startswith(prefix) for prefix in config.exclude_paths):
        return False
    return True


def plan_operations(
    spec: dict, config: OpenApiSpecConfig
) -> tuple[list[OperationPlan], list[str]]:
    """遍历 paths，产出操作计划列表与 notes（read_only 过滤、截断都在这里）。"""
    notes: list[str] = []
    plans: list[OperationPlan] = []
    used_names: set[str] = set()
    paths = spec.get("paths") or {}

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        if "$ref" in path_item:
            notes.append(f"路径级 $ref 不展开，跳过：{path}")
            continue
        if not _path_allowed(path, config):
            continue
        shared_parameters = path_item.get("parameters") or []
        for method, operation in path_item.items():
            method_l = method.lower()
            if method_l not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            if config.read_only and method_l not in _READ_ONLY_METHODS:
                continue

            properties: dict[str, Any] = {}
            required: list[str] = []
            path_params: list[str] = []
            query_params: list[str] = []

            # pathItem 级与 operation 级 parameters 合并（后者优先语义由后写覆盖体现）。
            for parameter in [*shared_parameters, *(operation.get("parameters") or [])]:
                if not isinstance(parameter, dict):
                    continue
                where = parameter.get("in")
                if where not in {"path", "query"}:
                    continue  # header / cookie 参数不暴露给模型（v0.2 边界）
                name, sub_schema, is_required = _parameter_property(parameter)
                properties[name] = sub_schema
                if where == "path":
                    path_params.append(name)
                    if name not in required:
                        required.append(name)  # OpenAPI 规定 path 参数恒为 required
                else:
                    query_params.append(name)
                    if is_required and name not in required:
                        required.append(name)

            body_fields: tuple[str, ...] = ()
            body_wrapped = False
            body_required = False
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content") or {}
                json_entry = content.get("application/json")
                if json_entry and isinstance(json_entry.get("schema"), dict):
                    body_fields, body_wrapped = _merge_body(
                        properties, required, json_entry["schema"], notes
                    )
                    body_required = bool(request_body.get("required", False))
                    if body_required and body_wrapped and "body" not in required:
                        required.append("body")

            operation_id = operation.get("operationId")
            raw_name = (
                _clean_operation_id(operation_id)
                if operation_id
                else _synthetic_name(method_l, path)
            )
            name = _dedupe_name(raw_name, used_names, notes)
            if config.prefix:
                name = f"{config.prefix}_{name}"

            summary = (operation.get("summary") or "").strip()
            description = (operation.get("description") or "").strip()
            tail = f"{summary} {description}".strip()
            tool_description = f"[{method.upper()} {path}] {tail}".strip()[:1000]

            input_schema = sanitize_schema(
                {"type": "object", "properties": properties, "required": required}
            )
            if not properties:
                input_schema = dict(EMPTY_OBJECT_SCHEMA)

            plans.append(
                OperationPlan(
                    name=name,
                    description=tool_description,
                    input_schema=input_schema,
                    method=method.upper(),
                    path_template=path,
                    path_params=tuple(path_params),
                    query_params=tuple(query_params),
                    body_fields=body_fields,
                    body_wrapped=body_wrapped,
                    body_required=body_required,
                    # operation 级 security 缺省回退全局 security。
                    security=operation.get("security", spec.get("security")) or [],
                )
            )

    if len(plans) > config.max_operations:
        notes.append(
            f"操作数 {len(plans)} 超过 max_operations={config.max_operations}，已截断"
        )
        plans = plans[: config.max_operations]
    return plans, notes
