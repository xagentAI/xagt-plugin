# 逐行讲解 10 · `integrations/mcp/client.py`：把外部 MCP Server 的工具接进 Core

> MCP（Model Context Protocol）是"工具界的 USB-C"：任何 MCP Server 暴露的工具，
> 任何 MCP Client 都能用同一套协议调用，不用为每个服务写专用对接代码。
> 本章实现的是 **MCP Client**（我们去用别人的工具）；v0.1 红线明确不做 MCP Server。
> 知识点：可选依赖懒加载、协议适配层、闭包按值捕获、JSON Schema 清洗、
> 三种传输（内存 / stdio / HTTP）、协议返回值归一。
> 配套示例：`examples/host_d_mcp/`（自带一个本地 stdio 演示 Server）。

## 块 0 · 先搞清楚 MCP 在架构里的位置

```
AgentCore
  └── ToolRegistry            ← 工具唯一注册表，里面的每张"身份证"都是 ToolSpec
        ├── Native Tools      ← 宿主自己的函数（discovery 自动发现）
        ├── MCP Tools         ← 本章：外部 MCP Server 的工具，被包成 ToolSpec
        └── （未来）OpenAPI Tools
```
关键思想只有一句：**MCP 工具在注册表里和本地函数长得一模一样**。Router、Loop、
Executor、权限策略、事件流全部零改动——它们根本不知道工具在本机还是在远端。
适配层只负责两件事：`list_tools` 把远端工具"翻译"成 ToolSpec；调用时把
`call_tool` 的协议返回值"翻译"回普通返回值/异常。

MCP Python SDK（`pip install mcp`）2026 年已进入 **v2 稳定线**（v2.x），高层 API：

```python
from mcp import Client, StdioServerParameters
from mcp.server import MCPServer        # 写 Server 用，本章测试/示例会用到

async with Client(target) as client:    # target 三种形态，见块 3
    tools = (await client.list_tools()).tools      # 列工具
    result = await client.call_tool("add", {"a": 1, "b": 2})  # 调工具
```

## 块 1 · 模块定位与零依赖红线（L1-L19）
```python
from dataclasses import dataclass, field
from typing import Any
from yai_core.types import ToolSpec
```
- 本文件**顶层只 import 标准库和内核自己的 types**，没有 `import mcp`。
- 内核红线：`pyproject.toml` 的 `dependencies` 永远为空；mcp 放在可选依赖组
  `mcp = ["mcp>=2.0,<3"]` 里，用户 `uv sync --extra mcp` 才有。
- 这样做的好处：只想要本地工具的宿主（比如未来内嵌进 AMBRACE 的移动端）
  不会被 mcp 那一长串传递依赖（anyio/httpx/pydantic…）拖累体积。
- 测试里有一条 AST 静态检查（`test_no_toplevel_mcp_import_keeps_kernel_dependency_free`），
  用语法树保证谁都不能手滑在顶层 import mcp——**红线用测试守住，不靠自觉**。

## 块 2 · JSON Schema 白名单清洗（L22-L73）
```python
_SCHEMA_KEYS = frozenset({"type", "properties", "required", "items", "enum", ...})

def sanitize_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                cleaned[key] = {name: sanitize_schema(sub) for name, sub in value.items()}
            elif key in _SCHEMA_KEYS:
                cleaned[key] = sanitize_schema(value)
        return cleaned or dict(_EMPTY_SCHEMA)
    if isinstance(schema, list):
        return [sanitize_schema(item) for item in schema]
    return schema
```
- MCP SDK 会从 Python 类型注解自动生成工具的入参 schema，但里面夹带实现私有键，
  实测形如 `{'title': 'echoArguments', 'properties': {'text': {'title': 'Text', ...}}}`。
  个别 OpenAI 兼容接口对多余键敏感，喂给模型前递归只保留 JSON Schema 标准关键字。
- **真实踩坑（测试先抓到的）**：第一版写成"所有键都过白名单"，结果连
  `properties` 里的**属性名**（如 `text`）也被删了——白名单只该作用于 schema
  关键字层，`properties`/`$defs` 的键是用户定义的名字，必须原样保留、只清洗值。
