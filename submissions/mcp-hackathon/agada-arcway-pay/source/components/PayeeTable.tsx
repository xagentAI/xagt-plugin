import type { Payee } from "@/lib/types";
import { formatUsdc, truncateAddress } from "@/lib/utils";
import { StatusBadge } from "./StatusBadge";

export function PayeeTable({
  payees,
  emptyMessage = "No payees yet. Add your first payee to provision them a wallet.",
  renderAction,
}: {
  payees: Payee[];
  emptyMessage?: string;
  /** Optional per-row action, e.g. "Pay again". Column is hidden when absent. */
  renderAction?: (payee: Payee) => React.ReactNode;
}) {
  if (payees.length === 0) {
    return (
      <div className="rounded-card border border-dashed border-line bg-card p-12 text-center text-[15px] text-ink-mute">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-card border border-line bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-[0.12em] text-ink-mute">
              <th className="px-5 py-3 font-semibold">Person</th>
              <th className="px-5 py-3 font-semibold">Wallet</th>
              <th className="px-5 py-3 text-right font-semibold">Amount</th>
              <th className="px-5 py-3 font-semibold">Status</th>
              <th className="px-5 py-3 font-semibold">Claimed</th>
              {renderAction && <th className="px-5 py-3" />}
            </tr>
          </thead>
          <tbody>
            {payees.map((payee) => (
              <tr key={payee.id} className="border-b border-line-soft last:border-0">
                <td className="px-5 py-4">
                  <div className="font-medium text-ink">{payee.name}</div>
                  <div className="text-[13px] text-ink-mute">{payee.email}</div>
                </td>
                <td className="px-5 py-4 font-mono text-[13px] text-ink-soft">
                  {truncateAddress(payee.walletAddress)}
                </td>
                <td className="px-5 py-4 text-right font-medium text-ink">
                  {formatUsdc(payee.amountUsdc)}{" "}
                  <span className="text-ink-mute">USDC</span>
                </td>
                <td className="px-5 py-4">
                  <StatusBadge status={payee.status} />
                  {payee.status === "failed" && payee.failureReason && (
                    <div className="mt-1.5 max-w-[240px] text-[13px] text-amber-text">
                      {payee.failureReason}
                    </div>
                  )}
                </td>
                <td className="px-5 py-4">
                  {payee.privyUserId ? (
                    <span className="text-ink-soft">Yes</span>
                  ) : (
                    <span className="text-amber-text">Not yet</span>
                  )}
                </td>
                {renderAction && (
                  <td className="px-5 py-4 text-right">{renderAction(payee)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
