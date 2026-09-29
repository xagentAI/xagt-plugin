import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { notifyPayout } from "@/lib/notify";
import { prisma } from "@/lib/prisma";
import { listPayoutsByIds } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Re-sends one payout's notification.
 *
 * Available for any settled payout, not only failed ones — the common real
 * complaint is "it says sent but I never got it" (spam, silent drop, full
 * inbox), which no failure state captures.
 *
 * Scoped to the caller's company: the payout is looked up by id AND
 * companyId, so one tenant cannot mail another tenant's recipients.
 */
export async function POST(request: Request) {
  try {
    const { company } = await requireEmployer(request);

    let body: { payoutId?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const payoutId = typeof body.payoutId === "string" ? body.payoutId : "";
    if (!payoutId) {
      return NextResponse.json({ error: "payoutId is required." }, { status: 400 });
    }

    const owned = await prisma.payout.findFirst({
      where: { id: payoutId, companyId: company.id },
      select: { id: true },
    });
    if (!owned) {
      return NextResponse.json({ error: "No such payout." }, { status: 404 });
    }

    const outcome = await notifyPayout(payoutId, { enforceCooldown: true });

    if (!outcome.ok && outcome.reason === "cooldown") {
      const seconds = Math.ceil(outcome.retryAfterMs / 1000);
      const at = outcome.lastAttemptAt.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      // A refusal that says when the last one went out is more useful than a
      // silent no-op — the employer can relay it to the payee immediately.
      return NextResponse.json(
        {
          error: `Already sent a moment ago (${at}). Try again in ${seconds}s.`,
          reason: "cooldown",
          retryAfterSeconds: seconds,
        },
        { status: 429, headers: { "Retry-After": String(seconds) } }
      );
    }

    if (!outcome.ok && outcome.reason === "not-settled") {
      return NextResponse.json(
        { error: "That payment hasn't settled, so there's nothing to announce yet." },
        { status: 409 }
      );
    }

    const [updated] = await listPayoutsByIds(company.id, [payoutId]);
    return NextResponse.json({
      payout: updated,
      delivered: outcome.ok,
      error: outcome.ok ? undefined : outcome.message,
    });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Resend failed:", err);
    return NextResponse.json({ error: "Could not resend." }, { status: 500 });
  }
}
