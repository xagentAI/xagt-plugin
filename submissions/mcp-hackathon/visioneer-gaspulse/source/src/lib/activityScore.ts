import type { ActivityScore, EtherscanTx } from "../types.js";

const DAY_MS = 86_400_000;
// One transaction every 3 days over the window earns full frequency credit.
const EXPECTED_TX_INTERVAL_DAYS = 3;

/**
 * Pure activity/liveliness signal — recency, frequency, and consistency of on-chain
 * transactions. This is deliberately NOT a risk, fraud, or compliance score: it says nothing
 * about an address's trustworthiness, only how recently and regularly it has transacted.
 */
export function computeActivityScore(transactions: EtherscanTx[], windowDays: number, now: Date): ActivityScore {
  const windowStart = now.getTime() - windowDays * DAY_MS;
  const inWindowMs = transactions
    .filter((tx) => Number(tx.timeStamp) * 1000 >= windowStart && tx.isError === "0")
    .map((tx) => Number(tx.timeStamp) * 1000)
    .sort((a, b) => a - b);

  if (inWindowMs.length === 0) {
    return { value: 0, recency: 0, frequency: 0, consistency: 0 };
  }

  const lastTxMs = inWindowMs[inWindowMs.length - 1];
  const daysSinceLastTx = (now.getTime() - lastTxMs) / DAY_MS;
  const recency = clamp(100 * (1 - daysSinceLastTx / windowDays), 0, 100);

  const expectedTxCount = windowDays / EXPECTED_TX_INTERVAL_DAYS;
  const frequency = clamp((100 * inWindowMs.length) / expectedTxCount, 0, 100);

  const consistency = computeConsistency(inWindowMs);

  const value = Math.round(0.4 * recency + 0.4 * frequency + 0.2 * consistency);

  return {
    value: clamp(value, 0, 100),
    recency: Math.round(recency),
    frequency: Math.round(frequency),
    consistency: Math.round(consistency),
  };
}

function computeConsistency(sortedTimestampsMs: number[]): number {
  if (sortedTimestampsMs.length < 3) return 0;

  const gapsDays: number[] = [];
  for (let i = 1; i < sortedTimestampsMs.length; i += 1) {
    gapsDays.push((sortedTimestampsMs[i] - sortedTimestampsMs[i - 1]) / DAY_MS);
  }

  const mean = gapsDays.reduce((sum, g) => sum + g, 0) / gapsDays.length;
  if (mean === 0) return 100;

  const variance = gapsDays.reduce((sum, g) => sum + (g - mean) ** 2, 0) / gapsDays.length;
  const coefficientOfVariation = Math.sqrt(variance) / mean;

  return clamp(100 * (1 - Math.min(1, coefficientOfVariation)), 0, 100);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
