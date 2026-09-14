# 逐行讲解 09 · `batteries/fastapi_server/app.py`：把 Core 变成在线 API

> Battery = 可选外围。内核不依赖 FastAPI；只有要部署成 HTTP 服务时才用它。
> 知识点：可选依赖的导入守卫、Pydantic 请求模型、闭包捕获、路由装饰器、JSON 安全序列化。
> 配套启动示例：`scripts/serve_example.py`。

## 块 1 · 依赖守卫（L15-L21）
```python
try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError as exc:
    raise ImportError(
        "FastAPI Battery 需要可选依赖：uv pip install -e '.[server]'"
    ) from exc
```
- 模块被 import 时就尝试引入 fastapi/pydantic；没装就给出**可操作的安装提示**，而不是让用户面对一堆难懂的 traceback。
- 注意：这个文件属于 Battery，允许依赖第三方；`yai_core` 内核文件（types/kernel/spi...）依然零硬依赖。边界要清楚。

## 块 2 · 请求体模型（L24-L25）
```python
class RunRequest(BaseModel):
    task: str
```
- Pydantic 模型：声明 HTTP 请求体长什么样。客户端 POST `{"task": "..."}`，FastAPI 自动校验：缺字段/类型错会直接返回 422，并把 JSON 转成 `req.task`。
- **踩过的坑（真实记录）**：这个类最初写在 `create_app` 函数内部，FastAPI 无法把闭包里的模型识别成请求体，报 422 query 参数缺失。提到模块级后正常——所以框架的"魔法"也有边界，遇到怪错先怀疑作用域。

## 块 3 · create_app：工厂函数
```python
def create_app(core: Any, lifespan: Any = None) -> FastAPI:
    app = FastAPI(title="YAI Agent Core API", version="0.1.0", lifespan=lifespan)
    commit = os.getenv("YAI_GIT_COMMIT", "dev")
    slug = os.getenv("YAI_PROJECT_SLUG", "yai-agent-core")
```
- **应用工厂**：传入一个已组装好的 core，返回一个 HTTP app。这样同一份代码可以挂不同宿主的 core。
- `core: Any`：Battery 不反向依赖内核具体类型，避免循环依赖，也方便测试时传假 core。
- commit/slug 从环境变量读，部署 X-Agent 时注入真实 pinned commit；本地缺省 "dev"。
- 可选 `lifespan` 形参（v0.2 加）：把 FastAPI 的生命周期钩子（启动挂载外部 MCP、
  关闭断开连接）留给宿主脚本注入，电池本身不认识 MCP——依赖方向仍然是"宿主 → 电池 → 内核"。
  具体用法见第 10 章块 10。

## 块 4 · 四个路由（L33-L54）

### 4.1 健康检查（X-Agent 硬门槛）
```python
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "commit": commit}
```
- `@app.get(...)`：路由装饰器，把 URL 和函数绑定。
- 返回 dict，FastAPI 自动转 JSON。X-Agent 审核机就靠这个端点确认服务在线且 commit 与提交一致。

### 4.2 验证文件（X-Agent 硬门槛）
```python
@app.get("/.well-known/xagent-verification.json")
async def verification() -> dict:
    return {"schemaVersion": 1, "slug": slug, "commit": commit}
```
- 固定路径、固定字段（官方契约）。`/.well-known/` 是业界放站点元信息的惯例目录。

### 4.3 工具清单
```python
@app.get("/v1/tools")
async def list_tools() -> list[dict]:
    return core.list_tools()
```
- 直接复用门面方法，把"自动发现了哪些能力"暴露出去，评委 curl 一下就能看到宿主能力集。

### 4.4 执行任务
```python
@app.post("/v1/agent/run")
async def run_agent(req: RunRequest) -> dict:
    result = await core.run(req.task)
    return {
        "strategy": result.strategy.value,
        "final_text": result.final_text,
        "events": [
            {"type": e.type.value, "data": _jsonable(e.data)} for e in result.events
        ],
    }
```
- 请求体由 Pydantic 自动解析成 `req`。
- `await core.run(...)`：异步框架配异步内核，一个进程就能并发处理多个请求。
- 响应三部分：用了什么策略、最终结果、**全过程事件**（这是 YAI 的差异化：别的黑盒 API 只给结果，我们给可审计过程）。
- 列表推导式逐个事件转成可 JSON 化的字典。

## 块 5 · JSON 安全兜底（L59-L63）
```python
def _jsonable(data: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v if isinstance(v, str | int | float | bool | list | dict | None) else str(v)
```
- 事件 data 里可能混进枚举、异常对象等不能直接 json.dumps 的东西。
- `isinstance(v, 白名单类型)`：是 JSON 原生类型就原样保留，否则 `str(v)` 转字符串，保证响应永远不会因为序列化失败而 500。
- 这是"边界层做防御"的典型：内部可以灵活，对外输出必须规整。

