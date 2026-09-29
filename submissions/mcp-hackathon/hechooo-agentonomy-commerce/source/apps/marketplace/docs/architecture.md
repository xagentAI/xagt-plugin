# Clink Marketplace 产品与技术架构

## 产品定位

Clink Marketplace 是 Agent Commerce 的可信供给市场，不是通用聊天机器人，也不是钱包托管系统。

- **Hermes**：理解买方目标，搜索、比较并选择服务。
- **Marketplace**：管理商家、服务、报价、交付和信誉，编排购买流程。
- **Clink Core**：唯一的身份、策略、风险、额度、支付和审计控制面。
- **商家服务**：返回实时 x402 报价，接收支付证明并交付结果。
- **Bazaar/peer Registry**：提供发现线索；Clink 必须本地复验实时支付条款后才授予有限的 Registry 信任。

## 产品架构

```text
                           买方
                            |
                      Hermes Agent
                            |
                 clink_marketplace MCP
                            |
  +------------------- Clink Marketplace -------------------+
  | 搜索与报价 | Preview | 购买编排 | 交付 | 信誉 | 运维状态 |
  +---------------------------------------------------------+
             |                                |
             |                                +--> 商家 x402 endpoint
             v
       Clink Core 控制面
  action -> policy/risk -> reserve -> settle/finalize -> audit

供给侧：
  Bazaar / peer Registry -> 候选池 -> 商家 claim -----------+
  商家 SIWE -> Manifest -> 钱包/域名/402 验证 --------------+
```

### 供应商增长路径

**Clink 主动补充**：worker 从 Bazaar/peer Registry 增量同步候选，规范化 Provider/Offering，并独立复验实时 402。通过后以 `registry_verified` 低额度公开，同时邀请对应域名商家 claim。

**商家主动迁移**：商家直接提交 Manifest，完成 SIWE、EIP-712 claim、域名证明和实时 402 复验。两条路径使用相同 canonical identity，因此不会产生来源型重复商家。

## 技术架构

```text
                         HTTPS / MCP
                              |
          +-------------------+--------------------+
          |                                        |
  Marketplace API :8050                    Marketplace MCP :9050
  merchant/admin/catalog/purchase           7 个 Agent tools
          |                                        |
          +-------------------+--------------------+
                              |
                         PostgreSQL
          provider / offering / provenance / manifest
          preview / purchase / reputation / outbox / worker
                              |
                         Redis (ephemeral)
                    购买输入、短期执行上下文

Marketplace Worker
  registry_sync -> offering_verify -> domain_verify
                -> payment reconciliation / purchase_finalization -> heartbeat

External dependencies
  CDP Bazaar / Clink peer Registry
  Merchant domain + x402 endpoint
  Clink Core private APIs
```

API、worker 和 MCP 使用同一镜像但不同进程角色和最小权限环境变量。migration 是独立的 DDL owner；API 和 worker 使用不同的非 owner、无 schema CREATE 权限角色。MCP 容器不接收数据库密码、Core token 或管理员钱包。

## 身份与去重

- `provider_id` 由 normalized domain 生成，与 Registry 来源无关。
- `offering_id` 由 HTTP method + normalized endpoint 生成。
- Registry 来源独立保存为 provenance，可保留多个来源。
- canonical Provider/Offering 只能在商家域名证明成功后物化或更新；Registry 后续同步只能更新 discovery/provenance，不能覆盖已受信的 provider 名称、域名、钱包或状态。
- Manifest 绑定 `manifest_hash`、domain、全部 `payTo`、nonce 和有效期。
- endpoint、价格、网络、资产或 `payTo` 修改后必须重新验证；复验结果绑定开始时的 canonical payload hash，过期结果不能发布替换后的 candidate。

## 信任边界

### 外部 Registry

Registry 数据永远是未信任输入。同步只更新 provenance 和候选记录；它不能把 Provider 改成 active，也不能授予 `clink_verified`。Clink 本地实时复验通过后可授予 `registry_verified`；关键支付字段发生漂移时立即下架，复验成功后才能重新公开。

### 商家身份

1. SIWE 证明当前 session 控制 EVM 地址。
2. EIP-712 `ManifestClaim` 绑定 Manifest 内容并防止篡改、过期和 replay。
3. `/.well-known/clink-verification.json` 证明钱包控制目标域名。
4. 实时 402 验证证明 endpoint 的 payment requirements 与 Manifest 一致。

