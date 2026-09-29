/**
 * Use case: caller-triggered reconciliation of one intent (ARCHITECTURE.md §8.2).
 *
 *   load intent
 *   → latestBlock = ChainProvider.getLatestBlock()
 *   → window end = latest, or the resolved expiry block once `expiresAt` has passed
 *   → ChainProvider.getUsdcTransfers(recipient, payer when declared, window)
 *   → defensively verify every transfer against the intent and the window
 *   → one timestamp lookup per distinct block
 *   → pure domain reconciliation (association, depth, status precedence)
 *   → repository applies the canonical observation atomically
 *
 * Provider calls happen outside any database transaction. A provider failure
 * is recorded as a failed attempt (when the database allows) and re-thrown as
 * the upstream error; it never touches intent state or evidence, so a failed
 * scan can never orphan anything.
 */
import "server-only";

import type { PaymentIntent } from "@/domain/payment-intent";
import { reconcile, type BlockWindow, type ObservedTransfer } from "@/domain/reconciliation";
import { AppError, isAppError } from "@/lib/errors";
import type { ChainProvider, ChainTransfer } from "@/ports/chain-provider";
import type { PaymentRepository } from "@/ports/payment-repository";

export interface ReconcilePaymentIntentDeps {
  readonly chainProvider: ChainProvider;
  readonly paymentRepository: PaymentRepository;
  readonly requestId: string;
  /** Clock seam for tests; defaults to the system clock. */
  readonly now?: () => Date;
}

export interface ReconcileOutcome {
  readonly intent: PaymentIntent;
  /** `false` when a newer observation had already been applied and this one was only recorded. */
  readonly applied: boolean;
  readonly latestBlock: bigint;
  readonly candidateCount: number;
}

interface ResolvedWindow {
  readonly window: BlockWindow;
  /** `true` when `window.toBlock` is the expiry boundary and the obligation's time has run out. */
  readonly expiryPassed: boolean;
  /** Expiry block newly resolved by this observation, to be persisted once. */
  readonly resolvedExpiryBlock: bigint | null;
}

/**
 * Determines how far this observation may look (ARCHITECTURE.md §7.1).
 * Before `expiresAt` the window runs to the latest block. After it, the
 * boundary is the greatest block with `timestamp <= expiresAt`, searched once
 * and then persisted. If the latest block itself is not later than
 * `expiresAt` the chain has not reached the boundary yet, so nothing is
 * persisted and the window still runs to the latest block.
 */
async function resolveWindow(intent: PaymentIntent, latestBlock: bigint, now: Date, chain: ChainProvider): Promise<ResolvedWindow> {
  const fromBlock = intent.startBlock;

  if (intent.expiryBlock !== null) {
    const toBlock = intent.expiryBlock < latestBlock ? intent.expiryBlock : latestBlock;
    return { window: { fromBlock, toBlock }, expiryPassed: intent.expiryBlock <= latestBlock, resolvedExpiryBlock: null };
  }
  if (now.getTime() <= intent.expiresAt.getTime() || fromBlock > latestBlock) {
    return { window: { fromBlock, toBlock: latestBlock }, expiryPassed: false, resolvedExpiryBlock: null };
  }

  const boundary = await chain.findLastBlockAtOrBefore(intent.expiresAt, { fromBlock, toBlock: latestBlock });
  if (boundary === latestBlock) {
    return { window: { fromBlock, toBlock: latestBlock }, expiryPassed: false, resolvedExpiryBlock: null };
  }
  // `null` means the first eligible block already post-dates expiry: an empty window.
  const expiryBlock = boundary ?? fromBlock - 1n;
  return { window: { fromBlock, toBlock: expiryBlock }, expiryPassed: true, resolvedExpiryBlock: expiryBlock };
}

