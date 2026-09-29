import type { OutboundEmail } from "./email";
import { formatUsdc } from "./utils";

/**
 * The "you've been paid" email.
 *
 * Deliberately plain: system fonts, no images, table-free layout, and colours
 * chosen so it stays legible if a client forces dark mode. The brand shows
 * through type and the emerald accent rather than through artwork that many
 * clients block by default.
 */

export interface PayoutEmailInput {
  payeeName: string;
  payeeEmail: string;
  companyName: string;
  amountUsdc: number;
  appUrl: string;
}

/**
 * The claim link carries the email only to PREFILL the sign-in field. It is
 * not a credential and grants nothing on its own — Privy's one-time code is
 * the security boundary, so a forwarded link is harmless.
 */
export function claimUrlFor(appUrl: string, email: string): string {
  return `${appUrl.replace(/\/$/, "")}/claim?email=${encodeURIComponent(email)}`;
}

export function renderPayoutEmail(input: PayoutEmailInput): OutboundEmail {
  const amount = `${formatUsdc(input.amountUsdc)} USDC`;
  const claimUrl = claimUrlFor(input.appUrl, input.payeeEmail);
  const firstName = input.payeeName.trim().split(/\s+/)[0] || "there";

  const subject = `${input.companyName} sent you ${amount}`;

  const text = [
    `Hi ${firstName},`,
    "",
    `${input.companyName} has sent you ${amount}. It's waiting for you.`,
    "",
    `Claim your payment: ${claimUrl}`,
    "",
    "You don't need a wallet, an app, or a seed phrase. Sign in with this",
    "email address and the money is yours to hold or move.",
    "",
    "— Arcway",
  ].join("\n");

  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light dark" />
    <title>${escapeHtml(subject)}</title>
  </head>
  <body style="margin:0;padding:0;background-color:#faf8f4;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
      ${escapeHtml(input.companyName)} sent you ${escapeHtml(amount)}. No wallet needed.
    </div>
    <div style="max-width:520px;margin:0 auto;padding:40px 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1917;">

      <div style="font-family:Georgia,'Times New Roman',serif;font-size:22px;letter-spacing:-0.01em;color:#1a1917;">
        Arcway
      </div>

      <div style="margin-top:36px;font-size:16px;line-height:1.6;color:#1a1917;">
        Hi ${escapeHtml(firstName)},
      </div>
      <div style="margin-top:12px;font-size:16px;line-height:1.6;color:#55524b;">
        <strong style="color:#1a1917;">${escapeHtml(input.companyName)}</strong>
        has sent you money. It&rsquo;s waiting for you &mdash; nothing is needed
        from you but a sign-in.
      </div>

      <div style="margin-top:28px;border:1px solid #e5e1d8;border-radius:12px;background-color:#ffffff;padding:24px;">
        <div style="font-size:11px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:#85806f;">
          Amount
        </div>
        <div style="margin-top:8px;font-size:30px;font-weight:600;color:#0b5c46;font-variant-numeric:tabular-nums;">
          ${escapeHtml(amount)}
        </div>
        <div style="margin-top:6px;font-size:14px;color:#85806f;">
          from ${escapeHtml(input.companyName)}
        </div>
      </div>

      <div style="margin-top:28px;">
        <a href="${escapeAttr(claimUrl)}"
           style="display:inline-block;background-color:#0b5c46;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:13px 22px;border-radius:6px;">
          Claim your payment
        </a>
      </div>

      <div style="margin-top:28px;font-size:14px;line-height:1.65;color:#55524b;">
        You don&rsquo;t need a wallet, an app, or a seed phrase. Sign in with
        this email address and the money is yours &mdash; hold it in dollars or
        move it out whenever you like.
      </div>

      <div style="margin-top:32px;padding-top:20px;border-top:1px solid #e5e1d8;font-size:12px;line-height:1.6;color:#85806f;">
        If the button doesn&rsquo;t work, paste this into your browser:<br />
        <span style="word-break:break-all;color:#55524b;">${escapeHtml(claimUrl)}</span>
      </div>

      <div style="margin-top:20px;font-size:12px;color:#85806f;">
        Arcway &middot; stablecoin payouts by email
      </div>
    </div>
  </body>
</html>`;

  return { to: input.payeeEmail, subject, html, text, claimUrl };
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value: string): string {
  return escapeHtml(value);
}
