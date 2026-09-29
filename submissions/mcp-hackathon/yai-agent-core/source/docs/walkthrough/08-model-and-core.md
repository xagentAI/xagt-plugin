# 逐行讲解 08 · `llm/openai_compat.py` 与 `core.py`

> 前者把"任意 OpenAI 兼容模型"插进 ModelProvider 插槽；后者是宿主认识的唯一门面。

## A. `llm/openai_compat.py`：真实模型适配

### A1. 懒加载第三方库（L13-L33）
```python
def __init__(self, *, api_key=None, base_url=None, model=None, strong_model=None):
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise ImportError(
            "使用 OpenAICompatProvider 需要安装可选依赖：uv pip install -e '.[llm]'"
        ) from exc
```
- **import 写在方法内部 = 懒加载**：只有真正实例化模型时才要求装 openai。这样内核在"没装 openai、只用离线假模型"时也能 import、能测试——零硬依赖原则的落地。
- `raise ... from exc`：保留原始错误链（caused-by），调试时能看到根因。
- `AsyncOpenAI`：openai 库的异步客户端，和我们全异步的 Loop 配套。

```python
self.client = AsyncOpenAI(
    api_key=api_key or os.getenv("OPENAI_API_KEY", "missing"),
    base_url=base_url or os.getenv("OPENAI_BASE_URL"),
)
self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
self.strong_model = strong_model or os.getenv("LLM_STRONG_MODEL") or self.model
```
- 参数优先，其次读环境变量（`.env` 里配置），再给默认值。`A or B or C` 链式兜底再次出现。
- **为什么换个 base_url 就能接 DeepSeek/通义**：它们都提供 OpenAI 兼容接口，请求格式一样，只是地址和模型名不同。这就是"模型无关"。

### A2. achat：内部消息 → 厂商请求（L35-L49）
```python
async def achat(self, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]] | None = None, *, tier="standard"):
    # messages 由 Context.llm_messages() 产出，已经是 OpenAI 线格式 dict
    kwargs: dict[str, Any] = {
        "model": self.strong_model if tier == "strong" else self.model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
```
- 根据 tier 选模型：规划用强模型，平时用普通模型（省钱/快）。
- **消息在这里只透传、不转换**：`Context.llm_messages()` 已经把内部 `ChatMessage` 逐个 `to_llm_dict()` 转成了 OpenAI 线格式 dict（见第 05 篇），Provider 直接转发即可。这里最初多写了一层 `to_llm_dict()`，对 dict 再调一次方法，真接 DeepSeek 必崩（Day 1-3 修复，离线假模块没暴露）——**格式转换只做一次，且在边界上做**。
- 形参类型因此是 `list[dict[str, Any]]`：Provider 插槽面向"厂商线格式"，不认识内核的 ChatMessage 类。
- 只有确实有工具时才传 tools，并设 `tool_choice="auto"`（让模型自行决定是否调用）。

```python
completion = await self.client.chat.completions.create(**kwargs)
msg = completion.choices[0].message
```
- 真正的网络调用，await。返回结构里第 0 个 choice 的 message 就是模型回复。

### A3. 解析工具调用，抹平厂商形状（L54-L62）
```python
tool_calls: list[ToolCallRequest] = []
for tc in getattr(msg, "tool_calls", None) or []:
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
return ModelResponse(content=msg.content or "", tool_calls=tool_calls, raw=completion)
```
- `getattr(msg, "tool_calls", None)`：属性可能不存在，安全取值；`... or []`：存在但为 None 时也变空列表。
- 模型给的参数是 **JSON 字符串**，`json.loads` 解析成字典；模型偶尔会吐出非法 JSON，解析失败就用空字典兜底，不崩。
- 最终统一返回我们自己的 `ModelResponse`——**厂商 SDK 的数据结构到此为止，不许泄漏进内核**，以后换厂商只改这一个文件。

## B. `core.py`：门面（Facade）

