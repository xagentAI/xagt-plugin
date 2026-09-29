# Clink Marketplace

Clink Marketplace 是面向 Agent Commerce 的可信服务市场。它把 CDP Bazaar、Clink peer Registry 和商家主动提交的 Manifest 汇聚成统一目录，由 Clink 本地完成身份、域名和实时 x402 三层复验，再让 Hermes 搜索、比较、预览并购买服务。

```text
Bazaar / peer Registry ──发现──┐
                              ├─> Clink 可信目录 ─> Hermes 搜索/比较/购买
商家 SIWE + Manifest ──入驻───┘              |
                                             v
                           Clink Core 授权/风控/预算/支付/审计
```

Marketplace 不持有用户私钥，也不是资金控制面。`clink-core` 是唯一可以批准策略、预留额度、结算支付和写入审计记录的组件；Hermes 只连接 `clink_marketplace` MCP，不直接调用 Core。

详细设计见 [产品与技术架构](docs/architecture.md)，生产部署见 [运维手册](docs/operations.md)。

## 最终能力

- 从 CDP Bazaar 和任意数量的 Clink peer Registry 增量同步服务。
- 将 Registry 数据视为候选线索，绝不继承外部可信状态。
- 商家通过 SIWE 登录，提交或认领 Clink Manifest，并签署 EIP-712 `ManifestClaim`。
- 通过 `/.well-known/clink-verification.json` 验证域名控制权。
- 实时请求服务 endpoint，严格比对 x402 `scheme + network + asset + amount + payTo`。
- 公开经过实时 402 复验的 `registry_verified` 服务，以及完成商家身份闭环的 `clink_verified` 服务。
- 为 Hermes 提供搜索、详情、可解释报价比较、购买预览、执行和查询。
- 通过 Core 原子执行 action、policy、spending reserve、settle/finalize 和 audit。
- 每个报价显式返回支付能力：`clink_allowance` 服务 Clink-native 商家；`clink_payer_proxy` 让兼容的外部 x402 商家在 Core mandate 额度内自动购买；`external_x402_signature` 是不兼容场景的逐笔签名兜底。Manifest 元数据不能自行选择支付轨道。
- 首次成功调用把服务结果瞬时返回给 Hermes；数据库只保存 input/output hash、状态、时延和 Core 引用。
- 基于可重放事件计算身份、报价一致性、可用率、支付、交付和争议信誉。
- 后台 worker 隔离运行 Registry 同步、offering/domain 复验、`payment_submitted` 对账和购买 finalize 重试。

## 两条供应增长路径

1. **Clink 主动补充**：研发团队从 Bazaar/peer Registry 批量发现候选服务，完成标准化和候选池建设，再邀请商家 claim。
2. **商家主动迁移**：商家直接登录控制台，提交 Clink Manifest，完成钱包、域名和实时 x402 验证后发布。

两条路径最终进入同一套 canonical Provider/Offering 模型。同一域名不会因为 Registry 来源不同而创建重复商家。

### 首批 Bazaar 目标供应

Worker 每轮会在全量分页同步之外，额外通过 Bazaar discovery search 定向发现以下首批供应能力：

| 类别 | 目标能力/品牌 |
|---|---|
| Data | CoinGecko、Nansen、Allium |
| Search | Firecrawl、Exa |
| Infrastructure | Alchemy、Pinata |
| Inference | Venice、ElevenLabs |
| Media | dTelecom |

定向发现不使用 `MARKETPLACE_BAZAAR_NETWORK` 或 `MARKETPLACE_BAZAAR_MAX_USD_PRICE` 过滤，否则 Base-only 或高于试购价格上限的服务会从候选池消失。网络和价格限制仍在 Agent 搜索、报价和购买阶段执行。

Clink 会保留 Bazaar 返回的真实 Provider 身份，并将品牌关系标为 `first_party`、`branded` 或 `powered_by`。例如调用 Venice 的第三方转售服务仍以第三方 Provider 名称入库，不能冒充 Venice 官方服务。上述目标首先进入 `discovered` 候选池；Clink 本地复验实时 402 条款后可进入低额度 `registry_verified` 目录，商家完成 claim 和三层复验后再升级为 `clink_verified`。

`/healthz` 只返回轻量 readiness 投影（API、worker、Registry 和 Core），不计算或返回运营 analytics。认证后的 `GET /admin/status` 才会提供 `metrics` 和 `supply_targets`，其中后者逐项显示 `missing / discovered / claimed / registry_verified / clink_verified` 及候选数量，便于运营确认首批供应覆盖。若需要替换清单，可配置 `MARKETPLACE_BAZAAR_TARGETS_JSON`；留空即使用上述默认清单。

## 信任状态

```text
Provider: discovered -> wallet_verified -> domain_verified -> active -> suspended
Offering: discovered -> registry_verified
          discovered -> submitted -> verifying -> verified / stale / rejected / disabled
```

