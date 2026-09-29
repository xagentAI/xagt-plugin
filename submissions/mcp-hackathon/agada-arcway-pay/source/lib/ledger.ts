import type { LedgerEntry, ReceivedPayment, WithdrawalRecord } from "./types";

/**
 * Merges payments in and withdrawals out into one chronological stream with a
 * running balance.
 *
 * Only settled rows move the balance: a pending or failed transfer has not
 * changed what the payee holds, so it appears in the list (they should see it)
 * carrying the balance as it stood. The running total is accumulated
 * oldest-first — that is the only order in which a balance means anything —
 * and the result is reversed for display, since the newest line is the one
 * people look at.
 */
export function buildLedger(
  payments: ReceivedPayment[],
  withdrawals: WithdrawalRecord[]
): LedgerEntry[] {
  // A plain Omit over a union collapses it into one object type, which loses
  // the `kind` discriminant and with it the ability to narrow below. The
  // conditional makes it distribute across each member instead.
  type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
    ? Omit<T, K>
    : never;
  type Row = DistributiveOmit<LedgerEntry, "balanceAfter">;

  const rows: Row[] = [
    ...payments.map<Row>((p) => ({
      kind: "payment",
      id: p.id,
      at: p.sentAt ?? p.createdAt,
      amountUsdc: p.amountUsdc,
      status: p.status,
      companyName: p.companyName,
      transferId: p.transferId,
    })),
    ...withdrawals.map<Row>((w) => ({
      kind: "withdrawal",
      id: w.id,
      at: w.sentAt ?? w.createdAt,
      // Negative: this is money leaving.
      amountUsdc: -w.amountUsdc,
      feeUsdc: w.feeUsdc,
      status: w.status,
      destinationAddress: w.destinationAddress,
      txHash: w.txHash,
      simulated: w.simulated,
    })),
  ];

  rows.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());

  let balance = 0;
  const withBalance = rows.map<LedgerEntry>((row) => {
    if (row.status === "sent") {
      balance +=
        row.kind === "withdrawal"
          ? row.amountUsdc - row.feeUsdc // already negative; the fee also leaves
          : row.amountUsdc;
    }
    return { ...row, balanceAfter: Math.max(0, balance) } as LedgerEntry;
  });

  return withBalance.reverse();
}
