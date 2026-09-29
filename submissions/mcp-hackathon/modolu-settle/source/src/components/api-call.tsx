"use client";

import { useEffect, useState } from "react";

interface ApiCallProps {
  readonly title: string;
  readonly command: string;
  readonly caption?: string;
}

/** A developer-facing command block with a clipboard action. */
export function ApiCall({ title, command, caption }: ApiCallProps) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (copied === "idle") {
      return;
    }
    const timer = setTimeout(() => setCopied("idle"), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
  }

  return (
    <section aria-label={title} className="min-w-0 rounded-md border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <h3 className="text-xs font-medium tracking-[0.12em] text-ink-muted uppercase">{title}</h3>
        <button
          type="button"
          onClick={() => void copy()}
          className="rounded border border-line-strong px-2.5 py-1 text-xs font-medium text-ink hover:bg-surface-muted"
        >
          {copied === "copied" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy API call"}
        </button>
        <span role="status" aria-live="polite" className="sr-only">
          {copied === "copied" ? "API call copied to clipboard" : copied === "failed" ? "Copy to clipboard failed" : ""}
        </span>
      </div>
      <pre className="px-4 py-3 font-mono text-[12.5px] leading-relaxed break-all whitespace-pre-wrap text-ink">
        <code>{command}</code>
      </pre>
      {caption !== undefined ? <p className="border-t border-line px-4 py-2 text-xs text-ink-muted">{caption}</p> : null}
    </section>
  );
}
