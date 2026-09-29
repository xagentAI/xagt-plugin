/**
 * In-memory fakes for the port interfaces (ARCHITECTURE.md §13 "Required
 * service tests"). Services are tested only through their entry points.
 */
import {
  ASSET,
  CHAIN,
  USDC_TOKEN_ADDRESS,
  type MatchedTransfer,
  type NewPaymentIntent,
  type PaymentIntent,
} from "@/domain/payment-intent";
import { compareTransfers, isInWindow, transferIdentity } from "@/domain/reconciliation";
import { findLastBlockAtOrBefore } from "@/integrations/chain/block-search";
import type { BlockRange, ChainProvider, ChainTransfer, UsdcTransferQuery } from "@/ports/chain-provider";
import type {
  ApplyReconciliationOutcome,
  EvidenceCursor,
  EvidencePage,
  PaymentRepository,
  ReconciliationAttemptRecord,
  ReconciliationObservation,
} from "@/ports/payment-repository";

export interface FakeChainState {
  latestBlock: bigint;
  transfers: ChainTransfer[];
  /** Block number → timestamp; blocks not listed derive a timestamp from their number. */
  timestamps?: Map<bigint, Date>;
  /** Injected failures per operation. */
  failLatestBlock?: Error;
  failTransfers?: Error;
  failTimestamps?: Error;
}

export class FakeChainProvider implements ChainProvider {
  calls = 0;
  readonly transferQueries: UsdcTransferQuery[] = [];
  readonly timestampRequests: bigint[] = [];
  readonly searchRequests: Array<{ at: Date; range: BlockRange }> = [];
  state: FakeChainState;

  constructor(behaviour: { latestBlock: bigint } | { error: Error } | FakeChainState) {
    if ("error" in behaviour) {
      this.state = { latestBlock: 0n, transfers: [], failLatestBlock: behaviour.error };
    } else if ("transfers" in behaviour) {
      this.state = behaviour;
    } else {
      this.state = { latestBlock: behaviour.latestBlock, transfers: [] };
    }
  }

  async getLatestBlock(): Promise<bigint> {
    this.calls += 1;
    if (this.state.failLatestBlock !== undefined) {
      throw this.state.failLatestBlock;
    }
    return this.state.latestBlock;
  }

  async getUsdcTransfers(query: UsdcTransferQuery): Promise<ChainTransfer[]> {
    this.transferQueries.push(query);
    if (this.state.failTransfers !== undefined) {
      throw this.state.failTransfers;
    }
    return this.state.transfers.filter(
      (transfer) =>
        (query.payer === null || transfer.from === query.payer) &&
        transfer.to === query.recipient &&
        transfer.blockNumber >= query.fromBlock &&
        transfer.blockNumber <= query.toBlock,
    );
  }

  async getBlockTimestamp(blockNumber: bigint): Promise<Date> {
    this.timestampRequests.push(blockNumber);
    if (this.state.failTimestamps !== undefined) {
      throw this.state.failTimestamps;
    }
    return this.state.timestamps?.get(blockNumber) ?? new Date(Number(blockNumber) * 2_000);
  }

  async findLastBlockAtOrBefore(at: Date, range: BlockRange): Promise<bigint | null> {
    this.searchRequests.push({ at, range });
    const outcome = await findLastBlockAtOrBefore((blockNumber) => this.getBlockTimestamp(blockNumber), at, range);
    return outcome.blockNumber;
  }
}

export class InMemoryPaymentRepository implements PaymentRepository {
  readonly intents = new Map<string, PaymentIntent>();
  /** intentId → identity → evidence row. */
  readonly evidence = new Map<string, Map<string, MatchedTransfer>>();
  readonly attempts: Array<ReconciliationAttemptRecord & { paymentIntentId: string }> = [];
  readonly now: () => Date;

  constructor(now: () => Date = () => new Date()) {
    this.now = now;
  }

