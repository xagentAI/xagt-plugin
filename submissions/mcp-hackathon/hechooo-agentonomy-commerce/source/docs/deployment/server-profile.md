# Clink Node Server Profile 部署

Server Profile 用于多用户或团队自托管。它复用 Personal Profile 的业务协议，
但将状态、事件、密钥和业务模块切换为生产基础设施。

## 拓扑

```text
HTTPS ingress
  -> Clink Node HTTP :8170
  -> Clink Node MCP  :9170
       |-> Core services
       |-> Marketplace API / MCP
       `-> Prediction Markets API / MCP

PostgreSQL  <- 权威状态与 transactional outbox
Redis       <- 事件投递
Vault       <- Node 内部 token 与加密主密钥
```

只有 Node 的 HTTP/MCP 经过 HTTPS 对外提供。Core 和业务模块端口应位于私网，
不要直接暴露 8015-8019、8040-8048、8050、9040 或 9050。

Node 同时是所有用户交互页面的唯一 public origin：

```text
https://clink.example.com/account/*
https://clink.example.com/x402/checkout/*
https://clink.example.com/polymarket/*
https://clink.example.com/execution/polymarket/*
```

Node 只代理完成钱包绑定、购买确认和场所签名所需的白名单路径，不代理
Marketplace 商家后台、管理员接口或任意 `/internal/*` 路由。

## 配置

```bash
python3 scripts/install_clink_node.py --profile server
export CLINK_HOME="$HOME/.clink"
cp clink.node.server.example.toml "$CLINK_HOME/config.toml"
chmod 600 "$CLINK_HOME/config.toml"
```

通过服务管理器或 Secret Manager 注入以下环境变量，不要写入 Git：

```text
CLINK_DATABASE_URL=postgresql+psycopg://...
CLINK_REDIS_URL=redis://...
CLINK_VAULT_ADDR=https://vault.internal
CLINK_VAULT_TOKEN=...
CLINK_PUBLIC_BASE_URL=https://clink.example.com
```

外部模块必须把生成给用户的链接指回 Node，而不是模块自己的私网地址：

```text
CLINK_ACCOUNT_PUBLIC_BASE_URL=https://clink.example.com
MARKETPLACE_PUBLIC_BASE_URL=https://clink.example.com
PREDICTION_MARKETS_ACCOUNT_BINDING_CONSOLE_BASE_URL=https://clink.example.com
PREDICTION_MARKETS_EXECUTION_CONSOLE_BASE_URL=https://clink.example.com
```

受管模式会由 Node 自动注入这些值。外部模块模式由部署平台注入，并应在
上线检查中确认返回链接均使用 HTTPS Node 域名。

如果 Prediction Account Binding 和 Execution 单独部署，可用配置文件中的
`[modules.prediction-markets.services]`，或环境变量覆盖：

```text
CLINK_PREDICTION_MARKETS_ACCOUNT_BINDING_SERVICE_URL=http://prediction:8047
CLINK_PREDICTION_MARKETS_EXECUTION_SERVICE_URL=http://prediction:8042
```

Core 五个服务也可分别通过 `CLINK_CORE_*_SERVICE_URL` 覆盖。Node 会生成和
管理内部 token，业务模块不应再各自生成不同的 Core token。

### Hosted execution wiring

Hosted Facilitator 与 Core authority 是独立的生产进程，二者只应通过私网
HTTPS 互通。Hosted Facilitator 的配置使用以下精确环境变量；值由部署平台的
Secret Manager 注入，仓库和 systemd unit 只保存 secret reference：

```text
CLINK_FACILITATOR_ENV=production
CLINK_HOSTED_PUBLIC_ORIGIN=https://facilitator.example.com
CLINK_HOSTED_POSTGRES_URL=secret://clink/hosted/postgres-url
CLINK_HOSTED_REDIS_URL=secret://clink/hosted/redis-url
CLINK_HOSTED_RESPONSE_KEY_REF=secret://clink/hosted/response-key
CLINK_CORE_AUTHORITY_ORIGIN=https://core.internal.example
CLINK_CORE_INTERNAL_API_TOKEN=secret://clink/core/internal-api-token
```

Core 使用 `CLINK_FACILITATOR_MODE=hosted` 和一组共享的
`CLINK_HOSTED_FACILITATOR_*` enrollment 参数。Node 只把这些 Hosted 凭据注入
Core 子进程，不注入 Marketplace 或 Prediction Markets。生产必须配置严格的
`CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS` JSON object；每个 target 都要提供
`origin` 和该链独立的 `server_public_jwk`：

```text
CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS='{"eip155:8453":{"origin":"https://base-facilitator.internal.example","server_public_jwk":"<resolved-base-response-jwk-json>"},"eip155:137":{"origin":"https://polygon-facilitator.internal.example","server_public_jwk":"<resolved-polygon-response-jwk-json>"}}'
```

`CLINK_HOSTED_FACILITATOR_NODE_ID`、`CLINK_HOSTED_FACILITATOR_TENANT_ID`、
`CLINK_HOSTED_FACILITATOR_WALLET_BINDING_ID`、
`CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN` 和
`CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY` 属于同一个 enrollment，值应由
Secret Manager 注入；origin 必须是私网 HTTPS，response JWK 必须是对应 chain
target 的受信公钥。不要把 token、私钥或 JWK 明文写入 `config.toml`。

Core 的 Hosted 经济 rail 只开放 Base (`eip155:8453`) 与 Polygon
(`eip155:137`) mainnet。Sepolia/Amoy 仅用于显式 rehearsal profile，不能无条件
进入生产 capability。旧的单 Base `CLINK_HOSTED_FACILITATOR_URL` +
`CLINK_HOSTED_FACILITATOR_SERVER_PUBLIC_JWK` 可在迁移窗口使用；Core 会把它显式
生成 Base target，绝不会把 Base endpoint 当作其他 chain 的 fallback。生产
启动 gate 未通过时必须保持 disabled。

## Telegram Mini App 与 Hermes

生产变更、只读 smoke、立即回滚条件和证据边界见
[`docs/operations/telegram-miniapp-runbook.md`](../operations/telegram-miniapp-runbook.md)。
该手册会明确区分“已在本地验证”和“仍需在生产验证”；在完成生产 smoke 前，
不得把真实 Telegram、PostgreSQL、Redis、Vault、Caddy 或 Hermes 恢复写成已验证。

Mini App 默认关闭。关闭时 Node 不创建 Hermes client 或 Mini App Redis
traffic guard，`/miniapp/`、对应静态资源和 `/miniapp/api/*` 均返回 404；这不会
改变 Core、Marketplace 或 Prediction Markets 的 readiness。

Hermes API Server 必须只监听 loopback。先锁定待发布的 Hermes 版本与制品，再从
该版本的权威文档或实现确认只读健康入口；本仓库只约束 loopback base URL，并未
定义 Hermes 的健康路径，不能默认假定为 `/health`。确认后在同一台机器上检查，
不要把 8642 端口加入公网 ingress。下面的占位符不得原样执行：

```bash
curl -fsS http://127.0.0.1:8642/<LOCKED_VERSION_HEALTH_PATH>
```

四项凭据只写入当前配置选择的 SecretStore。命令没有 value 参数，并通过
非回显提示读取值：

```bash
.venv-node/bin/clink secret set telegram-miniapp-bot-token
.venv-node/bin/clink secret set hermes-api-server-key
.venv-node/bin/clink secret set miniapp-cookie-key
.venv-node/bin/clink secret set hermes-session-key
```

`miniapp-cookie-key` 和 `hermes-session-key` 至少为 32 bytes。四项值不得写入
TOML、环境变量、systemd `Environment=`、ManagedEnvironmentBuilder 或任何子进程
环境。不要复制旧 `.env`，也不要把 `.env`、SecretStore 文件或生产凭据放入 Git、
安装包、日志和诊断输出。

完成 SecretStore 写入后，在 `config.toml` 显式启用：

```toml
[miniapp]
enabled = true
hermes_base_url = "http://127.0.0.1:8642"
auth_max_age_seconds = 300
session_ttl_seconds = 86400
connect_timeout_seconds = 3
read_timeout_seconds = 60
max_stream_seconds = 900
max_active_runs_per_subject = 1
ip_general_limit = 240
session_exchange_limit = 10
subject_general_limit = 120
message_submit_limit = 12
operation_link_limit = 12
stop_limit = 12
traffic_window_seconds = 60
max_sse_per_subject = 1
sse_lease_ttl_seconds = 960
```

安全配置也可用对应的 `CLINK_MINIAPP_*` 环境变量覆盖，例如
`CLINK_MINIAPP_ENABLED=true` 和
`CLINK_MINIAPP_HERMES_BASE_URL=http://127.0.0.1:8642`。boolean 只接受小写
`true` 或 `false`。Hermes URL 只接受无凭据、无 query/fragment、无业务 path 的
loopback HTTP URL。并发 run 数和每 subject SSE 数当前必须严格为 1。

Server Profile 启用 Mini App 时必须已有 `CLINK_REDIS_URL`，Node 会使用共享
`RedisMiniAppTrafficGuard`；Redis 异常时 Mini App 固定 fail closed，不回退内存。
Personal Profile 才使用进程内 Memory guard。

公网 Caddy 必须覆盖而不是透传客户端提供的可信 IP header。下例假设整个 Node
origin 都反代到 8170；Hermes 端口不在其中：

```caddyfile
node.example.com {
    reverse_proxy 127.0.0.1:8170 {
        header_up -X-Agentonomy-Client-IP
        header_up X-Agentonomy-Client-IP {remote_host}
    }
}
```

不要把 `X-Forwarded-For` 当作 Mini App 限流身份。Node 仅在直连 peer 为
loopback 时接受单一、规范的 `X-Agentonomy-Client-IP`。

重启 Node 后执行：

```bash
.venv-node/bin/clink doctor --json
curl -fsS http://127.0.0.1:8170/readyz
curl -fsS https://node.example.com/miniapp/
```

`doctor` 只报告四项凭据是否齐全，不输出值。Hermes 或 Mini App traffic backend
不可用只使 Mini App 请求失败，不得把业务模块伪报为 not ready。

最后在 BotFather 的 `/setmenubutton` 中把现有 Telegram Bot 菜单按钮指向
`https://node.example.com/miniapp/`。不要把 Bot token 放入命令行参数、URL、shell
history 或 Caddy 配置。

回滚时先把 Telegram 菜单按钮恢复到原入口，再把 `[miniapp].enabled` 改为
`false` 并重启 Node；确认 `/miniapp/` 和 Mini App API 返回 404，同时 `/readyz`
仍由 Core、Marketplace 与 Prediction Markets 决定。凭据保留在 SecretStore 便于
受控回滚；如因安全事件回滚，应在对应 SecretStore 和 Telegram/Hermes 控制面轮换。

## 启动与检查

```bash
.venv-node/bin/clink doctor --json
.venv-node/bin/clink migrate
.venv-node/bin/clink start --detach
.venv-node/bin/clink status --json

curl -fsS http://127.0.0.1:8170/healthz
curl -fsS http://127.0.0.1:8170/readyz
```

`healthz` 表示 Node 进程可响应；只有 `readyz` 为 `ready` 才能接收 Agent
流量。外部模块任一未就绪时，Node 不会伪装成 ready。

## 上线检查

1. PostgreSQL migration 已完成，备份和恢复演练通过。
2. Redis 不可用时，outbox 仍保留未投递事件，恢复后只投递一次。
3. Vault token 使用最小权限和可轮换认证，不使用 root token。
4. HTTPS ingress 限制请求体、超时和来源；内部端口仅私网可达。
5. Marketplace 与 Prediction Markets 只能通过同一个 Core 控制面执行资金动作。
6. 主网开关默认关闭，先在测试网和低额度 canary 验证。
7. 审计记录能关联 user、agent、action、policy、receipt 和 tx hash。
8. Account、checkout 和 Polymarket 链接全部使用 Node HTTPS origin。
9. `/merchant/*`、`/admin/*` 和 `/internal/*` 不能通过 Node public ingress 访问。

## 运行方式

生产环境建议使用 systemd、Kubernetes 或容器编排运行 Node 及外部模块。
`clink start --detach` 适合单机验证，不替代生产进程监督和集中日志。
