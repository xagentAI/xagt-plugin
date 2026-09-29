export interface StrategyRules {
  chain: "solana" | "bsc" | "robinhood";
  launchpads: ("pumpfun" | "meteora" | "bags" | "fourmeme" | "sherwood")[];
  minVolume24hUsd: number;
  minLiquiditySol: number;
  minOlaXbtScore: number;
  maxTokenAgeHours: number;
  tradeAmount: number;
  takeProfitPct: number;
  stopLossPct: number;
  maxSlippagePct: number;
  maxDailyTrades: number;
  mevProtection: boolean;
  honeypotCheck: boolean;
}

export interface ParsedStrategy {
  name: string;
  summary: string;
  targetCategory: "momentum_scalper" | "volatility_hunter" | "alpha_whale_follower" | "custom";
  rules: StrategyRules;
  confidenceScore: number;
  tags: string[];
}

export interface StrategySimulationResult {
  simulatedTrades: number;
  winRatePct: number;
  expectedPnlPct: number;
  estimatedGasTotal: string;
  mevRisk: "LOW" | "MEDIUM" | "HIGH";
  executionEngine: string;
  sampleTokens: {
    symbol: string;
    mint: string;
    launchpad: string;
    entryPrice: number;
    exitPrice: number;
    pnlPct: number;
    reason: string;
  }[];
}

export interface TradingAgent {
  id: string;
  name: string;
  description: string;
  prompt: string;
  mode: "paper" | "live";
  status: "active" | "paused" | "completed" | "failed";
  chain: string;
  launchpads: string[];
  strategyConfig: StrategyRules;
  budgetAllocated: number;
  budgetSpent: number;
  totalPnlPct: number;
  totalTrades: number;
  successfulTrades: number;
  createdAt: string;
  recentLogs?: string[];
}
