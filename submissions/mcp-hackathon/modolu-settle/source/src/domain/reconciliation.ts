/**
 * Pure reconciliation engine (ARCHITECTURE.md §7). Given one complete
 * observation of the chain for an intent's window — the latest block, the
 * window boundaries, whether the expiry boundary has passed, and every
 * canonical native USDC transfer to the recipient inside the window — it
 * associates evidence, computes amounts and confirmation depth, and resolves
 * the final v1 status with the architecture's explicit precedence:
 *
 *   ambiguous > overpaid > paid > partial > detected > expired > pending
 *
 * Association (§7.3): with a declared payer every transfer is `matched`
 * (`exact_payer`). Without one, transfers are grouped by sender: exactly one
 * sender group is `matched` (`single_sender`); two or more make the intent
 * `ambiguous` and every transfer stays a `candidate` that counts toward
 * nothing. No scoring, heuristics or amount matching.
 *
 * Pure TypeScript: no framework, database, RPC or environment imports.
 */
import type { MatchConfidence, PaymentStatus, TransferAssociation } from "./payment-intent";

/** One canonical USDC transfer as seen on chain, before confirmation depth is known. */
export interface ObservedTransfer {
  readonly txHash: string;
  readonly logIndex: number;
  readonly blockNumber: bigint;
  readonly blockHash: string;
  readonly from: string;
  readonly to: string;
  readonly amountUnits: bigint;
  readonly blockTimestamp: Date;
}

/** An observed transfer annotated with its depth at the observation's latest block. */
export interface ReconciledTransfer extends ObservedTransfer {
  /** `latestBlock - blockNumber + 1`; exact, never a JavaScript number. */
  readonly confirmations: bigint;
  readonly confirmed: boolean;
  readonly association: Extract<TransferAssociation, "matched" | "candidate">;
}

export interface BlockWindow {
  /** Inclusive; `toBlock < fromBlock` is an empty window. */
  readonly fromBlock: bigint;
  readonly toBlock: bigint;
}

export interface ReconciliationInput {
  readonly expectedAmountUnits: bigint;
  readonly requiredConfirmations: number;
  readonly latestBlock: bigint;
  /** Declared payer (lowercase) or `null` for sender-group association. */
  readonly payer: string | null;
  /** Blocks the observation covers; transfers outside it are ignored defensively. */
  readonly window: BlockWindow;
  /** `true` once `window.toBlock` is the resolved expiry boundary and the obligation's time has run out. */
  readonly expiryPassed: boolean;
  readonly transfers: readonly ObservedTransfer[];
}

export interface ReconciliationResult {
  readonly status: PaymentStatus;
  /** Sum of `matched` transfers regardless of confirmation depth. */
  readonly detectedAmountUnits: bigint;
  /** Sum of `matched` transfers with `confirmations >= requiredConfirmations`. */
  readonly receivedAmountUnits: bigint;
  readonly matchConfidence: MatchConfidence;
  /** Block timestamp of the transfer that first brought the confirmed total to the expected amount. */
  readonly paidAt: Date | null;
  /** Deduplicated in-window evidence ordered by `(blockNumber, logIndex, txHash)`, with depth and association. */
  readonly transfers: readonly ReconciledTransfer[];
}

/**
 * Base block confirmation depth: a transfer mined in the latest block has
 * exactly one confirmation. A transfer above the latest block (inconsistent
 * evidence) has zero and can never count as confirmed.
 */
export function confirmationDepth(blockNumber: bigint, latestBlock: bigint): bigint {
  return blockNumber <= latestBlock ? latestBlock - blockNumber + 1n : 0n;
}

/** Canonical evidence order (ARCHITECTURE.md §9): block, then log index, then tx hash. */
export function compareTransfers(
  a: Pick<ObservedTransfer, "blockNumber" | "logIndex" | "txHash">,
  b: Pick<ObservedTransfer, "blockNumber" | "logIndex" | "txHash">,
): number {
  if (a.blockNumber !== b.blockNumber) {
    return a.blockNumber < b.blockNumber ? -1 : 1;
  }
  if (a.logIndex !== b.logIndex) {
    return a.logIndex - b.logIndex;
  }
  return a.txHash < b.txHash ? -1 : a.txHash > b.txHash ? 1 : 0;
}

/** Transfer identity used by the double-counting guard: `(txHash, logIndex)`. */
export function transferIdentity(transfer: Pick<ObservedTransfer, "txHash" | "logIndex">): string {
  return `${transfer.txHash}:${transfer.logIndex}`;
}

export function isInWindow(blockNumber: bigint, window: BlockWindow): boolean {
  return blockNumber >= window.fromBlock && blockNumber <= window.toBlock;
}

