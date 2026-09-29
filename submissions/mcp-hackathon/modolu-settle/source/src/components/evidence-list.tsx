import { ASSOCIATION_COPY, type EvidenceItemResponse, type TransferAssociation } from "@/lib/public-api";

import { explorerAddressUrl, explorerTxUrl, formatUtc, groupAmount, shortenHex } from "./format";

const ASSOCIATION_CLASS: Readonly<Record<TransferAssociation, string>> = {
  matched: "text-status-paid border-status-paid/40",
  candidate: "text-status-ambiguous border-status-ambiguous/40",
  orphaned: "text-status-pending border-status-pending/40 line-through decoration-1",
};

function AssociationBadge({ association }: { readonly association: TransferAssociation }) {
  const copy = ASSOCIATION_COPY[association];
  return (
    <span
      title={copy.explanation}
      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-[0.08em] uppercase ${ASSOCIATION_CLASS[association]}`}
    >
      {copy.label}
    </span>
  );
}

function HashLink({ hash }: { readonly hash: string }) {
  const url = explorerTxUrl(hash);
  const short = shortenHex(hash);
  return url === null ? (
    <span className="font-mono" title={hash}>
      {short}
    </span>
  ) : (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={`${hash} — open on Basescan`}
      className="font-mono underline decoration-line-strong underline-offset-4"
    >
      {short}
    </a>
  );
}

function AddressText({ address }: { readonly address: string }) {
  const url = explorerAddressUrl(address);
  const short = shortenHex(address, 8, 4);
  return url === null ? (
    <span className="font-mono" title={address}>
      {short}
    </span>
  ) : (
    <a href={url} target="_blank" rel="noopener noreferrer" title={address} className="font-mono underline decoration-line-strong underline-offset-4">
      {short}
    </a>
  );
}

interface EvidenceListProps {
  readonly evidence: readonly EvidenceItemResponse[];
  readonly loading: boolean;
  readonly truncated: boolean;
}

/** Ledger of observed transfers: a table from `lg` up, stacked cards below. */
export function EvidenceList({ evidence, loading, truncated }: EvidenceListProps) {
  if (loading && evidence.length === 0) {
    return (
      <div aria-busy="true" className="rounded-md border border-line bg-surface px-5 py-6">
        <p className="text-sm text-ink-muted">Loading evidence…</p>
      </div>
    );
  }

  if (evidence.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line-strong bg-surface px-5 py-8 text-center">
        <p className="text-sm font-medium text-ink">No matching onchain evidence observed yet.</p>
        <p className="mt-1 text-xs text-ink-muted">
          Evidence appears here once a reconciliation finds native USDC transfers to the recipient inside the payment window.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted">
        {(Object.keys(ASSOCIATION_COPY) as TransferAssociation[]).map((association) => (
          <li key={association} className="flex items-center gap-2">
            <AssociationBadge association={association} />
            <span>{ASSOCIATION_COPY[association].explanation}</span>
          </li>
        ))}
      </ul>

      <div className="hidden overflow-x-auto rounded-md border border-line bg-surface lg:block">
        <table className="w-full text-sm">
          <thead className="text-left text-xs tracking-[0.12em] text-ink-muted uppercase">
            <tr className="border-b border-line">
              <th scope="col" className="px-4 py-2.5 font-medium">Transaction</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
              <th scope="col" className="px-4 py-2.5 font-medium">From</th>
              <th scope="col" className="px-4 py-2.5 font-medium">To</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Block</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Conf.</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Block time</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Association</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {evidence.map((row) => (
              <tr
                key={`${row.transactionHash}:${row.logIndex}`}
                data-association={row.association}
                className={row.association === "orphaned" ? "text-ink-muted" : ""}
              >
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <HashLink hash={row.transactionHash} />
                  <span className="ml-1 font-mono text-xs text-ink-faint">#{row.logIndex}</span>
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">{groupAmount(row.amount)}</td>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <AddressText address={row.from} />
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <AddressText address={row.to} />
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">{row.blockNumber}</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">{row.confirmations}</td>
                <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">{formatUtc(row.blockTimestamp)}</td>
                <td className="px-4 py-2.5">
                  <AssociationBadge association={row.association} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-3 lg:hidden">
        {evidence.map((row) => (
          <li
            key={`${row.transactionHash}:${row.logIndex}`}
            data-association={row.association}
            className="rounded-md border border-line bg-surface px-4 py-3 text-sm"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-base tabular-nums">
                {groupAmount(row.amount)} <span className="text-xs text-ink-muted">USDC</span>
              </span>
              <AssociationBadge association={row.association} />
            </div>
            <dl className="mt-2 grid grid-cols-[6rem_minmax(0,1fr)] gap-y-1 text-xs">
              <dt className="text-ink-muted">Transaction</dt>
              <dd>
                <HashLink hash={row.transactionHash} /> <span className="font-mono text-ink-faint">#{row.logIndex}</span>
              </dd>
              <dt className="text-ink-muted">From</dt>
              <dd>
                <AddressText address={row.from} />
              </dd>
              <dt className="text-ink-muted">To</dt>
              <dd>
                <AddressText address={row.to} />
              </dd>
              <dt className="text-ink-muted">Block</dt>
              <dd className="font-mono">
                {row.blockNumber} · {row.confirmations} conf.
              </dd>
              <dt className="text-ink-muted">Block time</dt>
              <dd className="font-mono">{formatUtc(row.blockTimestamp)}</dd>
            </dl>
          </li>
        ))}
      </ul>

      {truncated ? (
        <p className="text-xs text-ink-muted">
          Showing the first 100 transfers in canonical order. Use the evidence API with a cursor to page further.
        </p>
      ) : null}
    </div>
  );
}
