import { CreateIntentForm } from "@/components/create-intent-form";

// Rendered per request so the nonce-based Content Security Policy applies (see src/proxy.ts).
export const dynamic = "force-dynamic";

const FLOW = [
  { step: "Declare", detail: "An agent creates an expected USDC payment: amount, recipient, optional payer, expiry." },
  { step: "Pay", detail: "The payer sends native USDC on Base, entirely outside Settle." },
  { step: "Reconcile", detail: "Settle reads canonical Transfer logs and confirmation depth on request." },
  { step: "Verify", detail: "A deterministic status and transaction evidence drive the agent's next step." },
] as const;

export default function HomePage() {
  return (
    <div className="flex flex-col gap-12">
      <section className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-12">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">Settle · read-only reconciliation</p>
          <h1 className="text-4xl font-semibold tracking-tight text-ink sm:text-5xl">Payment truth for autonomous agents.</h1>
          <p className="max-w-xl text-lg text-ink-muted">
            Create an expected USDC payment. Settle verifies what actually arrived on Base and answers with a status an agent can act on:
            pending, detected, partial, paid, overpaid, expired or ambiguous.
          </p>
        </div>
        <ol className="grid grid-cols-2 gap-x-6 gap-y-5 self-end sm:grid-cols-4 lg:grid-cols-2">
          {FLOW.map((item, index) => (
            <li key={item.step} className="flex flex-col gap-1 border-t border-line pt-3">
              <p className="font-mono text-xs text-ink-faint">0{index + 1}</p>
              <p className="text-sm font-semibold text-ink">{item.step}</p>
              <p className="text-xs leading-relaxed text-ink-muted">{item.detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="create-heading" className="flex flex-col gap-6">
        <div className="flex flex-col gap-1 border-t border-line pt-8">
          <p className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">Create</p>
          <h2 id="create-heading" className="text-2xl font-semibold tracking-tight text-ink">
            Declare an expected payment
          </h2>
          <p className="text-sm text-ink-muted">
            This console calls the public <code className="font-mono">POST /v1/payment-intents</code> endpoint, exactly as an agent would.
          </p>
        </div>
        <CreateIntentForm />
      </section>
    </div>
  );
}
