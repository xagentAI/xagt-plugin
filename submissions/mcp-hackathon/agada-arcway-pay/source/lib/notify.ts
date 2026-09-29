import { prisma } from "./prisma";
import { sendEmail } from "./email";
import { renderPayoutEmail } from "./email-templates";

/**
 * Tells a recipient that a payout landed, and records the outcome on the
 * payout row.
 *
 * THE MONEY AND THE MESSAGE ARE SEPARATE. This function never throws: a
 * failed notification records `notifyStatus = failed` and returns, because a
 * transfer that already settled must not be rolled back — or even appear to
 * have failed — because an SMTP call did. The employer sees the failure on
 * the receipt and can retry it on its own.
 */
/**
 * Minimum gap between send attempts for one payout.
 *
 * Resending is now offered on every row, not just failures, so it is easy to
 * click repeatedly — and each click spends real Resend quota. A refusal that
 * says when the last one went out is more useful to the employer than a
 * silent no-op, so `notifyPayout` reports why it declined.
 */
export const RESEND_COOLDOWN_MS = 60_000;

export type NotifyOutcome =
  | { ok: true; skipped?: false }
  | { ok: false; reason: "cooldown"; retryAfterMs: number; lastAttemptAt: Date }
  | { ok: false; reason: "not-settled" | "missing" | "failed"; message?: string };

export function appUrl(): string {
  return (
    process.env.NEXT_PUBLIC_APP_URL ??
    process.env.APP_URL ??
    "http://localhost:3000"
  );
}

export async function notifyPayout(
  payoutId: string,
  options: { enforceCooldown?: boolean } = {}
): Promise<NotifyOutcome> {
  try {
    const payout = await prisma.payout.findUnique({
      where: { id: payoutId },
      include: { payee: true, company: true },
    });

    if (!payout) return { ok: false, reason: "missing" };

    // Only tell someone about money that actually arrived.
    if (payout.status !== "sent") {
      await prisma.payout.update({
        where: { id: payoutId },
        data: { notifyStatus: "skipped", notifyError: "Payout did not settle." },
      });
      return { ok: false, reason: "not-settled" };
    }

    // Rate limit manual resends. The automatic send at the end of a run passes
    // enforceCooldown: false, since that is the first attempt by definition.
    if (options.enforceCooldown && payout.lastNotifyAttemptAt) {
      const elapsed = Date.now() - payout.lastNotifyAttemptAt.getTime();
      if (elapsed < RESEND_COOLDOWN_MS) {
        return {
          ok: false,
          reason: "cooldown",
          retryAfterMs: RESEND_COOLDOWN_MS - elapsed,
          lastAttemptAt: payout.lastNotifyAttemptAt,
        };
      }
    }

    const message = renderPayoutEmail({
      payeeName: payout.payee.name,
      payeeEmail: payout.payee.email,
      companyName: payout.company.name,
      amountUsdc: payout.amountUsdc.toNumber(),
      appUrl: appUrl(),
    });

    const result = await sendEmail(message);
    const now = new Date();

    await prisma.payout.update({
      where: { id: payoutId },
      data: {
        // Counted whether or not delivery worked: the question support asks is
        // "how many times have we tried this address?"
        notifyAttempts: { increment: 1 },
        lastNotifyAttemptAt: now,
        ...(result.ok
          ? { notifyStatus: "sent", notifiedAt: now, notifyError: null }
          : { notifyStatus: "failed", notifyError: result.error ?? "Send failed." }),
      },
    });

    return result.ok
      ? { ok: true }
      : { ok: false, reason: "failed", message: result.error };
  } catch (err) {
    console.error(`Notification failed for payout ${payoutId}:`, err);
    // Best-effort status write; swallow anything here so the caller's payout
    // response is unaffected.
    await prisma.payout
      .update({
        where: { id: payoutId },
        data: {
          notifyStatus: "failed",
          notifyAttempts: { increment: 1 },
          lastNotifyAttemptAt: new Date(),
          notifyError: err instanceof Error ? err.message : "Unknown error.",
        },
      })
      .catch(() => undefined);

    return {
      ok: false,
      reason: "failed",
      message: err instanceof Error ? err.message : "Unknown error.",
    };
  }
}
