import { STATUS_COPY, type PaymentStatus } from "@/lib/public-api";

const STATUS_CLASS: Readonly<Record<PaymentStatus, string>> = {
  pending: "text-status-pending border-status-pending/40 bg-status-pending/5",
  detected: "text-status-detected border-status-detected/40 bg-status-detected/5",
  partial: "text-status-partial border-status-partial/40 bg-status-partial/5",
  paid: "text-status-paid border-status-paid/40 bg-status-paid/5",
  overpaid: "text-status-overpaid border-status-overpaid/40 bg-status-overpaid/5",
  expired: "text-status-expired border-status-expired/40 bg-status-expired/5",
  ambiguous: "text-status-ambiguous border-status-ambiguous/40 bg-status-ambiguous/5",
};

/** Compact status pill: glyph + label, colour is reinforcement only. */
export function StatusBadge({ status }: { readonly status: PaymentStatus }) {
  const copy = STATUS_COPY[status];
  return (
    <span
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-[0.08em] uppercase ${STATUS_CLASS[status]}`}
    >
      <span aria-hidden="true">{copy.glyph}</span>
      {copy.label}
    </span>
  );
}

/** The inspector's headline: large status word plus its one-line meaning. */
export function PaymentStatusHero({ status, reconciling }: { readonly status: PaymentStatus; readonly reconciling: boolean }) {
  const copy = STATUS_COPY[status];
  return (
    <div data-status={status} className={`rounded-md border px-5 py-4 ${STATUS_CLASS[status]}`}>
      <p className="text-xs font-medium tracking-[0.18em] uppercase opacity-80">Payment status</p>
      <p className="mt-1 flex items-center gap-3 text-3xl font-semibold tracking-tight sm:text-4xl">
        <span aria-hidden="true">{copy.glyph}</span>
        <span className="uppercase">{copy.label}</span>
      </p>
      <p className="mt-2 text-sm text-ink">{copy.explanation}</p>
      <p role="status" aria-live="polite" className="mt-1 min-h-4 text-xs text-ink-muted">
        {reconciling ? "Reconciling against Base…" : ""}
      </p>
    </div>
  );
}
