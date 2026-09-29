"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RunReceiptModal } from "@/components/RunReceipt";
import { StatusBadge } from "@/components/StatusBadge";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import type { Payout } from "@/lib/types";
import { formatUsdc, truncateAddress } from "@/lib/utils";
import { apiFetch } from "@/lib/client-api";

/** Every transfer ever attempted, read straight off the Payout ledger. */
export default function ActivityPage() {
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [loading, setLoading] = useState(true);
  // The run whose receipt is open in the modal, if any. Opening it changes no route.
  const [receiptRunId, setReceiptRunId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/payouts");
        const data = await res.json();
        if (!cancelled) setPayouts(data.payouts ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="font-display text-[40px] leading-none tracking-[-0.01em] text-ink">
        Activity
      </h1>
      <p className="mt-3 max-w-xl text-[15px] leading-[1.6] text-ink-soft">
        One row per recipient per run. These rows are never rewritten, so a
        person paid every month appears here every month. Open any row to
        reopen that run&rsquo;s receipt.
      </p>

      <div className="mt-8">
        {loading ? (
          <div className="rounded-card border border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Loading activity…
          </div>
        ) : payouts.length === 0 ? (
          <div className="rounded-card border border-dashed border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            No payouts yet. Confirm a run and it will show up here.
          </div>
        ) : (
          <div className="overflow-hidden rounded-card border border-line bg-card">
            <div className="border-b border-line px-5 py-3">
              <Eyebrow>{payouts.length} payout{payouts.length === 1 ? "" : "s"}</Eyebrow>
            </div>
            <ul>
              {payouts.map((p) => (
                <li
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-4 border-b border-line-soft px-5 py-4 last:border-0"
                >
                  <div className="min-w-0">
                    <Link
                      href={`/dashboard/runs/${p.runId}`}
                      className="font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-emerald"
                    >
                      {p.payeeName}
                    </Link>
                    <div className="text-[13px] text-ink-mute">{p.payeeEmail}</div>
                    <div className="mt-1 font-mono text-[12px] text-ink-mute">
                      {p.transferId ? truncateAddress(p.transferId, 6) : "—"}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    <span className="text-[13px] text-ink-mute">
                      {new Date(p.sentAt ?? p.createdAt).toLocaleString()}
                    </span>
                    <Chip tone={p.claimed ? "emerald" : "amber"}>
                      {p.claimed ? "Claimed" : "Unclaimed"}
                    </Chip>
                    <StatusBadge status={p.status} />
                    <div className="text-right font-medium text-ink">
                      {formatUsdc(p.amountUsdc)} <span className="text-ink-mute">USDC</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setReceiptRunId(p.runId)}
                      className={buttonClasses("secondary", "sm")}
                    >
                      View receipt
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {receiptRunId && (
        <RunReceiptModal runId={receiptRunId} onClose={() => setReceiptRunId(null)} />
      )}
    </div>
  );
}
