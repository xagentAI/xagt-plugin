"use client";

import { usePrivy } from "@privy-io/react-auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { Wordmark } from "@/components/Brand";
import { WithdrawalReceipt } from "@/components/WithdrawalReceipt";
import { buttonClasses } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import type { WithdrawalRecord } from "@/lib/types";
import { isPrivyClientConfigured } from "../../../providers";

/** A past withdrawal's receipt, reachable by URL. */
export default function WithdrawalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  if (!isPrivyClientConfigured) return <Shell><p className="text-ink-mute">Sign-in isn&rsquo;t configured.</p></Shell>;
  return <Inner id={id} />;
}

function Inner({ id }: { id: string }) {
  const { ready, authenticated } = usePrivy();
  const router = useRouter();
  const [withdrawal, setWithdrawal] = useState<WithdrawalRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (ready && !authenticated) router.replace("/");
  }, [ready, authenticated, router]);

  useEffect(() => {
    if (!ready || !authenticated) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/api/claim/withdrawals/${id}`);
        const data = await res.json();
        if (cancelled) return;
        if (!res.ok) throw new Error(data.error ?? "Could not load that receipt.");
        setWithdrawal(data.withdrawal);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, id]);

  if (!ready || !authenticated || loading) {
    return <Shell><p className="py-16 text-center text-[15px] text-ink-mute">Loading…</p></Shell>;
  }

  if (error || !withdrawal) {
    return (
      <Shell>
        <div className="rounded-card border border-amber-100 bg-amber-50 p-6">
          <p className="text-[15px] text-amber-text">{error ?? "Receipt not found."}</p>
          <Link href="/claim" className={buttonClasses("secondary", "md", "mt-4")}>
            Back to your money
          </Link>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <WithdrawalReceipt withdrawal={withdrawal} showPermalink={false} />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-card">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-ink">
            <Wordmark />
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">{children}</main>
    </div>
  );
}
