import { isCircleConfigured } from "./circle";
import type { ReceivedPayment } from "./types";

/**
 * A payee's spendable USDC balance.
 *
 * Follows the same honest-predicate pattern as lib/circle.ts: if the chain is
 * genuinely configured we read it, and if it isn't we say so rather than
 * dressing a derived number up as a chain read. A payee looking at a balance
 * needs to know whether it reflects real custody.
 *
 * LIVE: an ERC-20 `balanceOf` against the configured RPC, using the USDC
 * contract for the target chain. Plain JSON-RPC over fetch — no extra
 * dependency for one eth_call.
 *
 * MOCK: derived from this app's own ledger — payouts that reached "sent",
 * minus withdrawals that reached "sent". Labelled simulated everywhere it is
 * shown.
 */

/**
 * Reading the chain also requires Circle to be live.
 *
 * The two must agree or the page lies: with Circle in mock mode no payout ever
 * reaches a chain, so a live `balanceOf` would report 0 for a payee whose
 * ledger shows three payments. Deriving from the ledger is the truthful answer
 * in that case, and it is labelled "simulated" precisely so nobody mistakes it
 * for custody.
 */
export const isOnChainReadConfigured = Boolean(
  process.env.USDC_RPC_URL && process.env.USDC_TOKEN_ADDRESS && isCircleConfigured
);

export interface Balance {
  amountUsdc: number;
  simulated: boolean;
  source: string;
}

/** USDC carries 6 decimals on every chain Circle issues it on. */
const USDC_DECIMALS = 6;

/** `balanceOf(address)` — the first 4 bytes of keccak256 of the signature. */
const BALANCE_OF_SELECTOR = "0x70a08231";

function encodeBalanceOf(address: string): string {
  const bare = address.replace(/^0x/, "").toLowerCase();
  return BALANCE_OF_SELECTOR + bare.padStart(64, "0");
}

async function readOnChainBalance(walletAddress: string): Promise<number> {
  const res = await fetch(process.env.USDC_RPC_URL as string, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "eth_call",
      params: [
        {
          to: process.env.USDC_TOKEN_ADDRESS,
          data: encodeBalanceOf(walletAddress),
        },
        "latest",
      ],
    }),
  });

  if (!res.ok) throw new Error(`RPC returned ${res.status}`);

  const body = await res.json();
  if (body.error) throw new Error(body.error.message ?? "RPC error");

  const raw = BigInt(body.result ?? "0x0");
  // Convert from base units without going through float until the very end,
  // so large balances don't lose precision on the way.
  const whole = raw / BigInt(10 ** USDC_DECIMALS);
  const frac = raw % BigInt(10 ** USDC_DECIMALS);
  return Number(whole) + Number(frac) / 10 ** USDC_DECIMALS;
}

export interface DerivedBalanceInput {
  payments: ReceivedPayment[];
  /** Withdrawals that have left the wallet. Empty until Phase 2 Part B. */
  withdrawnUsdc?: number;
}

/**
 * Resolves the balance, preferring a real chain read and falling back to the
 * ledger. A configured-but-failing RPC falls back too rather than showing
 * nothing, but says which it used.
 */
export async function getPayeeBalance(
  walletAddress: string | null,
  derived: DerivedBalanceInput
): Promise<Balance> {
  const received = derived.payments
    .filter((p) => p.status === "sent")
    .reduce((sum, p) => sum + p.amountUsdc, 0);
  const ledgerBalance = Math.max(0, received - (derived.withdrawnUsdc ?? 0));

  if (isOnChainReadConfigured && walletAddress) {
    try {
      return {
        amountUsdc: await readOnChainBalance(walletAddress),
        simulated: false,
        source: "on-chain",
      };
    } catch (err) {
      console.error("On-chain balance read failed, falling back to ledger:", err);
      return {
        amountUsdc: ledgerBalance,
        simulated: true,
        source: "ledger (chain read failed)",
      };
    }
  }

  return { amountUsdc: ledgerBalance, simulated: true, source: "ledger" };
}
