import type { Offer } from "./catalogue.js";

/**
 * What one job costs on one offer.
 *
 * Everything here is integer arithmetic in micro-dollars. A price per million
 * tokens, held as micro-dollars, multiplied by a token count and divided by a
 * million, is exact in integers and drifts in floating point, and a price that
 * drifts is a price that can print below what is actually charged.
 */

export type Money = {
  /** Exact cost in micro-dollars, rounded up. */
  microUsd: number;
  /** The same figure as text, never below the exact cost. */
  display: string;
};

const MILLION = 1_000_000n;

/** Cost rounds up. A displayed figure below the real one understates the bill. */
export function costOf(tokens: number, perMillionMicro: number): number {
  if (!Number.isInteger(tokens) || tokens < 0) throw new Error("token count must be a whole number");
  const product = BigInt(tokens) * BigInt(perMillionMicro);
  return Number((product + MILLION - 1n) / MILLION);
}

/** A saving rounds down, for the same reason in the other direction. */
export function savingOf(moreMicro: number, lessMicro: number): number {
  return Math.max(0, moreMicro - lessMicro);
}

/**
 * Micro-dollars as text. The decimals widen until the printed figure reads
 * back as the same number, so nothing is silently rounded away; past six
 * decimals it rounds up rather than down.
 */
export function usd(microUsd: number): string {
  const dollars = microUsd / 1_000_000;
  for (let places = 2; places <= 6; places += 1) {
    const shown = dollars.toFixed(places);
    if (Number(shown) === dollars) return `$${shown}`;
  }
  // Unreachable: micro-dollars are integers, so six decimals always read back
  // exactly. It throws rather than rounding, because a safety net that has
  // never caught anything is a place for a wrong number to hide.
  throw new Error(`micro-dollar amount ${microUsd} did not round-trip at six decimals`);
}

export function money(microUsd: number): Money {
  return { microUsd, display: usd(microUsd) };
}

export type JobCost = {
  input: Money;
  output: Money;
  total: Money;
};

export function priceJob(offer: Offer, inputTokens: number, outputTokens: number): JobCost {
  const input = costOf(inputTokens, offer.inputPerMillionMicro);
  const output = costOf(outputTokens, offer.outputPerMillionMicro);
  return {
    input: money(input),
    output: money(output),
    // Each side is rounded up on its own and then added, so the total is never
    // below the sum of what the two sides would be charged separately.
    total: money(input + output),
  };
}
