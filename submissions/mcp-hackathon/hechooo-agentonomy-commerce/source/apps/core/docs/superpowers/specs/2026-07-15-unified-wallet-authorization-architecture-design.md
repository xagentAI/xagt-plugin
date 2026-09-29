# Clink 统一钱包身份与跨产品授权架构

## 1. 背景

Clink 已经通过 Prediction Markets 和 Marketplace 验证了两类 Agent Commerce 场景：

- Agent 为用户扫描、判断并执行预测市场交易；
- Agent 发现、比较并购买第三方服务。

当前实现已经把资金控制放在 Clink Core，但用户身份、链上 allowance 和垂直平台绑定仍存在重复与耦合：

- Prediction Markets 的账户页同时处理钱包连接、Core spending authorization 和 Polymarket CLOB Auth；
- Core 的 spending authorization 使用单一 `venue` 表达权限范围，难以自然覆盖多个产品和网络；
- 同一个用户在不同垂直产品中需要重复证明钱包所有权或手工传递 authorization id；
- 一个授权对象同时承担业务策略和链上 allowance 证明，难以表达 Polygon 与 Base 等多链资产；
- Polymarket 专属账户凭证和通用钱包权限之间的边界不够清晰。

本设计将 Clink 收敛为长期稳定的 Agent Commerce 控制面：Core 统一管理用户钱包身份、消费策略、链上 allowance、风控与审计；Prediction Markets、Marketplace 和未来垂直适配器只管理各自的平台能力与凭证。

## 2. 目标

### 2.1 产品目标

- 用户只需在 Clink 中绑定一次钱包身份。
- 用户可以创建一份跨产品消费策略，并明确限定产品、网络、资产、总额度、单笔额度、每日额度和有效期。
- 同一消费策略可以关联多条链上的独立 token allowance。
- Prediction Markets 和 Marketplace 可以自动选择符合 scope 的有效授权，不要求用户或 Hermes 传递内部 authorization id。
- Polymarket CLOB Auth 等平台授权保持独立，但复用 Core 已验证的钱包身份。
- 用户可以在统一账户页查看、暂停、缩减或撤销权限。
- 新增 DeFi、数据购买、Agent-to-Agent 支付等产品时，不需要重新设计钱包绑定和额度系统。

### 2.2 技术目标

- Core 成为钱包身份、消费策略、资金预留、结算、风控和审计的唯一数据真源。
- 垂直适配器通过稳定的内部 API 使用 Core，不直接复制身份或资金状态。
- 每笔消费必须能追踪到 wallet identity、spending grant、asset allowance、action、policy decision、reservation、receipt 和 audit events。
- 支持 Polygon 与 Base USDC，并允许未来增加其他 EVM 网络和资产。
- 所有状态变更具备幂等性、重放保护、原子预算预留和可恢复对账。

## 3. 非目标

- 本阶段不引入 Clink 托管钱包或保存用户私钥。
- 本阶段不实现任意链、任意 token 的自动支持。
- 本阶段不使用 smart account/session key 代替所有第三方 x402 单笔签名。
- Core 不保存 Polymarket、Kalshi 或商家平台的业务凭证。
- Hermes 不直接连接 Core MCP，也不能修改用户权限。
- 不把 external x402 商家自动视为可使用通用 spending allowance 的 Clink-native 商家。

## 4. 稳定架构边界

```text
User Wallet
    |
    | SIWE/EIP-712 ownership proof + on-chain approve
    v
Clink Core
├── Wallet Identity
├── Spending Grant
├── Asset Allowance
├── Action / Policy / Risk
├── Reservation / Settlement / Receipt
└── Audit
    |
    | private authenticated APIs
    +---------------------------+
    |                           |
    v                           v
Prediction Markets          Marketplace
├── market discovery        ├── provider discovery
├── Polymarket binding      ├── quote comparison
├── CLOB credentials        ├── delivery orchestration
├── order preview           ├── Clink allowance rail
└── venue execution         └── external x402 checkout
```

职责边界：

