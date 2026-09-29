import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { notifyPayout } from "@/lib/notify";
import { createTransfer, getTransferStatus, getTreasuryBalance } from "@/lib/circle";
import {
  createPayout,
  createPayoutRun,
  listPayees,
  listPayouts,
  listPayoutsByIds,
  updatePayeeStatus,
  updatePayoutStatus,
} from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** The payout ledger, newest first — what the Activity tab reads. */
export async function GET(request: Request) {
  try {
    const { company } = await requireEmployer(request);
    return NextResponse.json({ payouts: await listPayouts(company.id) });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to list payouts:", err);
    return NextResponse.json({ error: "Could not load activity." }, { status: 500 });
  }
}

/**
 * Executes a payout run.
 *
 * For each queued payee this opens a `Payout` ledger row *before* attempting
 * anything, then marks the payee "sending" -> creates a Circle transfer ->
 * waits for it to settle -> writes the terminal status to both the ledger row
 * and the payee. Opening the row first means a crash mid-run still leaves a
 * record of what was intended, rather than money moving with nothing to show
 * for it.
 *
 * The response carries the ids of the rows this run wrote, which is what the
 * receipt screen reads back.
 *
 * Accepts an optional `{ payeeIds: string[] }` body so the review gate can
 * hold back specific recipients; with no body, every queued payee is paid.
 */
export async function POST(request: Request) {
  let company;
  try {
    ({ company } = await requireEmployer(request));
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    throw err;
  }

  let requestedIds: string[] | null = null;
  try {
    const body = await request.json();
    if (Array.isArray(body?.payeeIds)) {
      requestedIds = body.payeeIds.filter((id: unknown) => typeof id === "string");
    }
  } catch {
    // No body is the normal case — pay everything queued.
  }

  const payees = await listPayees(company.id);
  const queued = payees.filter(
    (p) =>
      (p.status === "pending" || p.status === "failed") &&
      (requestedIds === null || requestedIds.includes(p.id))
  );

  if (queued.length === 0) {
    return NextResponse.json({
      processed: 0,
      runId: null,
      payoutIds: [],
      payees: await listPayees(company.id),
    });
  }

  // OVERDRAFT GUARD. With finite testnet funds this is real: without it a run
  // pays the first two recipients and fails the third, leaving a half-sent run
  // that looks like a bug. Partial runs are legitimate when a transfer fails on
  // chain — but not when we simply never checked the balance.
  //
  // Checked server-side because the client's figure is a display value; only
  // this number decides whether money moves.
  const treasury = await getTreasuryBalance();
  const runTotal = queued.reduce((sum, p) => sum + p.amountUsdc, 0);

  if (runTotal > treasury.amountUsdc + 1e-9) {
    return NextResponse.json(
      {
        error:
          `This run totals ${runTotal.toFixed(2)} USDC but the treasury holds ` +
          `${treasury.amountUsdc.toFixed(2)}. Nothing was sent — top up the treasury ` +
          `or hold some recipients back.`,
        reason: "insufficient-funds",
        runTotalUsdc: runTotal,
        treasuryUsdc: treasury.amountUsdc,
      },
      { status: 409 }
    );
  }

  // The run row is created first: it is the thing being confirmed, and every
  // payout below is written against it.
  const runId = await createPayoutRun(company.id);

  const payoutIds = await Promise.all(
    queued.map(async (payee) => {
      const payout = await createPayout(company.id, runId, payee.id, payee.amountUsdc);
      await updatePayeeStatus(company.id, payee.id, "sending");

      try {
        const created = await createTransfer({
          destinationAddress: payee.walletAddress,
          amountUsdc: payee.amountUsdc,
        });

        if (created.status === "failed") {
          const reason = created.errorMessage ?? "Transfer creation failed.";
          await updatePayoutStatus(company.id, payout.id, "failed", { failureReason: reason });
          await updatePayeeStatus(company.id, payee.id, "failed", { failureReason: reason });
          return payout.id;
        }

        // Poll once for a final state. In mock mode this resolves quickly;
        // against the real Circle API this moves to webhooks (Phase 3).
        const final = await getTransferStatus(created.transferId);

        if (final.status === "complete") {
          // Prefer the chain hash over Circle's internal transaction id — it is
          // the thing a recipient can actually look up in an explorer.
          const reference = final.txHash ?? created.transferId;
          await updatePayoutStatus(company.id, payout.id, "sent", { transferId: reference });
          await updatePayeeStatus(company.id, payee.id, "sent", { transferId: reference });
        } else if (final.status === "pending") {
          // Real transfers settle asynchronously. Leave both rows in flight and
          // keep Circle's id so a later refresh can resolve them.
          await updatePayoutStatus(company.id, payout.id, "sending", {
            transferId: created.transferId,
          });
          await updatePayeeStatus(company.id, payee.id, "sending", {
            transferId: created.transferId,
          });
        } else {
          const reason = final.errorMessage ?? "Transfer did not complete.";
          await updatePayoutStatus(company.id, payout.id, "failed", {
            transferId: created.transferId,
            failureReason: reason,
          });
          await updatePayeeStatus(company.id, payee.id, "failed", {
            transferId: created.transferId,
            failureReason: reason,
          });
        }
      } catch (err) {
        console.error(`Payout failed for payee ${payee.id}:`, err);
        const reason = err instanceof Error ? err.message : "Unknown error.";
        await updatePayoutStatus(company.id, payout.id, "failed", { failureReason: reason });
        await updatePayeeStatus(company.id, payee.id, "failed", { failureReason: reason });
      }

      return payout.id;
    })
  );

  // Notify AFTER every transfer has resolved. Each call records its own
  // outcome on the payout row and never throws, so a bounced address cannot
  // affect money that has already moved.
  await Promise.all(payoutIds.map((id) => notifyPayout(id)));

  return NextResponse.json({
    processed: queued.length,
    runId,
    payoutIds,
    payouts: await listPayoutsByIds(company.id, payoutIds),
    payees: await listPayees(company.id),
  });
}
