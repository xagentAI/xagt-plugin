# Claude Phase 2 — 独立结论 vs Codex Repo 对比

- 日期：2026-07-03
- 前置：Phase 1 盲评见 `2026-07-03-claude-independent-market-research.md`（未读 repo 先出结论）
- Repo 状态：可运行的确定性规则引擎（npm test 5/5 通过）+ 完整策略文档，已被 hard gate 停在本地；仅 demo 页公开

## 对比分析

### 1. Repo 与独立市场论点吻合处

- **A2MCP pay-per-call 是正确车道**：Codex 推荐以 A2MCP（固定 schema、按调用付费）上架、不做 A2A、不做 Evaluator staking——与我的独立结论一致
- **Codex 自己已察觉核心风险**：`market-demand-research-cn.md` 坦承 acceptance gate「不是最大或最被验证的需求」且「可能是平台内建 feature」；multi-model validation（2026-07-02）给了 Yellow / 直接上线 Red。我的外部证据把这个怀疑坐实了
- **Hard gate 纪律**：双方完全一致，repo 停在正确的位置

### 2. 过拟合 Codex 假设处

- **需求假设被平台事实推翻**：验收流程已捆绑进 OKX 托管流（用户签收放款 + 3 天 auto-accept + staked Evaluator/GenLayer 仲裁），第三方「验收门禁」没有独立产品面。Codex 的怀疑是「可能被平台做掉」；外部证据是「已经被平台做掉了」
- **收入模型悬空**：$85K MRR 目标 vs 整个 x402 轨道有机量仅 ~$28-37K/**天**（且约一半交易是刷的）——目标 MRR 接近整条支付轨的真实规模
- **定价撞塌陷带**：Quick tier $0.05-0.25 落在已塌陷的 sub-dollar 段（10c-$1 从 46% 跌到 4% of value）；市场用脚投票 $1+ 价值密集调用
- **5 层扩张（声誉/信用层）= 撞平台自营面**
- **数据点冲突待查**：repo 引 Genesis Hackathon $100K 奖池；我验证到的 Build X Hackathon 仅 14K USDT（最近一季已结束）。可能是两个不同活动，需核实

### 3. Keep / Change / Kill

**Keep:**
- `src/auditor.mjs` 确定性审计引擎 → 转内部用途：Leo 自己的 multi-agent 工作流验收（对齐 WORKER_WRITEBACK_PROTOCOL 的 artifact/validation/writeback 验收），这是它今天就有真实用户（Leo 本人）的场景
- HTTP server / billing-event protocol / discovery metadata / OpenAPI 脚手架 → 这是**通用 A2MCP 服务管线**，换掉 payload 即可复用
- 全部 OKX.AI 集成知识（A2MCP vs A2A、Payment SDK、402 计费、idempotency）
- sample-inputs/outputs 六个案例 → 内容素材（build in public）

**Change:**
- ASP 切入点从「验收审计」pivot 到「自有数据 A2MCP 服务」：Polymarket 衍生信号 / 跨市场数据 / okx-trade-mcp 164 工具未覆盖的交易分析，$1+/call
- repo 定位从「产品」改为「A2MCP 服务脚手架 + 内部验收工具」

**Kill:**
- 独立验收/验证作为对外收入产品
- $1M OPC 5 层扩张策略（撞平台自营面）
- sub-dollar 定价层
- dispute-tier 收入线（依赖未验证的纠纷量 + Evaluator 是角色不是产品层）

**New direction:**
- 用现有脚手架包 2-3 个 Polymarket 数据 endpoint 成 A2MCP 服务，小赌注验证平台买方是否存在

**Next 24h:**（全部只读/本地，不触 gate）
1. 核实 Genesis Hackathon $100K vs Build X 14K 差异
2. 浏览 OKX.AI BETA marketplace 实际吞吐信号（listing 数、任务数）——回答「有没有买方」
3. 列出候选数据 endpoint 清单 + 每个的差异化理由
4. 写预测市场数据变现 vs T0520 合规线的对照 memo，交 Leo 判断

**Next 7d:**
- 合规过线 + Leo 批准后：ASP 注册（gate）→ Payment SDK 集成（gate）→ 上架埋点 → 3-4 周 kill criteria 观察（<100 有机付费调用/周 或 <$50/周 → kill）

**Hard gates:**（不变，全部需 Leo 显式批准）
- OKX.AI 账号 / Agentic Wallet / API key / 钱包地址 / 签名 / 交易 / staking / 支付集成 / ASP 上架 / 公开 repo / push / deploy / leolabs 发布