- **Core**：谁在授权、可花多少、可在哪些范围消费、目标是否安全、预算是否可用、资金是否结算、过程如何审计。
- **垂直适配器**：买什么、平台需要什么凭证、如何构造平台请求、如何读取结果。
- **Hermes**：理解用户目标、搜索与比较、提出建议、请求用户确认，不持有资金权限和平台密钥。
- **用户钱包**：完成身份签名和逐链、逐资产 allowance；只有不兼容 Universal Payer 或被 policy 提升风险的第三方 x402 购买才逐笔签名。

## 5. 核心领域模型

### 5.1 WalletIdentity

代表 Clink 已验证的钱包主体，而不是某个平台账户。

```text
wallet_identity_id
user_id
chain_family               eip155
wallet_address
status                     pending | active | suspended | revoked
proof_scheme               siwe | eip712
proof_hash
verification_nonce
verified_at
last_seen_at
revoked_at
metadata
```

约束：

- `(user_id, chain_family, wallet_address)` 唯一。
- challenge 单次使用并有短 TTL。
- 签名恢复地址必须与 wallet address 一致。
- Core 只保存证明 hash 和必要审计信息，不保存可复用的原始签名。
- 一个用户可以绑定多个钱包，但每个产品动作必须明确使用一个 active identity。

### 5.2 SpendingGrant

代表用户授予 Agent 的业务消费策略，与具体链上 approve 交易解耦。

```text
spending_grant_id
wallet_identity_id
user_id
agent_id
status                     pending | active | paused | exhausted | expired | revoked
max_amount_usdc
per_transaction_limit_usdc
daily_limit_usdc
used_amount_usdc
reserved_amount_usdc
product_scopes             [prediction_markets, marketplace, ...]
venue_scopes               [polymarket, clink_marketplace, ...] optional
merchant_scopes            provider/category allowlist optional
network_scopes             [eip155:137, eip155:8453]
asset_scopes               token identifiers
risk_policy_id
starts_at
expires_at
created_at
updated_at
metadata
```

约束：

- product scope 必须显式授权，不能使用隐含的 `all` 默认值。
- venue 和 merchant scope 为空表示由 product scope 与 policy 控制，不代表绕过目标地址风控。
- 总额度、每日额度、单笔额度均由 Core 原子校验。
- 调低额度、暂停和撤销立即影响后续 reservation；已提交链上交易进入对账，不回滚事实状态。

### 5.3 AssetAllowance

代表某个钱包在某条链、某个 token、某个 spender 上的链上可执行能力。

```text
asset_allowance_id
wallet_identity_id
network
token_address
token_symbol
token_decimals
spender_address
approved_amount_atomic
observed_allowance_atomic
allowance_tx_hash
status                     pending | active | insufficient | revoked | stale
confirmed_block
last_chain_check_at
created_at
updated_at
```

约束：

- `(wallet_identity_id, network, token_address, spender_address)` 唯一。
- approve receipt、transaction sender、token contract、spender、amount 和确认数必须链上验证。
- Core 执行前重新确认 allowance 足够；数据库额度不能替代链上事实。
- Polygon USDC 与 Base USDC 是不同 AssetAllowance，即使共享一个 SpendingGrant。

### 5.4 PlatformBinding

PlatformBinding 不属于 Core 通用模型，由各垂直适配器保存。

Polymarket 示例：

```text
binding_id
user_id
wallet_identity_id
wallet_address_snapshot
account_mode
funder_address
signature_type
credential_fingerprint
credential_store_reference
status
created_at
revoked_at
metadata
```

约束：

- 创建 binding 时必须从 Core 获取 active WalletIdentity。
- 平台签名恢复的钱包必须和 WalletIdentity 一致。
- CLOB secret、passphrase 等凭证继续由 Prediction Markets 加密保存。
- 撤销 PlatformBinding 不自动撤销通用 SpendingGrant；界面必须向用户明确两者差异。

## 6. 用户体验

### 6.1 Clink Account & Permissions

Core 提供统一账户与权限页面，承担：