- `cleaned or 空schema`：清洗后若为空（Server 没给 schema），给一个最小合法的
  `{"type":"object","properties":{}}`，别让下游拿到空 dict。
- `frozenset`：不可变常量集合，查找 O(1) 且不会被任何代码改坏。

## 块 3 · 连接配置 McpServerConfig（L76-L93）
```python
@dataclass
class McpServerConfig:
    alias: str
    url: str | None = None              # ① Streamable HTTP，部署形态
    command: str | None = None          # ② stdio 子进程命令
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    prefix: str = ""                    # 工具名前缀，多 Server 重名时去重
    server: Any = None                  # ③ MCPServer 实例，内存直连（测试用）
```
三种 target 对应 MCP 的三种接法：
1. **url**：`https://host/mcp`，跨网络调远端服务（X-Agent 生态里的 MCP 服务多是这种）；
2. **command+args**：SDK 帮你拉起一个本地子进程，通过 stdin/stdout 通信（stdio）。
   好处是工具运行在独立进程，崩了不拖垮宿主；`env` 可以给它单独传密钥；
3. **server**：直接传 MCPServer 实例做内存直连，不起进程、不触网——**测试专用**，
   我们的离线测试全靠它，CI 里不需要任何网络。
- `prefix`：两个 Server 都有 `search` 时，注册表会因重名报错；加 `"shop__"` 这类
  前缀即可区分。注意前缀只改**本地注册名**，远端调用仍用原名（块 6）。
- `field(default_factory=list)`：dataclass 里可变默认值不能写 `= []`（会被所有实例
  共享，经典 Python 坑），必须用工厂函数。

## 块 4 · 协议返回值归一 _flatten_call_result（L95-L112）
```python
content = getattr(result, "content", []) or []
if getattr(result, "is_error", False):
    texts = [b.text for b in content if getattr(b, "text", None)]
    raise RuntimeError("; ".join(texts) or "MCP 工具返回错误")
texts = [b.text for b in content if getattr(b, "text", None)]
if texts:
    return "\n".join(texts)
structured = getattr(result, "structured_content", None)
if structured is not None:
    return structured
return ""
```
MCP `call_tool` 返回的 `CallToolResult` 有三种信息，实测（SDK v2.2）：
- `content`：内容块列表，文本块是 `TextContent`，取 `.text`。这是 MCP **面向 LLM 的
  规范输出**，所以优先用它；
- `structured_content`：结构化结果。注意两个实测细节：普通 `return "字符串"` 会被
  包成 `{'result': '...'}`，而返回 Pydantic 模型则直接展开成 dict；
- `is_error`：**蛇形命名**（不是协议 JSON 里的 isError），工具抛 ToolError 时
  SDK 不向客户端抛异常，而是返回 `is_error=True` + 错误文本块。
- 归一策略：错误 → 抛 `RuntimeError`，交给 ToolExecutor 既有的"异常回灌模型"路径
  （和本地工具报错走同一条路）；正常 → 文本优先、结构化兜底、都没有给空串。
- 全用 `getattr(..., 默认值)` 而不是直接取属性：对 SDK 小版本差异保持韧性。

## 块 5 · connect：懒加载、建连、列工具（L141-L154）
```python
async def connect(self) -> list[ToolSpec]:
    try:
        from mcp import Client, StdioServerParameters
    except ImportError as exc:
        raise ImportError(
            "MCP 集成需要可选依赖：uv sync --extra mcp（或 pip install 'yai-agent-core[mcp]'）"
        ) from exc
    self._client = Client(self._build_target(StdioServerParameters))
    await self._client.__aenter__()
    listed = await self._client.list_tools()
    self._specs = [self._to_spec(tool) for tool in listed.tools]
    return self._specs
```
- **懒加载**：`from mcp import ...` 写在方法体内。没装 mcp 的环境导入本模块不报错，
  只有真正 `connect()` 时才提示安装命令——`raise ... from exc` 保留原始报错链。
