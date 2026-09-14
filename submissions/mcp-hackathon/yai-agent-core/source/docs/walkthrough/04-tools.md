# 逐行讲解 04 · `tools/`：注册表与执行总线

> 两个文件分工：`registry.py` 管"有哪些工具"，`executor.py` 管"怎么安全地调用一次工具"。
> 知识点：类的封装、字典即存储、自定义异常、列表推导、async/sync 统一、错误回灌。

## A. `tools/registry.py`

### A1. 初始化（L8-L12）
```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
```
- 内部就是一个字典：`工具名 -> ToolSpec`。**数据结构选对，代码就简单**：查找天然 O(1)。
- `_tools` 下划线开头 = "外部别直接碰，走我的方法"（封装约定）。

### A2. 注册（L14-L21）
```python
def register(self, spec: ToolSpec) -> None:
    if spec.name in self._tools:
        raise ValueError(f"工具 {spec.name!r} 已注册，名称必须唯一")
    self._tools[spec.name] = spec

def register_many(self, specs: Iterable[ToolSpec]) -> None:
    for spec in specs:
        self.register(spec)
```
- 重名立刻报错（快速失败），否则后注册的会悄悄覆盖前者，极难排查。
- `register_many` 只是循环调用单个注册，**复用而不是重写**。
- `Iterable[ToolSpec]`：任何可迭代对象（列表/生成器）都行，比写死 `list` 更宽松。

### A3. 查询（L23-L35）
```python
def get(self, name: str) -> ToolSpec:
    if name not in self._tools:
        raise KeyError(f"未知工具 {name!r}，当前可用：{list(self._tools)}")
    return self._tools[name]

def has(self, name: str) -> bool:
    return name in self._tools

def all(self) -> list[ToolSpec]:
    return list(self._tools.values())

def llm_schemas(self) -> list[dict]:
    return [spec.llm_schema() for spec in self._tools.values()]
```
- `get` 找不到时把"当前有哪些工具"一并报出来，方便模型/开发者纠错。
- `all()` 返回 `list(...)` 而不是直接给内部字典视图，防止外部改坏内部状态（防御性拷贝）。
- `llm_schemas` 用列表推导式把每个 ToolSpec 翻译成模型要的格式——一行等价一个 for 循环。

### A4. 描述与长度（L37-L44）
```python
def describe(self) -> str:
    if not self._tools:
        return "（当前宿主没有提供任何工具）"
    return "\n".join(f"- {s.name}: {s.description}" for s in self._tools.values())

def __len__(self) -> int:
    return len(self._tools)
```
- `describe()` 生成系统提示词里的"能力清单"文本。
- `__len__` 是**魔术方法**：实现后就能写 `len(registry)`，router 里 `len(registry) == 0` 就是这么来的。

## B. `tools/executor.py`

### B1. 构造（L19-L27）
```python
def __init__(self, registry, policy, channel) -> None:
    self.registry = registry
    self.policy = policy
    self.channel = channel
```
- 执行器需要三样东西：从注册表找工具、问权限策略做决策、通过 channel 向人确认。这就是典型的**依赖注入**——需要什么就传什么，不自己 new，方便替换和测试。

### B2. execute 的骨架与返回约定（L29-L35）
```python
async def execute(self, name, arguments) -> tuple[list[AgentEvent], bool, str]:
    """返回 (过程事件列表, 是否成功, 文本结果)，永不向 Agent Loop 抛异常。"""
    events: list[AgentEvent] = []
    if not self.registry.has(name):
        return events, False, f"工具 {name!r} 不存在"
```
- 三元组返回：过程中产生的**事件**、成功与否、给模型看的**文本结果**。
- 铁律"永不抛异常"：工具是宿主写的，可能出错；但工具出错绝不能让整个 Agent 崩掉，而是把错误文本回灌给模型，让它自己换办法（在 06 篇会看到这条错误文本如何进入下一轮消息）。

### B3. 权限闸门（L37-L46）
```python
decision = await self.policy.check(name, arguments)
if decision == PermissionDecision.ASK:
    events.append(AgentEvent(EventType.PERMISSION_ASKED, {...}))
    approved = await self.channel.confirm(name, arguments)
    if not approved:
        return events, False, f"用户/宿主拒绝执行工具 {name}"
if decision == PermissionDecision.DENY:
    return events, False, f"权限策略拒绝执行工具 {name}"
```
- `await policy.check(...)`：权限判断本身也允许是异步的（比如要查数据库/问远程）。
- ASK：先发一个"正在请求权限"的事件（UI 可据此弹确认框），再通过 channel 等人确认。
- DENY / 拒绝都走同一条"返回失败文本"的路。

### B4. 真正执行（L48-L65）
```python
events.append(AgentEvent(EventType.TOOL_CALL, {"tool": name, "arguments": arguments}))
spec = self.registry.get(name)
try:
    result = spec.handler(**arguments)
    if inspect.isawaitable(result):
        result = await result
    text = json.dumps(result, ensure_ascii=False, default=str)
except Exception as exc:
    events.append(AgentEvent(EventType.TOOL_RESULT, {"tool": name, "ok": False, "error": str(exc)}))
    return events, False, f"工具 {name} 执行出错: {type(exc).__name__}: {exc}"
```
逐行：
- 先发 TOOL_CALL 事件（UI 上显示"正在调用 xxx"）。
- `spec.handler(**arguments)`：`**arguments` 把字典展开成关键字参数。模型给 `{"keyword":"周报"}`，等价于调用 `search_notes(keyword="周报")`。
- **同步/异步统一**：宿主函数可能是普通函数也可能是 `async def`。先调用，若返回的是可等待对象（协程），就再 `await` 一下。这样两种宿主函数都支持。
- `json.dumps(..., ensure_ascii=False)`：把任意 Python 对象（dict/list/数字）转成 JSON 文本；`ensure_ascii=False` 让中文直接显示而不是 `\uXXXX`；`default=str` 遇到不认识的类型就调 `str()` 兜底，不崩溃。
- `except Exception as exc` 兜住所有业务异常，`type(exc).__name__` 取异常类名，组成错误文本返回。`# noqa: BLE001` 是告诉 Ruff"我知道这里捕获很宽，是故意的"。

```python
events.append(AgentEvent(EventType.TOOL_RESULT, {"tool": name, "ok": True, "preview": text[:200]}))
return events, True, text
```
- 成功：发 TOOL_RESULT 事件，事件里只放前 200 字预览（避免 UI 被巨量数据刷屏），但**完整 text 返回给模型**。

## 一次工具调用的完整时序

```
Loop 说：执行 search_notes({"keyword":"周报"})
  → Executor: 有这个工具吗？
  → Policy: allow / deny / ask？
  → 发 TOOL_CALL 事件
  → handler(**arguments)，必要时 await
  → json.dumps 成文本
  → 发 TOOL_RESULT 事件
  → 把 (events, ok, text) 交回 Loop
```

## 自检

1. 为什么工具出错不能 raise 到 Loop？错误最后以什么形式回到模型？
2. `**arguments` 展开的是哪一步产生的字典？
3. Executor 怎么同时支持同步函数和 async 函数？
4. 为什么 TOOL_RESULT 事件里只放 200 字预览，而返回值给全文？
