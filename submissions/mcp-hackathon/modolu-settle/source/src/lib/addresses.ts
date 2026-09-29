/**
 * EVM address validation and normalization via viem (ARCHITECTURE.md §4.4).
 * Storage/equality form is lowercase; checksummed form is produced only at
 * the response boundary. No ENS resolution.
 */
import { getAddress, isAddress } from "viem";

/**
 * Returns the lowercase form of a valid EVM address, or `null`. Mixed-case
 * input must carry a valid EIP-55 checksum; all-lowercase input is accepted.
 */
export function normalizeAddress(input: unknown): string | null {
  if (typeof input !== "string" || !isAddress(input, { strict: true })) {
    return null;
  }
  return input.toLowerCase();
}

/** EIP-55 checksummed presentation of a stored (lowercase) address. */
export function toChecksumAddress(stored: string): string {
  return getAddress(stored);
}
