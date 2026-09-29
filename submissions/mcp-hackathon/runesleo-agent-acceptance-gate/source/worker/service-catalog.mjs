/** Listed OKX.AI services: per-path fee (USDT string + x402 atomic units).
 *  okx_service_id synced to live Agent #3977 receipt 2026-07-24 (30207–30216).
 */
export const LISTED_SERVICE_PATHS = new Set([
  '/world-cup-smart-money-radar',
  '/polymarket-smart-money-radar',
  '/agent-delivery-acceptance-audit',
  '/event-price-divergence-radar',
  '/crypto-market-regime-radar',
  '/world-cup-upset-alert',
  '/token-dd-verdict',
  '/pm-trade-preflight',
  '/pm-event-readout',
  '/content-verify-claims',
  '/sports-smart-money-radar',
  '/sports-upset-alert',
  '/pm-profile',
  '/pm-pnl-audit',
  '/content-slop-check',
  '/agent-budget-preflight',
  '/pm-brier',
  '/publish-readiness',
  '/finance-cockpit',
  '/sports-cockpit',
  '/weather-event-readout',
  '/politics-event-readout',
  '/macro-fed-readout',
  '/football-match-card',
  '/tennis-match-card',
  '/nba-match-card',
  '/pm-decision-card',
  '/pm-market-scan',
  '/pm-market-health',
  '/pm-wallet-report',
  '/pm-updown-readout'
]);

