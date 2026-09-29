# Bazaar 小规模供应接入设计

## 目标

将 CDP Bazaar 作为外部供应商发现来源，同时保持 Clink Marketplace 是最终的可信验证和交易编排层。第一阶段按 5–20 家商家的正式试运营规模建设。

成功标准是：Clink 能从 Bazaar 导入候选服务，协助商家认领已导入的服务，独立验证商家身份和支付信息，仅向 Hermes 发布通过验证的服务，并能持续监控供应链路。Clink 不直接继承 Bazaar 的可信状态。

## 产品边界

- Bazaar 提供服务发现元数据、声明的支付要求和外部质量信号。
- Marketplace 负责统一的商家与服务身份、来源记录、服务认领、验证、目录发布、报价比较、购买编排和 Clink 信誉。
- Core 仍是唯一的授权、风控、额度、结算和审计控制面。
- Hermes 只能发现和购买 Clink 本地验证通过的服务，不能访问候选商家、商家管理、Registry 同步或 Core。

## 试运营模式

首批 5–20 家商家采用运营辅助入驻：

1. Clink 从 Bazaar 同步服务，进入内部候选池。
2. 运营人员根据能力、网络、价格和 Bazaar 质量信号筛选候选商家。
3. 商家通过钱包所有权和域名控制权认领已导入的服务。
4. Clink 根据导入信息预填 Manifest，避免商家重复录入。
5. 商家签署 Manifest Claim，并完成域名验证。
6. Clink 独立请求商家接口，校验实时 HTTP 402 支付要求。
7. 所有本地验证通过后，服务才进入公开目录并允许 Hermes 发现。

所有权证明必须由商家本人完成。运营人员可以协助配置，但不能代替商家签名或认领服务。

## Bazaar 接入

### 目录同步

Worker 使用 CDP Bazaar 分页资源接口同步完整目录：

```text
GET /platform/v2/x402/discovery/resources?type=http&limit=<n>&offset=<n>
```

语义搜索接口只用于运营人员按主题寻找服务，不作为全量同步来源，因为它面向相关性搜索且不提供分页。

每个 Registry 的同步状态需要保存：

- Registry 标识；
- 当前 offset，以及接口返回时的 ETag；
- 最近一次同步成功时间；
- 最近错误和运行状态；
- 来源资源标识与标准化后的原始来源信息；
- 分页进度，保证单页失败不会丢弃此前成功结果。

同步必须幂等。新的 Bazaar 导入不能把 Clink 已验证的 Provider 或 Offering 降级为未验证状态。

### 统一身份与去重

- `provider_id` 根据标准化域名生成。
- `offering_id` 根据标准化 HTTP method 和 endpoint 生成。
- 同一服务来自多个 Registry 时，保留多条来源记录，但只生成一个统一 Offering。
- Bazaar 的 `payTo` 和质量分不能证明该服务已经获得 Clink 信任。
- 商家后续直接提交 Manifest Claim 时，更新现有 Provider 和 Offering，不创建重复记录。

### 候选服务可见性

导入记录初始状态为 `discovered`，只允许通过经过认证的商家或管理员接口访问。公开目录和 MCP 搜索继续只返回验证有效且未过期的 `verified` Offering。

### 首批目标供应覆盖

全量目录分页之外，Worker 对 CoinGecko、Nansen、Allium、Firecrawl、Exa、Alchemy、Pinata、Venice、ElevenLabs 和 dTelecom 执行定向 Bazaar discovery search，避免目标服务因目录排序和单周期页数预算而长期无法进入候选池。定向发现不应用买方网络或价格过滤；这些约束只在搜索、报价和购买阶段执行。

服务名称、域名、描述或标签命中目标品牌时，Clink 记录 `first_party`、`branded` 或 `powered_by` 关系，但保持 Bazaar 返回的真实 Provider 身份。第三方代理或转售服务不得被重命名为品牌官方服务。健康状态逐项返回目标供应的 `missing / discovered / claimed / verified` 覆盖情况。

## 商家认领与验证

### 认领流程

登录后的商家可以按标准化域名或 `payTo` 查找可认领的 Bazaar 候选服务。创建认领请求时，Clink 返回预填 Manifest 草稿，其中包含 endpoint、method、schema、支付选项和 Bazaar 来源信息。

商家随后必须完成：

1. SIWE 登录；
2. EIP-712 `ManifestClaim` 签名；
3. 域名所有权验证；
4. 实时 endpoint 验证。

如果 Provider 已归属于其他钱包，系统不得静默覆盖，必须进入管理员所有权冲突审核。

### Clink 本地验证门槛

发布前，Clink 必须独立验证：

- endpoint 为公开 HTTPS 地址，并防止访问内网地址和 DNS rebinding；
- 域名证明与 Provider ID、认领钱包一致；
- 实时 endpoint 返回 HTTP 402；
- `scheme`、`network`、`asset`、`amount`、`payTo` 与签名 Manifest 完全一致；
- 输入与输出发现元数据结构有效；
- endpoint 最近一小时内验证成功。

