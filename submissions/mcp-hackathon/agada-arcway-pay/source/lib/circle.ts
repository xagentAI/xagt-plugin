import { randomUUID } from "node:crypto";
import {
  initiateDeveloperControlledWalletsClient,
  type CircleDeveloperControlledWalletsClient,
} from "@circle-fin/developer-controlled-wallets";
import type { TransferResult } from "./types";

/**
 * USDC payout execution via Circle's Developer-Controlled Wallets, on Arc
 * (Circle's L1 for stablecoin finance — https://www.circle.com/arc).
 *
 * This module is the single place that talks to Circle. The official SDK does
 * the entity-secret encryption on every request — that ciphertext is
 * single-use and RSA-encrypted with Circle's rotating public key, so it is
 * emphatically not something to hand-roll.
 *
 * ---------------------------------------------------------------------------
 * LIVE vs MOCK
 * ---------------------------------------------------------------------------
 * Live mode requires all THREE of CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET and
 * CIRCLE_TREASURY_WALLET_ID. Anything less is mock mode, because an API key
 * with no treasury to send from cannot produce a transfer — treating that as
 * "configured" would fail every payout against the real API instead of
 * falling back cleanly.
 *
 * Mock mode is not decoration: X-Agent reviewers call the capability endpoint
 * without credentials, and it must work end to end for them. Mock transfer ids
 * are prefixed `mock_` so they can never be mistaken for a chain hash.
 *
 * ---------------------------------------------------------------------------
 * A NOTE ON USDC ON ARC
 * ---------------------------------------------------------------------------
 * Arc reports USDC twice: as the native gas asset (18 decimals) and as an
 * ERC-20 at 0x3600…0000 (6 decimals). They are two views of ONE balance — a
 * transfer debits both identically — not two pots of money. We use the ERC-20
 * view because 6 decimals matches `Decimal(20, 6)` in the schema and the
 * `balanceOf` read in lib/balance.ts.
 */

export const isCircleConfigured = Boolean(
  process.env.CIRCLE_API_KEY &&
    process.env.CIRCLE_ENTITY_SECRET &&
    process.env.CIRCLE_TREASURY_WALLET_ID
);

let cachedClient: CircleDeveloperControlledWalletsClient | null = null;

function getClient(): CircleDeveloperControlledWalletsClient {
  if (!cachedClient) {
    cachedClient = initiateDeveloperControlledWalletsClient({
      apiKey: process.env.CIRCLE_API_KEY as string,
      entitySecret: process.env.CIRCLE_ENTITY_SECRET as string,
    });
  }
  return cachedClient;
}

function treasuryWalletId(): string {
  return process.env.CIRCLE_TREASURY_WALLET_ID as string;
}

/**
 * Circle transaction states, mapped onto our three-state model.
 * INITIATED/QUEUED/PENDING/SENT all mean "in flight" — real transfers do not
 * settle instantly, so `pending` is a normal outcome, not a problem.
 */
const COMPLETE_STATES = new Set(["COMPLETE", "CONFIRMED"]);
const FAILED_STATES = new Set(["FAILED", "DENIED", "CANCELLED"]);

function mapState(state: string | undefined): TransferResult["status"] {
  if (!state) return "pending";
  if (COMPLETE_STATES.has(state)) return "complete";
  if (FAILED_STATES.has(state)) return "failed";
  return "pending";
}

/**
 * Resolves the USDC token id for the treasury's chain by reading the treasury's
 * own balances. Deliberately not hard-coded: the id differs per environment,
 * and reading it means the code cannot silently send the wrong asset.
 * Cached for the process — it does not change.
 */
let cachedTokenId: string | null = null;

async function usdcTokenId(): Promise<string> {
  if (cachedTokenId) return cachedTokenId;

  const res = await getClient().getWalletTokenBalance({ id: treasuryWalletId() });
  const balances = res.data?.tokenBalances ?? [];

  // Prefer the ERC-20 view (has a contract address) over the native one.
  const erc20 = balances.find(
    (b) => b.token?.symbol === "USDC" && Boolean(b.token?.tokenAddress)
  );
  const any = balances.find((b) => b.token?.symbol === "USDC");
  const token = erc20 ?? any;

  if (!token?.token?.id) {
    throw new Error(
      "No USDC balance on the treasury wallet — cannot resolve the token to send."
    );
  }
  cachedTokenId = token.token.id;
  return cachedTokenId;
}