/** The facts the status decision is made from; every predicate below reads only these. */
export interface StatusFacts {
  readonly expectedAmountUnits: bigint;
  readonly detectedAmountUnits: bigint;
  readonly receivedAmountUnits: bigint;
  readonly ambiguous: boolean;
  readonly expiryPassed: boolean;
}

/**
 * The obligation can no longer be met: its time has run out, the confirmed
 * total is short, and even every not-yet-confirmed in-window transfer would
 * leave it short (§7.4 rule 6). Under-confirmed pre-expiry evidence that could
 * still satisfy it keeps the intent `partial`/`detected` instead.
 */
function conclusivelyExpired(facts: StatusFacts): boolean {
  return (
    facts.expiryPassed &&
    facts.receivedAmountUnits < facts.expectedAmountUnits &&
    facts.detectedAmountUnits < facts.expectedAmountUnits
  );
}

/** ARCHITECTURE.md §7.4 status precedence, evaluated strictly in this order. */
export const STATUS_PRECEDENCE: readonly PaymentStatus[] = [
  "ambiguous",
  "overpaid",
  "paid",
  "partial",
  "detected",
  "expired",
  "pending",
];

const STATUS_PREDICATES: Readonly<Record<PaymentStatus, (facts: StatusFacts) => boolean>> = {
  ambiguous: (facts) => facts.ambiguous,
  overpaid: (facts) => facts.receivedAmountUnits > facts.expectedAmountUnits,
  paid: (facts) => facts.receivedAmountUnits === facts.expectedAmountUnits,
  partial: (facts) =>
    facts.receivedAmountUnits > 0n &&
    facts.receivedAmountUnits < facts.expectedAmountUnits &&
    !conclusivelyExpired(facts),
  detected: (facts) => facts.receivedAmountUnits === 0n && facts.detectedAmountUnits > 0n && !conclusivelyExpired(facts),
  expired: (facts) => conclusivelyExpired(facts),
  pending: () => true,
};

export function resolveStatus(facts: StatusFacts): PaymentStatus {
  for (const status of STATUS_PRECEDENCE) {
    if (STATUS_PREDICATES[status](facts)) {
      return status;
    }
  }
  return "pending";
}

export function reconcile(input: ReconciliationInput): ReconciliationResult {
  const required = BigInt(input.requiredConfirmations);
  const payer = input.payer === null ? null : input.payer.toLowerCase();

  // Each (txHash, logIndex) identity counts exactly once, and only inside the window.
  const unique = new Map<string, ObservedTransfer>();
  for (const transfer of input.transfers) {
    const identity = transferIdentity(transfer);
    if (!unique.has(identity) && isInWindow(transfer.blockNumber, input.window)) {
      unique.set(identity, transfer);
    }
  }
  const observed = [...unique.values()].sort(compareTransfers);

  // Association (§7.3).
  let association: ReconciledTransfer["association"] = "matched";
  let matchConfidence: MatchConfidence = "none";
  if (observed.length > 0) {
    if (payer !== null) {
      matchConfidence = "exact_payer";
    } else {
      const senders = new Set(observed.map((transfer) => transfer.from.toLowerCase()));
      if (senders.size === 1) {
        matchConfidence = "single_sender";
      } else {
        matchConfidence = "ambiguous";
        association = "candidate";
      }
    }
  }

  const transfers: ReconciledTransfer[] = observed.map((transfer) => {
    const confirmations = confirmationDepth(transfer.blockNumber, input.latestBlock);
    return {
      ...transfer,
      from: transfer.from.toLowerCase(),
      to: transfer.to.toLowerCase(),
      confirmations,
      confirmed: confirmations >= required,
      association,
    };
  });

  // Totals and paidAt from `matched` evidence only, in canonical order.
  let detectedAmountUnits = 0n;
  let receivedAmountUnits = 0n;
  let paidAt: Date | null = null;
  for (const transfer of transfers) {
    if (transfer.association !== "matched") {
      continue;
    }
    detectedAmountUnits += transfer.amountUnits;
    if (transfer.confirmed) {
      receivedAmountUnits += transfer.amountUnits;
      if (paidAt === null && receivedAmountUnits >= input.expectedAmountUnits) {
        paidAt = transfer.blockTimestamp;
      }
    }
  }

  const status = resolveStatus({
    expectedAmountUnits: input.expectedAmountUnits,
    detectedAmountUnits,
    receivedAmountUnits,
    ambiguous: matchConfidence === "ambiguous",
    expiryPassed: input.expiryPassed,
  });

  return {
    status,
    detectedAmountUnits,
    receivedAmountUnits,
    matchConfidence,
    paidAt: status === "paid" || status === "overpaid" ? paidAt : null,
    transfers,
  };
}