function assertTransferBelongs(transfer: ChainTransfer, intent: PaymentIntent, window: BlockWindow): void {
  const outsideFilter =
    transfer.to !== intent.recipientAddress || (intent.payerAddress !== null && transfer.from !== intent.payerAddress);
  const outsideWindow = transfer.blockNumber < window.fromBlock || transfer.blockNumber > window.toBlock;
  if (outsideFilter || outsideWindow) {
    throw new AppError("UPSTREAM_INVALID_RESPONSE", "Blockchain provider returned a transfer outside the query filter", {
      context: { txHash: transfer.txHash, logIndex: transfer.logIndex, outsideFilter, outsideWindow },
    });
  }
}

export async function reconcilePaymentIntent(
  id: string,
  deps: ReconcilePaymentIntentDeps,
): Promise<ReconcileOutcome> {
  const now = deps.now ?? (() => new Date());
  const intent = await deps.paymentRepository.getPaymentIntentById(id);
  if (intent === null) {
    throw new AppError("INTENT_NOT_FOUND", "Payment intent not found");
  }

  const startedAt = now();
  const attemptBase = { requestId: deps.requestId, provider: "alchemy" as const, fromBlock: intent.startBlock, startedAt };
  let latestBlock: bigint | null = null;
  let toBlock: bigint | null = null;

  try {
    latestBlock = await deps.chainProvider.getLatestBlock();
    const { window, expiryPassed, resolvedExpiryBlock } = await resolveWindow(intent, latestBlock, startedAt, deps.chainProvider);
    toBlock = window.toBlock;

    const transfers: ChainTransfer[] =
      window.fromBlock > window.toBlock
        ? []
        : await deps.chainProvider.getUsdcTransfers({
            fromBlock: window.fromBlock,
            toBlock: window.toBlock,
            recipient: intent.recipientAddress,
            payer: intent.payerAddress,
          });
    for (const transfer of transfers) {
      assertTransferBelongs(transfer, intent, window);
    }

    // Timestamps: one lookup per distinct block, however many transfers share it.
    const blockNumbers = [...new Set(transfers.map((transfer) => transfer.blockNumber))];
    const timestamps = new Map<bigint, Date>(
      await Promise.all(
        blockNumbers.map(async (blockNumber) => [blockNumber, await deps.chainProvider.getBlockTimestamp(blockNumber)] as const),
      ),
    );
    const observed: ObservedTransfer[] = transfers.map((transfer) => {
      const blockTimestamp = timestamps.get(transfer.blockNumber);
      if (blockTimestamp === undefined) {
        throw new Error(`missing timestamp for block ${transfer.blockNumber}`);
      }
      return { ...transfer, blockTimestamp };
    });

    const result = reconcile({
      expectedAmountUnits: intent.expectedAmountUnits,
      requiredConfirmations: intent.requiredConfirmations,
      latestBlock,
      payer: intent.payerAddress,
      window,
      expiryPassed,
      transfers: observed,
    });

    const outcome = await deps.paymentRepository.applyReconciliation(intent.id, {
      latestBlock,
      window,
      expiryBlock: resolvedExpiryBlock,
      result,
      attempt: { ...attemptBase, toBlock: window.toBlock, candidateCount: transfers.length, completedAt: now() },
    });
    if (outcome === null) {
      throw new AppError("INTENT_NOT_FOUND", "Payment intent not found");
    }
    return { intent: outcome.intent, applied: outcome.applied, latestBlock, candidateCount: transfers.length };
  } catch (error) {
    if (isAppError(error) && error.code.startsWith("UPSTREAM_")) {
      // Best effort: the failed attempt is operational history only. If the database is
      // also unavailable the original provider error still propagates unchanged.
      await deps.paymentRepository
        .recordReconciliationAttempt(intent.id, {
          ...attemptBase,
          toBlock: toBlock ?? latestBlock ?? intent.startBlock,
          latestBlock,
          candidateCount: 0,
          resultStatus: null,
          errorCode: error.code,
          completedAt: now(),
        })
        .catch(() => undefined);
    }
    throw error;
  }
}
