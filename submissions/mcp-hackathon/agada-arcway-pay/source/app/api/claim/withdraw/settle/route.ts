import { NextResponse } from "next/server";
import { createPublicClient, http } from "viem";
import { arcTestnet } from "@/lib/chain";
import { authErrorResponse, requirePayee } from "@/lib/auth";
import { getWithdrawalByHash, settleWithdrawal } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Asks the chain whether a recorded withdrawal has been mined, and settles the
 * row accordingly. Read-only with respect to funds: it can mark a row sent or
 * failed, never move anything.
 */
export async function POST(request: Request) {
  try {
    const { privyUserId, email } = await requirePayee(request);

    let body: { txHash?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const txHash = typeof body.txHash === "string" ? body.txHash.trim() : "";
    if (!/^0x[a-fA-F0-9]{64}$/.test(txHash)) {
      return NextResponse.json({ error: "A valid transaction hash is required." }, { status: 400 });
    }

    const existing = await getWithdrawalByHash(privyUserId, email, txHash);
    if (!existing) {
      return NextResponse.json({ error: "No such withdrawal." }, { status: 404 });
    }
    if (existing.status === "sent" || existing.status === "failed") {
      return NextResponse.json({ withdrawal: existing, settled: true });
    }

    const client = createPublicClient({ chain: arcTestnet, transport: http() });

    let receipt;
    try {
      receipt = await client.getTransactionReceipt({ hash: txHash as `0x${string}` });
    } catch {
      // Not mined yet is the normal case, and viem throws for it. Report it as
      // still pending rather than as an error.
      return NextResponse.json({ withdrawal: existing, settled: false });
    }

    if (receipt.status === "success") {
      // The actual gas paid, now that it is known.
      const feePaid = receipt.gasUsed * (receipt.effectiveGasPrice ?? BigInt(0));
      await settleWithdrawal(existing.id, "sent", { txHash });
      const updated = await getWithdrawalByHash(privyUserId, email, txHash);
      return NextResponse.json({
        withdrawal: updated,
        settled: true,
        gasPaidWei: feePaid.toString(),
      });
    }

    await settleWithdrawal(existing.id, "failed", {
      txHash,
      failureReason: "The transaction was mined but reverted on chain.",
    });
    const updated = await getWithdrawalByHash(privyUserId, email, txHash);
    return NextResponse.json({ withdrawal: updated, settled: true });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to settle withdrawal:", err);
    return NextResponse.json({ error: "Could not check that withdrawal." }, { status: 500 });
  }
}
