import { NextResponse } from "next/server";
import { authErrorResponse, requirePayee } from "@/lib/auth";
import { listAccountsForPerson, recordBroadcastWithdrawal } from "@/lib/store";
import { isPlausibleAddress } from "@/lib/withdraw";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Records a withdrawal the BROWSER has already broadcast.
 *
 * This endpoint holds no signing authority and cannot move funds — it only
 * writes down something the chain has already accepted. That is the whole
 * point of the ordering: the payee's embedded wallet signs in their browser,
 * the transaction goes to the network, and only then does the server hear
 * about it. A server that could sign would make the custody promise on /claim
 * false.
 *
 * Idempotent on txHash, so a client retrying after a dropped response — the
 * recovery path when the browser survives broadcast but loses the POST —
 * resolves to the same row instead of duplicating it.
 */
export async function POST(request: Request) {
  try {
    const { privyUserId, email } = await requirePayee(request);

    let body: {
      txHash?: unknown;
      amountUsdc?: unknown;
      feeUsdc?: unknown;
      destinationAddress?: unknown;
    };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const txHash = typeof body.txHash === "string" ? body.txHash.trim() : "";
    const amountUsdc = Number(body.amountUsdc);
    const feeUsdc = Number(body.feeUsdc);
    const destinationAddress =
      typeof body.destinationAddress === "string" ? body.destinationAddress.trim() : "";

    if (!/^0x[a-fA-F0-9]{64}$/.test(txHash)) {
      return NextResponse.json(
        { error: "A valid transaction hash is required." },
        { status: 400 }
      );
    }
    if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
      return NextResponse.json({ error: "Invalid amount." }, { status: 400 });
    }
    if (!isPlausibleAddress(destinationAddress)) {
      return NextResponse.json({ error: "Invalid destination address." }, { status: 400 });
    }

    const accounts = await listAccountsForPerson(privyUserId, email);
    if (accounts.length === 0) {
      return NextResponse.json({ error: "You have no wallet yet." }, { status: 400 });
    }

    const { withdrawal, created } = await recordBroadcastWithdrawal({
      payeeId: accounts[0].payeeId,
      amountUsdc,
      // Recorded as charged, so a receipt reopened later shows the fee that was
      // actually paid rather than whatever the current estimate happens to be.
      feeUsdc: Number.isFinite(feeUsdc) && feeUsdc >= 0 ? feeUsdc : 0,
      destinationAddress,
      txHash,
    });

    return NextResponse.json({ withdrawal, created }, { status: created ? 201 : 200 });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to record withdrawal:", err);
    return NextResponse.json({ error: "Could not record that withdrawal." }, { status: 500 });
  }
}
