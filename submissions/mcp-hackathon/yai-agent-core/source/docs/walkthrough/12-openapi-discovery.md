# 逐行讲解 12 · OpenAPI 发现：让任意 REST API 零适配变成工具

> 对应目录：`src/yai_core/integrations/openapi/`（spec.py / discovery.py / client.py）。
> 读前先读第 10 章（MCP 桥）——本章与它同构，只是"外部能力"从 MCP Server 换成了 REST API。

## A. OpenAPI 是什么，为什么它能做"发现"

OpenAPI（前身 Swagger）是 REST API 的**机器可读说明书**：一个 JSON/YAML 文件里写清楚了
有哪些路径（paths）、每个路径支持哪些 HTTP 方法（operations）、要什么参数、请求体长什么样、
怎么鉴权。主流后端框架（FastAPI、Spring、NestJS）都能自动导出它。

MCP 是"专门为 AI 工具设计的协议"；OpenAPI 是"互联网上已经存在几十年的 REST 世界的说明书"。
YAI 两者都接：MCP 面向新一代工具生态，OpenAPI 面向存量的海量 REST API。**发现的含义**：
宿主只要给一个 spec 地址，Core 自动读出工具清单并注册，不用为每个 API 手写一个函数。

## B. 三个文件的分工（先记住这张图）

```text
spec.py       载入（dict/文件/URL）→ 版本校验 → 内部 $ref 内联展开 → (spec, notes)
discovery.py  纯函数：spec + config → list[OperationPlan]（名字/入参/方法/路径/鉴权）
client.py     桥：connect() 串起前两步并生成 ToolSpec；handler 闭包负责真实 HTTP 调用
```

和 MCP 桥一样：顶层不 import httpx/pyyaml（内核零硬依赖），全部在函数里懒加载，
缺依赖时报 `uv sync --extra openapi`。

## C. spec.py：载入、校验、$ref 展开

### C1. 三选一载入与版本闸

`load_spec` 按 `config.spec / config.path / config.url` 三选一：文件读字节（先查
`max_spec_bytes` 体积闸），URL 用 httpx 拉取（测试时注入 MockTransport）；`.yaml/.yml`
或 content-type 含 yaml 才 import pyyaml，其余按 JSON 解析。然后两道版本闸：

- 没有 `openapi` 字段但有 `swagger: 2.x` → 明确报错让用户先转 OpenAPI 3；
- 版本号不是 3 开头 → 报错（v0.2 不支持 3 之外的世界）。

### C2. $ref 是什么，为什么要展开

OpenAPI 复用结构靠 JSON Reference：`{"$ref": "#/components/schemas/Pet"}` 指向文档内
另一个节点。模型看不懂 $ref，所以发现前要**内联展开**。`resolve_refs` 是一次带"展开栈"的
递归遍历：

- 内部引用（`#/` 开头）：沿 JSON Pointer 找到目标，深拷贝后递归展开；
- **循环引用**（Category.children.items 指回 Category）：如果当前 ref 已在展开栈里，
  说明绕成环了，停止展开、把 `{"$ref": ...}` 原样留下并记一条 note——否则无限递归；
- **外部引用**（指向另一个 URL/文件）：v0.2 不跨文档抓取，原样保留 + note；
- 3.1 允许 $ref 带兄弟键，内联后兄弟键覆盖同名属性。

notes 是这个模块的一贯设计：**遇到不完美的输入不静默、不崩溃，降级处理并留痕**，
启动日志打印给宿主看。

## D. discovery.py：operation → 工具

### D1. 工具命名（两条规则 + 去重）

1. 有合法 `operationId`：驼峰转蛇形（listPets → list_pets）、非法字符变下划线、截 64；
2. 没有：用方法+路径合成（`GET /pets/{petId}` → `get_pets_pet_id`：去花括号、连字符转下划线、
   驼峰转蛇形、全小写）。
同一 spec 内撞名追加 `__2/__3` 并记 note；**跨来源（native/mcp/openapi）撞名不在这处理**——
ToolRegistry.register 本来就直接报错，让宿主的 prefix 去解决。

### D2. 入参 schema 的合并（最需要细心的一段）

工具的入参是一个扁平 JSON Schema（object），来源有三处：

- **path 参数**（`in: path`）：OpenAPI 规定恒必填，强制进 required；调用时填进 URL 模板；
- **query 参数**（`in: query`）：按声明决定是否必填；header/cookie 参数 v0.2 直接忽略
  （不暴露给模型，避免模型伪造内部头）；
