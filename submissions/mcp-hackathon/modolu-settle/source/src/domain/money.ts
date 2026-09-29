/**
 * Exact USDC money helpers. API money is a decimal string ("850.00"); domain
 * money is `bigint` token units (850_000_000n). JavaScript `number` is never
 * used for monetary values (ARCHITECTURE.md §4.4, §12).
 */
import { USDC_DECIMALS } from "./payment-intent";

/**
 * Accepted API amount grammar: an unsigned decimal with no exponent, no sign,
 * no leading zeros (except a lone "0"), and 1–6 fractional digits when a
 * fraction is present. The integer part is capped at 30 digits so that units
 * always fit `numeric(78,0)`.
 */
const USDC_AMOUNT_PATTERN = /^(0|[1-9][0-9]{0,29})(?:\.([0-9]{1,6}))?$/;

export type ParseAmountResult =
  | { readonly ok: true; readonly units: bigint }
  | { readonly ok: false; readonly reason: string };

/** Parses an API decimal string into positive USDC units. Never throws. */
export function parseUsdcAmount(input: unknown): ParseAmountResult {
  if (typeof input !== "string") {
    return { ok: false, reason: "must be a decimal string such as \"850.00\"" };
  }
  const match = USDC_AMOUNT_PATTERN.exec(input);
  if (match === null) {
    return {
      ok: false,
      reason: `must be a positive decimal string with at most ${USDC_DECIMALS} decimal places`,
    };
  }
  const integerPart = match[1] ?? "0";
  const fractionPart = (match[2] ?? "").padEnd(USDC_DECIMALS, "0");
  const units = BigInt(`${integerPart}${fractionPart}`);
  if (units === 0n) {
    return { ok: false, reason: "must be greater than zero" };
  }
  return { ok: true, units };
}

/**
 * Formats USDC units as an API decimal string with at least two fractional
 * digits and no trailing zeros beyond them: 850_000_000n → "850.00",
 * 1n → "0.000001", 1_500_000n → "1.50".
 */
export function formatUsdcAmount(units: bigint): string {
  if (units < 0n) {
    throw new RangeError("USDC amounts are never negative");
  }
  const digits = units.toString().padStart(USDC_DECIMALS + 1, "0");
  const integerPart = digits.slice(0, -USDC_DECIMALS);
  const fraction = digits.slice(-USDC_DECIMALS).replace(/0+$/, "");
  return `${integerPart}.${fraction.length < 2 ? fraction.padEnd(2, "0") : fraction}`;
}