- 连接钱包并完成 WalletIdentity 验证；
- 创建或修改 SpendingGrant；
- 为每条网络创建 AssetAllowance；
- 查看授权覆盖的产品、网络、资产、额度与有效期；
- 暂停、恢复、调低额度和撤销授权；
- 查看最近消费和审计摘要。

页面不展示平台 API secret，也不处理 Polymarket CLOB Auth。

### 6.2 Prediction Markets

Prediction Markets 账户页仅处理平台连接：

1. 查询 Core WalletIdentity；没有则跳转统一账户页。
2. 用户选择已验证钱包。
3. 钱包签署 Polymarket CLOB Auth。
4. Adapter 派生凭证并创建 PlatformBinding。
5. 不再额外签署重复的 Clink binding message。

充值或执行时，Adapter 根据 `user_id + product + network + asset + amount` 向 Core 请求授权解析，不要求 Hermes 提供 grant id。

### 6.3 Marketplace

- Clink-native 服务：Marketplace 请求 Core 解析符合 scope 的 SpendingGrant 与 AssetAllowance，在 policy 通过后自动购买。
- compatible external x402 服务：Core Universal Payer 在 mandate 与 allowance 范围内生成商家限定 EIP-3009 支付，用户无需逐笔签名。
- incompatible external x402 服务：继续逐笔返回一次性 checkout URL。
- 外部商家不能通过 Manifest 或 Registry metadata 将自己声明成 Clink-native。

## 7. Core 内部 API 契约

建议稳定接口：

```text
POST /wallet-identities/challenges
POST /wallet-identities/verify
GET  /wallet-identities?user_id=...
POST /wallet-identities/{id}/revoke

POST /spending-grants
GET  /spending-grants?user_id=...&status=active
POST /spending-grants/{id}/pause
POST /spending-grants/{id}/resume
POST /spending-grants/{id}/reduce
POST /spending-grants/{id}/revoke

POST /asset-allowances/verify
GET  /asset-allowances?wallet_identity_id=...
POST /asset-allowances/{id}/refresh

POST /authorization-resolution
POST /spending-reservations
POST /spending-reservations/{id}/settle
POST /spending-reservations/{id}/reconcile
POST /spending-reservations/{id}/finalize
POST /spending-reservations/{id}/release
```

`POST /authorization-resolution` 输入：

```json
{
  "user_id": "telegram_demo_user",
  "agent_id": "hermes",
  "product": "prediction_markets",
  "venue": "polymarket",
  "network": "eip155:137",
  "asset": "0x...",
  "amount_usdc": "1",
  "destination": "0x...",
  "resource": "polymarket:funding"
}
```

输出只返回满足 scope 的授权引用和可解释状态，不返回用户签名或平台凭证：

```json
{
  "ready": true,
  "wallet_identity_id": "wallet_identity_...",
  "spending_grant_id": "spend_grant_...",
  "asset_allowance_id": "asset_allowance_...",
  "remaining_amount_usdc": "5",
  "next_action": "create_action_and_reserve"
}
```

最终是否允许消费仍由 action、policy、risk 和 reservation 阶段决定；resolution 不是付款批准。

## 8. Agent 与适配器边界

- Hermes 只连接垂直 MCP，例如 `clink_prediction_markets` 和 `clink_marketplace`。
- Core MCP 不向 Hermes 暴露。
- 垂直 MCP 的 readiness 可以返回 Core account console URL，但不能替用户创建或扩大授权。
- Adapter 使用内部 bearer token 调用 Core。
- Adapter 只能请求 resolution、action、policy、reservation、settlement 和 audit，不能直接修改 WalletIdentity 或 SpendingGrant。
- 用户权限变更只能从 Core 用户控制页面发起并由钱包确认。

## 9. 消费数据流

### 9.1 Polymarket 充值

```text
Hermes 请求充值
-> Prediction Markets 解析 active PlatformBinding 和 deposit wallet
-> Core authorization-resolution
-> Core action + policy + risk
-> Core reserve spending grant budget
-> Native Facilitator transferFrom
-> Core reconcile + receipt + audit
-> Prediction Markets 同步 venue balance
```

### 9.2 Polymarket 下单

