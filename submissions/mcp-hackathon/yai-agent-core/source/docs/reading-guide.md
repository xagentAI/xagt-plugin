# YAI Agent Core 代码学习导览（边学边造专用）

> 目标：不是"看懂每一行"，而是按顺序读完后，能向别人讲清楚 Core 怎么转起来，并能动手改。
> 建议节奏：每天 1～2 站，配合运行与小练习；卡住超过 30 分钟就先跳过，在文件里留 `# Q:` 注释。

> **配套逐行讲解**：`docs/walkthrough/` 里有每个源码文件逐块、逐行的解释（00 总览 → 09 在线 API），本篇负责路线，walkthrough 负责抠细节，两篇对照着看。

## 0. 先跑起来（10 分钟）

```powershell
cd "D:\YAI Agent Core"
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

观察三个宿主输出的差异：**同一份 Core 代码没动**，只是换了 `capabilities`，自动发现的工具、选择的策略就不同。这就是整个项目的核心主张，先建立感性认识。

## 1. 推荐阅读顺序（7 站）

### 站 1：`src/yai_core/types.py` —— 项目的"词汇表"
- 解决什么：全项目传递的数据长什么样（工具、消息、事件、策略）。
- Python 知识点：`dataclass`（数据容器）、`StrEnum`（字符串枚举）、`Literal`、类型注解、`field(default_factory=...)`。
- 读完标志：能说出 `ToolSpec / ChatMessage / ModelResponse / AgentEvent` 各自装什么。
- 小练习：给 `EventType` 加一个 `RETRY = "retry"`，想想哪个环节会发出它。

### 站 2：`src/yai_core/discovery/introspect.py` —— "能力自发现"的魔法来源
- 解决什么：宿主的普通函数如何自动变成带 JSON Schema 的工具。
- Python 知识点：`inspect.signature`、类型注解如何被程序读取、`get_origin/get_args`（Optional 原理）、字典构造。
- 关键理解：这里没有魔法，只是把函数签名"读"出来翻译成 LLM 认识的格式。
- 小练习：在 `examples/host_a_notes/capabilities.py` 加一个带默认参数的新函数，重跑 smoke，看它是否自动出现。

### 站 3：`src/yai_core/tools/` —— 注册表与执行总线
- `registry.py`：Python 知识点——类、字典封装、自定义异常（`KeyError/ValueError` 的使用场景）。
- `executor.py`：重点看三件事——权限决策、`inspect.isawaitable` 如何让同步/异步函数都能跑、为什么用 try/except 把工具错误"回灌"给模型而不是崩溃。
- 小练习：故意把工具函数改成 `raise ValueError("boom")`，观察 Agent 是否还能正常收尾。

### 站 4：`src/yai_core/kernel/router.py` —— 自适应决策的第一版
- 解决什么：凭什么选 direct/react/plan/clarify。
- Python 知识点：枚举比较、`any()/sum()` 生成器、纯函数（同样输入必同样输出，所以最好测）。
- 对照测试读：`tests/test_router.py` 每个用例就是一条决策规则的"说明书"。
- 小练习：加一个你自己的中文触发词，让"帮我看看"也能触发 react；同步加一条测试。

### 站 5：`src/yai_core/kernel/loop.py` —— Core 的心脏（最重要，慢读）
- 解决什么：策略选定后，模型与工具如何来回循环直到产出结果。
- Python 知识点（正好是你的学习清单）：
  - `async def / await`：为什么 IO 密集的 LLM 调用必须异步；
  - **异步生成器** `async ... yield`、`async for`：事件为什么能"边跑边往外吐"；
  - 控制流：plan 先拆步骤、react 循环、max_iters 兜底、clarify 递归重入。
- 调试建议：在 `_react_cycle` 每轮循环开头打印 `len(ctx.messages)`，看消息历史如何增长。
- 读完标志：能默画出"用户任务 → 模型 → 工具调用 → 工具结果 → 模型 → 最终答案"的闭环。

### 站 6：`src/yai_core/spi/` 与默认实现 —— 可替换的四个插槽
- 解决什么：为什么 Core 不绑定模型厂商、不绑定 UI、不绑定数据库。
- Python 知识点：`Protocol`（结构化子类型："只要长这样就能插进来"，不需要继承）、依赖注入（构造函数传入）。
- 对照读：`llm/openai_compat.py`（真实插槽）、`channels/collect.py`（测试插槽）、`tests/test_loop.py` 里的 `ScriptedModel`（假插槽）。
- 小练习：写一个 `EchoModel` 实现 `achat`（直接返回固定话），接进 Core 跑一次。

**加一站（v0.2）**：`src/yai_core/memory/sqlite_store.py` —— 同一个记忆插槽的第二个实现。
对照 InMemoryStore 读：表结构、scope 隔离、user_version 迁移钩子、为什么同步 SQL 直接跑在
async 方法里（见 walkthrough 第 11 章）。读完应能回答：为什么 Loop 一行没改就获得了持久记忆。

**再加一站（v0.2）**：`src/yai_core/integrations/openapi/` —— 对照第 10 章 MCP 桥读：
spec.py 的 $ref 内联与循环保护、discovery.py 的入参合并、client.py 的鉴权与响应归一。
读完应能回答：为什么一份 OpenAPI 描述就能让 Core 不写一行适配代码获得一批工具（见 walkthrough 第 12 章）。

### 站 7：`src/yai_core/core.py` 与 `batteries/fastapi_server/app.py`
- `core.py` 是门面：宿主只需要认识 `AgentCore.auto()` 和 `run()`，内部全被藏起来（门面模式）。
- Battery 展示"内核"与"外围"的边界：注意 fastapi/pydantic 是**懒加载**的，内核本体不依赖它们。
- 小练习：用 `scripts/serve_example.py` 的写法，把 host_c_companion 也变成一个 HTTP 服务。

## 2. 术语对照表（第一次读会反复遇到）

| 术语 | 在本项目里的意思 |
|---|---|
| 宿主 Host | 嵌入 Core 的现有软件（host_a/b/c，未来是 AMBRACE） |
| SPI | 宿主可替换、Core 给默认实现的接口契约（Model/Channel/Memory/Policy） |
| Adaptive Router | 决定任务走哪种执行策略的组件 |
| ReAct | 推理-调用工具-观察结果-再推理的循环 |
| Tool Bus | 统一执行工具的通道（权限、异常、结果格式化都在这） |
| Observer 事件流 | 运行过程对外发出的可观测事件，自适应决策不许黑盒 |
| Battery | 可选外围能力（HTTP 服务等），不属于内核 |

## 3. 动手实验环境

- 推荐用 VS Code 打开 `D:\YAI Agent Core`，在 `loop.py` 行号左侧点一下设断点，F5 调试 `scripts/smoke_test.py`。
- 常用命令：
  ```powershell
  .\.venv\Scripts\python.exe -m pytest            # 全部测试
  .\.venv\Scripts\python.exe -m pytest -k router  # 只跑路由测试
  .\.venv\Scripts\python.exe -m ruff check src tests examples scripts
  ```

## 4. "学懂了"自检清单

- [ ] 能不看代码画出 Core 的分层图并说出每层文件
- [ ] 能解释宿主为什么"零 Agent 代码"
- [ ] 能说出一次 react 循环中 messages 列表里依次出现了哪几种 role
- [ ] 能新增一个宿主函数并让 Agent 调用到它
- [ ] 能写一个假 ModelProvider 离线测试一条新执行路径
- [ ] 能指出哪部分代码是"内核绝不能依赖第三方"的边界

全部打勾后，再进入 Day 1-3（真实 DeepSeek 接入），那时你会清楚知道每一行在干什么。