Bazaar 导入后默认是 `discovered`。Clink 对 endpoint 和实时 402 的 `scheme + network + asset + amount + payTo` 完成独立复验后，Offering 可成为 `registry_verified`：它可以搜索和购买，但单笔默认不超过 `0.1 USDC`。EVM x402 v2 `exact` + EIP-3009 服务在 Core Universal Payer 和对应链 allowance ready 时可走 `clink_payer_proxy`；不兼容服务回落到逐笔 `external_x402_signature`。商家完成 claim、域名证明和实时 402 验证后，Provider 成为 `active`，Offering 成为 `verified`，对外信任等级为 `clink_verified`，并可按 allowlist 使用 `clink_allowance`。

低信任层单笔上限通过 `MARKETPLACE_REGISTRY_VERIFIED_MAX_USD` 配置，默认 `0.10`。该限制由 Marketplace 在创建 preview 时强制执行，不能由 Registry 或 Manifest 元数据覆盖。

## Agent MCP

默认地址：`http://127.0.0.1:9050/mcp/`

Hermes 可见的工具只有：

- `search_clink_services`
- `get_clink_service_details`
- `compare_clink_service_quotes`
- `create_clink_purchase_preview`
- `execute_clink_purchase`
- `get_clink_purchase`
- `clink_marketplace_health`

商家入驻、Registry 同步和管理员操作不会暴露给 Hermes。

连接 Hermes：

```bash
hermes mcp add clink_marketplace --url http://127.0.0.1:9050/mcp/
hermes mcp test clink_marketplace
```

## 商家入驻

商家流程：

```text
SIWE 登录
-> 查看 Bazaar 候选或新建 Manifest
-> EIP-712 ManifestClaim
-> 域名证明
-> 实时 x402 验证
-> 公开服务
```

浏览器控制台位于 `http://127.0.0.1:8050/merchant`。它直接调用浏览器 EVM 钱包完成 SIWE 和 EIP-712 签名，支持 Bazaar 候选检索/草稿认领、Manifest JSON 编辑提交、域名与实时 x402 验证、状态刷新和 Offering 下架。页面不接收或保存私钥；短期 bearer token 只保存在当前标签页的 `sessionStorage`。

主要接口：

| Method | Path | 作用 |
|---|---|---|
| `GET` | `/auth/siwe/config` | 返回浏览器登录所需的允许域名，不返回秘密配置 |
| `POST` | `/auth/siwe/challenge` | 创建 SIWE challenge |
| `POST` | `/auth/siwe/verify` | 验证签名并创建商家 session |
| `GET` | `/merchant/candidates` | 查询可认领 Bazaar 候选 |
| `POST` | `/merchant/candidates/{offering_id}/claim-draft` | 生成只读 Manifest 草稿 |
| `POST` | `/merchant/manifests` | 提交 Manifest |
| `GET` | `/merchant/manifests` | 列出当前钱包的持久 Manifest 摘要并继续入驻 |
| `POST` | `/merchant/manifests/{id}/claim-challenge` | 创建 EIP-712 claim |
| `POST` | `/merchant/manifests/{id}/submit-claim` | 提交钱包 claim |
| `GET` | `/merchant/providers` | 列出当前钱包拥有的 Provider/Offering 状态 |
| `GET` | `/merchant/providers/{id}/status` | 查看单个自有 Provider 的验证状态 |
| `POST` | `/merchant/providers/{id}/verify-domain` | 验证域名并物化 canonical 记录 |
| `POST` | `/merchant/offerings/{id}/verify` | 验证实时 x402 endpoint |
| `POST` | `/merchant/offerings/{id}/disable` | 下架服务 |

管理员控制台位于 `/admin`，同样通过 SIWE 登录，但钱包必须在 `MARKETPLACE_ADMIN_WALLETS` allowlist 中。受保护的 `GET /admin/status` 和 `GET /admin/providers` 提供 Registry/worker/Core/指标及 Provider 摘要；其中 `/admin/status` 承载运营 `metrics` 与 `supply_targets`，公开 `/healthz` 只保留 readiness。`POST /admin/registries/sync` 和 `POST /admin/providers/{id}/{suspend|restore}` 执行运营动作。响应不包含 Core token、数据库连接串或内部凭证。生产环境也可以通过 `MARKETPLACE_ADMIN_DISABLED=true` 完全关闭管理面，此时 `/admin` 与全部 `/admin/*` 固定返回 403。

## 购买闭环

```text
Hermes search/compare
-> create preview（锁价 5 分钟）
-> 从短期 Redis 获取输入；缺失或过期时在任何 Core 资金副作用前失败
-> Core action + policy
-> Core 解析 WalletIdentity + SpendingGrant，并为两种支付轨道统一预留额度
-> Core reserve
-> Clink-native 商家走 clink_allowance
-> 兼容外部商家由 Clink Universal Payer 签 EIP-3009 并自动提交
-> 不兼容商家才返回一次性 external x402 checkout URL
-> 商家交付
-> Core finalize + audit
-> Hermes 获取瞬时结果
-> Marketplace 记录 hash、收据引用和信誉事件
```

