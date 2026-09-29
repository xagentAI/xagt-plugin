import { NextResponse } from "next/server";
import { authErrorResponse, requirePayee } from "@/lib/auth";
import { getPayeeBalance } from "@/lib/balance";
import { buildLedger } from "@/lib/ledger";
import { isWithdrawalLive } from "@/lib/withdraw";
import {
  claimPayeeRows,
  listAccountsForPerson,
  listPaymentsForPerson,
  listWithdrawalsForPerson,
  sumWithdrawnForPerson,
} from "@/lib/store";
import type { ClaimSummary } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Everything the payee's own page shows, aggregated across every company that
 * has paid them. See lib/store.ts — this is the one place company scoping
 * must NOT be applied.
 */
export async function GET(request: Request) {
  try {
    const { privyUserId, email } = await requirePayee(request);

    // Idempotent: picks up any payee row added by a new employer since the
    // last visit, so a second client's payments attach to this identity.
    await claimPayeeRows(privyUserId, email);

    const [accounts, payments, withdrawals, withdrawnUsdc] = await Promise.all([
      listAccountsForPerson(privyUserId, email),
      listPaymentsForPerson(privyUserId, email),
      listWithdrawalsForPerson(privyUserId, email),
      sumWithdrawnForPerson(privyUserId, email),
    ]);

    // Every account for one person resolves to the same embedded wallet,
    // because Privy provisions it from the email address.
    const walletAddress = accounts.find((a) => a.walletAddress)?.walletAddress ?? null;

    const balance = await getPayeeBalance(walletAddress, { payments, withdrawnUsdc });

    const summary: ClaimSummary = {
      email,
      walletAddress,
      accounts,
      payments,
      withdrawals,
      ledger: buildLedger(payments, withdrawals),
      withdrawalsLive: isWithdrawalLive,
      balance,
    };

    return NextResponse.json(summary);
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to load claim summary:", err);
    return NextResponse.json({ error: "Could not load your account." }, { status: 500 });
  }
}
