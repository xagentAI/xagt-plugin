import type { EtherscanTx, GasBucket, GasTrend } from "../types.js";

const BUCKET_DAYS = 7;
const DAY_MS = 86_400_000;
// Below this fractional change between the first and last active bucket, the trend reads as flat.
const TREND_THRESHOLD = 0.05;

export function computeGasTrend(transactions: EtherscanTx[], windowDays: number, now: Date): GasTrend {
  const windowStart = now.getTime() - windowDays * DAY_MS;
  const inWindow = transactions.filter(
    (tx) => Number(tx.timeStamp) * 1000 >= windowStart && tx.isError === "0",
  );

  if (inWindow.length === 0) {
    return { totalGasUsed: "0", avgGasPriceGwei: 0, direction: "insufficient_data", buckets: [] };
  }

  const bucketCount = Math.max(1, Math.ceil(windowDays / BUCKET_DAYS));
  const buckets: GasBucket[] = [];
  let totalGasUsed = 0n;
  let totalGasPriceWei = 0n;

  for (let i = bucketCount - 1; i >= 0; i -= 1) {
    const periodEndMs = now.getTime() - i * BUCKET_DAYS * DAY_MS;
    const periodStartMs = periodEndMs - BUCKET_DAYS * DAY_MS;
    const bucketTxs = inWindow.filter((tx) => {
      const ts = Number(tx.timeStamp) * 1000;
      return ts >= periodStartMs && ts < periodEndMs;
    });

    let bucketGasUsed = 0n;
    let bucketGasPriceWei = 0n;
    for (const tx of bucketTxs) {
      bucketGasUsed += BigInt(tx.gasUsed);
      bucketGasPriceWei += BigInt(tx.gasPrice);
    }
    totalGasUsed += bucketGasUsed;
    totalGasPriceWei += bucketGasPriceWei;

    buckets.push({
      periodStart: new Date(periodStartMs).toISOString(),
      periodEnd: new Date(periodEndMs).toISOString(),
      txCount: bucketTxs.length,
      gasUsed: bucketGasUsed.toString(),
      avgGasPriceGwei: bucketTxs.length > 0 ? weiToGwei(bucketGasPriceWei / BigInt(bucketTxs.length)) : 0,
    });
  }

  const avgGasPriceGwei = weiToGwei(totalGasPriceWei / BigInt(inWindow.length));
  const direction = computeDirection(buckets);

  return { totalGasUsed: totalGasUsed.toString(), avgGasPriceGwei, direction, buckets };
}

function computeDirection(buckets: GasBucket[]): GasTrend["direction"] {
  const active = buckets.filter((b) => b.txCount > 0);
  if (active.length < 2) return "insufficient_data";

  const first = active[0].avgGasPriceGwei;
  const last = active[active.length - 1].avgGasPriceGwei;
  if (first === 0) return "insufficient_data";

  const change = (last - first) / first;
  if (change > TREND_THRESHOLD) return "increasing";
  if (change < -TREND_THRESHOLD) return "decreasing";
  return "flat";
}

function weiToGwei(wei: bigint): number {
  return Math.round((Number(wei) / 1e9) * 100) / 100;
}
