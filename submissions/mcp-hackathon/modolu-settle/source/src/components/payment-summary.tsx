import type { PaymentIntentResponse } from "@/lib/public-api";

import { groupAmount } from "./format";

function Figure({ label, amount, emphasis }: { readonly label: string; readonly amount: string; readonly emphasis?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">{label}</dt>
      <dd
        className={`flex flex-wrap items-baseline gap-x-2 font-mono tabular-nums ${emphasis === true ? "text-3xl font-semibold text-ink lg:text-4xl" : "text-2xl text-ink lg:text-3xl"}`}
      >
        <span className="[overflow-wrap:anywhere]">{groupAmount(amount)}</span>
        <span className="text-sm whitespace-nowrap text-ink-muted">USDC</span>
      </dd>
    </div>
  );
}

/** Expected vs received vs remaining — values are the API's, never recomputed here. */
export function PaymentSummary({ intent }: { readonly intent: PaymentIntentResponse }) {
  return (
    <dl className="grid grid-cols-1 gap-6 rounded-md border border-line bg-surface px-5 py-5 sm:grid-cols-3">
      <Figure label="Expected" amount={intent.expectedAmount} />
      <Figure label="Received" amount={intent.receivedAmount} emphasis />
      <Figure label="Remaining" amount={intent.remainingAmount} />
    </dl>
  );
}