- `Client(target)` 是异步上下文管理器，我们要把连接存起来跨多次调用使用，
  所以不写 `async with`，而是手动 `__aenter__()`，配对 `aclose()` 里的 `__aexit__()`。
- `list_tools()` 返回分页结果（`.tools` + `.next_cursor`）；v0.2 工具数量少，先取
  首页，未来接大 Server 再补游标翻页（SDK 官方教程里有分页范式）。
- 列表推导式把每个远端工具交给 `_to_spec` 翻译成 ToolSpec。

## 块 6 · _to_spec：一个远端工具 → 一张 ToolSpec（L168-L185）
```python
def _to_spec(self, tool: Any) -> ToolSpec:
    remote_name = tool.name
    local_name = f"{self.config.prefix}{remote_name}"
    schema = sanitize_schema(getattr(tool, "input_schema", None)) or dict(_EMPTY_SCHEMA)

    async def handler(**kwargs: Any) -> Any:
        result = await self._client.call_tool(remote_name, kwargs)
        return _flatten_call_result(result)

    return ToolSpec(name=local_name, description=..., input_schema=schema,
                    handler=handler, source="mcp")
```
- **闭包按值捕获**：`handler` 是异步闭包，`remote_name` 是 `_to_spec` 的局部变量，
  每次调用生成一个新闭包、各自记住自己的工具名。若图省事在循环体里用可变的
  循环变量，所有闭包最后会指向同一个名字——这是闭包经典坑，这里天然避开。
- 本地名可能带前缀，远端只认原名，所以闭包内部坚持用 `remote_name`。
- `handler(**kwargs)`：Executor 调用规范就是"关键字参数展开"，和本地函数完全一致；
  返回值交回 Executor 统一 `json.dumps`（所以字符串结果会被 JSON 编码成带引号形式，
  这是既有契约，测试里用 `json.loads` 断言）。
- `source="mcp"`：ToolSpec 早预留好的字段，`core.list_tools()` 会如实标注来源，
  评委一眼能看出哪些是外部生态工具。

## 块 7 · 生命周期与便捷函数（L134-L139、L187-L203）
```python
async def __aenter__(self) -> McpToolBridge:
    await self.connect()
    return self

async def aclose(self) -> None:
    if self._client is not None:
        await self._client.__aexit__(None, None, None)
        self._client = None

async def attach_mcp_tools(registry, config) -> McpToolBridge:
    bridge = McpToolBridge(config)
    specs = await bridge.connect()
    registry.register_many(specs)
    return bridge
```
- 两种用法：`async with McpToolBridge(cfg) as b:` 自动关连接；或手动
  `connect()/aclose()`（host_d 用后者，因为要在整个任务期间保持连接、任务结束才关）。
- `aclose()` 幂等：关完置 `None`，重复调用不报错。
- stdio 形态下 `aclose()` 会终止子进程——**不关掉就会在后台留孤儿进程**，
  host_d 用 `try/finally` 保证任何退出路径都关。
- `attach_mcp_tools` 是给宿主的一行流：建连 + 翻译 + 注册，返回 bridge 供稍后关闭。

## 块 8 · 演示 Server（`examples/host_d_mcp/demo_mcp_server.py`）
```python
from mcp.server import MCPServer
mcp = MCPServer("YAI-DemoTools")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b

if __name__ == "__main__":
    mcp.run()          # 默认 stdio 传输：stdin/stdout 即 MCP 通道
```
- 写 MCP Server 简单到"类型注解 + docstring 即 schema"，不用手写 JSON Schema。
- `mcp.run()` 默认走 stdio；也可以 `run("streamable-http", port=...)` 起 HTTP。
- 这个文件同时是教学样本：未来你想把 AMBRACE 的能力开放给别的 MCP 宿主，
  照这个样子包一层即可（那是 v1 之后的事，v0.1 红线不做 Server）。

