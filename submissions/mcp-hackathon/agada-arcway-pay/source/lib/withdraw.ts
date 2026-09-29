import { randomBytes } from "node:crypto";
import { isOnChainReadConfigured } from "./balance";

/**
 * Moving a payee's USDC out to an address they chose.
 *
 * LIVE (Phase 3): the transfer is signed by the payee's own Privy embedded
 * wallet in the browser, because only they can authorise it — that is the
 * whole point of the custody model, and a server-side signature would
 * contradict the promise made on /claim. The server records the resulting
 * hash. `isWithdrawalLive` gates that path on the same predicate the balance
 * read uses, so the two can never disagree about whether a chain exists.
 *
 * MOCK: no chain is touched. A hash is generated with an unmistakable
 * `0xmock` prefix so it can never be mistaken for a real transaction, and
 * every surface that shows it says "simulated".
 */
export const isWithdrawalLive = isOnChainReadConfigured;

/** A flat, honest estimate. Real fee quoting arrives with the live path. */
export const NETWORK_FEE_USDC = 0.01;

export function mockTxHash(): string {
  return `0xmock${randomBytes(28).toString("hex")}`;
}

/** Basic EVM address shape check — the only validation we can do off-chain. */
export function isPlausibleAddress(value: string): boolean {
  return /^0x[a-fA-F0-9]{40}$/.test(value.trim());
}
