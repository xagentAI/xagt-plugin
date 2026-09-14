# 逐行讲解 11 · SQLite 持久化记忆：把"便签本"换成"笔记本"

> 对应文件：`src/yai_core/memory/sqlite_store.py`、`src/yai_core/spi/memory.py`。
> 读前先读第 07 章（InMemoryStore）。本章只新增一个契约实现，**不改契约、不改 Loop**。

## A. 先回顾：记忆契约长什么样

`spi/memory.py` 五个方法（注意第 2 个是**同步**方法，其余是 async）：

```python
async def append_history(self, message: ChatMessage) -> None   # 追加一条历史
def history(self) -> list[ChatMessage]                         # 取全部历史（同步）
async def put(self, key: str, value: str) -> None              # KV 写
async def get(self, key: str) -> str | None                    # KV 读
async def clear(self) -> None                                  # 清空
```

Loop 只在两个地方碰记忆（`kernel/loop.py`）：

1. 任务开始：`for msg in self.memory.history(): ctx.add(msg)` —— 把历史回放进上下文；
2. 任务结束：写 user、assistant 两条历史。

**关键认知：Loop 只认识契约，不认识具体实现。** 所以只要新类实现了这五个方法，
Loop、Core、三个 host 示例一行都不用改——这就是 SPI（插槽）的意义，也是本章最好的教学点。

## B. 为什么放 memory/ 而不是 integrations/

MCP 客户端放在 `integrations/`，因为它依赖第三方 `mcp` 包；SQLite 用的 `sqlite3`
是 Python 自带标准库，零依赖、零 extra，和 InMemoryStore 是同一层东西，所以放在 `memory/`。
判断口诀：**要装第三方包才能用的能力进 integrations，标准库能力留在本体包。**

## C. 表结构：两张表 + 一个版本号

```sql
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 自增主键，顺序以它为准
    scope TEXT NOT NULL DEFAULT 'default',  -- 会话/宿主隔离标签
    role TEXT NOT NULL,                     -- user/assistant/system/tool
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,                        -- ChatMessage.tool_calls 的 JSON 文本，无则 NULL
    tool_call_id TEXT,
    name TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_history_scope_id ON history(scope, id);  -- 按会话取历史的常用路径

CREATE TABLE IF NOT EXISTS kv (
    scope TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    PRIMARY KEY (scope, key)                -- 复合主键：同会话内 key 唯一
);

PRAGMA user_version = 1;                    -- schema 版本，迁移钩子
```

逐块解释：

- **为什么顺序用 `id` 不用 `created_at`**：CURRENT_TIMESTAMP 精度到秒，同一轮任务
  连续写两条消息可能同一秒，时间戳分不出先后；自增 id 严格递增。
- **为什么 history 要建 `(scope, id)` 索引**：查询永远是"某 scope 的全部历史，按 id 排序"，
  索引前缀就是 scope，一次索引扫描拿完。
- **KV 为什么是复合主键 `(scope, key)`**：不同会话允许有同名 key（比如都叫 "profile"），
  单 key 主键会互相覆盖。
- **为什么 tool_calls 用 TEXT 存 JSON**：SQLite 是动态类型但没有原生 list/dict；
  ChatMessage 里只有 tool_calls 是结构化字段，`json.dumps/json.loads` 往返最简单。
- **`IF NOT EXISTS`**：重复打开同一个库不报错，幂等初始化靠它。

### C1. 迁移钩子 user_version

SQLite 内置一个整数 `PRAGMA user_version`，专门留给应用存 schema 版本：

```python
version = int(conn.execute("PRAGMA user_version").fetchone()[0])
if version == 0:           # 全新数据库：建表并写版本号
    conn.executescript(_SCHEMA_SQL); conn.commit()
elif version > _SCHEMA_VERSION:   # 未来版本：旧代码打开新库，直接拒绝，避免写坏
    raise RuntimeError(...)
# version == 当前版本：什么都不做
```

以后表结构要改（v0.3 加列、加表），就在这里加 `if version == 1: ...迁移到 2` 的分支。
**注意：PRAGMA user_version 不能用 ? 参数化，版本号必须是 SQL 字面量。**

## D. 连接策略：线程、锁与 WAL

```python
self._lock = threading.Lock()
self._conn = sqlite3.connect(db_path, check_same_thread=False)
self._conn.row_factory = sqlite3.Row
if not self._is_memory:
    self._conn.execute("PRAGMA journal_mode=WAL")
    self._conn.execute("PRAGMA synchronous=NORMAL")
```

- `check_same_thread=False`：sqlite3 默认禁止"在 A 线程建连、在 B 线程使用"，
  而 FastAPI/uvicorn 会把同步函数丢到线程池，不同请求可能落在不同线程。
  关掉这个保护后，**互斥要自己负责**——所以每个方法体都在 `with self._lock:` 里。
