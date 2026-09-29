# OKX.AI ASP 集成规格（实施版摘要）

- 日期：2026-07-03 · 来源：onchainos-skills repo 源码研读（clone 于 scratchpad）+ okx/payments SDK 文档
- 完整报告见 agent 返回（本文件为实施要点）

## 架构：两套系统

1. **链上身份 + 服务列表**：`onchainos` CLI 创建（ERC-8004 on X Layer）
2. **自托管 x402 endpoint**：用 OKX Payments SDK 自建，真实收款发生在这里（HTTP 402 → 买方签 EIP-3009 → 重放）。listing 的 fee 只是展示价，实际收费由 endpoint 的 402 challenge 决定，需自行保持一致

## 注册流程

1. Agentic Wallet：`onchainos wallet login <email>` + OTP → 自动建钱包。**仅邮箱、无 KYC、无助记词**（私钥在服务端 TEE）。收款地址 = 该钱包的 X Layer (chainId 196) 0x 地址
2. `onchainos agent pre-check --role asp` → `agent create --role asp ... --service '[...]'` → 上传头像（ASP 必须，传文件不能链接）→ `agent activate`
3. **可能存在 beta 白名单门**（error 10016，需申请等邮件批准）——只有真跑 pre-check 才知道是否仍生效
4. activate 后 **~24h LLM/人工审核**才上架

## 多服务模型（对组合方案有利）

- **一个钱包 = 一个 ASP 身份 = 可挂 N 个服务**（`--service` 是 JSON 数组，可增量 create/update/delete）——W1/F1/F2/S1 全挂一个身份下，正合布局需求
- 链上操作平台代付 gas，无 per-listing 费用（结算是否抽成未确认，a2a 路径有 fee_bps 字段）

## Listing 字段硬规则（内容审核会卡）

- 服务名 5-30 字符、名词短语、不含价格；描述两行（①核心能力 ②用户需提供什么），各 ≤200 全角字符，**禁 URL/0x 地址/技术栈名/免责声明/名人名**
- fee：纯数字字符串（如 `"1"`），单位恒为 USDT，≤6 位小数
- endpoint：必须 `https://` 公网可达，**上链后永久**（改 = 链上更新交易）；拒绝 http/localhost/内网地址

## Seller 端技术栈（TS）

- `@okxweb3/x402-core` + `@okxweb3/x402-evm` + `@okxweb3/x402-express`（有 hono/fastify/next 适配器）
- 网络锁死 `eip155:196`（X Layer mainnet），默认 token USDT0（6 decimals），EIP-3009 gasless
- **OKX 托管 facilitator**（web3.okx.com），verify+settle 不需要自己连链；鉴权用 SA API key（OKX_API_KEY/SECRET/PASSPHRASE）——**这意味着还需要申请一套 API key（hard gate）**
- 计费模式用 `exact`（固定单价）；`syncSettle: true` 确认到账再交付
- 现有 acceptance-gate 的 Node http server 可直接套 express 适配器改造

## Hosting 要求

- 公网 HTTPS 24/7，URL 永久上链 → **必须用稳定域名**（如 api.leolabs.me 子域反代），换机器不换 URL
- 无正式 SLA，但挂了 = 付费调用失败 + 链上评分受损
- 数据拓扑建议：本地/SSD 的 PolyData 派生信号定时同步到 serving 机器，endpoint 只读预计算结果（endpoint 不直连重数据库）

## ⚠️ 最大风险：服务端区域封锁

- error `50125`/`80001` = "Service is not available in your region"，**API 服务端强制**，公开文档不列封锁国家清单
- 工具链明文规则：*"Never suggest checking the network environment, using a VPN, or any region workaround"*
- 对大陆 operator：注册/登录/SA API/facilitator 任何一环被 geo 挡 = 整条路死。**必须先探测再投入建设**
- 未决：具体封锁名单、白名单是否仍生效、TS 是否有 MCP-tool wrapper（Go 有；但 A2MCP endpoint 本质是普通 x402 HTTPS API，大概率够用）

## 执行序（更新）

0. **Geo 探测**（无 gate，立即）：从实际操作位置探 web3.okx.com API 可达性
1. Leo 批 gate 包 → 邮箱建钱包 → `pre-check` 摸白名单
2. 改造脚手架为 multi-service x402 host（W1+F1 先行）
3. 部署到稳定域名 → SA API key → listing 提交 → 24h 审核