### B1. 构造 = 把所有零件组装起来（L22-L47）
```python
def __init__(self, model, *, channel=None, memory=None, policy=None,
             router=None, auto_approve_tools=True, llm_router=False):
    self.model = model
    self.registry = ToolRegistry()
    self.channel = channel or CollectChannel()
    self.memory = memory or InMemoryStore()
    self.policy = policy or AllowlistPolicy(
        mode="allow_all" if auto_approve_tools else "auto")
    if router is not None:
        self.router = router                       # 显式传入优先
    else:
        self.router = AdaptiveRouter(model=model if llm_router else None)
    self.executor = ToolExecutor(self.registry, self.policy, self.channel)
    self._loop = AgentLoop(model=self.model, registry=self.registry,
                           executor=self.executor, channel=self.channel,
                           memory=self.memory, router=self.router)
```
- 组装顺序：先建无依赖的注册表/默认组件 → 再建执行器（依赖注册表、策略、通道）→ 最后建 Loop（依赖全部）。**依赖顺序就是创建顺序。**
- 每个 SPI 都是"传了用你的，没传用默认款"。宿主可以只给一个 model，其他全自动。
- `llm_router`（v0.2）：开启才把 model 注入路由器做模型分类（失败回退规则，见 05 篇 C 节）；
  默认关闭，离线测试与极简部署零额外模型调用。
- `_loop` 下划线：外部不该直接操作发动机，走门面方法。

### B2. auto：一行接入（L51-L56）
```python
@classmethod
def auto(cls, host: object, model: ModelProvider, **kwargs: object) -> AgentCore:
    core = cls(model, **kwargs)
    core.register_tools(discover(host))
    return core
```
- `@classmethod` + 第一个参数 `cls`：这是"工厂方法"，`AgentCore.auto(...)` 内部先构造自己、再自动发现宿主能力并注册、返回装好的 core。
- `**kwargs` 把 channel/policy 等自定义参数透传给构造函数，保持 auto 也能高度定制。
- **这就是 YAI 的招牌三行**：`core = AgentCore.auto(宿主, 模型)` → 能力自动长出来。

### B3. 工具查看（L58-L65）
```python
def register_tools(self, specs): self.registry.register_many(specs)

def list_tools(self):
    return [{"name": s.name, "description": s.description, "source": s.source}
            for s in self.registry.all()]
```
- 手动补注册的入口（除 auto 外，也允许手工加工具）。
- `list_tools` 返回精简字典（不含 handler 这种不能序列化的东西），供 `/v1/tools` API 直接吐 JSON。

### B4. 两种运行方式（L69-L91）
```python
async def astream(self, task: str) -> AsyncIterator[AgentEvent]:
    async for event in self._loop.astream(task):
        await self.channel.emit(event)
        yield event
```
- 流式：转发 Loop 事件的**唯一出口**，并在这里统一 `channel.emit`。注意第 04 篇重构后，Executor 不再自己发事件，所有事件都从这条路径经过——**全项目事件流只有一条路径**，便于排查。

```python
async def run(self, task: str) -> RunResult:
    events, final_text, strategy = [], "", None
    async for event in self.astream(task):
        events.append(event)
        data = event.data
        if "strategy" in data:
            from yai_core.types import Strategy
            strategy = Strategy(data["strategy"])
        if event.type.value == "done":
            final_text = data.get("final_text", "")
    return RunResult(strategy=strategy or self.router.classify(task, self.registry),
                     events=events, final_text=final_text)
```
- `run` 是"懒人版"：内部消费 astream，把事件攒起来，最后打包成 RunResult。
- 从事件数据里反推策略；兜底再 classify 一次（防御）。
- 函数内 import Strategy 只是为了避免顶部循环导入的写法，你也可以放到顶部（这里没有真正的环，后续可简化）。

## 两条接入路径对比

```python
# 路径 1：要实时过程（CLI/Web SSE/Flutter 流式 UI）
async for ev in core.astream(task):  # 边跑边渲染

# 路径 2：只要最终结果（脚本/HTTP 普通响应）
result = await core.run(task)       # result.final_text / .events
```

## 自检

1. openai 为什么在 `__init__` 里才 import？顶层 import 会破坏什么？
2. DeepSeek、通义千问为什么能用同一个 Provider？要改哪几个配置？
3. ChatMessage → 厂商 dict 的转换发生在哪一层？为什么 Provider 里不能再转一次？
4. `AgentCore.auto` 内部按什么顺序组装零件？
5. `run` 和 `astream` 分别适合什么场景？为什么说事件流只有一条路径？
