# 逐行讲解 02 · `spi/`：四个可替换插槽

> 目标：理解 Core 为什么不绑定模型厂商、不绑定 UI、不绑定数据库。
> 知识点：Protocol（结构化子类型 / 鸭子类型）、runtime_checkable、`...` 函数体、接口与实现分离。

## 0. 什么是 SPI

SPI = Service Provider Interface（服务提供者接口）。意思是：**Core 只规定"你得长这样"，不规定"你是谁家的"。**
谁满足这套方法签名，谁就能插进 Core 当模型/通道/记忆/权限。Core 自己另外提供了"默认款"（见第 07 篇）。

四个文件结构几乎一样，学会一个就会四个。

## 1. `spi/model.py`：模型插槽

```python
from typing import Any, Protocol, runtime_checkable
from yai_core.types import ChatMessage, ModelResponse

@runtime_checkable
class ModelProvider(Protocol):
    async def achat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        ...
```

逐行：
- `class Xxx(Protocol)`：声明一个**协议**。它不写实现，只写"符合本协议的对象必须有哪些方法、什么参数、返回什么"。
- `@runtime_checkable`：允许用 `isinstance(obj, ModelProvider)` 运行时检查（没它只能做类型提示）。
- `async def achat(...)`：模型调用是网络 IO，所以是异步方法。
- `messages`：对话历史；`tools`：本轮给模型的工具清单（None=不让用工具）。
- `*`：**仅限关键字参数分隔符**，它后面的 `tier` 调用时必须写名字 `tier="strong"`，防止位置传参搞错。`tier` 是模型路由的钩子：standard 走便宜模型，strong 走强模型（规划时用）。
- 函数体只有 `...`（Ellipsis）：协议方法不需要实现，`...` 就是"占位、到此为止"。

**关键理解**：DeepSeek 适配（`OpenAICompatProvider`）、测试里的 `ScriptedModel`、示例里的 `OfflineScriptedModel` 都没有继承 `ModelProvider`，但因为它们都"恰好有一个签名一致的 `achat` 方法"，就都能被 Core 当模型用。这叫**结构化子类型**（俗称鸭子类型：走起来像鸭子就是鸭子）。

## 2. `spi/channel.py`：输入输出插槽

```python
@runtime_checkable
class Channel(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...
    async def ask(self, question: str) -> str: ...
    async def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool: ...
```
- `emit`：Core 把运行事件往外发（打印、推给网页、推给 Flutter 都靠各自实现）。
- `ask`：策略为 clarify 时反问用户，拿回一句回答。
- `confirm`：权限策略为 ASK 时，问宿主"这个工具允许执行吗"，返回布尔。
- 返回 `None` 表示这个方法没有有意义的返回值（只做动作）。

**为什么 Core 不直接 print？** 因为 Core 是内核，它不知道自己将来跑在终端、网页还是 Flutter 里。把"怎么显示/怎么问人"抽成 Channel，内核就和 UI 彻底解耦。

## 3. `spi/memory.py`：记忆插槽

```python
@runtime_checkable
class MemoryStore(Protocol):
    async def append_history(self, message: ChatMessage) -> None: ...
    def history(self) -> list[ChatMessage]: ...
    async def put(self, key: str, value: str) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def clear(self) -> None: ...
```
- v0.1 只要求两件事：**会话历史**（append/history）和**简单 KV**（put/get）。
- 注意 `history()` 不是 async：它只是读内存列表，没有 IO，没必要异步。**同步/异步的选择标准：有没有等待 IO（网络/磁盘）。**
- 未来 `SqliteStore`、向量记忆只要实现这几个方法就能替换，Loop 一行不用改。

## 4. `spi/policy.py`：权限插槽

```python
class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

@runtime_checkable
class PermissionPolicy(Protocol):
    async def check(self, tool_name: str, arguments: dict[str, Any]) -> PermissionDecision: ...
```
- 每次工具执行前问一句权限：直接放行 / 拒绝 / 先问人。
- 三态而不是两态，是因为陪伴/数据类软件里"删除、发送、付款"这类动作必须有人确认，这是 AMBRACE 未来必备的安全闸。

## 5. `spi/__init__.py`：统一出口

```python
from yai_core.spi.channel import Channel
from yai_core.spi.memory import MemoryStore
from yai_core.spi.model import ModelProvider
from yai_core.spi.policy import PermissionDecision, PermissionPolicy
```
- 把四个协议集中到 `yai_core.spi` 包名下，外部一行导入：`from yai_core.spi import ModelProvider, Channel`。
- `__init__.py` 的作用：把一个文件夹标记为 Python 包，并决定"对外暴露什么"。

## 设计思想小结（比赛材料也用得上）

> Core 面向协议编程，不面向具体实现编程。新增一种模型/UI/数据库 = 新写一个满足协议的小类，内核零修改——这正是"可扩展、可内嵌"的根。

## 自检

1. `ScriptedModel` 没有继承 `ModelProvider`，为什么能传给 AgentCore 当模型？
2. `*, tier` 里的星号起什么作用？
3. 为什么 `history()` 是同步方法而 `append_history` 是异步？
4. 如果要接微信小程序当 UI，你需要实现哪个 SPI？实现哪几个方法？
