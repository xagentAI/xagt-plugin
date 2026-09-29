"use client";

import Link from "next/link";
import Image from "next/image";

const footerSections = {
  products: [
    "Token Orchestrator",
    "Meme Coin Explorer",
    "DEX Trading Terminal",
    "Multi-Chain Balances",
    "Creator Earnings",
  ],
  protocols: [
    "Pump.fun (Solana)",
    "Meteora DLMM (Solana)",
    "Bags App (Solana)",
    "Four.meme (BNB Chain)",
    "Pons Protocol (Robinhood)",
  ],
  developers: [
    "REST API Reference",
    "KeeperHub MCP Server",
    "OlaXBT Strategy Signals",
    "Webhooks & Events",
    "Developer Keys",
  ],
  ecosystem: [
    { label: "Token Manager" },
    { label: "Launch History" },
    { label: "Documentation", href: "https://docs.multipu.fun" },
    { label: "GitHub Repository", href: "https://github.com/wisdomnova/multipu" },
    { label: "Network Telemetry" },
  ],
};

export function Footer() {
  return (
    <footer className="border-t border-white/[0.06] bg-[#050608] text-text-secondary">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10 py-16 md:py-20">
        
        {/* Sitelinks Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-10 pb-16 border-b border-white/[0.06]">
          
          {/* Brand Info Column */}
          <div className="col-span-2 md:col-span-4 lg:col-span-1 space-y-4">
            <Link href="/" className="flex items-center gap-2.5">
              <div className="relative w-7 h-7 flex-shrink-0">
                <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
              </div>
              <span className="text-base font-bold tracking-tight text-white">
                Multipu
              </span>
            </Link>
            <p className="text-xs text-text-muted leading-relaxed font-normal">
              Multi-chain token orchestrator, real-time DEX terminal, and autonomous agent protocol across Solana, BNB Chain, and Robinhood Chain.
            </p>
          </div>

          {/* Sitelinks Column 1: Products */}
          <div className="space-y-3">
            <div className="font-mono text-[11px] uppercase tracking-wider text-white font-semibold">
              Platform
            </div>
            <ul className="space-y-2 text-xs">
              {footerSections.products.map((item) => (
                <li key={item} className="text-text-muted/90 font-normal select-none">
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* Sitelinks Column 2: Supported Protocols */}
          <div className="space-y-3">
            <div className="font-mono text-[11px] uppercase tracking-wider text-white font-semibold">
              Launchpads
            </div>
            <ul className="space-y-2 text-xs">
              {footerSections.protocols.map((item) => (
                <li key={item} className="text-text-muted/90 font-normal select-none">
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* Sitelinks Column 3: Developers */}
          <div className="space-y-3">
            <div className="font-mono text-[11px] uppercase tracking-wider text-white font-semibold">
              Agents &amp; API
            </div>
            <ul className="space-y-2 text-xs">
              {footerSections.developers.map((item) => (
                <li key={item} className="text-text-muted/90 font-normal select-none">
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* Sitelinks Column 4: Ecosystem */}
          <div className="space-y-3">
            <div className="font-mono text-[11px] uppercase tracking-wider text-white font-semibold">
              Ecosystem
            </div>
            <ul className="space-y-2 text-xs">
              {footerSections.ecosystem.map((item) => (
                <li key={item.label}>
                  {item.href ? (
                    <a
                      href={item.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-text-muted hover:text-white transition-colors duration-150 inline-flex items-center gap-1.5"
                    >
                      {item.label}
                    </a>
                  ) : (
                    <span className="text-text-muted/90 font-normal select-none">
                      {item.label}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>

        </div>

        {/* Bottom Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between pt-8 gap-4 font-mono text-xs text-text-muted">
          <div>
            &copy; {new Date().getFullYear()} Multipu. All rights reserved.
          </div>
          <div className="flex items-center gap-6">
            <a
              href="https://docs.multipu.fun"
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-muted hover:text-white transition-colors"
            >
              Docs
            </a>
            <a
              href="https://github.com/wisdomnova/multipu"
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-muted hover:text-white transition-colors"
            >
              GitHub
            </a>
          </div>
        </div>

      </div>
    </footer>
  );
}
