# 从三个独立应用迁移到 Clink Node

本流程把旧部署收口到一个 Node 入口，同时保留 Core、Marketplace 与
Prediction Markets 已验证的业务能力。迁移工具不会修改源目录，也不会重放
历史支付、充值或订单。

## 1. 记录与备份

停止新流量后，备份三个应用的数据库、JSONL、加密凭证文件和 `.env`。不要
把 `.env` 或钱包密钥复制到新仓库。记录当前数据库 migration revision 和
正在进行中的 purchase/execution ID。

先停止三个旧仓库中独立运行的进程或 systemd unit，确认其端口已经释放，再
启动 Node。不要让旧服务和 Node 同时管理同一个 Core funding ledger、
Spending Mandate 或执行幂等键。

## 2. 安装 Personal Node

```bash
cd Clink
python3 scripts/install_clink_node.py --profile personal
export CLINK_HOME="$HOME/.clink"
.venv-node/bin/clink doctor
```

Personal Node 的权威本地数据库为：

```text
~/.clink/data/clink.db
```

Core 与 Marketplace 在共享文件中使用各自的 Alembic version table。Node
启动时按顺序应用 migration，不需要用户分别运行三个项目的迁移命令。
两张版本表分别为 `alembic_version_core` 与
`alembic_version_marketplace`，不会互相覆盖 migration revision。

## 3. 只读归档旧状态

```bash
.venv-node/bin/clink migrate --legacy-root /path/to/legacy-root
```

迁移器会：

- 发现 `.jsonl`、`.sqlite`、`.sqlite3` 和 `.db` 文件。
- 计算 SHA-256，复制到 `~/.clink/data/imports/` 的权限受限目录。
- 生成 `manifest.json` 并写入 Node 审计事件。
- 重复执行时跳过相同哈希的归档文件。

迁移器不会：

- 从历史记录再次扣款、充值、下单或调用商家。
- 将 Marketplace/Prediction 的状态覆盖 Core 资金账本。
- 导入私钥、助记词或 `.env`。

Core identity、funding、policy 和 audit 始终是资金事实来源。存在冲突时暂停
迁移并人工核对，不做“最后写入者胜出”。

## 4. 启动统一入口

```bash
.venv-node/bin/clink start --detach
.venv-node/bin/clink status
curl -fsS http://127.0.0.1:8170/readyz
```

Hermes 删除旧的 `clink_marketplace` 和 `clink_prediction_markets` 配置，只保留：

```text
clink_node -> http://127.0.0.1:9170/mcp
```

打开 Companion，逐项确认钱包身份、Mandate、allowance、Polymarket binding
和活动记录。不要根据旧 JSONL 的存在推断授权仍有效，必须以 Core readiness
和链上状态为准。

Node 会把受管模块生成的用户链接统一改写为 Node origin：

```text
/account/*
/x402/checkout/*
/polymarket/*
/execution/polymarket/*
```

迁移后不应再把 8019、8042、8047 或 8050 链接发给用户。

## 5. 验收

1. Node `/readyz` 和统一 MCP 正常。
2. Marketplace 搜索/preview 与 Prediction 市场搜索/preview 可用。
3. Core Policy、MistTrack 风险事实、`misttrack-policy-v1` 决策、reserve/release
   和 audit 可追踪；业务模块不能绕过 Core。
4. 在测试网完成服务购买和预测市场 preview。
5. 主网仅用新幂等键和低额度 canary，禁止重放旧 purchase/execution。
6. Node stop 后三个受管模块都退出，没有残留 runner 或占用内部端口。
7. 商家后台、管理员接口和内部 API 不会被 Node public proxy 暴露。

## 回滚

`clink stop` 后可恢复旧应用的只读或独立运行；归档迁移不修改旧数据，因此
不会破坏回滚。若已经通过 Node 产生新资金动作，回滚前必须先对账，不能让
旧服务和 Node 同时消费同一 Mandate 或幂等键。

回滚前先关闭 Node，并确认受管模块已经全部退出。恢复旧入口时使用只读或
冻结资金模式完成数据核对，确认 reservation、receipt 和 execution 状态没有
跨系统悬挂后，才允许重新开启资金执行。
