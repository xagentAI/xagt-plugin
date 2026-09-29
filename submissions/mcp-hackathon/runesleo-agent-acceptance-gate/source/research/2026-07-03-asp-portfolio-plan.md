# OKX.AI ASP 多领域布局方案（T0521）

- 日期：2026-07-03
- 决策：Leo override「Park+触发器」→ 直接干 + 多领域占位（早进吃平台增长红利）
- 原则：每个服务 = 薄 wrapper（复用现有数据资产 + acceptance-gate 脚手架），单个服务建设成本 ≤1 天；不做重建设

## 服务组合（按平台类目布局）

### 🔥 世界杯（平台 hero 类目，流量最大）
**W1. 世界杯聪明钱雷达**（vs World Cup Alpha 已售51）
- 数据：PolyData 全量 Polymarket 数据 → 世界杯市场的 top 盈利地址持仓变动
- 差异化：竞品只给 top-50 地址列表；我们给「持仓变动事件流」（谁在加仓/翻转），对 agent 更可操作
- 定价：1 USDT/call
- ⏰ 时效：世界杯期间流量红利，**优先级最高，先发**

### 金融（核心类目，Leo 主场）
**F1. Polymarket 聪明钱追踪·全市场版**
- Task 端有同名挂单需求（未被满足）；W1 的全市场泛化，同一套代码两个 listing
- 1-2 USDT/call

**F2. 事件概率 vs 币价背离信号**
- PM 隐含概率 × perp funding/spot 背离 → trading agent 的事件风险输入
- 白区（官方 tradekit 明说不做信号层），无竞品
- 1-2 USDT/call

**F3. 加密市场脉动报告**（对应 Task 端挂单需求）
- 资金流 + 异动 + fear/greed 聚合 readout，trader 数据管线现成
- 1 USDT/call

### 软件服务（零成本占位）
**S1. Agent 交付验收审计**（acceptance auditor 本体）
- 已建成已测试（npm test 5/5），直接上架 = 沉没成本变期权
- 定价对齐 $1+：Full audit 1 USDT/call（放弃原 $0.05-0.25 塌陷带定价）
- 预期低销量，纯占位 + 万一 A2A 纠纷场景起量就是先发

### 暂不做
- 生活/艺术创作：无资产适配，不硬凑
- Evaluator/Arbitrator：需 stake ≥100 OKB + 24h uptime + slashable，资金 gate 且运维重，观察

## 建设顺序

1. **W1 + F1**（同一套聪明钱代码，两个 listing，吃最热类目）
2. **S1**（几乎零工作量，改定价即可）
3. **F2 → F3**（新数据管线接入，各 ≤1 天）

## 共享基建（做一次全组合复用）

- acceptance-gate 的 HTTP server / billing-event protocol / discovery metadata / OpenAPI 脚手架 → 抽成 multi-service host
- OKX Payment SDK 集成一次，所有服务共用
- 统一 idempotency / 计费事件 / 健康检查
- 数据依赖：PolyData（外接 SSD/VPS）→ 需要确定 serving 拓扑（本地数据如何喂线上 endpoint，等集成规格返回后定）

## Hard gate 打包清单（等集成规格确认细节后，Leo 一次批）

| # | Gate | 状态 |
|---|---|---|
| 1 | Agentic Wallet 创建（邮箱） | 待批 + 用哪个邮箱 |
| 2 | 收款地址/crypto 收入 | 方向已被「直接干」覆盖，金额阈值待定 |
| 3 | Deploy 目标（VPS/Workers/其他） | 等集成规格 → 提方案 |
| 4 | Payment SDK 集成 | 待批 |
| 5 | ASP listing 提交（×4 服务） | 待批 |
| 6 | 大陆资格 | ToS 无明确条款；风险自担推进（Leo 决策默认接受，可复核） |

## Review 节点（写死，防多点布局变时间黑洞）

- 上架后 4 周：全组合 <100 有机付费调用/周 且平台 GMV 无增长 → 降维护模式（不下架、停新增、注意力回主线）
- 平台周 GMV 破 $10K 或单服务 >50 单/周 → 加码扩品类