## 块 9 · 宿主接线（`examples/host_d_mcp/run.py`）
```python
def build_config():
    url = os.getenv("MCP_SERVER_URL")                  # ① 环境变量给 URL → HTTP
    if url: return McpServerConfig(alias="remote", url=url)
    command_line = os.getenv("MCP_SERVER_COMMAND")     # ② 给命令 → stdio
    if command_line:
        parts = shlex.split(command_line, posix=(os.name != "nt"))
        return McpServerConfig(alias="stdio", command=parts[0], args=parts[1:])
    return McpServerConfig(alias="demo-stdio",          # ③ 缺省拉起自带演示 Server
                           command=sys.executable, args=[str(demo_server)])

bridge = await attach_mcp_tools(core.registry, build_config())
try:
    await stream(core, task, backend)
finally:
    await bridge.aclose()
```
- 同一份宿主代码，靠环境变量在 HTTP / stdio / 本地演示三种部署形态间切换，
  这就是"传输无关"的适配层价值。
- `shlex.split` 把命令字符串切成 argv；Windows 下 `posix=False` 保留反斜杠路径。
- host_d 还注册了一个本地函数 `host_label`：跑起来你会在工具列表里同时看到
  `native` 和 `mcp` 两种来源——统一注册表的直接证据。
- 运行：`.venv/Scripts/python.exe examples/host_d_mcp/run.py`（需 `--extra mcp`）。

## 块 10 · 部署期接线：config_from_env 与 FastAPI lifespan（线上也能调 MCP）

host_d 里"读环境变量 → 构造 config"的逻辑被收敛成可复用函数 `config_from_env`：

```python
def config_from_env(*, alias="remote",
                    url_env="MCP_SERVER_URL",
                    command_env="MCP_SERVER_COMMAND", env=None):
    environ = os.environ if env is None else env
    if url := environ.get(url_env):
        return McpServerConfig(alias=alias, url=url)          # HTTP 形态
    if command_line := environ.get(command_env):
        parts = shlex.split(command_line, posix=(os.name != "nt"))
        if parts:
            return McpServerConfig(alias=alias, command=parts[0], args=parts[1:])
    return None                                                # 没配置 → None
```
- `env=None` 时默认读 `os.environ`，测试时可传入假字典——纯函数、离线可测。
- 返回 `None` 而不是抛异常：**"不接外部 MCP"是合法部署形态**，调用方据此决定跳过。

在线服务 `scripts/serve_example.py` 用 FastAPI 的 lifespan 在进程启停时挂载/断开：

```python
@contextlib.asynccontextmanager
async def app_lifespan(_app):
    bridges = []
    try:
        from yai_core.integrations.mcp import attach_mcp_tools, config_from_env
        if (cfg := config_from_env(alias="remote")) is not None:
            try:
                bridges.append(await attach_mcp_tools(core.registry, cfg))
            except Exception as exc:                # 外部 Server 挂了是运行时常态
                print(f"[警告] 外部 MCP 挂载失败，仅提供本地工具：{exc}")
        yield                                    # ← 服务在这期间对外提供请求
    finally:
        for bridge in bridges:
            with contextlib.suppress(Exception):  # 关闭阶段任何异常都不能拖住停机
                await bridge.aclose()

app = create_app(core, lifespan=app_lifespan)
```
> v0.2 持久化记忆落地后，app_lifespan 的 finally 段同时负责关闭 SqliteStore（探测式调用 close()），见第 11 章 G 节。

逐行要点：
- **优雅降级**：MCP 挂载失败只打印警告，native 工具、`/health`、验证端点照常服务。
  外部依赖永远不能成为内核启动的单点——这是嵌入式内核的自我要求。
- `contextlib.suppress(Exception)`：停机清理阶段"尽力而为"，连接早断了也不该抛栈。
- `create_app(core, lifespan=...)`：battery 的 `create_app` 增加了可选 lifespan 形参，
  电池本身不认识 MCP，接线仍由宿主脚本决定（依赖方向不反转）。
