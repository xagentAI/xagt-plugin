# 逐行讲解 05 · `kernel/router.py` 与 `kernel/context.py`

> Router 决定"用什么打法"，Context 管理"发给模型的消息本"。都很短，但都是决策核心。

## A. `kernel/router.py`：自适应路由

### A1. 信号词表（router.py 顶部）
```python
_PLAN_HINTS = ("然后", "接着", "之后", "再把", "分步", "步骤", "先", "并且",
               "同时", "对比", "整理成", "汇总成", "最终", "一共", "分别")
_ACTION_HINTS = ("查", "找", "搜", "列出", "统计", "计算", "导出", "获取",
                 "读取", "记录", "新增", "整理", "分析", "筛选", "生成",
                 # 显式的工具/MCP 调用意图（v0.2 接外部 MCP Server 后补齐）
                 "问一下", "查询", "调用", "工具", "mcp")
_CLARIFY_HINTS = ("随便", "你看着办", "什么都行", "帮我弄一下")
```
- 三个元组就是三张"关键词表"。这是 v0.1 的确定性规则实现：**零成本、离线可跑、每条规则都能写单元测试**（见 `tests/test_router.py`）。
- 元组而不是列表：这些表不该被运行时修改，元组语义更准确。
- 最后五个词是一次真实回归补的：任务写"用 MCP 工具**问一下**……"时，旧词表没有任何动作信号，被路由成 direct，结果模型想调工具却拿不到工具清单，只能把工具调用写成文本。规则路由是 LLM 路由的兜底，**兜底也必须覆盖最直白的工具意图表达**。

### A2. 类与构造（L27-L29）
```python
class AdaptiveRouter:
    def __init__(self, *, min_plan_steps: int = 2) -> None:
        self.min_plan_steps = min_plan_steps
```
- 预留参数 `min_plan_steps`（v0.2 LLM 分类器会用到）。v0.1 先占住扩展位，这叫"为变化留门，但不提前实现"。

### A3. classify 决策函数（L31-L47）——按顺序读，顺序就是优先级
```python
def classify(self, task: str, registry: ToolRegistry) -> Strategy:
    text = task.strip()
    if not text:
        return Strategy.CLARIFY
```
- `strip()` 去掉首尾空白；空任务无法处理 → 反问。

```python
    if any(h in text for h in _CLARIFY_HINTS) and len(text) < 12:
        return Strategy.CLARIFY
```
- `any(生成器)`：只要有一个信号词命中就为 True。
- **为什么还要 `len(text) < 12`？** 防止误杀：一句很长、很具体但恰好含"随便"二字的任务不该被当成模糊请求。规则系统要靠这种"组合条件"降低误判。

```python
    if len(registry) == 0:
        return Strategy.DIRECT
```
- 宿主一个工具都没有，再复杂也没法调工具，只能让模型直接回答。注意它在行动判断**之前**——能力边界优先于用户意图。

```python
    # 拉丁字母提示词（如 mcp）大小写不敏感；中文提示词按原文匹配。
    lowered = text.lower()
    wants_action = any(
        (h in lowered) if h.isascii() else (h in text) for h in _ACTION_HINTS
    )
    multi_step = sum(1 for h in _PLAN_HINTS if h in text) >= 1
    if multi_step and wants_action:
        return Strategy.PLAN
    if wants_action:
        return Strategy.REACT
    return Strategy.DIRECT
```
- `wants_action`：像需要动手的任务。
- `h.isascii()` 判断提示词是不是纯拉丁字母（如 `"mcp"`）：是就对**小写化后的任务**匹配，让 "MCP"、"mcp"、"Mcp" 都能命中；中文词不受影响（中文没有大小写，`lower()` 也不会改它，但保持语义清晰）。
- 生成器表达式里的三元表达式 `(h in lowered) if h.isascii() else (h in text)`：逐个提示词选择匹配文本，`any(...)` 有一个命中即 True。
- `multi_step`：`sum(1 for h in ... if 命中)` 是"数命中了几个多步信号"的生成器写法；命中 ≥1 就算多步。
- 决策优先级：**多步且要动手 → PLAN（先规划再执行）；只动手 → REACT；其余 → DIRECT。**
- 最后一行注释解释了一个反直觉点：DIRECT 时模型并非被禁止用工具，只是首轮不塞工具清单（在 06 篇看 `use_tools`）。

> v0.2 已加 LLM 分类器（见 C 节），**规则实现保留作兜底**：模型分类失败/超时时回退到这里。
> 这种"智能方案 + 确定性兜底"是生产级 Agent 的常见结构。

