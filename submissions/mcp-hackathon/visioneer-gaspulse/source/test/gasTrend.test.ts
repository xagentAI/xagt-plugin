import { describe, expect, it } from "vitest";
import { computeGasTrend } from "../src/lib/gasTrend.js";
import type { EtherscanTx } from "../src/types.js";

const NOW = new Date("2026-09-02T00:00:00.000Z");
const DAY_S = 86_400;

function tx(daysAgo: number, gasUsed: string, gasPriceGwei: number): EtherscanTx {
  return {
    hash: `0x${daysAgo}`,
    timeStamp: String(Math.floor(NOW.getTime() / 1000) - daysAgo * DAY_S),
    gas: gasUsed,
    gasPrice: String(gasPriceGwei * 1e9),
    gasUsed,
    isError: "0",
  };
}

describe("computeGasTrend", () => {
  it("returns insufficient_data for no transactions", () => {
    const result = computeGasTrend([], 30, NOW);
    expect(result).toEqual({
      totalGasUsed: "0",
      avgGasPriceGwei: 0,
      direction: "insufficient_data",
      buckets: [],
    });
  });

  it("excludes failed transactions and out-of-window transactions", () => {
    const transactions = [
      tx(2, "21000", 10),
      { ...tx(2, "21000", 10), isError: "1" },
      tx(60, "21000", 10),
    ];
    const result = computeGasTrend(transactions, 30, NOW);
    expect(result.totalGasUsed).toBe("21000");
  });

  it("detects an increasing gas price trend", () => {
    const transactions = [tx(27, "21000", 10), tx(1, "21000", 20)];
    const result = computeGasTrend(transactions, 30, NOW);
    expect(result.direction).toBe("increasing");
  });

  it("detects a decreasing gas price trend", () => {
    const transactions = [tx(27, "21000", 20), tx(1, "21000", 10)];
    const result = computeGasTrend(transactions, 30, NOW);
    expect(result.direction).toBe("decreasing");
  });

  it("reports flat when gas price barely changes", () => {
    const transactions = [tx(27, "21000", 10), tx(1, "21000", 10.2)];
    const result = computeGasTrend(transactions, 30, NOW);
    expect(result.direction).toBe("flat");
  });

  it("reports insufficient_data with only one active bucket", () => {
    const transactions = [tx(1, "21000", 10), tx(2, "21000", 12)];
    const result = computeGasTrend(transactions, 30, NOW);
    expect(result.direction).toBe("insufficient_data");
  });
});