```text
Hermes 扫描并创建 preview
-> 用户确认
-> Core action + policy + risk
-> Prediction Markets 使用 PlatformBinding/CLOB credentials 提交订单
-> Core audit execution result
-> portfolio sync
```

订单消费的是已充值到平台账户的资金，因此不重复扣减链上充值 grant；但交易风险和额度政策可以使用独立的 trading policy 约束。

### 9.3 Clink-native Marketplace 购买

```text
Hermes 选择服务并创建 preview
-> Core authorization-resolution
-> Core action + policy + risk + reserve
-> Native Facilitator transferFrom
-> Core settle receipt
-> Marketplace 携带 Clink receipt 调用商家
-> Core finalize + reputation event
```

### 9.4 External x402 购买

本节描述不兼容 Universal Payer 时的 fail-closed 兜底。兼容的 EVM x402 v2 exact + EIP-3009 商家优先使用 `clink_payer_proxy`，详见 `2026-07-21-universal-payer-design.md`。

```text
Hermes 选择服务并创建 preview
-> Core action + policy + external reservation
-> 用户打开一次性 checkout URL
-> 钱包签署 merchant-specific EIP-3009
-> Marketplace 用 PAYMENT-SIGNATURE 重试同一请求
-> Core 验证 transaction scope 并审计
```

逐笔签名的 external x402 不消耗 AssetAllowance，但仍消耗 SpendingGrant 的预算统计。兼容商家可通过 Universal Payer 使用 AssetAllowance 自动支付；不兼容网络、资产、challenge 或高风险决策必须回落到本节流程。

## 10. 安全要求

- Core account session 使用高熵、短 TTL、单次消费 token。
- WalletIdentity challenge 必须绑定 user id、wallet、domain、nonce、issued at 和 expiration。
- SpendingGrant 只能缩减或撤销；扩大范围、提高额度、延长有效期必须重新经过钱包确认。
- Core 必须校验 product、venue、network、asset、destination、resource 和 amount 的完整 scope。
- destination 必须经过 CreditModel、allowlist/denylist 和垂直上下文校验。
- Adapter 不能传入一个任意 grant id 绕过 resolution；Core 必须重新验证 grant 属于 user 和 wallet。
- Budget reserve、settle、finalize、release 必须原子、幂等，并防止重复扣款。
- Platform credential store 与 Core identity store 使用不同加密域和访问凭证。
- 日志不得输出钱包签名、CLOB secret、API passphrase、内部 token 或原始敏感服务输入。
- 生产环境必须使用 HTTPS；钱包页面不得通过明文公网 HTTP 提供。

## 11. 状态与撤销语义

- **撤销 WalletIdentity**：暂停其全部 SpendingGrant，并通知 Adapter 将关联 PlatformBinding 标记为 `identity_revoked`。
- **撤销 SpendingGrant**：停止后续资金消费，不删除 WalletIdentity 和 PlatformBinding。
- **撤销 AssetAllowance**：Core 标记不可用；用户还应执行链上 `approve(spender, 0)`，确认后状态变为 revoked。
- **撤销 PolymarketBinding**：删除平台凭证，不影响 Core 钱包身份和其他产品授权。
- **进行中的链上交易**：进入 reconciliation，不因本地撤销而伪造回滚。

## 12. 存储与一致性

- Core 长期状态使用 PostgreSQL；Redis 只保存 challenge、页面 session 和短期 checkout 上下文。
- WalletIdentity、SpendingGrant、AssetAllowance、Reservation、Receipt 和 Audit 通过不可变 ID 关联。
- 预算修改使用数据库事务和行级锁/CAS。
- 链上 allowance 以 RPC 观测为最终事实，定期刷新并记录观测区块。
- Adapter 只保存 `wallet_identity_id` 快照，不复制 SpendingGrant 余额。
- 跨服务调用使用 idempotency key 和 correlation id。

## 13. 可观测性

核心指标：

- active wallet identities；
- active/paused/revoked spending grants；
- allowance verification success/failure；
- authorization resolution 命中率和拒绝原因；
- reserve/settle/finalize/release 数量与延迟；
- destination risk block 数量；
- 重复请求命中、reconciliation pending 和 manual review 数量；
- 每产品、网络和资产的授权使用量。

