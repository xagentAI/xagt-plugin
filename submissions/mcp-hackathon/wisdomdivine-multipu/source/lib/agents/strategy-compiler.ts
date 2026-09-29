import { ParsedStrategy, StrategyRules } from "./types";

/**
 * Compiles a natural language prompt into structured trading strategy rules.
 * Extracts intent, triggers, risk metrics, targets, and parameters.
 */
export function compilePromptToStrategy(prompt: string): ParsedStrategy {
  const clean = prompt.toLowerCase();

  // 1. Target Chain
  let chain: "solana" | "bsc" | "robinhood" = "solana";
  if (clean.includes("bnb") || clean.includes("bsc") || clean.includes("binance")) {
    chain = "bsc";
  } else if (clean.includes("robinhood") || clean.includes("rh")) {
    chain = "robinhood";
  }

  // 2. Launchpads
  const launchpads: ("pumpfun" | "meteora" | "bags" | "fourmeme" | "sherwood")[] = [];
  if (clean.includes("pump") || clean.includes("pump.fun") || clean.includes("pumpfun")) {
    launchpads.push("pumpfun");
  }
  if (clean.includes("meteora") || clean.includes("dlmm")) {
    launchpads.push("meteora");
  }
  if (clean.includes("bags")) {
    launchpads.push("bags");
  }
  if (clean.includes("four") || clean.includes("four.meme")) {
    launchpads.push("fourmeme");
  }
  if (clean.includes("sherwood") || clean.includes("pons")) {
    launchpads.push("sherwood");
  }

  // Default launchpads if none specified
  if (launchpads.length === 0) {
    if (chain === "bsc") {
      launchpads.push("fourmeme");
    } else if (chain === "robinhood") {
      launchpads.push("sherwood");
    } else {
      launchpads.push("pumpfun", "meteora");
    }
  }

  // 3. Take Profit % extraction
  let takeProfitPct = 35;
  const tpMatch = clean.match(/(?:tp|take\s*profit|profit|gain|target|sell\s*at)\s*(?:of|at|around)?\s*(\+?\d+(?:\.\d+)?)\s*%/i)
    || clean.match(/(\d+(?:\.\d+)?)\s*%\s*(?:tp|take\s*profit|profit|gain)/i);
  if (tpMatch && tpMatch[1]) {
    takeProfitPct = Math.min(Math.max(parseFloat(tpMatch[1]), 5), 500);
  }

  // 4. Stop Loss % extraction
  let stopLossPct = 15;
  const slMatch = clean.match(/(?:sl|stop\s*loss|loss|cut|stop\s*at)\s*(?:of|at|around)?\s*(\-?\d+(?:\.\d+)?)\s*%/i)
    || clean.match(/(\d+(?:\.\d+)?)\s*%\s*(?:sl|stop\s*loss|loss)/i);
  if (slMatch && slMatch[1]) {
    stopLossPct = Math.min(Math.max(Math.abs(parseFloat(slMatch[1])), 2), 80);
  }

  // 5. Trade Amount extraction
  let tradeAmount = chain === "solana" ? 0.2 : chain === "bsc" ? 0.05 : 10;
  const amountMatch = clean.match(/(\d+(?:\.\d+)?)\s*(?:sol|bnb|usdc|usd|per\s*trade)/i)
    || clean.match(/(?:max|budget|spend|size|allocate)\s*(?:of)?\s*(\d+(?:\.\d+)?)/i);
  if (amountMatch && amountMatch[1]) {
    tradeAmount = parseFloat(amountMatch[1]);
  }

  // 6. Volume extraction
  let minVolume24hUsd = 2500;
  const volMatch = clean.match(/(\d+(?:\.\d+)?)\s*(?:k|kilo|thousand)?\s*(?:volume|vol|\$)/i)
    || clean.match(/(?:volume|vol|liquidity)\s*(?:above|>|over|of|at\s*least)?\s*\$?(\d+(?:\.\d+)?)\s*(k)?/i);
  if (volMatch && volMatch[1]) {
    let rawVol = parseFloat(volMatch[1]);
    if (volMatch[2] === "k" || clean.includes("k volume") || clean.includes("k vol") || clean.includes("k $")) {
      rawVol *= 1000;
    }
    if (rawVol > 0) minVolume24hUsd = rawVol;
  }

  // 7. OlaXBT momentum score
  let minOlaXbtScore = 75;
  if (clean.includes("high momentum") || clean.includes("trending") || clean.includes("viral")) {
    minOlaXbtScore = 85;
  } else if (clean.includes("early") || clean.includes("fresh") || clean.includes("newborn")) {
    minOlaXbtScore = 65;
  }

  // 8. Category & Name
  let targetCategory: ParsedStrategy["targetCategory"] = "momentum_scalper";
  let name = "Momentum Scalper Bot";

  if (clean.includes("dlmm") || clean.includes("volatility") || clean.includes("yield")) {
    targetCategory = "volatility_hunter";
    name = "DLMM Volatility Hunter";
  } else if (clean.includes("whale") || clean.includes("alpha") || clean.includes("smart money")) {
    targetCategory = "alpha_whale_follower";
    name = "OlaXBT Alpha Whale Sniper";
  } else if (clean.includes("snipe") || clean.includes("launch")) {
    name = "Launchpad Fast Sniper";
  }

  const rules: StrategyRules = {
    chain,
    launchpads,
    minVolume24hUsd,
    minLiquiditySol: chain === "solana" ? 10 : 2,
    minOlaXbtScore,
    maxTokenAgeHours: clean.includes("new") || clean.includes("fresh") ? 2 : 24,
    tradeAmount,
    takeProfitPct,
    stopLossPct,
    maxSlippagePct: 2.5,
    maxDailyTrades: 10,
    mevProtection: true,
    honeypotCheck: true,
  };

  const summary = `Trades ${chain.toUpperCase()} meme pairs on ${launchpads.join(", ")} with >$${minVolume24hUsd.toLocaleString()} vol & OlaXBT score >${minOlaXbtScore}. Allocates ${tradeAmount} ${chain === "solana" ? "SOL" : "BNB"} / trade. Auto TP at +${takeProfitPct}%, SL at -${stopLossPct}%.`;

  const tags = [
    chain.toUpperCase(),
    ...launchpads.map((l) => l.toUpperCase()),
    `TP +${takeProfitPct}%`,
    `SL -${stopLossPct}%`,
    `MEV Shield`,
  ];

  return {
    name,
    summary,
    targetCategory,
    rules,
    confidenceScore: 0.94,
    tags,
  };
}