  async createPaymentIntent(intent: NewPaymentIntent): Promise<PaymentIntent> {
    if (this.intents.has(intent.id)) {
      throw new Error(`duplicate payment intent id ${intent.id}`);
    }
    const timestamp = this.now();
    const row: PaymentIntent = {
      id: intent.id,
      externalReference: intent.externalReference,
      chain: CHAIN,
      asset: ASSET,
      tokenAddress: USDC_TOKEN_ADDRESS,
      expectedAmountUnits: intent.expectedAmountUnits,
      recipientAddress: intent.recipientAddress,
      payerAddress: intent.payerAddress,
      startBlock: intent.startBlock,
      expiryBlock: null,
      requiredConfirmations: intent.requiredConfirmations,
      status: "pending",
      receivedAmountUnits: 0n,
      detectedAmountUnits: 0n,
      matchConfidence: "none",
      paidAt: null,
      lastReconciledBlock: null,
      lastReconciledAt: null,
      createdAt: timestamp,
      expiresAt: intent.expiresAt,
      updatedAt: timestamp,
    };
    this.intents.set(row.id, row);
    return row;
  }

  async getPaymentIntentById(id: string): Promise<PaymentIntent | null> {
    return this.intents.get(id) ?? null;
  }

  async applyReconciliation(
    intentId: string,
    observation: ReconciliationObservation,
  ): Promise<ApplyReconciliationOutcome | null> {
    const current = this.intents.get(intentId);
    if (current === undefined) {
      return null;
    }
    const stale = current.lastReconciledBlock !== null && observation.latestBlock < current.lastReconciledBlock;
    const now = this.now();
    let intent = current;

    if (!stale) {
      const rows = this.evidence.get(intentId) ?? new Map<string, MatchedTransfer>();
      const seen = new Set(observation.result.transfers.map(transferIdentity));
      for (const [identity, row] of rows) {
        if (
          !seen.has(identity) &&
          row.association !== "orphaned" &&
          isInWindow(row.blockNumber, observation.window)
        ) {
          rows.set(identity, { ...row, association: "orphaned" });
        }
      }
      for (const transfer of observation.result.transfers) {
        const identity = transferIdentity(transfer);
        const existing = rows.get(identity);
        rows.set(identity, {
          txHash: transfer.txHash,
          logIndex: transfer.logIndex,
          blockNumber: transfer.blockNumber,
          blockHash: transfer.blockHash,
          fromAddress: transfer.from,
          toAddress: transfer.to,
          amountUnits: transfer.amountUnits,
          blockTimestamp: transfer.blockTimestamp,
          association: transfer.association,
          confirmations: Number(transfer.confirmations),
          firstSeenAt: existing?.firstSeenAt ?? now,
          lastSeenAt: now,
        });
      }
      this.evidence.set(intentId, rows);
      intent = {
        ...current,
        status: observation.result.status,
        receivedAmountUnits: observation.result.receivedAmountUnits,
        detectedAmountUnits: observation.result.detectedAmountUnits,
        matchConfidence: observation.result.matchConfidence,
        paidAt: observation.result.paidAt,
        expiryBlock: current.expiryBlock ?? observation.expiryBlock,
        lastReconciledBlock: observation.latestBlock,
        lastReconciledAt: now,
        updatedAt: now,
      };
      this.intents.set(intentId, intent);
    }

    this.attempts.push({
      paymentIntentId: intentId,
      ...observation.attempt,
      latestBlock: observation.latestBlock,
      resultStatus: stale ? null : observation.result.status,
      errorCode: stale ? "STALE_OBSERVATION" : null,
    });
    return { applied: !stale, intent };
  }

  async recordReconciliationAttempt(intentId: string, attempt: ReconciliationAttemptRecord): Promise<void> {
    this.attempts.push({ paymentIntentId: intentId, ...attempt });
  }

  async getEvidencePage(
    intentId: string,
    { limit, cursor }: { limit: number; cursor: EvidenceCursor | null },
  ): Promise<EvidencePage> {
    const all = [...(this.evidence.get(intentId)?.values() ?? [])].sort(compareTransfers);
    const after = cursor === null ? all : all.filter((row) => compareTransfers(row, cursor) > 0);
    const items = after.slice(0, limit);
    const last = items[items.length - 1];
    const nextCursor =
      after.length > limit && last !== undefined
        ? { blockNumber: last.blockNumber, logIndex: last.logIndex, txHash: last.txHash }
        : null;
    return { items, nextCursor };
  }

  evidenceRows(intentId: string): MatchedTransfer[] {
    return [...(this.evidence.get(intentId)?.values() ?? [])].sort(compareTransfers);
  }
}