`/merchant` 和 `/admin` 是 API 镜像内的独立 HTML/CSS/JS 控制台。浏览器只调用现有 SIWE、Manifest、验证和运营 API；钱包签名通过 EVM provider 完成，access token 仅存当前标签页 `sessionStorage`。商家状态查询按 session 钱包过滤，管理员状态与 Provider 查询复用相同的 admin session + allowlist 鉴权。控制台响应不传递 Core token、数据库凭证或其他内部秘密。

公开目录接受 fresh `registry_verified` 或 `clink_verified` Offering。前者明确显示身份尚未由商家 claim 并强制低额度；兼容 EVM x402 v2 + EIP-3009 的报价可由 Core Universal Payer 自动支付。实时 challenge 若不兼容，当前购买会在扣款前释放预留并失败，后续必须创建明确的逐笔签名 preview。后者要求 Provider active，并可按受控 allowlist 使用 Clink allowance。Suspended provider 的全部 offering 都不可购买。

### 买方 Agent

Hermes 只能调用 Marketplace MCP。商家入驻、管理员、Registry 和 Core API 不暴露给 Hermes。Marketplace 使用独立内部 bearer token 调用受保护购买 API；Marketplace 再通过私网 token 调用 Core。

### 资金

Marketplace 不持有用户或 payer 私钥，也不自行转账。Core 创建 action、执行 policy/risk、原子 reserve/settle/finalize、签署 Universal Payer 的商家限定 EIP-3009 授权并写 audit。Marketplace 只校验实时 challenge、提交 Core 返回的支付 payload，并保存不可变引用。

## 供给验证数据流

```text
Registry fetch_page(cursor/ETag)
-> lease + fenced page commit
-> discovered candidate + provenance
-> merchant SIWE session
-> claim draft（只读）
-> submit Manifest（pending）
-> ManifestClaim（wallet_verified）
-> domain proof（canonical provider/domain_verified）
-> live 402 verification（offering/verified + provider/active）
-> public catalog
```

单个 Registry 故障不会阻止其他 Registry 同步。每页数据和 cursor/ETag 在同一 fenced transaction 内提交，过期 worker 不能覆盖新数据。

## 购买数据流

```text
Hermes search/compare
-> select offering
-> create preview(service_input)
   - PostgreSQL: input_hash + locked quote
   - Redis: plaintext input with TTL
-> execute
-> acquire input；缺失时在 action/policy/reserve/settle 前失败
-> Core create_action/evaluate_policy/audit
-> Core 解析 WalletIdentity + SpendingGrant，并统一执行 spending reserve
-> clink_allowance settle，或 clink_payer_proxy 获取实时 402 后自动代付
-> 不兼容 external x402 才通过一次性浏览器 checkout 签 EIP-3009
-> 使用 PAYMENT-SIGNATURE 重试同一 merchant request
-> terminal purchase + reputation event + finalize outbox（同事务）
-> plaintext service_result 只返回当前 Hermes 调用
-> replay 返回相同 purchase，service_result=null
```

比较阶段不会把真实用户输入广播给多个商家。只有选定服务创建 preview 后，输入才进入短期 Redis context。
`max_price_usd` 在搜索、报价和 preview 共同过滤 payment options；preview 的索引只针对过滤后的列表，不能通过默认索引或 index drift 选中超限报价。

## 购买状态机

```text
preview_created
-> confirmation_required
-> spending_reserved
-> payer_funded / proxy_payment_ready (clink_payer_proxy)
-> signing_required          (external x402)
-> payment_submitted
-> delivered
   |-> paid_but_undelivered
   |-> failed
```

- `preview_created` 锁定 quote，默认 5 分钟。
- quote、network、asset、amount 或 `payTo` 漂移会使 preview 失效。
- `payment_submitted` 是对不确定结算结果的恢复点，重试和 worker 调用 Core reconciliation endpoint。`pending` 只对账或重播同一份 native raw transaction；`retryable` 才允许 native 重新结算或 external 提交修正证明。超过 Core 配置的自动尝试次数或时间后进入 `manual_review_required/operator_reconcile`，额度继续安全持有，worker 不再自动领取该 purchase。
- Marketplace 在提交前保存支付授权/证明 hash 和交易引用，不保存 native raw transaction；只有 Core `settled/finalized` 才允许商家交付。
- `paid_but_undelivered` 代表已经付款但商家交付失败，禁止自动再次付款。
- purchase execution 使用 claim token/CAS；并发请求只能有一个结算与交付者。
- terminal purchase、信誉事件和 native finalize outbox 在同一数据库事务提交。

## 支付轨道

### clink_allowance

