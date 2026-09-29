"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PayeeForm, type PayeeFormValues } from "@/components/PayeeForm";
import { PayAgain } from "@/components/PayAgain";
import { PayeeTable } from "@/components/PayeeTable";
import { RunReceiptModal } from "@/components/RunReceipt";
import { isQueued } from "@/components/StatusBadge";
import { buttonClasses, Eyebrow } from "@/components/ui";
import type { Payee } from "@/lib/types";
import { cn, formatUsdc } from "@/lib/utils";
import { apiFetch } from "@/lib/client-api";

type Filter = "all" | "queued" | "paid";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "queued", label: "Queued" },
  { id: "paid", label: "Paid" },
];

export default function PayoutsPage() {
  const [payees, setPayees] = useState<Payee[]>([]);
  const [treasury, setTreasury] = useState<{ amountUsdc: number; mocked: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [notice, setNotice] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  // The most recent run, for "View last receipt". The ledger is newest-first,
  // so the first row's run is the latest. A read — nothing here writes.
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [receiptRunId, setReceiptRunId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/payouts");
        const data = await res.json();
        if (!cancelled) setLastRunId(data.payouts?.[0]?.runId ?? null);
      } catch {
        // Non-essential: without it the button simply does not appear.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const [payeeRes, treasuryRes] = await Promise.all([
      apiFetch("/api/payees"),
      apiFetch("/api/treasury"),
    ]);
    const payeeData = await payeeRes.json();
    setPayees(payeeData.payees ?? []);
    setTreasury(await treasuryRes.json());
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const queued = useMemo(() => payees.filter((p) => isQueued(p.status)), [payees]);
  const queuedTotal = useMemo(
    () => queued.reduce((sum, p) => sum + p.amountUsdc, 0),
    [queued]
  );

  const visible = useMemo(() => {
    if (filter === "queued") return queued;
    if (filter === "paid") return payees.filter((p) => p.status === "sent");
    return payees;
  }, [filter, payees, queued]);

  async function handleAddPayee(values: PayeeFormValues) {
    setAdding(true);
    setNotice(null);
    try {
      const res = await apiFetch("/api/payees", {
        method: "POST",
        body: JSON.stringify(values),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to add payee.");
      await refresh();
      setNotice({
        kind: "info",
        text: data.requeued
          ? `${values.name} is already on your list — queued another ${formatUsdc(values.amountUsdc)} USDC for them.`
          : `${values.name} added to the next run. A wallet is waiting for them.`,
      });
    } finally {
      setAdding(false);
    }
  }

  /**
   * Minimal CSV import: one `name,email,amount` row per payee, with an
   * optional header line. Each row goes through the same POST /api/payees the
   * form uses, so a wallet is provisioned per payee exactly as it would be
   * when adding them by hand.
   */
  async function handleImport(file: File) {
    setImporting(true);
    setNotice(null);
    try {
      const text = await file.text();
      const rows = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => line.split(",").map((cell) => cell.trim()))
        .filter((cells) => cells.length >= 3 && !/^name$/i.test(cells[0]));

      if (rows.length === 0) {
        throw new Error("No usable rows. Expected: name,email,amount");
      }

      let added = 0;
      const failures: string[] = [];
      for (const [name, email, amount] of rows) {
        const amountUsdc = Number(amount);
        if (!name || !email || !Number.isFinite(amountUsdc) || amountUsdc <= 0) {
          failures.push(email || name || "(blank row)");
          continue;
        }
        const res = await apiFetch("/api/payees", {
          method: "POST",
          body: JSON.stringify({ name, email, amountUsdc }),
        });
        if (res.ok) added += 1;
        else failures.push(email);
      }

      await refresh();
      setNotice({
        kind: failures.length ? "error" : "info",
        text: failures.length
          ? `Imported ${added}. Skipped ${failures.length}: ${failures.join(", ")}`
          : `Imported ${added} payee${added === 1 ? "" : "s"} into the next run.`,
      });
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof Error ? err.message : "Import failed.",
      });
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="font-display text-[40px] leading-none tracking-[-0.01em] text-ink">
          Payouts
        </h1>
        <div className="flex items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleImport(file);
            }}
          />
          {lastRunId && (
            <button
              type="button"
              onClick={() => setReceiptRunId(lastRunId)}
              className={buttonClasses("secondary", "md")}
            >
              View last receipt
            </button>
          )}
          <button
            onClick={() => fileInput.current?.click()}
            disabled={importing}
            className={buttonClasses("secondary", "md")}
          >
            {importing ? "Importing…" : "Import CSV"}
          </button>
          <button
            onClick={() => setShowForm((v) => !v)}
            className={buttonClasses("primary", "md")}
          >
            {showForm ? "Close" : "Add payee"}
          </button>
          {receiptRunId && (
            <RunReceiptModal runId={receiptRunId} onClose={() => setReceiptRunId(null)} />
          )}
        </div>
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-3">
        <StatCard
          label="Treasury balance"
          value={treasury ? `${formatUsdc(treasury.amountUsdc)} USDC` : "—"}
          note={treasury?.mocked ? "Sandbox balance — no Circle credentials set" : undefined}
        />
        <StatCard
          label="Queued this run"
          value={`${formatUsdc(queuedTotal)} USDC`}
          note={`${queued.length} recipient${queued.length === 1 ? "" : "s"}`}
        />
        <ReadyCard count={queued.length} total={queuedTotal} />
      </div>

      {notice && (
        <div
          className={cn(
            "mt-6 rounded-card border px-5 py-4 text-sm",
            notice.kind === "error"
              ? "border-amber-100 bg-amber-50 text-amber-text"
              : "border-emerald-100 bg-emerald-50 text-emerald"
          )}
        >
          {notice.text}
        </div>
      )}

      {showForm && (
        <div className="mt-6">
          <PayeeForm onSubmit={handleAddPayee} submitting={adding} />
        </div>
      )}

      <div className="mt-10 flex items-center gap-2">
        {FILTERS.map((f) => {
          const active = filter === f.id;
          const count =
            f.id === "all"
              ? payees.length
              : f.id === "queued"
                ? queued.length
                : payees.filter((p) => p.status === "sent").length;
          return (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              aria-pressed={active}
              className={cn(
                "rounded-chip border px-3 py-1.5 text-[13px] font-medium transition-colors",
                active
                  ? "border-emerald bg-emerald text-white"
                  : "border-line bg-card text-ink-soft hover:text-ink"
              )}
            >
              {f.label}
              <span className={cn("ml-1.5", active ? "text-emerald-100" : "text-ink-mute")}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-4">
        {loading ? (
          <div className="rounded-card border border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Loading payees…
          </div>
        ) : (
          <PayeeTable
            payees={visible}
            renderAction={(payee) => (
              <PayAgain
                payee={payee}
                onQueued={(updated) =>
                  setPayees((prev) =>
                    prev.map((p) => (p.id === updated.id ? updated : p))
                  )
                }
              />
            )}
            emptyMessage={
              filter === "all"
                ? "No payees yet. Add your first payee to provision them a wallet."
                : `Nothing ${filter} right now.`
            }
          />
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="rounded-card border border-line bg-card p-6">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-3 text-[28px] leading-none font-semibold text-ink">{value}</div>
      {note && <div className="mt-2 text-[13px] text-ink-mute">{note}</div>}
    </div>
  );
}

function ReadyCard({ count, total }: { count: number; total: number }) {
  const ready = count > 0;
  return (
    <div className="flex flex-col rounded-card border border-emerald-100 bg-emerald-50 p-6">
      <Eyebrow className="text-emerald">Ready to send</Eyebrow>
      <div className="mt-3 text-[28px] leading-none font-semibold text-emerald">
        {formatUsdc(total)} USDC
      </div>
      <div className="mt-2 text-[13px] text-emerald">
        {ready
          ? `${count} recipient${count === 1 ? "" : "s"} waiting on this run`
          : "Nothing queued right now"}
      </div>
      <div className="mt-5">
        {ready ? (
          <Link href="/dashboard/review" className={buttonClasses("primary", "md")}>
            Review payout run
          </Link>
        ) : (
          <button disabled className={buttonClasses("primary", "md")}>
            Review payout run
          </button>
        )}
      </div>
    </div>
  );
}
