# 逐行讲解 13 · 历史保留策略：会"忘事"的记忆才跑得久

> 对应代码：`memory/retention.py`（新增）、`memory/inmemory.py`、`memory/sqlite_store.py`、
> `kernel/context.py`（_compact 修复）。v0.3，opt-in：不配置环境变量时行为与旧版完全一致。

## A. 为什么需要裁剪：记忆只会涨，不会自己落

SQLite 记忆落地后出现一个新问题：`history` 表只增不减。Loop 每跑一轮就追加两条
（user 任务 + assistant 最终答复，见 `kernel/loop.py` 末尾），下一轮启动时
`for msg in self.memory.history()` 全量回放给模型。跑得越久：

1. 每次请求的 token 越多，越慢越贵（评审期每一分钱都是 DeepSeek 额度）；
2. 超长上下文更容易触发模型的"注意力稀释"，答非所问；
3. 几个月前的陈旧对话永远占着上下文。

v0.3 给出两个 opt-in 开关：**条数上限**（`YAI_HISTORY_MAX_MESSAGES`）与
**存活时间 TTL**（`YAI_HISTORY_TTL_SECONDS`）。默认都不开——"忘事"是策略，
不是内核该擅自做的决定。

## B. 最大的坑：不能按"第几条"硬删

OpenAI 兼容的对话接口要求消息序列合法，其中一条铁律：

- `assistant` 消息带 `tool_calls`（"我要调工具"）之后，**必须**紧跟对应 `tool` 消息（工具结果）。

假设历史是这样（一轮任务里模型调了工具）：

```
user          "查一下订单"
assistant     tool_calls=[get_orders]     ← 工具调用的发起
tool          "订单结果..."               ← 必须跟在发起后面
user          "谢谢"
assistant     "不客气"
```

如果按"只留最近 3 条"硬删，会从第 2、3 条之间切开：`tool` 留下了、它配对的
`assistant(tool_calls)` 没了——这叫**孤儿 tool 消息**，发给 DeepSeek 直接 400。

所以裁剪边界必须落在**一轮的开头**。

## C. "轮"的定义（全章统一口径）

一条 `role == "user"` 的消息，到下一条 user 消息之前，算**一轮**：

```
user  ┐ 第 1 轮
assistant ┘
user  ┐ 第 2 轮（含工具调用）
assistant(tool_calls)
tool  ┘
user  ┐ 第 3 轮
assistant ┘
```

历史开头若有非 user 消息（理论上的边界情况），归入"第 0 轮"，与相邻轮同生共死。
裁剪只在轮与轮之间下刀，任何一轮内部都不可切。

## D. retention.py：把"下刀位置"算成纯函数

两个 Store（内存/SQLite）的删除逻辑必须**逐字节一致**，所以边界计算抽成纯函数，
放在 `memory/retention.py`，存储实现只负责"取角色序列"和"按边界删"。

### D1. 条数裁剪 count_cut：边界向后对齐

```python
candidate = len(roles) - max_messages      # 朴素切点
k = _next_round_start(roles, candidate)    # 从切点向后找第一个轮首
```

6 条消息、上限 2 条：朴素切点 = 4，而 roles[4] 正好是 user → k=4，删 [0,4)，
留最后一轮。若朴素切点落在一轮中间（比如上限 3，切点=4 之前的 3 是 assistant），
就**往后**退到这一轮结束后的下一个轮首——宁可少留，不可切轮。找不到后续轮首
（只有一轮、或单轮自身就超限）→ 返回 None，**宁可超限也不裁**。

### D2. TTL 裁剪 ttl_cut：边界向前对齐

TTL 先数"从头开始连续过期"的条数 n（`expired[i]` 由存储层按 cutoff 算好，
严格 `<`，恰好等于 cutoff 的保留），再从 n 往**前**找最近的轮首：

- 过期前缀恰好结束在轮边界（n 本身就是轮首）→ 删整轮；
- 过期前缀伸进了一轮中间 → 退回到这一轮开头，整轮保留（不能切一半）；
- **全部过期**（n == len）→ 返回 len，整库清空。空历史是合法序列，TTL 的语义
  是"过期就该删"，这一条高于条数裁剪"至少留最后一轮"的约束。

### D3. 两个边界取 max

