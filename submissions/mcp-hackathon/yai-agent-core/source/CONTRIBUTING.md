# 参与贡献 YAI Agent Core

感谢你对 YAI Agent Core 的兴趣。本项目是一个**进程内嵌入式、自适应的 Agent 内核**：宿主软件只声明普通业务函数，Core 自动把函数变成工具、自适应选择执行策略并把全过程以事件流"喊"出来。在动手之前，请先读 [README.md](README.md) 的定位章节——我们不做又一个需要开发者自己拼装的 Agent 框架。

本文档同时是维护者本人的标准操作手册：环境怎么装、代码往哪放、提交前必须过哪些检查。

## 1. 开发环境

要求 Python 3.11+（开发与 CI 以 3.13 为准），包管理使用 [uv](https://docs.astral.sh/uv/)。

```bash
# 1. 创建并激活虚拟环境
uv venv
.venv\Scripts\activate            # Windows PowerShell；Linux/macOS 用 source .venv/bin/activate

# 2. 安装：可编辑模式 + 开发/真实模型/在线API 可选依赖（接入 MCP 工具再加 ,mcp）
uv pip install -e ".[dev,llm,server]"
uv pip install -e ".[mcp]"          # 仅在开发/运行 MCP Client 集成时需要

# 3. 验证：离线测试与冒烟，全程不需要 API Key
pytest
python scripts/smoke_test.py
```

需要跑通真实模型（DeepSeek 等 OpenAI 兼容端点）时，复制 `.env.example` 为 `.env` 并填入 Key：

```bash
cp .env.example .env              # Windows: copy .env.example .env
```

`.env` 已在 `.gitignore` 中，**永远不要把 API Key 提交进仓库**。

## 2. 架构红线（改动前必读）

1. **内核本体零第三方硬依赖**。`pyproject.toml` 的 `dependencies` 必须保持为空；openai、fastapi、mcp 等只能出现在可选依赖（`llm` / `server` / `mcp`）里，并在对应模块内**懒加载**（`integrations/mcp/` 顶层禁止 import mcp，有 AST 测试守这条线）。
2. **一切外部能力走 SPI 契约**（`src/yai_core/spi/`）：模型、通道、记忆、权限四个插槽必须可替换，Core 只依赖 `Protocol`，不依赖具体实现。
3. **事件流只有一条出口**：工具执行等过程事件由执行方收集、统一由 `AgentLoop` yield、`AgentCore.astream` 是唯一对外 emit 点，不允许出现第二条事件路径。
4. **每个自适应决策必须可观测**：新增任何"Core 自己做决定"的分支，都要通过 `AgentEvent` 发出对应事件，不允许静默决策。
5. **v0.1 不做**：MCP Server、Multi-Agent、自进化写工具、向量记忆、内置 UI、coding agent。相关讨论先进 Issue。

## 3. 代码规范

- Linter / import 排序：[Ruff](https://docs.astral.sh/ruff/)，规则集见 `pyproject.toml`（`E,F,I,UP,B`），行宽 100。
- 提交前必须本地通过：

  ```bash
  ruff check src tests examples scripts
  pytest
  ```

- 类型注解为硬性要求：公开 API 必须带参数与返回值注解；数据结构优先用 `@dataclass`，枚举用 `StrEnum`。
- 每个模块开头写模块 docstring，说明它在全景图中的位置；面向学习者，复杂逻辑块配行内注释。
- **改了源码就要同步改逐行讲解**：`docs/walkthrough/` 与代码逐块对应，行为变化时同 PR 更新对应篇目。

## 4. 测试约定

- 测试**不允许依赖网络、API Key 或外部服务**。真实协议用假模块/假端点验证，参考 `tests/test_openai_compat.py`（注入假 `openai` 模块）、`tests/test_loop.py`（ScriptedModel）与 `tests/test_mcp_bridge.py`（内存 MCPServer 实例直连，不起子进程、不触网；文件首行 `pytest.importorskip` 保证最小环境可跳过）。
- 新功能必须带测试：新策略、新工具来源、新 SPI 实现至少各一条端到端用例。
- 修 Bug 先写一个能复现该 Bug 的失败测试，再修代码让它通过。

## 5. 常见开发任务怎么做

| 想做的事 | 动哪里 | 参考 |
|---|---|---|
| 让一个新软件被 Core 适配 | 新建 `examples/host_x/`，只写普通函数 + run 脚本 | `examples/host_a_notes/` |
| 支持一家新模型厂商 | 实现 `ModelProvider` 契约（OpenAI 兼容优先复用现有 provider） | `src/yai_core/llm/`、`spi/model.py` |
| 增加一种工具来源（MCP/OpenAPI） | 产出统一 `ToolSpec` 注册进 `ToolRegistry`，执行侧不改；MCP 范式见 `integrations/mcp/` | `integrations/mcp/client.py`、`discovery/introspect.py` |
| 增加一种执行策略 | 先在 `AdaptiveRouter` 加确定性规则并补测试，LLM 分类是 v0.2 的事 | `kernel/router.py` |
| 换记忆/权限/输入输出 | 实现对应 SPI，通过 `AgentCore(..., memory=/policy=/channel=)` 注入 | `src/yai_core/spi/` |

## 6. 提交与 PR 流程

- 分支命名：`feat/xxx`、`fix/xxx`、`docs/xxx`、`test/xxx`、`chore/xxx`。
- Commit message 使用 Conventional Commits：`feat: host_a 接入 DeepSeek 真实工具调用`、`fix: provider 直接消费 Context 产出的线格式消息`、`docs: 补 06 loop 逐行讲解`。
- 一个 PR 只解决一件事；保持小步提交，不要把重构和功能混在一起。
- PR 描述需说明：改了什么、为什么、怎么验证的（贴命令与结果）、是否改动了公开 API 或 walkthrough。
- 合并前 checklist：`ruff check` 通过、`pytest` 全绿、新行为有测试、文档同步、无 Key/隐私泄露。

## 7. Issue 与讨论

- Bug 报告请附：系统与 Python 版本、复现命令、期望与实际结果、完整报错堆栈；模型相关问题注明厂商、模型名、是否离线测试可通过。
- 功能建议先描述**宿主场景与痛点**（哪个软件、原本要写什么 Agent 代码），再谈方案；与"嵌入式自适应内核"定位不符的需求可能会被建议放到 Battery 或独立仓库。

## 8. 许可证

本项目采用 MIT 许可证，提交 PR 即表示你同意你的贡献以 MIT 许可发布。