- `row_factory = sqlite3.Row`：查出来的行能用 `row["role"]` 按列名取值，比下标好读。
- WAL（Write-Ahead Logging）：文件形态下读写不互相阻塞、崩溃更稳；内存库不需要。
  副作用是产生 `-wal`/`-shm` 两个旁车文件，所以 `.gitignore`/`.dockerignore` 要忽略它们。
- `synchronous=NORMAL`：WAL 模式下安全且更快。

### D1. 为什么 async 方法里直接跑同步 SQL（不引 aiosqlite）

契约方法是 `async def`，但 sqlite3 是同步驱动。v0.2 的每次操作都是单条小事务
（一行 INSERT / 主键点查），毫秒级返回，不会真的卡住事件循环；引入 aiosqlite 要多一个
依赖、多一套连接生命周期，收益为零。**边界要记牢**：批量导入、长事务、高并发写场景
才需要异步驱动或连接池，那时再换不迟——这是有意识的取舍，不是偷懒。

### D2. 为什么 history() 是同步的也要加锁

契约里 `history()` 不是 async（Loop 启动时直接 `for ... in history()`）。
但它同样访问连接，而别的 async 方法可能正在别的线程里写——同步方法也要进同一把锁。

## E. 字段往返：最容易错的三个边界

```python
tool_calls = None if message.tool_calls is None else json.dumps(...)
```

| 情形 | 存进去 | 读回来 |
|---|---|---|
| `tool_calls=None`（普通消息） | NULL | None |
| `tool_calls=[{...}]`（工具调用消息） | JSON 文本 | list[dict] |
| `tool_calls=[]`（空列表） | `"[]"` | **[]，不是 None** |

第三行是最容易写错的：`None` 和 `[]` 在 Python 里都是假值，图省事写
`json.dumps(x) if x else None` 就会把空列表吞成 NULL，与 InMemoryStore（原样保留 []）
行为不一致，参数化对等测试会立刻红。`tool_call_id/name` 同理：None 存 NULL，
**空字符串按空字符串存**，不折叠。

## F. UPSERT 与 scope 语义

KV 覆盖写用 SQLite 的 UPSERT（需要 SQLite ≥ 3.24，Python 3.11+ 自带版本远高于此）：

```sql
INSERT INTO kv(scope, key, value) VALUES (?, ?, ?)
ON CONFLICT(scope, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
```

`excluded` 是"这次试图插入但撞了主键的值"的固定别名。

- `clear()` 只删**当前 scope** 的两张表行；一个文件可以装多个会话，互不干扰。
- 需要多会话的宿主：构造多个 `SqliteStore(path, scope="user-a")` 实例，契约方法签名不变。

## G. 装配：from_env 与 lifespan 关闭

```python
@classmethod
def from_env(cls, env=None):
    raw = (environ.get("YAI_DB_PATH") or "").strip()
    return None if not raw else cls(raw)
```

- 返回 None 而不是抛异常："不持久化"是合法部署形态，`SqliteStore.from_env() or InMemoryStore()`
  一行完成回退，不配置环境变量时行为与改动前**完全一致**。
- `env` 参数允许测试注入假字典，绝不碰真实 `os.environ`。
- `close()` 不是契约方法（Protocol 里没有），所以 serve_example 用
  `getattr(_store, "close", None)` 探测式调用，InMemoryStore 没有这个方法就跳过。

## H. 诚实的边界（写进比赛材料也不心虚）

1. **Render 免费层磁盘是临时的**：redeploy/休眠回收后文件丢失，要"永久记忆"得挂持久卷或 VPS；
2. **历史裁剪已落地、摘要归档未做**：Context 层有 24000 字符压缩兜底；持久层的条数上限/TTL
   已在 v0.3 落地（`memory/retention.py`，由宿主按 env 注入，见第 13 章），摘要归档仍列入后续规划；
3. **单 worker + 单文件**：多进程同时写一个文件可能 `database is locked`，v0.2 用 WAL+锁覆盖单进程场景；
4. **DB 里是用户对话**：不进 git、不进镜像、不进提交快照、日志不打印内容（启动只印路径）。

## 自检

1. 为什么 SqliteStore 放在 `memory/` 而 MCP 客户端放在 `integrations/`？
2. `history()` 为什么是同步方法？为什么同步方法也要持锁？
3. `tool_calls=[]` 落库再读出应该是什么？写错会怎样？
4. `PRAGMA user_version` 的作用是什么？打开一个版本号更高的库会怎样？
5. 为什么顺序按 `id` 而不是 `created_at`？
6. `from_env()` 为什么返回 None 而不是给默认路径？
7. 为什么 v0.2 不引入 aiosqlite？什么场景下才需要？
8. 为什么 Loop / Core / 三个 host 示例不需要任何改动就能用上 SQLite 记忆？