每笔消费必须贯穿：

```text
correlation_id
wallet_identity_id
spending_grant_id
asset_allowance_id
action_id
policy_decision_id
reservation_id
receipt_id
audit_event_ids
```

## 14. 迁移策略

为避免错误扩大旧授权权限，不自动把现有单 venue authorization 转换成跨产品 grant。

迁移顺序：

1. Core 新增模型和 API，与旧 spending authorization 并行只读观察。
2. 上线统一账户页，测试用户创建新的 WalletIdentity、SpendingGrant 和 AssetAllowance。
3. Prediction Markets 改为 resolution，停止创建旧 authorization。
4. Marketplace 的 Clink-native rail 改为 resolution。
5. 验证两条产品链路、撤销和预算一致性。
6. 将旧 authorization 标记为 legacy，并要求用户重新授权。
7. 清理 Prediction Markets 中的 Core funding UI/代理和旧 API。
8. 稳定后删除 legacy 写路径；历史 receipt 与 audit 保留只读。

## 15. 测试与验收

### 身份

- challenge 过期、重放、domain 不匹配、签名地址不匹配必须失败。
- 同一个钱包不能被错误绑定到另一个 user。
- revoked identity 不能通过 authorization resolution。

### 授权

- product、venue、network、asset、amount 任一不匹配必须失败。
- 总额度、每日额度、单笔额度分别验证。
- 并发 reservation 不能超出剩余额度。
- 提高额度或扩大产品范围不能绕过钱包确认。
- Polygon allowance 不能用于 Base，反之亦然。

### 垂直产品

- Prediction Markets 不再创建重复钱包身份签名。
- Polymarket CLOB Auth 钱包必须匹配 Core identity。
- Marketplace Clink-native 自动选择 grant，不接收 Hermes 指定的任意 grant。
- external x402 保持单次 checkout、单次 merchant call 和防重放。

### 撤销与恢复

- 暂停 grant 后新消费立即失败。
- identity 撤销后所有产品 funding 失败。
- PlatformBinding 撤销不影响 Marketplace grant。
- 已提交交易在撤销后仍可完成对账，但不能产生第二笔扣款。

### 端到端验收

1. 用户绑定一次钱包。
2. 创建一份覆盖 Prediction Markets 和 Marketplace 的 SpendingGrant。
3. 分别创建 Polygon 与 Base AssetAllowance。
4. 使用 Polygon allowance 为 Polymarket funding。
5. 使用 Marketplace Clink-native 服务消费 Base allowance。
6. external x402 服务仍进入单笔钱包签名。
7. Core 展示统一预算、receipt 和 audit trail。
8. 撤销 grant 后两个产品的自动消费同时停止。

## 16. 未来扩展

- 增加 DeFi、数据、基础设施和 Agent-to-Agent 采购适配器时复用同一 resolution contract。
- 支持 smart account/session key，但必须作为新的 AssetExecutionCapability，不修改 WalletIdentity 语义。
- 支持组织账户、多签和角色审批时，在 WalletIdentity 之上增加 Principal/ApprovalPolicy。
- 支持非 EVM 链时增加 chain-family adapter，不把 EVM 签名假设写入 SpendingGrant。
- 支持隐私预算和商家类别策略时扩展 policy，而不是把规则复制到 Adapter。

## 17. 架构决策

- Core 统一管理钱包身份和跨产品消费权限。
- SpendingGrant 与链上 AssetAllowance 分离。
- 平台凭证由垂直 Adapter 保存，Core 只持有绑定引用和审计关联。
- Hermes 不直接访问 Core。
- 一份 grant 可以覆盖多个产品，但权限范围必须显式选择。
- 一条链、一个 token、一个 spender 对应独立 allowance。
- external x402 先协商 Universal Payer 兼容性；兼容且通过 policy 的商家可免逐笔签名，不兼容或高风险场景 fail closed 到逐笔签名。
- 旧授权不自动升级为跨产品授权，用户需重新确认一次。
