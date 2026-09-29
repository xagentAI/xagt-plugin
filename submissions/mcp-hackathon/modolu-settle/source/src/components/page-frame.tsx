import Link from "next/link";
import type { ReactNode } from "react";

/** Shared chrome: wordmark, the "demo console" framing, and a quiet footer. */
export function PageFrame({ children }: { readonly children: ReactNode }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>
      <header className="border-b border-line">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <Link href="/" className="flex items-baseline gap-3 no-underline">
            <span className="text-sm font-semibold tracking-[0.18em] text-ink">SETTLE</span>
            <span className="hidden text-xs text-ink-muted sm:inline">Payment truth for autonomous agents</span>
          </Link>
          <p className="text-xs text-ink-muted">
            <span className="hidden sm:inline">Demo console · </span>
            <span className="font-medium text-ink">The API is the product.</span>
          </p>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 sm:px-8 sm:py-12">
        {children}
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-4 text-xs text-ink-muted sm:px-8">
          <p>Read-only reconciliation of native USDC on Base. Settle never holds keys or sends payments.</p>
          <p className="font-mono">
            <a href="/health" className="underline underline-offset-4">
              GET /health
            </a>
          </p>
        </div>
      </footer>
    </>
  );
}
