"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { RunReceipt } from "@/components/RunReceipt";
import { buttonClasses } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import type { Payout } from "@/lib/types";

/**
 * A past run's receipt, reachable by URL. The post-run screen keeps its state
 * in memory; this is what survives a refresh, a new tab, or a demo recorded
 * three days later.
 */
export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [payouts, setPayouts] = useState<Payout[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/api/runs/${id}`);
        const data = await res.json();
        if (cancelled) return;
        if (!res.ok) throw new Error(data.error ?? "Could not load that run.");
        setPayouts(data.payouts);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <Link
        href="/dashboard/activity"
        className="text-[13px] text-ink-soft underline underline-offset-2 hover:text-ink"
      >
        ← Back to activity
      </Link>

      <div className="mt-5">
        {loading ? (
          <div className="rounded-card border border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Loading run…
          </div>
        ) : error || !payouts ? (
          <div className="rounded-card border border-amber-100 bg-amber-50 p-6">
            <p className="text-[15px] text-amber-text">{error ?? "Run not found."}</p>
            <Link href="/dashboard/activity" className={buttonClasses("secondary", "md", "mt-4")}>
              Back to activity
            </Link>
          </div>
        ) : (
          <RunReceipt payouts={payouts} />
        )}
      </div>
    </div>
  );
}
