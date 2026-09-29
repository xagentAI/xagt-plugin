"use client";

import { useState } from "react";
import { buttonClasses } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import { cn } from "@/lib/utils";

/**
 * Resend control, shared by the run receipt and the People page.
 *
 * Offered for EVERY settled payout, not only failed ones: the common
 * complaint is "it says sent but I never got it". A failure is an alarm and
 * reads as one; a successful send gets a quiet secondary action instead.
 *
 * The last-sent time is always shown alongside, because the useful thing an
 * employer can say back is "it went out at 14:32, check your spam folder".
 */
export function ResendNotification({
  payoutId,
  notifyStatus,
  notifiedAt,
  attempts,
  onUpdated,
  compact = false,
}: {
  payoutId: string;
  notifyStatus: "pending" | "sent" | "failed" | "skipped";
  notifiedAt?: string;
  attempts?: number;
  onUpdated?: (payout: unknown) => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [tone, setTone] = useState<"ok" | "warn">("ok");

  const failed = notifyStatus === "failed";
  // Never hidden. "skipped" means a send was attempted while the transfer was
  // still in flight — the payout may well have settled since, in which case the
  // recipient still needs telling. The server refuses with 409 if it genuinely
  // has not settled, so offering the action costs nothing and hiding it strands
  // the row.
  const neverSent = notifyStatus === "skipped" || notifyStatus === "pending";

  async function resend() {
    setBusy(true);
    setMessage(null);
    try {
      const res = await apiFetch("/api/payouts/resend", {
        method: "POST",
        body: JSON.stringify({ payoutId }),
      });
      const data = await res.json();

      if (res.status === 429) {
        setTone("warn");
        setMessage(data.error ?? "Sent a moment ago — try again shortly.");
        return;
      }
      if (!res.ok) {
        setTone("warn");
        setMessage(data.error ?? "Could not resend.");
        return;
      }

      if (data.payout && onUpdated) onUpdated(data.payout);
      setTone(data.delivered ? "ok" : "warn");
      setMessage(data.delivered ? "Sent again just now." : data.error ?? "Send failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-1", compact ? "items-start" : "items-end")}>
      <div className="flex items-center gap-2">
        <LastSent notifyStatus={notifyStatus} notifiedAt={notifiedAt} attempts={attempts} />
        <button
          onClick={resend}
          disabled={busy}
          className={buttonClasses(failed || neverSent ? "secondary" : "quiet", "sm")}
        >
          {busy
            ? "Sending…"
            : failed
              ? "Resend notification"
              : neverSent
                ? "Send notification"
                : "Resend"}
        </button>
      </div>
      {message && (
        <span
          className={cn(
            "text-[12px]",
            tone === "warn" ? "text-amber-text" : "text-emerald"
          )}
        >
          {message}
        </span>
      )}
    </div>
  );
}

/**
 * Exported so the read-only receipt modal can show notification state without
 * the resend control — the modal performs no writes.
 */
export function LastSent({
  notifyStatus,
  notifiedAt,
  attempts,
}: {
  notifyStatus: string;
  notifiedAt?: string;
  attempts?: number;
}) {
  if (notifyStatus === "failed") {
    return <span className="text-[12px] text-amber-text">Not delivered</span>;
  }
  if (notifyStatus === "skipped") {
    return (
      <span className="text-[12px] text-amber-text">
        Not sent — was still in flight
      </span>
    );
  }
  if (notifyStatus === "pending" || !notifiedAt) {
    return <span className="text-[12px] text-ink-mute">Not sent yet</span>;
  }

  const when = new Date(notifiedAt);
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const isToday = when.toDateString() === new Date().toDateString();

  return (
    <span className="text-[12px] text-ink-mute" title={when.toLocaleString()}>
      Sent {isToday ? time : `${when.toLocaleDateString()} ${time}`}
      {typeof attempts === "number" && attempts > 1 && ` · ${attempts} attempts`}
    </span>
  );
}
