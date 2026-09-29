import type { ReactNode } from "react";

import type { PaymentIntentResponse } from "@/lib/public-api";

import { explorerAddressUrl, formatUtc } from "./format";

function AddressValue({ address }: { readonly address: string | null }) {
  if (address === null) {
    return <span className="text-ink-muted">Not declared — single-sender matching</span>;
  }
  const url = explorerAddressUrl(address);
  return url === null ? (
    <span className="font-mono break-all">{address}</span>
  ) : (
    <a href={url} target="_blank" rel="noopener noreferrer" className="font-mono break-all underline decoration-line-strong underline-offset-4">
      {address}
    </a>
  );
}

function Row({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-xs font-medium tracking-[0.12em] text-ink-muted uppercase sm:pt-0.5">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  );
}

const CONFIDENCE_LABEL = {
  none: "None — no evidence associated",
  exact_payer: "Exact payer — transfers from the declared payer",
  single_sender: "Single sender — one unambiguous sender observed",
  ambiguous: "Ambiguous — several senders observed",
} as const;

/** Compact obligation metadata beneath the payment summary. */
export function PaymentDetails({ intent }: { readonly intent: PaymentIntentResponse }) {
  return (
    <dl className="min-w-0 divide-y divide-line rounded-md border border-line bg-surface px-5">
      <Row label="Payer">
        <AddressValue address={intent.payer} />
      </Row>
      <Row label="Recipient">
        <AddressValue address={intent.recipient} />
      </Row>
      <Row label="External reference">{intent.externalReference ?? <span className="text-ink-muted">—</span>}</Row>
      <Row label="Required confirmations">
        <span className="font-mono">{intent.requiredConfirmations}</span>
      </Row>
      <Row label="Match confidence">{CONFIDENCE_LABEL[intent.matchConfidence]}</Row>
      <Row label="Paid at">{intent.paidAt === null ? <span className="text-ink-muted">—</span> : <span className="font-mono">{formatUtc(intent.paidAt)}</span>}</Row>
      <Row label="Created">
        <span className="font-mono">{formatUtc(intent.createdAt)}</span>
      </Row>
      <Row label="Window closes">
        <span className="font-mono">{formatUtc(intent.expiresAt)}</span>
      </Row>
      <Row label="Network · asset">
        <span>Base · native USDC</span>
      </Row>
      <Row label="Intent ID">
        <span className="font-mono break-all">{intent.id}</span>
      </Row>
    </dl>
  );
}
