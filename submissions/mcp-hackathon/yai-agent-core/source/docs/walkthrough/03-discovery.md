# 逐行讲解 03 · `discovery/introspect.py`：能力自发现

> 这是 YAI"宿主零 Agent 代码"的魔法来源。其实没有魔法——只是用标准库 `inspect` 把函数签名读出来。
> 知识点：inspect.signature、类型注解的读取、Optional 原理、字典构建、模块/方法判断。

## 块 1 · 导入与类型映射表（L7-L22）

```python
import inspect
import types
from typing import Any, get_args, get_origin
from yai_core.types import ToolSpec

_PY_TO_JSON: dict[type, str] = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object",
}
```
- `inspect`：Python 反射标准库，可以在运行时读取"函数叫什么、有哪些参数、注解是什么、docstring 是什么"。
- `get_origin / get_args`：拆解复杂注解的工具，比如把 `Optional[str]`（即 `str | None`）拆成 `(str, NoneType)`。
- `_PY_TO_JSON`：Python 类型 → JSON Schema 类型名的对照表。**字典的键可以是类型本身**（类也是对象）。
- 下划线前缀 `_PY_TO_JSON`：约定"模块内部使用"，`from xxx import *` 不会导出它。

## 块 2 · 把单个注解翻译成 JSON 类型（L25-L36）

```python
def _annotation_to_json_type(annotation: Any) -> tuple[str, bool]:
    if annotation is inspect.Parameter.empty:
        return "string", False
```
- 返回值标注 `tuple[str, bool]`：返回一个二元组（JSON 类型、是否可空）。
- `inspect.Parameter.empty` 是个**哨兵对象**：当参数根本没写类型注解时，`param.annotation` 就是它。这里保守回退成 `"string"`。

```python
    origin = get_origin(annotation)
    if origin in (types.UnionType, getattr(__import__("typing"), "Union", object)):
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if args:
            return _PY_TO_JSON.get(args[0], "string"), nullable
    return _PY_TO_JSON.get(annotation, "string"), False
```
逐行：
- `get_origin(annotation)`：取出"外壳"。`str | None` 的外壳是 union 类型；普通 `str` 的外壳是 None。
- 判断外壳是不是联合类型：`types.UnionType` 对应新式 `X | None`；`typing.Union` 对应老式 `Optional[X]`。两种写法都兼容。
  - 这里 `getattr(__import__("typing"), "Union", object)` 是"动态导入 typing 再取 Union"的防御写法，等价于先 `from typing import Union` 再用 `Union`（你自己写代码时用普通 import 更清晰）。
- 列表推导式 `[a for a in get_args(...) if a is not type(None)]`：把 `NoneType` 过滤掉，剩下真实类型。
- `nullable`：过滤前后数量不一样，说明里面原本有 None → 可空。
- `dict.get(k, 默认)`：找不到映射就回退 `"string"`，绝不因为陌生类型崩溃。

## 块 3 · build_spec：一个函数 → 一张工具身份证（L39-L74）

```python
def build_spec(fn: Any, *, name: str | None = None, source: str = "native") -> ToolSpec:
    if not callable(fn):
        raise TypeError(f"build_spec 需要可调用对象，得到 {type(fn)!r}")
```
- `*,` 后面的参数必须用关键字传：`build_spec(f, name="x")`。
- `callable(fn)`：判断是不是函数/可调用对象；不是就**快速失败**并给出清晰错误。
- f-string 里 `!r` 表示用 `repr()` 显示（带引号/类型细节），调试信息更明确。

```python
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
```
- `inspect.signature(fn)` 拿到函数签名对象；后两个变量分别装"参数 schema"和"必填参数名"。

```python
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
```
逐行：
- `sig.parameters` 是有序映射，键是参数名，值是参数对象。
- `VAR_POSITIONAL`（`*args`）和 `VAR_KEYWORD`（`**kwargs`）无法表达成固定 JSON 参数，`continue` 跳过。
- 每个参数生成一个 `{"type": ...}` 描述。
- **没有默认值 = 必填**（加入 required）；有默认值就把默认值写进 schema，模型可以不传。
- 可空时 JSON Schema 写法是 `"type": ["string", "null"]`。
- 最后挂进 `properties[参数名]`。

```python
    doc = inspect.getdoc(fn) or ""
    description = doc.split("\n\n", 1)[0].strip() or name or fn.__name__
```
- `inspect.getdoc(fn)`：拿到函数 docstring（还会自动去掉缩进）。
- `split("\n\n", 1)[0]`：只取第一段（空行之前）作为简介，避免把长篇说明塞给模型。
- `A or B or C` 链式兜底：没 docstring 就用传入 name，再不行用函数自身的 `__name__`。

```python
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return ToolSpec(
        name=name or fn.__name__, description=description,
        input_schema=schema, handler=fn, source=source,
    )
```
- 拼成标准 JSON Schema：`{"type":"object","properties":{...},"required":[...]}`。
- required 为空就不写这个键（干净）。
- 产出 ToolSpec：函数本体存进 `handler`，以后执行就是调它。

## 块 4 · discover：自动扫出一批函数（L77-L100）

```python
def discover(host: Any) -> list[ToolSpec]:
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
```
针对**模块**（我们的 `capabilities.py` 就是模块）：
- `inspect.getmembers(host, inspect.isfunction)`：列出模块里所有函数，返回 `(名字, 函数)` 列表。
- 下划线开头的跳过（私有约定）。
- **关键防线**：`fn.__module__ != module_name` 时跳过——因为模块顶部 `import xxx` 进来的函数也会被 getmembers 列出来！只保留"本模块自己定义的"，避免把 `date`、第三方函数误注册成工具。

```python
    for member_name, fn in inspect.getmembers(host, inspect.ismethod):
        if member_name.startswith("_"):
            continue
        specs.append(build_spec(fn))
    return specs
```
针对**对象实例**（未来宿主用类组织能力时）：`inspect.ismethod` 只挑绑定方法，同样跳过私有方法。

## 串起来看

`examples/host_a_notes/capabilities.py` 里写：
```python
def search_notes(keyword: str) -> list[dict]: ...
```
`discover(capabilities)` 会自动产出等价于：
```json
{"name": "search_notes",
 "description": "按关键词搜索笔记标题与正文。",
 "parameters": {"type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"]}}
```
宿主完全没写 Agent 代码，工具就"长出来了"。

## 自检

1. 为什么必须判断 `fn.__module__`？删掉这行会发生什么（可以在 host_a 顶部加个 import 试试）？
2. 参数 `limit: int = 5` 会被翻译成什么 schema？必填吗？
3. `Optional[str]` 经过 `_annotation_to_json_type` 返回什么？
4. 给 host_c 新增一个带两个参数的函数，跑 smoke 观察自动发现结果。