## B. `kernel/context.py`：消息本与 token 预算

### B1. 初始化（L9-L11）
```python
def __init__(self, system_prompt: str, *, max_chars: int = 24000) -> None:
    self.max_chars = max_chars
    self.messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
```
- 一次运行对应一个 Context。创建时**第一条永远是 system 消息**（角色设定 + 工具清单）。
- v0.1 用字符数粗略估 token（中文约 1 字 ≈ 1～2 token），所以预算叫 `max_chars`；v2 再换精确的 tokenizer。

### B2. 追加并自动压缩（L13-L25）
```python
def add(self, message: ChatMessage) -> None:
    self.messages.append(message)
    self._compact()
```
- 每次追加后立刻检查是否超预算，调用方不用操心。

```python
def _compact(self) -> None:
    total = sum(len(m.content) for m in m for m in self.messages)  # 示意
```
实际代码：
```python
    total = sum(len(m.content) for m in self.messages)
    i = 1
    while total > self.max_chars and i < len(self.messages) - 1:
        total -= len(self.messages[i].content)
        i += 1
    if i > 1:
        self.messages = [self.messages[0], *self.messages[i:]]
```
逐行：
- 先算所有消息内容总字符数（生成器求和）。
- `i = 1`：**从下标 1 开始**，因为下标 0 是 system 消息，永远保留；最后一条也保留（`i < len-1`），因为它通常是当前问题。
- while 循环：只要还超预算，就"虚拟跳过"第 i 条并累加 i。
- `[self.messages[0], *self.messages[i:]]`：`*` 解包——保留 system，拼接从 i 开始的剩余消息，中间旧消息被丢弃。
- 这是最简单的"滑动窗口"记忆压缩；v2 会换成摘要式压缩。

### B3. 输出给模型（L27-L28）
```python
def llm_messages(self) -> list[dict]:
    return [m.to_llm_dict() for m in self.messages]
```
- 把内部 ChatMessage 列表统一转成模型接口要的字典列表。再次体现"内部对象、边界翻译"。

## C. LLM 路由器（v0.2）：模型分类 + 规则兜底

规则路由零成本、可测试，但覆盖不了千变万化的自然表达（"用 MCP 工具问一下"就是补了
又补的例子）。v0.2 增加一次**轻量模型分类**：让模型直接输出结构化路由 JSON，
解析失败/超时/非法输出时**自动回退 A 节的规则**。规则实现一行没删，它是兜底。

### C1. 决策记录 RouteDecision（dataclass）
```python
@dataclass
class RouteDecision:
    strategy: Strategy   # 四种策略之一
    source: str          # "llm"（模型分类）或 "rules"（规则，含兜底）
    reason: str          # 人话理由，随事件流给用户/评委看
    tier: str = "standard"   # 建议模型档位：standard 便宜快 / strong 给规划等重活
```
- 规则路径以前只返回一个 `Strategy` 枚举，现在统一返回 `RouteDecision`——
  **每个决策都带来源、理由、档位**，对应红线"每个自适应决策必须发事件、禁止静默决策"。
- `classify()`（同步，返回枚举）保留给外部兜底调用；内部新增 `_rules()` 返回完整记录。

### C2. 规则路径改造 `_rules()`
原来 `classify` 里的每个 `return Strategy.X` 都换成
`return RouteDecision(Strategy.X, "rules", "理由", 档位)`，判定顺序与条件完全不变；
`classify()` 变成一行：`return self._rules(task, registry).strategy`。
注意 plan 分支带 `"strong"`：多步规划是重活，建议用强模型（见 06 篇 `_make_plan`）。

### C3. 异步入口 `aclassify()`——短路、尝试、兜底
```python
async def aclassify(self, task, registry) -> RouteDecision:
    text = task.strip()
    if not text or self.model is None or len(registry) == 0:
        return self._rules(task, registry)          # 三种情况不浪费模型调用
    try:
        raw = await asyncio.wait_for(
            self._llm_classify(text, registry), timeout=self.classify_timeout)
        return self._parse(raw, registry)
    except Exception as exc:                        # 网络/超时/JSON 非法/策略越界
        fallback = self._rules(task, registry)
        fallback.reason = f"LLM 分类失败（{type(exc).__name__}），回退规则：{fallback.reason}"
        return fallback
```
- **三个短路条件**：空任务（必澄清）、没配模型（纯规则部署）、宿主无工具（必 direct）——
  能力边界判断永远在本地，不花一次模型调用，也不会被模型带偏。