## 块 6 · 怎么启动（对照 `scripts/serve_example.py`）
```python
core = AgentCore.auto(capabilities, _model)   # 组装内核（有 Key 用真模型，否则离线模型）
app = create_app(core)                        # 包成 HTTP 应用
```
启动脚本还做了两件部署相关的小事：
- `load_dotenv()`：自动读项目根 `.env`（Key、base_url、slug 都在里面），不用手动 set 环境变量；
- `YAI_GIT_COMMIT` 留空时自动执行 `git rev-parse HEAD` 取 40 位 commit——本地直跑永远和当前代码同源。

本地直跑（**宿主机统一用 8001**；8000 是容器内端口，且本机 8000 可能被别的程序占用）：
```powershell
uv run uvicorn scripts.serve_example:app --host 127.0.0.1 --port 8001
```
然后：
```powershell
curl http://localhost:8001/health
curl -X POST http://localhost:8001/v1/agent/run -H "Content-Type: application/json" -d '{"task":"列出全部笔记"}'
```

## 块 7 · 容器化部署（对照 `Dockerfile` 与 `docker-compose.yml`）
端口约定：**容器内永远监听 8000**（Dockerfile 的 EXPOSE、HEALTHCHECK 都打 8000），宿主机映射 `8001:8000`。这样镜像可以原样部署到任何机器，宿主机端口冲突只改映射、不改镜像。

Dockerfile 的几个教学点：
```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/   # 从官方 uv 镜像里直接拷二进制
ARG YAI_GIT_COMMIT=dev
ENV YAI_GIT_COMMIT=${YAI_GIT_COMMIT}                      # 构建时把 pinned commit 烤进镜像
ARG INDEX_URL=https://pypi.org/simple
ENV UV_INDEX_URL=${INDEX_URL}                             # 网络受限时构建参数换国内镜像源
HEALTHCHECK ... CMD python -c "urllib 请求 /health ..."   # 容器级健康检查，打同一个端点
```
- **commit 在构建时固化**：镜像里没有 `.git`（被 `.dockerignore` 排除），运行时取不到哈希，所以用 `--build-arg YAI_GIT_COMMIT=$(git rev-parse HEAD)` 在构建期注入。注意 `.env` 里不要留 `YAI_GIT_COMMIT=` 空行——空值会在运行时覆盖镜像里烤好的值。
- `.dockerignore` 把 `.env`、`.venv`、`.git`、`docs/` 全部挡在镜像外：密钥不进镜像、镜像只装跑服务需要的东西。
- 一键起：`docker compose up --build`（compose 经 `env_file: .env` 注入密钥）。
- 踩坑记录：容器内访问官方 PyPI 会超时，构建时加 `--build-arg INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`；宿主机端口被占时换宿主端口（如 8002:8000），容器内 8000 不动。
- **PaaS 平台的端口约定**：Render 这类平台不让你自己决定监听端口，它会注入 `PORT` 环境变量（Render 默认 10000），只把流量转发到容器的这个端口。所以 CMD 写成 shell 形式 `--port ${PORT:-8000}`：自管环境没有 `PORT` 就听 8000，上了平台自动听平台指定的端口。同理，平台还会注入"本次部署的 commit"（Render 是 `RENDER_GIT_COMMIT`），启动脚本按 `YAI_GIT_COMMIT → RENDER_GIT_COMMIT → git HEAD → dev` 的顺序解析，且只认完整 40 位哈希（镜像里烤的默认值 `dev` 不是合法哈希，会被自动跳过，平台注入的真实 SHA 才会生效——这是 Render 首部署时实测出来的坑），验证端点在任何环境都能报出真实版本。这就是"一次构建、处处可部署"的写法：**环境差异全部走环境变量，代码不写死。**

## 一次 HTTP 请求的完整链路
```
客户端 POST /v1/agent/run
  → Pydantic 校验请求体
  → core.run(task)
      → Router 选策略 → Loop 跑 ReAct → Executor 调宿主函数 → 事件流
  → 结果经 _jsonable 规整
  → JSON 响应回客户端
```

## 自检

1. 为什么 Pydantic 模型必须放模块级而不能放在 create_app 里？
2. `/health` 里的 commit 为什么要从环境变量读，而不是写死？
3. 为什么响应里要带 events？这对比赛评审意味着什么？
4. `_jsonable` 防的是什么问题？删掉它、在事件 data 里放一个枚举会怎样？
5. 把 host_c_companion 也包成一个 app（改 serve_example 即可），用 curl 跑通。
6. 为什么 commit 要在构建镜像时用 ARG/ENV 固化，而不是容器启动后再读 git？
7. 容器内端口为什么固定 8000、宿主机却映射 8001？端口冲突时该改哪一边？
8. 部署到 Render 时为什么不需要改代码就能监听平台端口？`${PORT:-8000}` 这种写法叫什么、解决了什么问题？
