/**
 * Shared domain types for the payout app.
 *
 * These are the shapes the UI and API routes speak. They map 1:1 onto the
 * Prisma models in prisma/schema.prisma, with two deliberate conversions
 * applied at the store boundary (lib/store.ts): `Decimal` becomes `number`,
 * and `DateTime` becomes an ISO-8601 `string`, so nothing above the store
 * has to know Prisma's runtime types.
 */

export type PayeeStatus = "pending" | "sending" | "sent" | "failed";

export interface Payee {
  /** Internal id (uuid). */
  id: string;
  name: string;
  email: string;
  /** Amount to pay out, denominated in whole USDC (e.g. 250.5 = 250.50 USDC). */
  amountUsdc: number;
  /**
   * The payee's embedded wallet address, provisioned via Privy the moment
   * the payee is added (see lib/privy.ts). In mock mode this is a
   * deterministically-generated fake address so the UI still looks real.
   */
  walletAddress: string;
  /**
   * Set once the payee has signed in and claimed their embedded wallet.
   * Absent means unclaimed — the amber "Not yet" state in the dashboard.
   */
  privyUserId?: string;
  status: PayeeStatus;
  /** Circle transfer id once a payout has been attempted, if any. */
  transferId?: string;
  /** Human-readable failure reason, set only when status === "failed". */
  failureReason?: string;
  createdAt: string;
  updatedAt: string;
}

export interface NewPayeeInput {
  name: string;
  email: string;
  amountUsdc: number;
}

/**
 * Result of a single payout attempt, returned by lib/circle.ts.
 */
export interface TransferResult {
  transferId: string;
  status: "pending" | "complete" | "failed";
  /** The on-chain transaction hash, once the transfer has been mined. */
  txHash?: string;
  errorMessage?: string;
}

/**
 * One recipient's line in one payout run — an immutable ledger row, so a
 * payee paid every month has one `Payout` per month. Written when a run is
 * confirmed, then updated in place only to record its terminal status.
 */
export interface Payout {
  id: string;
  /** The run this payout was part of — the receipt permalink key. */
  runId: string;
  payeeId: string;
  /** Denormalised for display, so a receipt renders without a second query. */
  payeeName: string;
  payeeEmail: string;
  walletAddress: string;
  /** True when the payee had claimed their wallet at the time of the run. */
  claimed: boolean;
  amountUsdc: number;
  status: PayeeStatus;
  transferId?: string;
  failureReason?: string;
  createdAt: string;
  sentAt?: string;
  /** Whether the recipient has been told — independent of whether money moved. */
  notifyStatus: "pending" | "sent" | "failed" | "skipped";
  notifyError?: string;
  /** When delivery last succeeded — quotable to the payee ("sent at 14:32"). */
  notifiedAt?: string;
  /** When a send was last attempted, successful or not. Drives the cooldown. */
  lastNotifyAttemptAt?: string;
  notifyAttempts: number;
}

/**
 * One employer relationship, from the payee's side. A contractor with two
 * clients has two of these — two `Payee` rows under two different companies.
 */
export interface PayeeAccount {
  payeeId: string;
  companyName: string;
  /** Their standing amount with this employer, not a balance. */
  amountUsdc: number;
  walletAddress: string;
  status: PayeeStatus;
}

/** One payment received, from the payee's side. */
export interface ReceivedPayment {
  id: string;
  companyName: string;
  amountUsdc: number;
  status: PayeeStatus;
  transferId?: string;
  createdAt: string;
  sentAt?: string;
}

/**
 * Everything /claim renders. Deliberately aggregated across every company
 * that has ever paid this person — see lib/store.ts for why this is the one
 * place company scoping must NOT apply.
 */
export interface ClaimSummary {
  email: string;
  walletAddress: string | null;
  accounts: PayeeAccount[];
  payments: ReceivedPayment[];
  withdrawals: WithdrawalRecord[];
  /** Payments and withdrawals interleaved, newest first, with running balance. */
  ledger: LedgerEntry[];
  /**
   * Which withdrawal path applies. True = the payee signs a real transfer in
   * their browser and it is broadcast to Arc; false = the simulated mock path
   * reviewers use. Withdrawals work either way — this says which, not whether.
   */
  withdrawalsLive: boolean;
  balance: {
    amountUsdc: number;
    /** True when derived from the ledger rather than read from a chain. */
    simulated: boolean;
    source: string;
  };
}

/** Money the payee moved out of their wallet themselves. */
export interface WithdrawalRecord {
  id: string;
  /** What the payee receives at the destination. */
  amountUsdc: number;
  /** Fee charged at the time — stored, not recomputed, so receipts stay true. */
  feeUsdc: number;
  destinationAddress: string;
  status: PayeeStatus;
  txHash?: string;
  failureReason?: string;
  createdAt: string;
  sentAt?: string;
  /** True when no chain was touched — mock mode. */
  simulated: boolean;
}

/** A payee plus the notification state of their most recent payout. */
export interface PersonNotification {
  payee: Payee;
  latestPayout?: {
    id: string;
    runId: string;
    amountUsdc: number;
    status: PayeeStatus;
    notifyStatus: "pending" | "sent" | "failed" | "skipped";
    notifiedAt?: string;
    lastNotifyAttemptAt?: string;
    notifyAttempts: number;
    notifyError?: string;
  };
}

/**
 * One line in the payee's unified activity list: money in from an employer, or
 * money out to an address they chose. Merged into a single chronological
 * stream so the balance visibly moves — two separate tables made it
 * impossible to see why the number changed.
 */
export type LedgerEntry =
  | {
      kind: "payment";
      id: string;
      at: string;
      /** Signed: positive for money in. */
      amountUsdc: number;
      status: PayeeStatus;
      companyName: string;
      transferId?: string;
      /** Balance after this entry, oldest-to-newest. */
      balanceAfter: number;
    }
  | {
      kind: "withdrawal";
      id: string;
      at: string;
      /** Signed: negative for money out. Excludes the fee. */
      amountUsdc: number;
      feeUsdc: number;
      status: PayeeStatus;
      destinationAddress: string;
      txHash?: string;
      simulated: boolean;
      balanceAfter: number;
    };
