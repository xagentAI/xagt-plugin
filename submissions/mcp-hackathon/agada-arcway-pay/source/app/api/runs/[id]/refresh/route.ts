import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { getTransferStatus } from "@/lib/circle";
import { notifyPayout } from "@/lib/notify";
import { listPayoutsInRun, updatePayeeStatus, updatePayoutStatus } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Re-checks any still-in-flight transfers in a run and returns the updated rows.
 *
 * Real transfers settle asynchronously, so a run can legitimately sit in
 * "Sending" after the request that started it has returned. Circle webhooks
 * would be the better mechanism; this is the honest interim — it only asks
 * about rows that are actually pending, so an already-settled run costs one
 * database read and no API calls.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { company } = await requireEmployer(request);
    const { id: runId } = await params;

    const payouts = await listPayoutsInRun(company.id, runId);
    if (payouts.length === 0) {
      return NextResponse.json({ error: "No such run." }, { status: 404 });
    }

    const inFlight = payouts.filter(
      (p) => (p.status === "sending" || p.status === "pending") && p.transferId
    );

    await Promise.all(
      inFlight.map(async (payout) => {
        const result = await getTransferStatus(payout.transferId as string);
        if (result.status === "pending") return;

        if (result.status === "complete") {
          const reference = result.txHash ?? payout.transferId;
          await updatePayoutStatus(company.id, payout.id, "sent", { transferId: reference });
          await updatePayeeStatus(company.id, payout.payeeId, "sent", { transferId: reference });

          // NOTIFY HERE, not only in the run route. A real transfer is usually
          // still pending when the run responds, so the notification attempt
          // there is skipped ("Payout did not settle") — and settlement, which
          // happens here, is the moment the recipient can actually be told.
          // Without this a live payout lands and nobody is ever emailed.
          // notifyPayout never throws, so a bounced address cannot fail the
          // refresh or reopen a settled payout.
          await notifyPayout(payout.id);
        } else {
          const reason = result.errorMessage ?? "Transfer failed.";
          await updatePayoutStatus(company.id, payout.id, "failed", { failureReason: reason });
          await updatePayeeStatus(company.id, payout.payeeId, "failed", { failureReason: reason });
        }
      })
    );

    const refreshed = await listPayoutsInRun(company.id, runId);
    return NextResponse.json({
      payouts: refreshed,
      settled: refreshed.filter((p) => p.status === "sent").length,
      stillPending: refreshed.filter((p) => p.status === "sending" || p.status === "pending").length,
      checked: inFlight.length,
    });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Run refresh failed:", err);
    return NextResponse.json({ error: "Could not refresh that run." }, { status: 500 });
  }
}
