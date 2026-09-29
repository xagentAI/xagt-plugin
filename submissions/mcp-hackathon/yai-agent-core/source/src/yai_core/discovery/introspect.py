"""Python 函数内省：type hints + docstring -> JSON Schema 工具规格。

这是"宿主只声明能力、Core 自动长出 Agent"的第一块基石。
v0.2 计划：openapi.py（OpenAPI 文档 -> 工具）、mcp.py（MCP tools/list -> 工具）。
"""

from __future__ import annotations

import inspect
import types
from typing import Any, get_args, get_origin

from yai_core.types import ToolSpec

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _annotation_to_json_type(annotation: Any) -> tuple[str, bool]:
    """返回 (json 类型, 是否可空)。无法识别时回退为 string。"""
    if annotation is inspect.Parameter.empty:
        return "string", False
    # Optional[X] / X | None
    origin = get_origin(annotation)
    if origin in (types.UnionType, getattr(__import__("typing"), "Union", object)):
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if args:
            return _PY_TO_JSON.get(args[0], "string"), nullable
    return _PY_TO_JSON.get(annotation, "string"), False


def build_spec(fn: Any, *, name: str | None = None, source: str = "native") -> ToolSpec:
    """把一个 Python 可调用对象转换成 ToolSpec。"""
    if not callable(fn):
        raise TypeError(f"build_spec 需要可调用对象，得到 {type(fn)!r}")

    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        json_type, nullable = _annotation_to_json_type(param.annotation)
        prop: dict[str, Any] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            prop["default"] = param.default
        if nullable:
            prop["type"] = [json_type, "null"]
        properties[param_name] = prop

    doc = inspect.getdoc(fn) or ""
    description = doc.split("\n\n", 1)[0].strip() or name or fn.__name__

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return ToolSpec(
        name=name or fn.__name__,
        description=description,
        input_schema=schema,
        handler=fn,
        source=source,  # type: ignore[arg-type]
    )


def discover(host: Any) -> list[ToolSpec]:
    """从模块 / 类实例 / 对象上自动发现公开可调用能力。

    - 模块：只收该模块内定义的函数（避免把 import 进来的函数误注册）
    - 对象实例：收公开方法（不以 _ 开头）
    """
    specs: list[ToolSpec] = []

    if inspect.ismodule(host):
        module_name = host.__name__
        members = inspect.getmembers(host, inspect.isfunction)
        for member_name, fn in members:
            if member_name.startswith("_"):
                continue
            if getattr(fn, "__module__", None) != module_name:
                continue
            specs.append(build_spec(fn))
        return specs

    for member_name, fn in inspect.getmembers(host, inspect.ismethod):
        if member_name.startswith("_"):
            continue
        specs.append(build_spec(fn))
    return specs