export const SERVICE_CATALOG = {
  '/world-cup-smart-money-radar': {
    service_id: 'world_cup_smart_money_radar',
    okx_service_id: 30207,
    title: 'World Cup Smart Money Radar',
    category: 'world_cup',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/polymarket-smart-money-radar': {
    service_id: 'polymarket_smart_money_radar',
    okx_service_id: 30208,
    title: 'Polymarket Smart Money Radar',
    category: 'finance',
    fee_usdt: '0.05',
    fee_atomic: '50000',
    mode: 'live'
  },
  '/agent-delivery-acceptance-audit': {
    service_id: 'agent_delivery_acceptance_audit',
    okx_service_id: 30209,
    title: 'Agent Delivery Audit Gate',
    category: 'agent_ops',
    fee_usdt: '0.2',
    fee_atomic: '200000',
    mode: 'live'
  },
  '/event-price-divergence-radar': {
    service_id: 'event_price_divergence_radar',
    okx_service_id: 30210,
    title: 'Event Price Divergence Radar',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/crypto-market-regime-radar': {
    service_id: 'crypto_market_regime_radar',
    okx_service_id: 30211,
    title: 'Crypto Market Regime Radar',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/world-cup-upset-alert': {
    service_id: 'world_cup_upset_alert',
    okx_service_id: 30212,
    title: 'World Cup Upset Alert',
    category: 'world_cup',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/token-dd-verdict': {
    service_id: 'token_dd_verdict',
    okx_service_id: 30213,
    title: 'Token DD Verdict',
    category: 'finance',
    fee_usdt: '0.05',
    fee_atomic: '50000',
    mode: 'live'
  },
  '/pm-trade-preflight': {
    service_id: 'pm_trade_preflight',
    okx_service_id: 30214,
    title: 'PM Trade Preflight',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-event-readout': {
    service_id: 'pm_event_readout',
    okx_service_id: 30215,
    title: 'PM Event Analyst (Football-ready)',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/content-verify-claims': {
    service_id: 'content_verify_claims',
    okx_service_id: 30216,
    title: 'Content Verify Claims',
    category: 'agent_ops',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  // Code-ready; NOT on OKX listing until Leo authorize create/activate
  '/content-slop-check': {
    service_id: 'content_slop_check',
    okx_service_id: 36664,
    title: 'Content Slop Check',
    category: 'agent_ops',
    fee_usdt: '0.05',
    fee_atomic: '50000',
    mode: 'live'
  },
  '/sports-smart-money-radar': {
    service_id: 'sports_smart_money_radar',
    okx_service_id: 36661,
    title: 'Sports Smart Money Radar',
    category: 'sports',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/sports-upset-alert': {
    service_id: 'sports_upset_alert',
    okx_service_id: 36662,
    title: 'Sports Upset Alert',
    category: 'sports',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-profile': {
    service_id: 'pm_profile',
    okx_service_id: 36663,
    title: 'PM Profile',
    category: 'finance',
    fee_usdt: '0.05',
    fee_atomic: '50000',
    mode: 'live'
  },
  '/pm-pnl-audit': {
    service_id: 'pm_pnl_audit',
    okx_service_id: 37157,
    title: 'PM PnL Audit',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/agent-budget-preflight': {
    service_id: 'agent_budget_preflight',
    okx_service_id: 36666,
    title: 'Agent Budget Preflight',
    category: 'agent_ops',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-brier': {
    service_id: 'pm_brier',
    okx_service_id: 36668,
    title: 'PM Brier',
    category: 'finance',
    fee_usdt: '0.05',
    fee_atomic: '50000',
    mode: 'live'
  },
  '/publish-readiness': {
    service_id: 'publish_readiness',
    okx_service_id: 36669,
    title: 'Publish Readiness',
    category: 'agent_ops',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/finance-cockpit': {
    service_id: 'finance_cockpit',
    okx_service_id: 36670,
    title: 'Finance Cockpit',
    category: 'finance',
    fee_usdt: '0.15',
    fee_atomic: '150000',
    mode: 'live'
  },
  '/sports-cockpit': {
    service_id: 'sports_cockpit',
    okx_service_id: 36671,
    title: 'Sports Cockpit',
    category: 'sports',
    fee_usdt: '0.15',
    fee_atomic: '150000',
    mode: 'live'
  },
  '/weather-event-readout': {
    service_id: 'weather_event_readout',
    okx_service_id: 36675,
    title: 'Weather Event Readout',
    category: 'weather',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/politics-event-readout': {
    service_id: 'politics_event_readout',
    okx_service_id: 36676,
    title: 'Politics Event Readout',
    category: 'politics',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/macro-fed-readout': {
    service_id: 'macro_fed_readout',
    okx_service_id: 36677,
    title: 'Macro Fed Readout',
    category: 'macro',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/football-match-card': {
    service_id: 'football_match_card',
    okx_service_id: 36678,
    title: 'Football Match Card',
    category: 'sports',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/tennis-match-card': {
    service_id: 'tennis_match_card',
    okx_service_id: 36679,
    title: 'Tennis Match Card',
    category: 'sports',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/nba-match-card': {
    service_id: 'nba_match_card',
    okx_service_id: 36680,
    title: 'NBA Match Card',
    category: 'sports',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-decision-card': {
    service_id: 'pm_decision_card',
    okx_service_id: 36681,
    title: 'PM Decision Card',
    category: 'finance',
    fee_usdt: '0.15',
    fee_atomic: '150000',
    mode: 'live'
  },
  // Code-ready; NOT on OKX until Leo authorize create/activate
  '/pm-market-scan': {
    service_id: 'pm_market_scan',
    okx_service_id: 37171,
    title: '市场扫描 / PM Market Scan',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-market-health': {
    service_id: 'pm_market_health',
    okx_service_id: 37172,
    title: '盘口健康 / PM Market Health',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  },
  '/pm-wallet-report': {
    service_id: 'pm_wallet_report',
    okx_service_id: 37173,
    title: '钱包一页纸 / PM Wallet Report',
    category: 'finance',
    fee_usdt: '0.15',
    fee_atomic: '150000',
    mode: 'live'
  },
  '/pm-updown-readout': {
    service_id: 'pm_updown_readout',
    okx_service_id: 37174,
    title: '涨跌盘读出 / PM Up/Down Readout',
    category: 'finance',
    fee_usdt: '0.1',
    fee_atomic: '100000',
    mode: 'live'
  }
};

export function getServiceCatalogEntry(pathname) {
  return SERVICE_CATALOG[pathname] ?? null;
}

export function getFeeAtomicForPath(pathname) {
  return getServiceCatalogEntry(pathname)?.fee_atomic ?? '1000000';
}

/** OKX onchain listing copy (two lines, no URLs). Keys = live okx_service_id */
export const OKX_LISTING_COPY = {
  30207: {
    serviceName: 'World Cup Smart Money Radar',
    serviceDescription:
      'Sports smart-money radar with World Cup preference: scans large public trades; if no active World Cup markets, auto-expands to football and returns live signals with scope_expanded.\n'
      + '世界杯优先的聪明钱雷达：无活跃世界杯盘时自动扩展到足球并返回 live 信号（scope_expanded）。输入 market/all + limit 1-10。'
  },
  30208: {
    serviceName: 'Polymarket Smart Money Radar',
    serviceDescription:
      'Heuristic Polymarket wallet signals from recent large trades; topic search with limited coverage per call.\n'
      + 'Polymarket 全市场聪明钱雷达。输入 market/topic 关键词（如 bitcoin 或 all）+ limit 1-10；数据信号，非投资建议。'
  },
  30209: {
    serviceName: 'Agent Delivery Audit Gate',
    serviceDescription:
      'Rule-based audit of agent task delivery vs goals and evidence; returns pass, needs review, or fail.\n'
      + 'Agent 交付验收闸门：对照任务目标与证据，输出 pass/需复核/fail。输入 task、delivery_summary、artifacts、validation。'
  },
  30210: {
    serviceName: 'Event Price Divergence Radar',
    serviceDescription:
      'Flags where 24h prediction-market probability moves diverge from 24h OKX spot momentum on major crypto assets.\n'
      + '事件概率与币价背离雷达：PM 24h 概率变动 vs OKX 现货 24h 动量。输入 asset（bitcoin/ethereum/solana 或省略查主流）。'
  },
  30211: {
    serviceName: 'Crypto Market Regime Radar',
    serviceDescription:
      'Blends OKX spot momentum, perp funding/premium and Polymarket drift into risk_on/off/neutral/mixed with explainable score.\n'
      + '加密市场状态雷达：现货动量+资金费率+PM 情绪 → risk_on/off/neutral 及 0-100 分。输入 focus/asset 关键词 + limit。'
  },
  30212: {
    serviceName: 'World Cup Upset Alert',
    serviceDescription:
      'Upset alert with World Cup preference: flags profitable wallets on low-probability sides; if no active World Cup markets, auto-expands to football with scope_expanded.\n'
      + '世界杯优先的冷门预警：无活跃世界杯盘时自动扩展到足球（scope_expanded）。输入 market/all + limit；非投注建议。'
  },
  30213: {
    serviceName: 'Token DD Verdict',
    serviceDescription:
      'Rule-based token research gate with DEX liquidity/volume heuristics for EVM contracts; returns avoid/watch/research buckets.\n'
      + '代币尽调闸门：规则引擎输出 avoid/观望/可研究等分桶；EVM 合约查 DEX 流动性与活跃度。输入 asset（ticker 或合约地址）。'
  },
  30214: {
    serviceName: 'PM Trade Preflight',
    serviceDescription:
      'Read-only eligible/watch/skip gate before a Polymarket order; checks liquidity, price zone, spread, and decision-card lite fields. eligible ≠ buy tip.\n'
      + '预测市场下单前检查：eligible/观望/跳过，只读不下单。输入 market_url 或 slug + side(yes/no)，可选 size_usd。'
  },
  30215: {
    serviceName: 'PM Event Readout',
    serviceDescription:
      'Event evidence card: same-event matrix + football/tennis/NBA/politics/weather/macro-Fed/Musk plugins (fixture/hard_veto where applicable). Not a buy tip.\n'
      + '预测市场事件解读卡：同场矩阵；足球/网球/NBA/政治/天气/美联储/Musk 等品类插件（含赛程/硬闸）。输入 market_url 或 slug；不下单。'
  },
  30216: {
    serviceName: 'Content Verify Claims',
    serviceDescription:
      'Rule-based check that publish claims overlap caller-supplied source excerpts; pass, needs_review, or fail.\n'
      + '发布前断言核查：对照你提供的原文摘录核对数字/关键词。输入 claims[] + sources[].text；不抓网页。'
  },
  36661: {
    serviceName: 'Sports Smart Money Radar',
    serviceDescription:
      'Heuristic sports prediction-market wallet signals (football leagues, tennis, NBA, NFL, UFC, MLB, etc.); data only.\n'
      + '体育预测市场聪明钱雷达：不绑死世界杯。输入 sport + 可选 league/query/tag_slug + limit。'
  },
  36662: {
    serviceName: 'Sports Upset Alert',
    serviceDescription:
      'Flags profitable wallets entering low-probability sports outcomes; optional max_prob threshold; data only.\n'
      + '体育冷门预警：盈利钱包买低概率侧。输入 sport/league/query + 可选 max_prob(0.05-0.5)；非投注建议。'
  },
  36663: {
    serviceName: 'PM Profile',
    serviceDescription:
      'Read-only Polymarket wallet snapshot: 7d leaderboard PnL + open positions sample. From public APIs / polymarket-toolkit lineage.\n'
      + 'Polymarket 钱包画像：7日榜 PnL + 持仓抽样。输入 address 或 username；只读不下单。'
  },
  36664: {
    serviceName: 'Content Slop Check',
    serviceDescription:
      'Rule-based AI-slop / filler detection for draft text before publish; returns slop_score and flags. Not a rewrite service.\n'
      + '发布前注水/AI 废话检测：输出 slop_score 与旗帜。输入 text；不改写、不发帖。'
  },
  36666: {
    serviceName: 'Agent Budget Preflight',
    serviceDescription:
      'Deterministic spend gate before an agent pays for an API/x402 call: buy / skip_sufficient / reject with reasons. No wallet, no settle.\n'
      + 'Agent 付费调用前预算闸门：输出 buy/跳过/拒绝及原因。输入 budget_cap_usdt + offer.price_usdt；不签名、不结算。'
  },
  36668: {
    serviceName: 'PM Brier',
    serviceDescription:
      'Read-only Polymarket calibration score from settled positions (Brier); good/moderate/poor rating. From polymarket-toolkit lineage.\n'
      + 'Polymarket 校准分（Brier）：已结算持仓抽样。输入 address 或 username；只读不下单。'
  },
  36669: {
    serviceName: 'Publish Readiness',
    serviceDescription:
      'Pre-publish gate combining slop detection + claim/source overlap; returns ready / edit_first / block with Chinese buyer summary.\n'
      + '发布就绪闸门：注水检测 + 断言核查 → ready/先改/别发。输入 text + 可选 claims[]/sources[]；不改写、不发帖。'
  },
  36670: {
    serviceName: 'Finance Cockpit',
    serviceDescription:
      'Composed crypto co-pilot card: market regime score + event-price divergence signals in one JSON response. Data only.\n'
      + '金融副驾驶组合卡：市场状态分 + 事件概率/现货背离。输入 focus/asset + limit；不下单。'
  },
  36671: {
    serviceName: 'Sports Cockpit',
    serviceDescription:
      'Composed sports co-pilot card: smart-money signals + upset alerts (+ cross-market wallet cohort) in one JSON response. Data only.\n'
      + '体育副驾驶组合卡：聪明钱 + 冷门预警（含跨场钱包）。输入 sport/league/query + 可选 max_prob；非投注建议。'
  },
  36675: {
    serviceName: 'Weather Event Readout',
    serviceDescription:
      'Live weather temperature-ladder card: query/default discovery, bucket surface, hard_veto_gaps (station/obs/snapshot/ladder) + adjacent-ladder diagnostics; no_active_markets if none. Optional caller weather{}; no station scrape.\n'
      + '天气温度阶梯卡：发现活跃盘、桶面、station/实况/快照硬闸、相邻桶诊断；无盘 no_active_markets。可选 weather{}；不爬站、不下单。'
  },
  36676: {
    serviceName: 'Politics Event Readout',
    serviceDescription:
      'Live politics/election ladder card: query discovery or category default to an active market; exclusivity sanity; no_active_markets if none.\n'
      + '政治选举盘口卡：query/品类默认发现活跃盘；无盘返回 no_active_markets。输入 query 或 slug；不下单。'
  },
  36677: {
    serviceName: 'Macro Fed Readout',
    serviceDescription:
      'Live Fed/FOMC rate card: query/default discovery + L1 rate-decision ladder / expected-move heuristic; honest external-anchor gaps; no_active_markets if none.\n'
      + '美联储利率宏观卡：发现活跃盘 + L1 利率阶梯/隐含变动；外部锚定缺口如实标注。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  36678: {
    serviceName: 'Football Match Card',
    serviceDescription:
      'Live football evidence card: discovery + same-event matrix, fixture gate, matrix_completeness/hard_veto_gaps, expression compare; match vs outright_season; no_active_markets if none. Not a buy tip.\n'
      + '足球比赛卡：同场矩阵、赛程闸门、完备性硬闸、表达比较；区分单场/赛季 outright。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  36679: {
    serviceName: 'Tennis Match Card',
    serviceDescription:
      'Live tennis evidence card: format-aware ML/set/totals, fixture gate, matrix_completeness/hard_veto_gaps, domination check; no_active_markets if none. Not a buy tip.\n'
      + '网球比赛卡：赛制感知矩阵、赛程闸门、完备性硬闸、直落盘检查。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  36680: {
    serviceName: 'NBA Match Card',
    serviceDescription:
      'Live NBA evidence card: query/default discovery; moneyline/spread/totals matrix; match vs outright_season filter; no_active_markets if none. Not a buy tip.\n'
      + 'NBA 比赛卡：胜负/让分/总分矩阵；区分单场/赛季 outright。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  36681: {
    serviceName: 'PM Decision Card',
    serviceDescription:
      'Pre-trade decision gate: preflight + optional event context → opportunity_state + skip/watch/eligible_for_manual_review; optional size_usd/bankroll_usd → order_quantity_shares (share-first). Replay before each order. Not a buy tip; no orders.\n'
      + '预测市场决策卡：机械检查+事件上下文 → opportunity_state + 跳过/观望/可人工复核；可选 size/bankroll → shares。每次下单前重跑；非买点、不下单。'
  },
  37157: {
    serviceName: 'PM PnL Audit',
    serviceDescription:
      'Polymarket PnL trust gate: quick LB vs position cashPnL, or mode=full Worker-safe cashflow replay (TRADE/REDEEM/MERGE/SPLIT/REBATE/… ) with honest pagination_incomplete. Data only.\n'
      + 'Polymarket PnL 审计：quick 对比排行榜与持仓 cashPnL；mode=full 做现金回流（含分页 incomplete 诚实标记）。输入 address/username；只读不下单。'
  },
  37171: {
    serviceName: '市场扫描 / PM Market Scan',
    serviceDescription:
      'Read-only Polymarket market scanner: rank active books by 24h volume and spread (toolkit pm scan). Optional query + min_volume + limit. Not a buy tip.\n'
      + '市场扫描：按 24h 成交量与价差筛活跃盘（toolkit pm scan）。输入可选 query + min_volume + limit；只读不下单。'
  },
  37172: {
    serviceName: '盘口健康 / PM Market Health',
    serviceDescription:
      'Read-only book health: spread, depth proxies, yes/no overround for one market or event. Flags wide/thin/incoherent books. Not a buy tip.\n'
      + '盘口健康：价差/深度/overround 快照（单盘或同场）。宽价差或 incoherent 会标出。输入 market_url/slug/event_slug；只读不下单。'
  },
  37173: {
    serviceName: '钱包一页纸 / PM Wallet Report',
    serviceDescription:
      'Composed wallet one-pager: profile + Brier calibration + PnL audit (quick/full) in one JSON. Copy-trust composite; data only.\n'
      + '钱包一页纸：画像 + Brier 校准 + PnL 审计（quick/full）合成。输出 composite_action；输入 address/username；只读不下单。'
  },
  37174: {
    serviceName: '涨跌盘读出 / PM Up/Down Readout',
    serviceDescription:
      'Crypto up/down event surface from Gamma with resolution-source pitfalls (toolkit pm updown). Verify settlement rules before pricing. Not a buy tip.\n'
      + '涨跌盘读出：Gamma 涨跌事件面 + 结算源陷阱提示（toolkit pm updown）。先核结算定义再谈价。输入 event_slug 或 query；只读不下单。'
  }
};

/** Listing copy for services not yet on OKX (use with onchainos create). Keys = service_id */
export const PENDING_OKX_LISTING_COPY = {
  content_slop_check: {
    serviceName: 'Content Slop Check',
    serviceDescription:
      'Rule-based AI-slop / filler detection for draft text before publish; returns slop_score and flags. Not a rewrite service.\n'
      + '发布前注水/AI 废话检测：输出 slop_score 与旗帜。输入 text；不改写、不发帖。'
  },
  sports_smart_money_radar: {
    serviceName: 'Sports Smart Money Radar',
    serviceDescription:
      'Heuristic sports prediction-market wallet signals (football leagues, tennis, NBA, NFL, UFC, MLB, etc.); data only.\n'
      + '体育预测市场聪明钱雷达：不绑死世界杯。输入 sport + 可选 league/query/tag_slug + limit。'
  },
  sports_upset_alert: {
    serviceName: 'Sports Upset Alert',
    serviceDescription:
      'Flags profitable wallets entering low-probability sports outcomes across competitions; data only.\n'
      + '体育冷门预警：盈利钱包买低概率侧。输入 sport/league/query；非投注建议。'
  },
  pm_profile: {
    serviceName: 'PM Profile',
    serviceDescription:
      'Read-only Polymarket wallet snapshot: 7d leaderboard PnL + open positions sample. From public APIs / polymarket-toolkit lineage.\n'
      + 'Polymarket 钱包画像：7日榜 PnL + 持仓抽样。输入 address 或 username；只读不下单。'
  },
  pm_pnl_audit: {
    serviceName: 'PM PnL Audit',
    serviceDescription:
      'Polymarket PnL trust gate: quick LB vs position cashPnL, or mode=full Worker-safe cashflow replay (TRADE/REDEEM/MERGE/SPLIT/REBATE/… ) with honest pagination_incomplete. Data only.\n'
      + 'Polymarket PnL 审计：quick 对比排行榜与持仓 cashPnL；mode=full 做现金回流（含分页 incomplete 诚实标记）。输入 address/username；只读不下单。'
  },
  agent_budget_preflight: {
    serviceName: 'Agent Budget Preflight',
    serviceDescription:
      'Deterministic spend gate before an agent pays for an API/x402 call: buy / skip_sufficient / reject with reasons. No wallet, no settle.\n'
      + 'Agent 付费调用前预算闸门：输出 buy/跳过/拒绝及原因。输入 budget_cap_usdt + offer.price_usdt；不签名、不结算。'
  },
  pm_brier: {
    serviceName: 'PM Brier',
    serviceDescription:
      'Read-only Polymarket calibration score from settled positions (Brier); good/moderate/poor rating. From polymarket-toolkit lineage.\n'
      + 'Polymarket 校准分（Brier）：已结算持仓抽样。输入 address 或 username；只读不下单。'
  },
  publish_readiness: {
    serviceName: 'Publish Readiness',
    serviceDescription:
      'Pre-publish gate combining slop detection + claim/source overlap; returns ready / edit_first / block with Chinese buyer summary.\n'
      + '发布就绪闸门：注水检测 + 断言核查 → ready/先改/别发。输入 text + 可选 claims[]/sources[]；不改写、不发帖。'
  },
  finance_cockpit: {
    serviceName: 'Finance Cockpit',
    serviceDescription:
      'Composed crypto co-pilot card: market regime score + event-price divergence signals in one JSON response. Data only.\n'
      + '金融副驾驶组合卡：市场状态分 + 事件概率/现货背离。输入 focus/asset + limit；不下单。'
  },
  sports_cockpit: {
    serviceName: 'Sports Cockpit',
    serviceDescription:
      'Composed sports co-pilot card: smart-money signals + upset alerts (+ cross-market wallet cohort) in one JSON response. Data only.\n'
      + '体育副驾驶组合卡：聪明钱 + 冷门预警（含跨场钱包）。输入 sport/league/query + 可选 max_prob；非投注建议。'
  },
  weather_event_readout: {
    serviceName: 'Weather Event Readout',
    serviceDescription:
      'Live weather temperature-ladder card: query/default discovery, bucket surface, hard_veto_gaps (station/obs/snapshot/ladder) + adjacent-ladder diagnostics; no_active_markets if none. Optional caller weather{}; no station scrape.\n'
      + '天气温度阶梯卡：发现活跃盘、桶面、station/实况/快照硬闸、相邻桶诊断；无盘 no_active_markets。可选 weather{}；不爬站、不下单。'
  },
  politics_event_readout: {
    serviceName: 'Politics Event Readout',
    serviceDescription:
      'Live politics/election ladder card: query discovery or category default; exclusivity sanity; no_active_markets if none.\n'
      + '政治选举盘口卡：query/品类默认发现活跃盘；无盘返回 no_active_markets。输入 query 或 slug；不下单。'
  },
  macro_fed_readout: {
    serviceName: 'Macro Fed Readout',
    serviceDescription:
      'Live Fed/FOMC rate card: query/default discovery + L1 rate-decision ladder / expected-move heuristic; honest external-anchor gaps; no_active_markets if none.\n'
      + '美联储利率宏观卡：发现活跃盘 + L1 利率阶梯/隐含变动；外部锚定缺口如实标注。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  football_match_card: {
    serviceName: 'Football Match Card',
    serviceDescription:
      'Live football evidence card: discovery + same-event matrix, fixture gate, matrix_completeness/hard_veto_gaps, expression compare; match vs outright_season; no_active_markets if none. Not a buy tip.\n'
      + '足球比赛卡：同场矩阵、赛程闸门、完备性硬闸、表达比较；区分单场/赛季 outright。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  tennis_match_card: {
    serviceName: 'Tennis Match Card',
    serviceDescription:
      'Live tennis evidence card: format-aware ML/set/totals, fixture gate, matrix_completeness/hard_veto_gaps, domination check; no_active_markets if none. Not a buy tip.\n'
      + '网球比赛卡：赛制感知矩阵、赛程闸门、完备性硬闸、直落盘检查。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  nba_match_card: {
    serviceName: 'NBA Match Card',
    serviceDescription:
      'Live NBA evidence card: query/default discovery; moneyline/spread/totals matrix; match vs outright_season filter; no_active_markets if none. Not a buy tip.\n'
      + 'NBA 比赛卡：胜负/让分/总分矩阵；区分单场/赛季 outright。无盘 no_active_markets。输入 query/slug；不下单。'
  },
  pm_decision_card: {
    serviceName: 'PM Decision Card',
    serviceDescription:
      'Pre-trade decision gate: preflight + optional event context → opportunity_state + skip/watch/eligible_for_manual_review; optional size_usd/bankroll_usd → order_quantity_shares (share-first). Replay before each order. Not a buy tip; no orders.\n'
      + '预测市场决策卡：机械检查+事件上下文 → opportunity_state + 跳过/观望/可人工复核；可选 size/bankroll → shares。每次下单前重跑；非买点、不下单。'
  },
  pm_market_scan: OKX_LISTING_COPY[37171],
  pm_market_health: OKX_LISTING_COPY[37172],
  pm_wallet_report: OKX_LISTING_COPY[37173],
  pm_updown_readout: OKX_LISTING_COPY[37174],
  crypto_market_regime_radar: OKX_LISTING_COPY[30211],
  world_cup_upset_alert: OKX_LISTING_COPY[30212],
  token_dd_verdict: OKX_LISTING_COPY[30213],
  pm_trade_preflight: OKX_LISTING_COPY[30214],
  pm_event_readout: OKX_LISTING_COPY[30215],
  content_verify_claims: OKX_LISTING_COPY[30216]
};

/** Map catalog path → pending copy entry */
export function pendingListingCopyForPath(pathname) {
  const entry = getServiceCatalogEntry(pathname);
  if (!entry?.service_id) return null;
  return PENDING_OKX_LISTING_COPY[entry.service_id] ?? null;
}

export function okxListingFeeForServiceId(serviceId) {
  const entry = Object.values(SERVICE_CATALOG).find((s) => s.okx_service_id === serviceId);
  return entry?.fee_usdt ?? '0.1';
}