只有 `MARKETPLACE_NATIVE_PROVIDER_IDS` 可信配置中的 Clink-native 商家接受 `X-CLINK-PAYMENT-RECEIPT`。Manifest、Bazaar 或 peer metadata 不能自行声明资格，未配置时全部 fail closed 到 external x402。用户有有效 Core spending mandate、链上 allowance 且 policy 通过时，Core 可以在单笔、滚动一小时、每日和总额度内自动结算。Marketplace 将 receipt token 发送给商家。

### clink_payer_proxy

兼容 EVM x402 v2、`exact`、EIP-3009 的外部商家可以复用用户在 Core Account 中签署的 mandate 和对应链 USDC allowance。Marketplace 先锁定报价并校验商家的实时 402 challenge；Core 原子预留所有额度，先复核 canonical token domain 并签署只对该商家、金额、网络、资产、nonce 和有效期有效的短期 EIP-3009 支付，再将精确购买金额从用户 allowance 转入 Universal Payer。补偿确认后 Marketplace 才能提交支付。用户不需要逐笔签名，Marketplace 和 Hermes 都接触不到 payer 私钥。

Core 分别持久化用户到 payer 的补偿交易和 payer 到商家的付款交易。任一重试必须复用同一 reservation；用户额度只结算一次，商家付款失败不会重新扣用户，商家已交付但 Core finalize 超时也不会再次调用商家。

### external_x402_signature

不满足 Universal Payer 条件的标准第三方 x402 商家仍要求 Core 先解析有效的 WalletIdentity 与 SpendingGrant，并原子预留统一预算。首次 `execute_clink_purchase` 返回一次性 checkout URL；浏览器严格复核锁定的 scheme/network/asset/amount/payTo/resource，并确认连接钱包与 Core WalletIdentity 一致。签名后 Marketplace 使用 `PAYMENT-SIGNATURE` 重试同一请求，再把商家的 `PAYMENT-RESPONSE` 交给 Core 对账。

checkout token 仅存在 URL fragment，服务端只持有 token hash；支付 challenge 通过 Redis `GETDEL` 或进程内锁原子消费。并发或重复回调不能产生第二次 merchant payment request，执行轨道也被写入 action、policy、audit 和 reservation scope，禁止在 allowance 与 external x402 之间切换。

同一 `execute_clink_purchase` continuation 可以重复原证明，或在 Core 已确认旧交易失败并返回 `retryable` 后提交修正证明。Core 将 Ethereum transaction hash 规范为小写 `0x` + 64 hex，并只用已校验的 canonical payment scope 构造 proof identity；数据库对 normalized hash 强制唯一。仍然 `pending` 或 `manual_review_required` 时拒绝切换交易。

## 持久化与瞬时数据

PostgreSQL 持久化：

- Provider、Offering、Manifest、provenance 和验证时间。
- Registry cursor/ETag/lease。
- Purchase preview、purchase 状态、input/output hash。
- action、policy、reservation、receipt、audit 引用。
- 信誉事件、信誉快照和 finalize outbox。
- worker heartbeat 和 stage 状态。

Redis/内存短期保存：

- 选定服务的 plaintext input。
- 尚未交付的短期购买上下文。

生产 Redis 明确关闭 RDB save 和 AOF，`/data` 使用 tmpfs 且没有 named volume。明文输入只存在内存并遵守 TTL；执行期间先 acquire，terminal 状态、信誉和 finalize outbox 落库后才删除。

不持久化：

- 用户私钥、钱包签名密钥。
- 用户服务输入明文。
- 商家服务结果明文。
- 多商家比较阶段的用户真实输入。

## 信誉

每个 terminal purchase 最多生成一个不可变 reputation event。维度及默认权重：

| 维度 | 权重 |
|---|---:|
| identity | 25 |
| quote_consistency | 15 |
| availability | 15 |
| payment_success | 20 |
| delivery_success | 15 |
| dispute | 10 |

结果同时返回 `sample_size` 和 `confidence`。快照可以完全从事件重建；preview 过期、quote drift 等未发起支付的失败不会惩罚商家。

## Worker 与健康模型

Worker 周期包含五个隔离阶段：

1. Registry sync。
2. Offering 每 15 分钟复验。
3. Domain 每日复验，连续三次失败暂停 Provider。
4. Purchase finalization outbox 重试。
5. Heartbeat。

`/livez` 只表示 API 进程存活并始终返回 200。`/healthz` 只投影轻量的 API、worker、Registry 和 Core readiness，不计算或返回运营 analytics；认证后的 `/admin/status` 承载 `metrics` 与 `supply_targets`。任一 mandatory stage 当前周期失败、worker stale、Registry stale/failed 或 Core degraded 时 `/healthz` 返回 503。降级不会删除已有可信目录，搜索仍可读取最后一份 fresh verified 数据。