- `asyncio.wait_for` 给分类加硬超时（默认 15s）：路由是主流程的第一道关，不能卡死。
- `except Exception` 兜底一切：**分类是增强而不是依赖**。失败理由里写清异常类型，
  事件流里能直接看到"这次为什么走了规则"。

### C4. 分类调用 `_llm_classify()`
```python
prompt = ("你是嵌入式 Agent 的任务路由器。……只输出一个 JSON 对象……\n"
          '{"strategy": "direct|react|plan|clarify", "tier": "standard|strong",'
          ' "reason": "不超过30字的中文理由"}\n'
          "策略判定标准：……\n宿主可用工具：\n{逐行 name: description}\n任务：{task}")
resp = await self.model.achat(messages, tools=None, tier="standard")
```
- `tools=None`：分类轮**不给工具清单的 function-calling 形式**，而是把工具的
  name/description 以文本列进提示词——分类只需要"看得懂有什么能力"，不调工具。
- 固定 `tier="standard"`：路由本身用最便宜快的模型/档位，成本一次调用、几十 token。
- 走的还是 SPI 的 `ModelProvider.achat`：DeepSeek、离线假模型、未来的本地模型一视同仁。

### C5. 解析与校验 `_parse()`
```python
fenced = re.search(r"\{.*\}", text, flags=re.DOTALL)   # 容忍 ```json 围栏与前后啰嗦
data = json.loads(fenced.group(0))
if data["strategy"] not in {s.value for s in Strategy}:
    raise ValueError(...)                              # 非法策略 -> 触发兜底
if len(registry) == 0 and strategy in (REACT, PLAN):
    raise ValueError(...)                              # 模型让调不存在的工具 -> 兜底
tier = data.get("tier", "standard")
if tier not in ("standard", "strong"):
    tier = "standard"                                  # 档位非法：降级而不是报错
```
- 用"截取第一个 `{` 到最后一个 `}`"容忍模型套代码块或说客套话（实测常见）。
- **校验而不是信任模型输出**：策略值必须是四枚举之一；无工具却选工具策略直接判非法；
  只有档位字段采取"非法即归一化"的宽容策略（它不影响安全，只影响成本）。

### C6. 接线：AgentCore 开关 + Loop 事件
- `AgentCore(..., llm_router=False)`：默认关闭（零额外调用、离线测试完全确定）；
  开启时构造 `AdaptiveRouter(model=model)`，把同一个模型后端注入路由器。
- `AgentLoop.astream` 改为 `decision = await self.router.aclassify(...)`，
  `STRATEGY_SELECTED` 事件数据从 `{"strategy"}` 扩成
  `{"strategy","source","reason","tier"}`（strategy 键保留，老断言不破）。
- `_make_plan(..., tier=decision.tier)`：规划轮的模型档位由路由决策建议，
  规则路由的 plan 默认 strong，LLM 路由可按需给 standard。

### C7. 实测（DeepSeek）
- "你好，简单介绍一下你自己" → `direct / llm / "闲聊自我介绍，无需调用工具"`；
- "搜索笔记里关于比赛的内容并总结" → `react / llm / "搜索笔记即可，单步工具调用"`；
- 分类输出乱码/超时时自动回退规则，事件 reason 以"LLM 分类失败（…），回退规则："开头。

## 两个文件如何协作

Loop 开始时：
1. `await router.aclassify(任务, 注册表)` → 得到 RouteDecision（LLM 或规则兜底）；
2. `Context(系统提示词)` → 建消息本；
3. 之后每轮模型回复、工具结果都 `ctx.add(...)`，超预算自动压缩；
4. 每次调模型前 `ctx.llm_messages()` 取最新快照。

## 自检

1. classify 的四个 if 顺序能不能调换？为什么"没有工具"必须排在前面？
2. "随便帮我写个周报框架，要包含本周进展和下周计划"会被路由成什么？为什么？
3. `_compact` 为什么从下标 1 开始、且保留最后一条？
4. 给 `_ACTION_HINTS` 加一个你常用的动词，并在 `tests/test_router.py` 加对应测试。
5. LLM 分类失败有哪几种情况？代码分别在哪里兜底？为什么兜底理由要写进事件？
6. 分类轮为什么 `tools=None`、tier 固定 standard？
7. 模型返回 `{"strategy":"react"}` 但宿主一个工具都没有，怎么走？为什么？
8. `llm_router` 为什么默认关闭？哪些部署形态会希望它关着？
