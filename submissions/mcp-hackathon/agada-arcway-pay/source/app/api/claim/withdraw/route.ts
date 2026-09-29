import { NextResponse } from "next/server";
import { authErrorResponse, requirePayee } from "@/lib/auth";
import { getPayeeBalance } from "@/lib/balance";
import {
  createWithdrawal,
  getWithdrawalForPerson,
  listAccountsForPerson,
  listPaymentsForPerson,
  settleWithdrawal,
  sumWithdrawnForPerson,
} from "@/lib/store";
import {
  isPlausibleAddress,
  isWithdrawalLive,
  mockTxHash,
  NETWORK_FEE_USDC,
} from "@/lib/withdraw";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const { privyUserId, email } = await requirePayee(request);

    // Refuse BEFORE writing anything. The row-first discipline elsewhere
    // exists so a crash mid-operation still leaves a record of intent — but a
    // withdrawal that is structurally unavailable never starts, and recording
    // it as a "failed withdrawal" pollutes the payee's ledger with events that
    // never happened.
    if (isWithdrawalLive) {
      return NextResponse.json(
        {
          error:
            "Moving funds out isn't enabled yet on this deployment. Signing has to " +
            "happen in your browser with your own wallet, and that isn't built. " +
            "Your balance is untouched.",
          reason: "withdrawals-unavailable",
        },
        { status: 503 }
      );
    }

    let body: { amountUsdc?: unknown; destinationAddress?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const amountUsdc = Number(body.amountUsdc);
    const destinationAddress =
      typeof body.destinationAddress === "string" ? body.destinationAddress.trim() : "";

    if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
      return NextResponse.json({ error: "Enter an amount greater than zero." }, { status: 400 });
    }
    if (!isPlausibleAddress(destinationAddress)) {
      return NextResponse.json(
        { error: "That doesn't look like a wallet address (expected 0x followed by 40 characters)." },
        { status: 400 }
      );
    }

    const accounts = await listAccountsForPerson(privyUserId, email);
    if (accounts.length === 0) {
      return NextResponse.json({ error: "You have no wallet yet." }, { status: 400 });
    }

    // Re-derive the balance server-side. The client's figure is a display
    // value and must never be what authorises a withdrawal.
    const [payments, withdrawnUsdc] = await Promise.all([
      listPaymentsForPerson(privyUserId, email),
      sumWithdrawnForPerson(privyUserId, email),
    ]);
    const walletAddress = accounts.find((a) => a.walletAddress)?.walletAddress ?? null;
    const balance = await getPayeeBalance(walletAddress, { payments, withdrawnUsdc });

    if (amountUsdc + NETWORK_FEE_USDC > balance.amountUsdc + 1e-9) {
      return NextResponse.json(
        { error: "That's more than your balance, once the network fee is included." },
        { status: 400 }
      );
    }

    // Open the row before attempting anything, so an interrupted withdrawal
    // still leaves a trace — the same discipline the payout run uses.
    const withdrawalId = await createWithdrawal(
      accounts[0].payeeId,
      amountUsdc,
      NETWORK_FEE_USDC,
      destinationAddress
    );

    const txHash = mockTxHash();
    await settleWithdrawal(withdrawalId, "sent", { txHash });

    // Return the stored record, not a hand-assembled echo of the request, so
    // the success screen renders exactly what the permalink will later.
    const withdrawal = await getWithdrawalForPerson(privyUserId, email, withdrawalId);
    return NextResponse.json(withdrawal);
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Withdrawal failed:", err);
    return NextResponse.json({ error: "Could not complete the withdrawal." }, { status: 500 });
  }
}