相同 purchase 的重复执行只返回原状态，不会再次扣款或调用商家。支付成功但交付失败进入 `paid_but_undelivered`，禁止自动再次支付。

`payment_submitted` 重试和 worker 都调用 Core 的幂等 reconcile contract。Core 只有在确认交易失败或同步提交明确被拒绝后才返回 `retryable`；nonce 已前进但交易查询暂时不可见仍保持 `pending`，Marketplace 不释放额度也不创建第二笔交易。`clink_allowance` 仅在 Core 结算后调用商家；`clink_payer_proxy` 则在用户补偿交易确认且短期授权仍有效后调用商家，再由 Core finalize 商家付款证明。

三种支付轨道都必须先由 Core 解析有效的 WalletIdentity 与 SpendingGrant。缺少身份或额度时，购买会在创建 Action 和资金副作用之前停止，并返回 Core 统一账户页。对于兼容的第三方 x402，Core 在单笔、滚动一小时、每日和总额度内原子 reserve，先校验实时 challenge 与 canonical token domain 并生成短期商家限定 EIP-3009 授权，再从用户 allowance 精确补偿 Universal Payer；补偿确认后 Marketplace 才能提交授权。Hermes 不获得私钥，也不需要 checkout URL。如果实时 challenge 暴露出网络、资产或协议不兼容，当前 proxy purchase 会在扣款前释放预留并失败；后续 preview 会明确标记为 `external_x402_signature` 的逐笔签名轨道。搜索、报价和 preview 共用同一 `max_price_usd` 约束，超限选项不会进入可选索引空间。

## Docker 启动

生产形态使用 Docker Compose，包含 PostgreSQL、Redis、migration、API、worker 和 MCP。Core 独立部署并通过私网访问。

```bash
cp .env.example .env
chmod 600 .env
# 编辑 .env，替换四个数据库角色密码、Marketplace/Core 内部 token、公开 URL 等

docker compose --env-file .env config
docker compose --env-file .env build
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

默认只发布 loopback：

- Marketplace API：`http://127.0.0.1:8050`
- Marketplace MCP：`http://127.0.0.1:9050/mcp/`
- PostgreSQL/Redis：仅 Compose 内网

生产必须由反向代理终止 TLS，只开放需要的 API/MCP 路由。不要公开 Core、PostgreSQL 或 Redis。

## 本地启动

本地方式要求 PostgreSQL、Redis 和 Clink Core 已经运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# 本地可把 POSTGRES_HOST 和 REDIS_URL 保持为 127.0.0.1

bash run_demo.sh
```

另一个终端：

```bash
bash run_demo_status.sh
curl --fail http://127.0.0.1:8050/livez
curl --include http://127.0.0.1:8050/healthz
.venv/bin/python scripts/public_mcp_surface_smoke.py --live
```

停止：

```bash
bash run_demo_stop.sh
```

## 验证

完全本地、无真实网络/资金/钱包私钥的 pilot smoke：

```bash
.venv/bin/python scripts/bazaar_pilot_smoke.py
```

它覆盖 Bazaar 分页同步、候选不可公开、商家 claim、域名/402 复验、Hermes 报价/preview、fake Core 结算、fake 商家交付、瞬时结果、幂等重放和信誉样本。

完整验证：

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/bazaar_pilot_smoke.py
.venv/bin/python scripts/public_mcp_surface_smoke.py
.venv/bin/python -m compileall adapters services shared storage mcp_servers scripts
bash -n run_demo.sh run_demo_stop.sh run_demo_status.sh scripts/*.sh
.venv/bin/alembic heads
docker compose --env-file .env config
git diff --check
```

`scripts/public_mcp_surface_smoke.py` 默认离线验证精确 MCP contract；运行服务后加 `--live` 验证传输层。`/healthz` 返回 `503 degraded` 代表运行依赖未就绪，不等于 MCP transport 连接失败。

全量 Bazaar 当前可能需要多个 worker cycle 才能扫完。达到单周期页数预算时 Registry 状态为 `running`，不再误报为失败；真正的 HTTP、JSON 或分页错误会在 `last_error` 中以脱敏摘要返回。Worker 在每个 Registry page 和每个 offering 复验后刷新 heartbeat，并对短暂 endpoint 网络错误做有界重试。`MARKETPLACE_BAZAAR_REQUEST_TIMEOUT_SECONDS`、`MARKETPLACE_OFFERING_VERIFY_BATCH_SIZE`、`MARKETPLACE_ENDPOINT_VERIFY_TIMEOUT_SECONDS` 和 `MARKETPLACE_ENDPOINT_VERIFY_ATTEMPTS` 必须共同落在 `MARKETPLACE_WORKER_STAGE_TIMEOUT_SECONDS` 内，启动时会拒绝不安全的预算配置。
