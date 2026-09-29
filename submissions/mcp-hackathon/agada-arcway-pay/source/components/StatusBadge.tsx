import { Chip } from "./ui";
import type { PayeeStatus } from "@/lib/types";

/**
 * The employer reads two things off this column: is this person still owed
 * money, or have they been paid. So `pending` and `failed` both present as
 * work outstanding (amber) rather than as separate colours — the failure
 * reason is shown next to the chip, not encoded in it.
 */
const PRESENTATION: Record<PayeeStatus, { label: string; tone: "neutral" | "emerald" | "amber" }> = {
  pending: { label: "Queued", tone: "amber" },
  sending: { label: "Sending…", tone: "neutral" },
  sent: { label: "Paid", tone: "emerald" },
  failed: { label: "Failed", tone: "amber" },
};

export function StatusBadge({ status }: { status: PayeeStatus }) {
  const { label, tone } = PRESENTATION[status];
  return (
    <Chip tone={tone}>
      {status === "sending" && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-chip bg-ink-mute" />
      )}
      {label}
    </Chip>
  );
}

/** Whether a payee still owes a payment — the definition the whole UI shares. */
export function isQueued(status: PayeeStatus): boolean {
  return status === "pending" || status === "failed";
}