所有外部质量信号单独记录，不能绕过上述验证。

## 状态模型

Provider 状态：

```text
discovered -> wallet_verified -> domain_verified -> active
                                             \-> suspended
```

Offering 状态：

```text
discovered -> submitted -> verifying -> verified
                                      \-> rejected
verified -> stale -> verified
verified/stale -> disabled
```

Registry 同步状态：

```text
idle -> running -> succeeded
                \-> partial
                \-> failed
```

## 必要接口

### 内部与管理员接口

- 触发或查看 Bazaar 目录同步。
- 根据能力、网络、价格、收款地址、质量和来源筛选候选服务。
- 查看 Registry offset、数据新鲜度、分页进度和失败原因。
- 暂停或恢复 Provider。
- 审核商家所有权冲突。

### 商家接口

- 查看当前钱包或域名可认领的候选服务。
- 从候选服务生成预填 Manifest 草稿。
- 继续使用 Manifest 签名、域名验证和 endpoint 验证流程。
- 查看验证失败原因并在修复后重试。

### Agent 接口

公开 MCP 继续只提供可信服务搜索、报价比较、购买预览、购买执行和购买状态查询。不得向 Hermes 暴露 Bazaar 同步或商家管理工具。

## 稳定性与运维

试运营阶段继续使用 Postgres 作为数据真源，Redis 保存短期购买输入和会话数据。不引入搜索集群、Kubernetes 或事件总线。

必须具备以下运行能力：

- 一个定时 Worker 负责 Bazaar 同步和验证刷新；
- 每个 Registry 独立超时和故障隔离；
- 有上限的重试与退避；
- 健康检查分别展示 API、Worker、Registry 数据新鲜度和 Core 连通性；
- 统计候选服务数、已认领商家数、已验证服务数、过期服务数、同步失败、购买成功率和交付成功率；
- 结构化日志包含 Registry ID、Provider ID、Offering ID、Purchase ID 和 Core Action ID；
- 密钥只能通过运行环境配置注入。

## 本轮必须修复的生产阻断项

达到试运营标准前，必须同时修复现有代码中的以下问题：

- Core policy 请求使用真实接口 `/policies/evaluate`。
- 将 `python-dotenv` 加入运行依赖。
- SIWE session、challenge 和待签 Manifest 在进程重启后不会丢失。
- 购买执行必须使用 Preview 中实际选择的 payment option。
- 服务调用成功后，结果只即时返回给 Hermes；Marketplace 只持久化 hash 和交付元数据。
- 购买结果能够生成可重放的信誉快照。
- Docker Compose 启动 Marketplace API、Worker、MCP、Postgres、Redis 和 migration，并配置健康检查。

## 安全与异常处理

- Registry 数据必须视为不可信输入，经过与直接 Manifest 相同的 URL 和 schema 校验。
- 同步过程不得调用任何付费接口。
- 报价比较阶段不得把买家的真实服务输入广播给多个商家。
- 单个 Registry 失败不能删除或破坏已经验证的服务。
- 报价或支付信息漂移必须在 Core 预留资金前使 Preview 失效。
- 已付款但未交付的订单不得自动再次付款。
- 必须拒绝重复 Claim、过期签名、Manifest 被修改以及钱包或域名不匹配。

## 测试要求

自动化测试必须覆盖：

- Bazaar 分页导入、单页失败、断点恢复、去重和 ETag；
- 导入不能继承 verified 状态，也不能降级现有 verified Offering；
- 候选服务查询与预填 Manifest；
- 商家所有权冲突；
- SIWE、challenge 和 Manifest Claim 状态在重启后仍然有效；
- 每一个支付字段的实时不一致验证；
- Preview 选择的 payment option 在执行时保持一致；
- Core policy 接口兼容性；
- 结果即时返回 Hermes、持久层只保存 hash；
- delivered、failed、paid-but-undelivered 对信誉的影响；
- 容器健康检查和 migration 启动 smoke test。

## 试运营验收标准

满足以下条件后，才能认为首批试运营可用：

- 至少 20 个 Bazaar 候选服务可以反复同步且不会重复；
- 至少 5 家商家可以完成认领和 Clink 本地验证；
- Hermes 只能看到验证有效且未过期的 Offering；
- Clink-native 与 external x402 两种购买方式各完成一笔端到端购买，且不会重复扣款；
- 服务结果返回 Hermes，但不以明文写入 Marketplace 持久存储；
- 每笔购买都能查询 Core Action、Policy、Reservation、Receipt 和 Audit 引用；
- API 或 Worker 重启不会丢失商家入驻或购买状态；
- endpoint 过期和 Registry 失败能通过健康检查或运维接口看到。

## 本轮不做

- 面向数百家商家的完全开放式自助入驻。
- 主观星级评论。
- 自动退款和完整争议仲裁。
- 多地域高可用。
- Elasticsearch、Kafka、Kubernetes 或消费者商城。
