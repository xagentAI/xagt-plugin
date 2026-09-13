# 逐行讲解 07 · 默认实现：memory / policy / channels

> SPI 只定契约，这四个文件是"开箱即用的默认款"。都很短，合在一起讲。
> 知识点：默认实现与接口解耦、防御性拷贝、asyncio.to_thread、字典映射替代长 if。

## A. `memory/inmemory.py`：内存记忆

```python
class InMemoryStore:
    def __init__(self) -> None:
        self._history: list[ChatMessage] = []
        self._kv: dict[str, str] = {}
```
- 两个私有容器：历史消息列表、键值小仓库。全在内存里，进程退出即清空——v0.1 够用，v2 换 SQLite 实现同一套方法即可持久化。

```python
async def append_history(self, message: ChatMessage) -> None:
    self._history.append(message)

def history(self) -> list[ChatMessage]:
    return list(self._history)
```
- 追加是 async（为了和 SPI 契约一致，将来换成数据库时本来就要 await）。
- `history()` 返回 `list(...)` 浅拷贝：外部遍历/改这份列表不会动到内部存储。

```python
async def put(self, key, value) -> None:
    self._kv[key] = value

async def get(self, key) -> str | None:
    return self._kv.get(key)

async def clear(self) -> None:
    self._history.clear()
    self._kv.clear()
```
- KV 读写；`dict.get` 找不到返回 None；clear 同时清空两块。
- **对照 SPI 看**：方法签名和 `spi/memory.py` 一一对应，但不需要继承——这就是第 02 篇说的结构化子类型。

## B. `policy/allowlist.py`：白名单权限

```python
def __init__(self, allowed: Iterable[str] = (), *, mode: str = "auto") -> None:
    self.allowed = set(allowed)
    self.mode = mode
```
- `allowed` 白名单；转成 `set` 让"是否在白名单"的判断 O(1)。
- 默认参数用不可变的空元组 `()` 而不是空列表/集合（可变默认参数坑，和 dataclass 那条同理）。
- 三种模式：`auto`（白名单放行，其余询问）、`allow_all`（全自动，演示/测试用）、`deny_all`（默认拒绝，最保守）。

```python
async def check(self, tool_name: str, arguments: dict) -> PermissionDecision:
    if tool_name in self.allowed:
        return PermissionDecision.ALLOW
    if self.mode == "allow_all":
        return PermissionDecision.ALLOW
    if self.mode == "deny_all":
        return PermissionDecision.DENY
    return PermissionDecision.ASK
```
- 决策顺序：白名单优先（任何模式下都放行）→ 再看模式 → auto 兜底返回 ASK。
- 在 `core.py` 里，`auto_approve_tools=True`（默认）会选 `allow_all`，让你本地跑 demo 不被确认打断；做真实产品时关掉它走 ASK。

## C. `channels/collect.py`：收集通道（测试/API 用）

```python
class CollectChannel:
    def __init__(self, *, auto_confirm: bool = True, default_answer: str = "") -> None:
        self.events: list[AgentEvent] = []
        self.auto_confirm = auto_confirm
        self.default_answer = default_answer

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    async def ask(self, question: str) -> str:
        return self.default_answer

    async def confirm(self, tool_name, arguments) -> bool:
        return self.auto_confirm
```
- 三个方法正好实现 SPI Channel：emit 把事件存进列表（事后可断言/可转 JSON）、ask 给预设回答、confirm 给预设是否批准。
- **它为什么重要**：测试和 HTTP API 没有"真人"可问，必须有一个不交互、只记录的通道。`tests/test_loop.py` 断言事件序列、FastAPI Battery 返回事件数组，靠的都是它。

## D. `channels/cli.py`：终端通道（人看的）

```python
_LABELS = {
    EventType.STRATEGY_SELECTED: "策略",
    EventType.PLAN_CREATED: "计划",
    EventType.MODEL_MESSAGE: "回复",
    EventType.TOOL_CALL: "调用工具",
    ...
}
```
- 用字典把事件类型映射成中文标签。**用字典查表代替一长串 if/elif**，是这段代码想让你学的手法。

```python
async def emit(self, event: AgentEvent) -> None:
    label = _LABELS.get(event.type, event.type.value)
    if event.type == EventType.TOOL_CALL:
        print(f"  [{label}] {event.data['tool']}({event.data['arguments']})")
    elif event.type == EventType.STRATEGY_SELECTED:
        print(f"  [{label}] {event.data['strategy']}")
    elif event.type == EventType.MODEL_MESSAGE:
        print(f"  [{label}] {event.data.get('text', '')}")
    else:
        print(f"  [{label}] {event.data}")
```
- 不同事件 data 结构不同，所以分三种定制打印，其余直接打印字典。
- `data['tool']`（确定有键，缺了是 bug 该报错）vs `data.get('text','')`（可空，给默认）——**两种取值方式的选择体现你对数据是否必填的判断**。

```python
async def ask(self, question: str) -> str:
    return await asyncio.to_thread(input, f"  [澄清] {question} > ")
```
- **重点难点**：`input()` 是阻塞函数，会卡住整个事件循环！`asyncio.to_thread(input, 提示)` 把它丢到另一个线程执行，await 其结果，既保留同步输入体验又不阻塞异步循环。confirm 同理。
- `answer.strip().lower() in ("y","yes","是")`：去空白、转小写再判断，兼容 `Y / yes / 是`。

## 四个默认款的共同设计套路

1. 都实现 SPI 协议但不继承它；
2. 构造零参数或带安全默认值，做到"装上就能跑"；
3. 需要真人/外部系统的地方留好替换点（channel.ask/confirm）。

## 自检

1. 为什么 `history()` 要返回拷贝？直接 `return self._history` 有什么风险？
2. 默认参数为什么写 `allowed=()` 而不是 `allowed=[]` 或 `set()`？
3. 为什么不能在 async 函数里直接调 `input()`？`asyncio.to_thread` 解决了什么？
4. 试着写一个只打印 TOOL_CALL 事件、忽略其他事件的 QuietChannel，接进 AgentCore 跑一次。