- **requestBody（application/json）**：schema 是 object 就**拍平合并**（Pet 的 id/name/category
  变成工具的顶层入参，required 并集去重保序）；是数组等非 object 类型就包成一个 `body` 入参。

每个子 schema 都过一遍 `sanitize_schema`（第 10 章已见过，本批次它归位到 `tools/schema.py`，
MCP 桥和 OpenAPI 桥共用）。

### D3. 过滤与截断

- `include_paths / exclude_paths`：按路径**前缀**白/黑名单（先白后黑）；
- `read_only=True`：只留 GET/HEAD——在线演示服务的安全闸，写操作不暴露到公网；
- `max_operations=40`：超出截断并记 note，防止一个巨型 spec 注册几百个工具撑爆系统提示词。

工具描述统一成 `[METHOD /path] summary description`，截 1000 字符——模型一眼知道这工具打哪。

## E. client.py：注册与执行

### E1. connect 做四件事

载入+展开（spec.py）→ 发现计划（discovery.py）→ 解析 base_url（override > servers[0]，
相对地址按 spec 的 URL 补全）→ 建 `httpx.AsyncClient` 并把每个 plan 闭包成 ToolSpec。
同时做**鉴权审计**：oauth2/basic/mutualTLS 暂不支持，注册期只记 note（不阻断）。

### E2. 一次调用的完整路径（handler 闭包）

```text
模型给出参数 kwargs
  → _auth_for：按 security 挑方案（bearer→Authorization 头；apiKey→头/query），
              令牌只从环境变量读，缺失在【调用期】抛错（注册期不报错，允许先发现后配钥）
  → _build_path：path 参数 quote(safe="") 填模板（参数里的 / 也编码，防路径穿越）
  → _build_query：query 参数组装；bool → true/false；list 交给 httpx 展开成重复键
  → _build_body：拍平型按 body_fields 重组 dict；包裹型取 body
  → client.request(method, url, params, json, headers)
  → 响应归一：204→""；非 2xx→RuntimeError（走工具错误事件通道）；
             JSON content-type→.json()；文本超 max_result_chars(16000)→截断加 …[truncated]
```

为什么令牌缺失是**调用期**而不是注册期报错：发现是"看菜单"，调用才是"点菜"；
宿主可能先把工具清单展示出来，稍后才配置密钥。

### E3. 为什么用 httpx 而不是 requests

- 全栈异步：handler 是 async 闭包，跑在 Loop 的事件循环里，不能用同步 requests 阻塞循环；
- `MockTransport`：测试可以不触网地断言 method/url/headers/body，这是选型的决定性理由；
- 同步拉 spec 用短生命周期的 `httpx.Client`（只在启动时跑一次），执行期统一 AsyncClient。

## F. 安全边界（写进比赛材料）

1. 在线演示端点 `read_only=True` 硬编码，公网只暴露 GET/HEAD；
2. 令牌只从环境变量读，不进 spec、不进日志、不进事件；
3. path 参数全编码；非 2xx 不把响应体直接喂模型（抛错并截断 500 字符）；
4. 结果文本 16000 字符截断（对照 Context 24000 上限，给模型的工具结果不能反客为主）；
5. 不支持的鉴权方案显式记 note，绝不"假装支持"发匿名请求到需要鉴权的写接口
   （需要鉴权却没令牌 = 调用期 RuntimeError）。

## G. 测试怎么做到全程离线

所有 HTTP 都不真实发出：`httpx.MockTransport(handler)` 接收 request、返回预制 response，
还能在 handler 里**断言请求本身**（方法、路径、query 重复键、Authorization 头、JSON body）。
spec 用仓库内 `tests/fixtures/petstore.min.json`（含 $ref、递归 schema、bearer/apiKey、404）。
这就是"测试不触网"纪律在集成层的标准打法，和 MCP 桥用内存假 server 是同一个思想。

## 自检

1. 为什么 OpenAPI 发现能做到"零适配接入"？它依赖 spec 里的哪些信息？
2. 循环 $ref 和外部 $ref 分别怎么处理？为什么不能一律递归展开？
3. object 型 requestBody 和数组型 requestBody 生成的入参 schema 有什么不同？
4. path 参数为什么强制必填？为什么 quote 要 `safe=""`？
5. 令牌缺失为什么在调用期而不是注册期报错？
6. read_only 过滤为什么是在线演示服务的硬要求？
7. 为什么选 httpx？MockTransport 在测试里替代了什么？
8. sanitize_schema 为什么从 mcp/client.py 归位到 tools/schema.py？
