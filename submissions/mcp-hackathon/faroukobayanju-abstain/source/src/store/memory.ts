/**
 * In-process store. Used by tests and by `NEXUS_MODE=replay` runs, so a
 * reviewer can reproduce every receipt with no Redis and no API key.
 *
 * `onBeforeWrite` is a test seam: it lets a test suspend a writer between the
 * head read and the commit, forcing the exact interleave that forks a naive
 * chain. Without a way to force that schedule, "no fork under concurrency" is
 * an untestable claim.
 */
import type { Receipt } from '../receipt/schema.js';
import type { Head, ReceiptStore } from './types.js';

export class MemoryStore implements ReceiptStore {
  private records: Receipt[] = [];
  private currentHead: Head | null = null;
  private readonly rateWindows = new Map<string, { startedAt: number; count: number }>();

  constructor(private readonly onBeforeWrite?: () => Promise<void>) {}

  async head(): Promise<Head | null> {
    return this.currentHead;
  }

  async compareAndAppend(expected: Head | null, receipt: Receipt): Promise<boolean> {
    if (this.onBeforeWrite) await this.onBeforeWrite();

    // The compare and the write are adjacent with no await between them, so
    // they are atomic under Node's single-threaded event loop.
    if (!headsEqual(this.currentHead, expected)) return false;
    this.records.push(receipt);
    this.currentHead = { seq: receipt.seq, hash: receipt.hash };
    return true;
  }

  async get(seq: number): Promise<Receipt | null> {
    return this.records.find((r) => r.seq === seq) ?? null;
  }

  async all(): Promise<Receipt[]> {
    return [...this.records].sort((a, b) => a.seq - b.seq);
  }

  async allowWrite(scope: string, limit: number, windowMs: number): Promise<boolean> {
    const now = Date.now();
    const current = this.rateWindows.get(scope);
    if (!current || now - current.startedAt >= windowMs) {
      this.rateWindows.set(scope, { startedAt: now, count: 1 });
      return true;
    }
    current.count++;
    return current.count <= limit;
  }
}

export function headsEqual(a: Head | null, b: Head | null): boolean {
  if (a === null || b === null) return a === b;
  return a.seq === b.seq && a.hash === b.hash;
}