条数裁剪和 TTL 可能同时命中，各自得到一个删除上界。两个上界都落在轮首，
较大的那个仍然是轮首，所以直接 `max(k_count, k_ttl)` 一次删完，工具对依旧完整。

## E. InMemoryStore：并行时间戳列表

ChatMessage 没有时间字段（也不该为存储策略改 `types.py` 的核心数据结构），
于是用一个与 `_history` **严格同长同序**的 `_timestamps` 列表记录每条消息的时间：

```python
async def append_history(self, message):
    self._history.append(message)
    self._timestamps.append(self._clock())   # 注入时钟，测试可拨快
    self.prune()                             # 未配置策略时立即返回 0
```

`prune()` 是非契约方法：`spi/memory.py` 的 Protocol 五个方法一个没加，
它和 `SqliteStore.close()` 同属"宿主探测式调用"的先例，内核契约保持稳定。

## F. SqliteStore：取行 → 算边界 → 按 id 删

`_prune_locked()`（调用方已持锁）三步走：

1. `SELECT id, role, created_at ... ORDER BY id ASC` 取本 scope 全部历史；
2. 复用 retention 的两个纯函数算出删除上界 k；
3. `DELETE ... WHERE id < rows[k]["id"]`（k == 行数时整 scope 清空）。

注意 TTL **不用**裸 `DELETE ... WHERE created_at < ?`——那会绕过轮对齐、
切散工具对。会话历史量级很小，统一走 Python 算边界更安全。

两个细节：

- **created_at 改由 Python 侧注入时钟写入**（列默认 CURRENT_TIMESTAMP 保留给
  外部插入）。否则测试在毫秒内跑完，DB 时钟根本不前进，假时钟管不到落库时间，
  两种 Store 就没法做对等测试。
- **构造时自动 prune 一次**：服务重启后库里可能全是过期数据，打开连接、建完
  schema 就清一遍，覆盖"重启场景"。

## G. Context._compact：同一类 bug 的另一处

`kernel/context.py` 的 `_compact()` 是**单次请求内**的字符预算压缩（与跨请求的
记忆裁剪是两层），旧实现按下标逐个丢消息，同样可能切散工具对。本批一并修复：
候补边界向后对齐到轮首，之后没有新一轮就宁可超预算也不裁。kernel 不能反向
依赖 memory 包，所以那里保留一份同源私有实现——两处规则改动时必须同步。

## H. env 解析与装配：只解析一次

`retention_from_env()` 是唯一入口：空白=未设置（静默）；0/负数/非整数=忽略并
`warnings.warn`（不崩、不静默）。`serve_example.py` 启动时解析一次，显式传给
`SqliteStore.from_env(retention=...)`，回落 InMemoryStore 时用同一组参数，
避免非法值 warning 两次。

## I. 诚实的边界

- KV（键值记忆）没有 TTL：给 kv 表加过期时间要 `ALTER TABLE`（schema v1→v2
  迁移），是第一次实战迁移，留到 v0.4 单独做。
- 裁剪不发 AgentEvent：它是存储维护，不是自适应决策，Loop 不感知；
  可观测性由 `prune()` 返回值与启动日志一行承担。
- 条数上限是"上限"不是"目标值"：轮对齐后实际保留可能少于配置值。
- 多进程/多实例共享同一个 SQLite 文件的场景仍不在支持范围（v0.2 已声明）。
- **两种实现的时间精度不同**：SQLite 侧 `created_at` 落库是**秒级**文本
  （`strftime("%Y-%m-%d %H:%M:%S")`），内存实现保留**微秒**。TTL 以秒/天为量级时两者等价，
  但当"消息时间戳与 cutoff 相差不足 1 秒"时，两种实现可能给出不同结果——不要假设它们逐比特一致。

## 自检

1. 为什么删除边界必须落在轮首？切散了会发生什么？
2. 条数裁剪的边界向哪个方向对齐？TTL 呢？为什么方向相反？
3. TTL 判定全部过期时为什么允许整库清空，而条数裁剪永远保留最后一轮？
4. `prune()` 为什么不写进 MemoryStore 契约？
5. SQLite 的 created_at 为什么改由 Python 侧写入？
6. Context._compact 和 Store 的 prune 是同一层东西吗？分别在什么时候触发？
