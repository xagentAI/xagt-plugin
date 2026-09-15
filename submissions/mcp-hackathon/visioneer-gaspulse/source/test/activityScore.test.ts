import { describe, expect, it } from "vitest";
import { computeActivityScore } from "../src/lib/activityScore.js";
import type { EtherscanTx } from "../src/types.js";

const NOW = new Date("2026-09-02T00:00:00.000Z");
const DAY_S = 86_400;

function tx(daysAgo: number): EtherscanTx {
  return {
    hash: `0x${daysAgo}`,
    timeStamp: String(Math.floor(NOW.getTime() / 1000) - daysAgo * DAY_S),
    gas: "21000",
    gasPrice: "10000000000",
    gasUsed: "21000",
    isError: "0",
  };
}

describe("computeActivityScore", () => {
  it("returns all zeros for an address with no in-window activity", () => {
    const result = computeActivityScore([], 30, NOW);
    expect(result).toEqual({ value: 0, recency: 0, frequency: 0, consistency: 0 });
  });

  it("ignores failed transactions", () => {
    const failed = { ...tx(1), isError: "1" };
    const result = computeActivityScore([failed], 30, NOW);
    expect(result.value).toBe(0);
  });

  it("scores a regularly active address highly", () => {
    const transactions = Array.from({ length: 10 }, (_, i) => tx(i * 3));
    const result = computeActivityScore(transactions, 30, NOW);
    expect(result.recency).toBeGreaterThanOrEqual(90);
    expect(result.frequency).toBeGreaterThanOrEqual(90);
    expect(result.consistency).toBeGreaterThanOrEqual(90);
    expect(result.value).toBeGreaterThanOrEqual(90);
  });

  it("scores low recency for an address whose last transaction was long ago in the window", () => {
    const result = computeActivityScore([tx(29)], 30, NOW);
    expect(result.recency).toBeLessThanOrEqual(10);
  });

  it("caps frequency at 100 even with far more than the expected transaction count", () => {
    const transactions = Array.from({ length: 40 }, (_, i) => tx(i));
    const result = computeActivityScore(transactions, 30, NOW);
    expect(result.frequency).toBe(100);
  });

  it("always returns values clamped between 0 and 100", () => {
    const transactions = [tx(0), tx(15), tx(29)];
    const result = computeActivityScore(transactions, 30, NOW);
    for (const value of Object.values(result)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    }
  });
});
