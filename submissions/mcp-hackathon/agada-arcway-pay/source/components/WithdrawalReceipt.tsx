"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import type { WithdrawalRecord } from "@/lib/types";
import { formatUsdc } from "@/lib/utils";

/**
 * A withdrawal's receipt.
 *
 * Shared by the screen shown immediately after withdrawing and by the
 * permalink at /claim/withdrawals/<id>, on the same reasoning as RunReceipt:
 * what you reopen later must be what you saw at the time. The fee is read from
 * the stored row rather than the current estimate, so an old receipt does not
 * silently re-price itself.
 */
export function WithdrawalReceipt({
  withdrawal,
  heading,
  showPermalink = true,
}: {
  withdrawal: WithdrawalRecord;
  heading?: string;
  showPermalink?: boolean;
}) {
  const total = withdrawal.amountUsdc + withdrawal.feeUsdc;
  const when = new Date(withdrawal.sentAt ?? withdrawal.createdAt);

  return (
    <div>
      <h1 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink">
        {heading ?? (withdrawal.status === "sent" ? "Withdrawal sent" : "Withdrawal")}
      </h1>
      <p className="mt-3 text-[15px] text-ink-soft">
        {when.toLocaleString()}
      </p>

      <div className="mt-6 rounded-card border border-line bg-card p-6">
        <Eyebrow>You received</Eyebrow>
        <div className="mt-2 text-[32px] leading-none font-semibold text-ink">
          {formatUsdc(withdrawal.amountUsdc)}{" "}
          <span className="text-[20px] text-ink-mute">USDC</span>
        </div>

        <dl className="mt-5 border-t border-line-soft pt-4 text-[14px]">
          <Row label="Destination">
            <span className="break-all font-mono text-[13px] text-ink">
              {withdrawal.destinationAddress}
            </span>
          </Row>
          <Row label="Network fee">
            <span className="text-ink-soft">{formatUsdc(withdrawal.feeUsdc)} USDC</span>
          </Row>
          <Row label="Total from balance">
            <span className="font-medium text-ink">{formatUsdc(total)} USDC</span>
          </Row>
          <Row label="Status">
            <div className="flex items-center gap-2">
              <StatusBadge status={withdrawal.status} />
              {withdrawal.simulated && <Chip tone="amber">Simulated</Chip>}
            </div>
          </Row>
        </dl>

        <div className="mt-5 border-t border-line-soft pt-4">
          <Eyebrow>Transaction hash</Eyebrow>
          <div className="mt-1 break-all font-mono text-[12px] text-ink-soft">
            {withdrawal.txHash ?? "Not available"}
          </div>
          {withdrawal.simulated && (
            <p className="mt-2 text-[12px] leading-[1.5] text-amber-text">
              This withdrawal was simulated — no chain was touched, and this
              hash will not resolve on a block explorer.
            </p>
          )}
        </div>

        {withdrawal.failureReason && (
          <p className="mt-4 text-[13px] text-amber-text">{withdrawal.failureReason}</p>
        )}
      </div>

      {showPermalink && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-[13px] text-ink-mute">
          <Eyebrow>Permalink</Eyebrow>
          <Link
            href={`/claim/withdrawals/${withdrawal.id}`}
            className="text-emerald underline underline-offset-2"
          >
            /claim/withdrawals/{withdrawal.id}
          </Link>
        </div>
      )}

      <Link href="/claim" className={buttonClasses("secondary", "lg", "mt-6")}>
        Back to your money
      </Link>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-1.5">
      <dt className="text-ink-soft">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
