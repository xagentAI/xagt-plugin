# 逐行讲解 01 · `types.py`：全项目的数据词汇表

> 目标：看懂项目里传递的每一种"数据包"长什么样。
> 知识点：模块 docstring、`from __future__`、类型别名、StrEnum、dataclass、field。

## 块 1 · 文件头与导入（L1-L11）

```python
"""YAI Agent Core 的核心数据类型。

刻意只依赖标准库：内核本体零第三方依赖，第三方能力全部通过 SPI 注入。
"""
```
- 三引号字符串放在文件最开头叫**模块 docstring**，调用 `help(模块)` 或 IDE 悬停时能看到。它也是给你自己看的设计说明。

```python
from __future__ import annotations
```
- "未来导入"。Python 3.11 其实已经支持新注解，但加上它后，所有类型注解都不在运行时立刻求值（当成字符串处理），可以放心写 `list[ToolSpec]`、自引用等而不报错。**项目里每个文件第一行都是它，照抄即可。**

```python
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
```
- `Callable`："这是一个可以被调用的东西（函数）"的类型。注意它从 `collections.abc` 导入（现代写法），Ruff 会自动帮你从旧的 `typing` 挪过来。
- `dataclass, field`：数据类装饰器和它的辅助函数，下面细讲。
- `StrEnum`：字符串枚举（Python 3.11+），成员本身就是字符串。
- `Any`：任意类型（放弃检查，只在确实无法确定时用）；`Literal[...]`：取值只能是列出的字面量之一。

## 块 2 · 角色类型别名（L13）

```python
Role = Literal["system", "user", "assistant", "tool"]
```
- 定义**类型别名**：以后写 `role: Role` 等价于 `role: Literal[...]`，IDE 会提示只能填这 4 种字符串，拼错立刻警告。
- 这 4 个角色正是大模型对话协议里的角色：系统设定 / 用户 / 助手（模型）/ 工具回传。

## 块 3 · 两个枚举（L16-L36）

```python
class Strategy(StrEnum):
    DIRECT = "direct"
    REACT = "react"
    PLAN = "plan"
    CLARIFY = "clarify"
```
- 枚举 = "有限的几个候选值"。`Strategy.DIRECT` 既是枚举成员，`str(Strategy.DIRECT)` 又是 `"direct"`，这就是 StrEnum 比 `(str, Enum)` 更干净的地方。
- 为什么不直接到处写字符串 `"react"`？因为字符串拼错不报错，而 `Strategy.REAC` 拼错会直接报 `AttributeError`，且 IDE 能自动补全。

`EventType` 同理，列出运行全过程可能出现的 9 种事件。**这就是"可观测"的词汇表**：以后每做一个动作，都从这里挑一个事件类型发出去，不会出现叫法不一。

## 块 4 · ToolSpec：工具的统一身份证（L39-L58）

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    source: Literal["native", "openapi", "mcp"] = "native"
```
- `@dataclass` 会自动生成 `__init__`，所以你能直接 `ToolSpec(name="x", description=..., ...)`，不用手写构造函数。
- 字段逐个看：
  - `name`：工具名（模型靠它点名调用）；
  - `description`：给模型看的"这个工具干嘛的"；
  - `input_schema`：参数的 JSON Schema（什么参数、什么类型、哪些必填）；
  - `handler`：真正干活的 Python 函数；`Callable[..., Any]` 表示"任意参数、返回任意值的可调用对象"；
  - `source`：工具来源，默认 `"native"`（宿主自己的函数），未来 OpenAPI/MCP 来的工具也用**同一个类**装——这就是"同构"。
- 注意写法规则：**没有默认值的字段必须排在有默认值的前面**（和函数参数一个道理）。

```python
def llm_schema(self) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        },
    }
```
- 普通方法：把内部表示翻译成 OpenAI 兼容接口要求的工具形状。以后 DeepSeek 收到的就是这个字典。**"内部一种结构，对外按需翻译"是贯穿项目的手法。**

## 块 5 · ChatMessage：一条对话消息（L61-L78）

```python
@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
```
- `X | None`：要么是 X，要么是 None（等价旧写法 `Optional[X]`）。
- 一条消息在不同角色下用不同字段：
  - user/assistant 普通对话：主要用 `role + content`；
  - assistant 决定调工具时：填 `tool_calls`（可能一次调多个）；
  - 工具回传结果时：`role="tool"` + `tool_call_id`（对应哪次调用）+ `name`（哪个工具）。

```python
def to_llm_dict(self) -> dict[str, Any]:
    d: dict[str, Any] = {"role": self.role, "content": self.content}
    if self.tool_calls:
        d["tool_calls"] = self.tool_calls
    ...
    return d
```
- 先建一个最小字典，**有值才加键**：因为模型接口不喜欢收到 `tool_calls: None` 这种空字段。
- `d: dict[str, Any] = {...}` 里的注解是写给人和 IDE 看的，运行不影响。

## 块 6 · 其余四个数据类（L81-L107）

```python
@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
```
- 模型说"我要调工具"时的结构化请求。
- **重点：`field(default_factory=dict)`**。可变默认值（列表/字典）不能直接写 `={}`，否则所有实例会共享同一个字典！`default_factory=dict` 的意思是"每次新建时调用 `dict()` 生成一个新的"。下面 `ModelResponse.tool_calls`、`AgentEvent.data` 同理，这是 Python 经典坑，记住就好。

```python
@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    raw: Any = None
```
- 模型回复的统一形状：要么有正文 `content`，要么有工具调用，也可能都有。`raw` 保存厂商原始返回，调试用。

```python
@dataclass
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
```
- Observer 事件：`type` 说明发生了什么，`data` 装细节。Loop 里 `yield AgentEvent(...)` 就是在"对外广播"。

```python
@dataclass
class RunResult:
    strategy: Strategy
    events: list[AgentEvent]
    final_text: str
```
- `core.run()` 最终交给宿主的结果包：用了什么策略、全过程事件、最终文本。

## 自检

1. 为什么 `arguments` 要用 `field(default_factory=dict)` 而不能直接 `={}`？
2. 一条 `role="tool"` 的消息为什么必须带 `tool_call_id`？
3. `ToolSpec.source` 留了哪三种来源？这和"不重复造轮子"有什么关系？
4. 把 `EventType` 里删掉一个、在 loop.py 里引用它会发生什么？（动手试）
