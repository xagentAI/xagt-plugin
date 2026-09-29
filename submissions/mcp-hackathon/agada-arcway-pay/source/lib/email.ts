import { mkdir, readdir, readFile, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

/**
 * Outbound email, provider-agnostic.
 *
 * LIVE: Resend, via RESEND_API_KEY + RESEND_FROM.
 *
 * MOCK (no API key): the message is rendered exactly as it would be sent,
 * logged to the server console with its claim URL, and written to
 * `.mock-emails/` so it can be opened and clicked through at /dev/emails.
 * It deliberately does NOT silently no-op — an email nobody can see is
 * indistinguishable from a bug, and this is the one part of the product the
 * recipient experiences first.
 */

export const isEmailConfigured = Boolean(
  process.env.RESEND_API_KEY && process.env.RESEND_FROM
);

const MOCK_DIR = path.join(process.cwd(), ".mock-emails");
/** Keep the most recent N so the dev inbox stays readable. */
const MOCK_KEEP = 25;

export interface SendResult {
  ok: boolean;
  /** Provider message id in live mode; a local filename in mock mode. */
  id?: string;
  mocked: boolean;
  error?: string;
}

export interface OutboundEmail {
  to: string;
  subject: string;
  html: string;
  text: string;
  /** Surfaced in the dev inbox so the claim link can be clicked directly. */
  claimUrl?: string;
}

export async function sendEmail(message: OutboundEmail): Promise<SendResult> {
  if (!isEmailConfigured) return sendMock(message);

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: process.env.RESEND_FROM,
        to: [message.to],
        subject: message.subject,
        html: message.html,
        text: message.text,
      }),
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      return { ok: false, mocked: false, error: `Resend ${res.status}: ${body.slice(0, 300)}` };
    }

    const data = await res.json().catch(() => ({}));
    return { ok: true, id: data?.id, mocked: false };
  } catch (err) {
    return {
      ok: false,
      mocked: false,
      error: err instanceof Error ? err.message : "Unknown email error.",
    };
  }
}

async function sendMock(message: OutboundEmail): Promise<SendResult> {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const safeTo = message.to.replace(/[^a-zA-Z0-9@._-]/g, "_");
  const filename = `${stamp}__${safeTo}.json`;

  console.info(
    [
      "",
      "──────────────────────────────────────────────────────────────",
      " MOCK EMAIL (RESEND_API_KEY not set — nothing was delivered)",
      `   to:      ${message.to}`,
      `   subject: ${message.subject}`,
      message.claimUrl ? `   claim:   ${message.claimUrl}` : "",
      `   view:    /dev/emails`,
      "──────────────────────────────────────────────────────────────",
      "",
    ]
      .filter(Boolean)
      .join("\n")
  );

  try {
    await mkdir(MOCK_DIR, { recursive: true });
    await writeFile(
      path.join(MOCK_DIR, filename),
      JSON.stringify({ ...message, sentAt: new Date().toISOString() }, null, 2),
      "utf-8"
    );

    // Trim the oldest so the directory does not grow without bound.
    const files = (await readdir(MOCK_DIR)).filter((f) => f.endsWith(".json")).sort();
    for (const stale of files.slice(0, Math.max(0, files.length - MOCK_KEEP))) {
      await unlink(path.join(MOCK_DIR, stale)).catch(() => undefined);
    }

    return { ok: true, id: filename, mocked: true };
  } catch (err) {
    // Even if the file cannot be written, the console log above already
    // happened, so the message is never invisible.
    return {
      ok: false,
      mocked: true,
      error: err instanceof Error ? err.message : "Could not persist mock email.",
    };
  }
}

export interface StoredMockEmail extends OutboundEmail {
  filename: string;
  sentAt: string;
}

/** Reads the mock outbox, newest first. Used by the dev inbox page. */
export async function listMockEmails(): Promise<StoredMockEmail[]> {
  try {
    const files = (await readdir(MOCK_DIR)).filter((f) => f.endsWith(".json")).sort().reverse();
    const items = await Promise.all(
      files.map(async (filename) => {
        const raw = await readFile(path.join(MOCK_DIR, filename), "utf-8");
        return { ...(JSON.parse(raw) as OutboundEmail & { sentAt: string }), filename };
      })
    );
    return items;
  } catch {
    return [];
  }
}