- 镜像侧：Dockerfile 的依赖安装改为 `.[server,llm,mcp]`；Render 侧 `render.yaml`
  增加普通环境变量 `MCP_SERVER_URL=https://mcp.deepwiki.com/mcp`（公共免鉴权 DeepWiki）。
  **接哪个 MCP Server 是部署期配置，代码一行不用改。**

### 一次真实端到端（DeepSeek × DeepWiki MCP）

设置 `MCP_SERVER_URL=https://mcp.deepwiki.com/mcp` 后跑 host_d，任务
"用 MCP 工具问一下 GitHub 仓库 modelcontextprotocol/python-sdk：Client 初始化最小代码？"：
1. 第一次跑路由误判成 `direct`（不传工具清单），模型把工具调用写成了文本标签——
   规则词表缺"问一下/工具/mcp"这类**显式工具意图**；
2. 给 `_ACTION_HINTS` 补词、拉丁词改大小写不敏感匹配，并在 `tests/test_router.py`
   加 3 条回归测试（见 05 篇 A1）；
3. 重跑：路由 `react` → DeepSeek 发出标准 function call → HTTP 调远程
   `ask_question` → 真实 wiki 内容回灌 → 模型产出中文结论与代码。
这条链路（本服务 → LLM 规划 → Streamable HTTP MCP → 结果回灌 → 模型总结）
就是 X-Agent "MCP 产品化"评分项最硬的证据，且可被评审用 curl 复现。

## 测试策略（`tests/test_mcp_bridge.py` + `tests/test_battery_api.py`）
- 文件首行 `pytest.importorskip("mcp")`：最小安装（无 mcp extra）的环境整文件跳过，
  内核老测试照常全绿；CI 矩阵统一加装 `--extra mcp` 后这些用例才真正执行。
- 用块 3 的第 ③ 种形态（内存 MCPServer 实例）测：文本工具、Pydantic 结构化工具、
  ToolError 错误工具各一个，不起子进程、不触网、毫秒级。
- 端到端用例把 MCP 工具塞进真的 `ToolExecutor`（配 allow_all 策略 + CollectChannel），
  验证成功路径的事件序列和失败路径的 `ok=False` 回灌——证明对 Loop 完全透明。
- `test_config_from_env`：空环境返回 None、URL/命令两种形态的解析，纯函数离线覆盖。
- `tests/test_battery_api.py::test_lifespan_attaches_mcp_tools`：用 TestClient 跑
  lifespan，内存 MCP Server 的工具必须出现在 `/v1/tools` 且 `source=="mcp"`，
  这是线上部署形态（块 10）的离线回放。
- stdio 子进程路径、公共 HTTP MCP（DeepWiki）端到端在开发期用临时探针/示例实测，
  不进自动化测试，避免给 CI 引入网络与平台差异；实测步骤沉淀在本章块 10。

## 自检

1. 为什么 `import mcp` 必须写在 connect() 方法体内而不是模块顶层？哪条测试在守这条红线？
2. sanitize_schema 第一版误删了工具属性名（如 text），根因是什么？为什么 properties
   的键不能过白名单？
3. MCP 工具执行失败时，SDK v2 是抛异常还是返回 is_error？我们为什么要把它翻译成
   RuntimeError 再抛一次？
4. `handler` 闭包为什么用 `_to_spec` 的局部变量 remote_name，而不是直接用注册名？
   如果两个 Server 都有 search 工具，prefix 怎么配、远端收到的是哪个名字？
5. MCP 的三种连接 target 分别是什么？为什么测试选内存直连？
6. 为什么 host_d 要用 try/finally 调 aclose？不关掉 stdio 形态会留下什么？
7. 让 host_d 改接一个 HTTP 形态的 MCP Server，需要改代码吗？要改什么？
8. 本章新增的代码，哪些属于"内核零依赖"范围，哪些属于可选集成？边界由什么机制保证？
9. 线上服务启动时外部 MCP Server 不可达，为什么不能让服务启动失败？代码怎么实现降级？
10. "用 MCP 工具问一下……"第一次被路由成 direct 导致什么现象？为什么规则兜底也必须
    覆盖显式工具意图？
