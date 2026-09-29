"use client";

import Link from "next/link";

export function MinimalFooter() {
  return (
    <footer className="pt-20 pb-16 px-6 md:px-12 max-w-[1360px] mx-auto">
      <div className="grid grid-cols-1 md:grid-cols-12 gap-12 mb-16">
        {/* Brand & Mission */}
        <div className="md:col-span-6">
          <Link href="/" className="inline-flex items-center gap-2 text-white mb-4">
            <span className="text-xl text-accent leading-none">●</span>
            <span className="text-xl font-bold tracking-tight">multipu</span>
          </Link>
          <p className="text-sm text-neutral-400 max-w-sm leading-relaxed">
            The multi-chain launchpad and DEX execution engine for Solana, BNB Chain, and Robinhood Chain with real-time memecoin intelligence.
          </p>
        </div>

        {/* Navigation Links */}
        <div className="md:col-span-3">
          <div className="text-xs font-mono uppercase tracking-wider text-neutral-500 mb-4">
            Products
          </div>
          <div className="flex flex-col gap-2.5">
            <Link href="/launch" className="text-sm text-neutral-300 hover:text-white transition-colors">
              Launchpad
            </Link>
            <Link href="/dashboard/explore" className="text-sm text-neutral-300 hover:text-white transition-colors">
              Explore Memes
            </Link>
            <Link href="/dashboard" className="text-sm text-neutral-300 hover:text-white transition-colors">
              Trading Terminal
            </Link>
            <Link href="/dashboard/earnings" className="text-sm text-neutral-300 hover:text-white transition-colors">
              Creator Earnings
            </Link>
          </div>
        </div>

        <div className="md:col-span-3">
          <div className="text-xs font-mono uppercase tracking-wider text-neutral-500 mb-4">
            Developers
          </div>
          <div className="flex flex-col gap-2.5">
            <Link href="/dashboard/api" className="text-sm text-neutral-300 hover:text-white transition-colors">
              API Keys
            </Link>
            <a
              href="https://github.com/wisdomnova/multipu"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-neutral-300 hover:text-white transition-colors"
            >
              GitHub Repository
            </a>
            <div className="text-sm text-neutral-400 flex items-center gap-2 mt-2 font-mono text-xs">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span>Multi-chain online</span>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom line */}
      <div className="pt-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-mono text-neutral-600">
        <div>(c) 2026 Multipu Protocol. All rights reserved.</div>
        <div>Built for multi-chain liquidity</div>
      </div>
    </footer>
  );
}
