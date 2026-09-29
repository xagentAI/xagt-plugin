"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PayAgain } from "@/components/PayAgain";
import { ResendNotification } from "@/components/ResendNotification";
import { StatusBadge } from "@/components/StatusBadge";
import { Chip, Eyebrow } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import type { PersonNotification } from "@/lib/types";
import { formatUsdc, truncateAddress } from "@/lib/utils";

/**
 * The payee directory — and the place an employer lands when someone says
 * "I never got the email". Each row carries the last notification time and a
 * resend for that person's most recent payout, so the answer doesn't require
 * finding the run it came from.
 */
export default function PeoplePage() {
  const [people, setPeople] = useState<PersonNotification[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/people");
        const data = await res.json();
        if (!cancelled) setPeople(data.people ?? []);
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
        People
      </h1>
      <p className="mt-3 max-w-xl text-[15px] leading-[1.6] text-ink-soft">
        Everyone you pay. A wallet exists for each of them from the moment they
        were added; &ldquo;Claimed&rdquo; tracks whether they have signed in to
        take control of it. If someone says the email never arrived, resend it
        from here.
      </p>

      <div className="mt-8">
        {loading ? (
          <div className="rounded-card border border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Loading people…
          </div>
        ) : people.length === 0 ? (
          <div className="rounded-card border border-dashed border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Nobody here yet. Add a payee from the Payouts tab.
          </div>
        ) : (
          <div className="overflow-hidden rounded-card border border-line bg-card">
            <div className="border-b border-line px-5 py-3">
              <Eyebrow>
                {people.length} {people.length === 1 ? "person" : "people"}
              </Eyebrow>
            </div>
            <ul>
              {people.map(({ payee, latestPayout }) => (
                <li
                  key={payee.id}
                  className="flex flex-wrap items-center justify-between gap-4 border-b border-line-soft px-5 py-4 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-ink">{payee.name}</div>
                    <div className="text-[13px] text-ink-mute">{payee.email}</div>
                    <div className="mt-1 font-mono text-[12px] text-ink-mute">
                      {truncateAddress(payee.walletAddress)}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-4">
                    <Chip tone={payee.privyUserId ? "emerald" : "amber"}>
                      {payee.privyUserId ? "Claimed" : "Not yet claimed"}
                    </Chip>
                    <StatusBadge status={payee.status} />
                    <div className="text-right font-medium text-ink">
                      {formatUsdc(payee.amountUsdc)}{" "}
                      <span className="text-ink-mute">USDC</span>
                    </div>

                    <PayAgain
                      payee={payee}
                      onQueued={(updated) =>
                        setPeople((prev) =>
                          prev.map((row) =>
                            row.payee.id === updated.id ? { ...row, payee: updated } : row
                          )
                        )
                      }
                    />

                    {latestPayout ? (
                      <div className="flex flex-col items-end gap-1">
                        <ResendNotification
                          payoutId={latestPayout.id}
                          notifyStatus={latestPayout.notifyStatus}
                          notifiedAt={latestPayout.notifiedAt}
                          attempts={latestPayout.notifyAttempts}
                        />
                        <Link
                          href={`/dashboard/runs/${latestPayout.runId}`}
                          className="text-[12px] text-ink-soft underline underline-offset-2 hover:text-ink"
                        >
                          View last run
                        </Link>
                      </div>
                    ) : (
                      <span className="text-[12px] text-ink-mute">Never paid</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
