"use client";

import { useState } from "react";
import { buttonClasses } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import type { Payee } from "@/lib/types";
import { formatUsdc } from "@/lib/utils";

/**
 * Queues an existing payee for another payment.
 *
 * Shared by the People page and the dashboard's payee table. Defaults the
 * amount to what they were last paid, since paying the same person the same
 * retainer again is the common case; it stays editable for the rest.
 */
export function PayAgain({
  payee,
  onQueued,
}: {
  payee: Payee;
  onQueued?: (payee: Payee) => void;
}) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState(payee.amountUsdc.toFixed(2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const alreadyQueued = payee.status === "pending" || payee.status === "failed";

  async function submit() {
    const amountUsdc = Number(amount);
    if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/api/payees/requeue", {
        method: "POST",
        body: JSON.stringify({ payeeId: payee.id, amountUsdc }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Could not queue that payment.");
      onQueued?.(data.payee);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue that payment.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => {
          setAmount(payee.amountUsdc.toFixed(2));
          setOpen(true);
        }}
        className={buttonClasses("secondary", "sm")}
      >
        {alreadyQueued ? "Change amount" : "Pay again"}
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <input
          type="number"
          min="0"
          step="0.01"
          autoFocus
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
            if (e.key === "Escape") setOpen(false);
          }}
          aria-label={`Amount to pay ${payee.name}`}
          className="w-28 rounded-btn border border-line bg-card px-2.5 py-1.5 text-right text-[13px] text-ink outline-none focus:border-emerald"
        />
        <button onClick={submit} disabled={busy} className={buttonClasses("primary", "sm")}>
          {busy ? "Queuing…" : "Queue"}
        </button>
        <button onClick={() => setOpen(false)} className={buttonClasses("quiet", "sm")}>
          Cancel
        </button>
      </div>
      {error ? (
        <span className="text-[12px] text-amber-text">{error}</span>
      ) : (
        <span className="text-[12px] text-ink-mute">
          Adds {formatUsdc(Number(amount) || 0)} USDC to the next run
        </span>
      )}
    </div>
  );
}