export interface CreateTransferInput {
  /** Destination USDC wallet address (the payee's Privy embedded wallet). */
  destinationAddress: string;
  /** Amount in whole USDC, e.g. 250.5. */
  amountUsdc: number;
  /** Used as the request's idempotency key so retries are safe. */
  idempotencyKey?: string;
}

/**
 * Starts a USDC transfer from the treasury to a payee.
 *
 * Returns as soon as Circle accepts it. On a real chain settlement is
 * asynchronous, so the caller polls `getTransferStatus()`.
 */
export async function createTransfer(
  input: CreateTransferInput
): Promise<TransferResult> {
  if (!isCircleConfigured) {
    // --- MOCK MODE ---
    await new Promise((resolve) => setTimeout(resolve, 400));
    return { transferId: `mock_${randomUUID()}`, status: "pending" };
  }

  try {
    const tokenId = await usdcTokenId();
    const res = await getClient().createTransaction({
      walletId: treasuryWalletId(),
      tokenId,
      destinationAddress: input.destinationAddress,
      // Circle takes human-readable decimal strings and applies the token's
      // own decimals, so no base-unit conversion here. The SDK spells this
      // `amount` even though the wire field is `amounts`.
      amount: [String(input.amountUsdc)],
      fee: { type: "level", config: { feeLevel: "MEDIUM" } },
      // Retrying with the same key returns the original transaction rather
      // than sending a second one — the difference between a safe retry and
      // paying somebody twice.
      idempotencyKey: input.idempotencyKey ?? randomUUID(),
    });

    const id = res.data?.id;
    if (!id) {
      return {
        transferId: "",
        status: "failed",
        errorMessage: "Circle accepted the request but returned no transaction id.",
      };
    }

    return { transferId: id, status: mapState(res.data?.state) };
  } catch (err) {
    return {
      transferId: "",
      status: "failed",
      errorMessage: describeCircleError(err),
    };
  }
}

/** Checks the current state of a previously-created transfer. */
export async function getTransferStatus(
  transferId: string
): Promise<TransferResult> {
  if (!isCircleConfigured || transferId.startsWith("mock_")) {
    // --- MOCK MODE ---
    // Settles quickly, with an occasional failure so the UI's failure path is
    // exercised rather than theoretical.
    await new Promise((resolve) => setTimeout(resolve, 600));
    const failed = Math.random() < 0.15;
    return failed
      ? {
          transferId,
          status: "failed",
          errorMessage: "Simulated network failure (mock mode).",
        }
      : { transferId, status: "complete" };
  }

  try {
    const res = await getClient().getTransaction({ id: transferId });
    const tx = res.data?.transaction;
    const status = mapState(tx?.state);

    return {
      transferId,
      status,
      txHash: tx?.txHash ?? undefined,
      errorMessage:
        status === "failed"
          ? tx?.errorReason ?? tx?.errorDetails ?? "Transfer failed on chain."
          : undefined,
    };
  } catch (err) {
    return { transferId, status: "pending", errorMessage: describeCircleError(err) };
  }
}

/**
 * The treasury's spendable USDC — read from Circle in live mode, so the
 * dashboard shows what can actually be sent rather than a stored figure.
 */
export interface TreasuryBalance {
  amountUsdc: number;
  mocked: boolean;
}

const MOCK_TREASURY_USDC = 25_000;

export async function getTreasuryBalance(): Promise<TreasuryBalance> {
  if (!isCircleConfigured) {
    return { amountUsdc: MOCK_TREASURY_USDC, mocked: true };
  }

  try {
    const res = await getClient().getWalletTokenBalance({ id: treasuryWalletId() });
    const balances = res.data?.tokenBalances ?? [];
    const usdc =
      balances.find((b) => b.token?.symbol === "USDC" && Boolean(b.token?.tokenAddress)) ??
      balances.find((b) => b.token?.symbol === "USDC");

    return { amountUsdc: Number(usdc?.amount ?? 0), mocked: false };
  } catch (err) {
    console.error("Failed to read treasury balance:", err);
    // Zero, not the mock figure: an unreadable balance must not look like a
    // funded treasury, and the overdraft guard should refuse rather than send.
    return { amountUsdc: 0, mocked: false };
  }
}

/** Circle errors nest their useful detail; surface it rather than "[object Object]". */
function describeCircleError(err: unknown): string {
  const anyErr = err as {
    response?: { data?: { message?: string; code?: number } };
    message?: string;
  };
  const detail = anyErr?.response?.data;
  if (detail?.message) {
    return detail.code ? `Circle ${detail.code}: ${detail.message}` : detail.message;
  }
  return anyErr?.message ?? "Unknown Circle error.";
}
