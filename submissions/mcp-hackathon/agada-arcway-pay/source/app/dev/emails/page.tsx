"use client";

import { useEffect, useState } from "react";
import { Wordmark } from "@/components/Brand";
import { Chip, Eyebrow } from "@/components/ui";
import { cn } from "@/lib/utils";

interface MockEmail {
  filename: string;
  to: string;
  subject: string;
  html: string;
  text: string;
  claimUrl?: string;
  sentAt: string;
}

/**
 * Local inbox for mock-mode email. Renders exactly the HTML that would have
 * been delivered, so the template and the claim link can be checked without
 * depending on a provider or on deliverability.
 */
export default function DevEmailsPage() {
  const [emails, setEmails] = useState<MockEmail[]>([]);
  const [live, setLive] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/dev/emails");
        const data = await res.json();
        if (cancelled) return;
        setEmails(data.emails ?? []);
        setLive(Boolean(data.live));
        setSelected((data.emails ?? [])[0]?.filename ?? null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const current = emails.find((e) => e.filename === selected) ?? null;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Wordmark />
          <div className="flex items-center gap-3">
            <Chip tone={live ? "emerald" : "amber"}>
              {live ? "Resend configured" : "Mock mode — nothing delivered"}
            </Chip>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
        <h1 className="font-display text-[36px] leading-none tracking-[-0.01em] text-ink">
          Mock outbox
        </h1>
        <p className="mt-3 max-w-xl text-[15px] leading-[1.6] text-ink-soft">
          Every notification the app would have sent, rendered as the recipient
          would see it. Development only.
        </p>

        {loading ? (
          <div className="mt-8 rounded-card border border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Loading…
          </div>
        ) : emails.length === 0 ? (
          <div className="mt-8 rounded-card border border-dashed border-line bg-card p-12 text-center text-[15px] text-ink-mute">
            Nothing sent yet. Confirm a payout run and it appears here.
          </div>
        ) : (
          <div className="mt-8 grid gap-6 lg:grid-cols-[300px_1fr]">
            <div className="overflow-hidden rounded-card border border-line bg-card">
              <div className="border-b border-line px-4 py-3">
                <Eyebrow>{emails.length} message{emails.length === 1 ? "" : "s"}</Eyebrow>
              </div>
              <ul>
                {emails.map((e) => (
                  <li key={e.filename}>
                    <button
                      onClick={() => setSelected(e.filename)}
                      className={cn(
                        "w-full border-b border-line-soft px-4 py-3 text-left transition-colors last:border-0",
                        e.filename === selected ? "bg-emerald-50" : "hover:bg-paper"
                      )}
                    >
                      <div className="truncate text-[13px] font-medium text-ink">{e.to}</div>
                      <div className="mt-0.5 truncate text-[12px] text-ink-mute">{e.subject}</div>
                      <div className="mt-1 text-[11px] text-ink-mute">
                        {new Date(e.sentAt).toLocaleString()}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {current && (
              <div className="overflow-hidden rounded-card border border-line bg-card">
                <div className="border-b border-line px-5 py-4">
                  <div className="text-[13px] text-ink-mute">
                    To <span className="text-ink">{current.to}</span>
                  </div>
                  <div className="mt-1 font-medium text-ink">{current.subject}</div>
                  {current.claimUrl && (
                    <a
                      href={current.claimUrl}
                      className="mt-2 inline-block break-all text-[13px] text-emerald underline underline-offset-2"
                    >
                      {current.claimUrl}
                    </a>
                  )}
                </div>
                <iframe
                  title={current.subject}
                  srcDoc={current.html}
                  className="h-[620px] w-full border-0 bg-white"
                />
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
