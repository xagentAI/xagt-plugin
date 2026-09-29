"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";

export function TerminalShowcase() {
  return (
    <section className="relative py-28 md:py-36 border-t border-white/[0.06] bg-black">
      <div className="mx-auto max-w-[1340px] px-6 md:px-10">
        
        {/* Section Header */}
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={stagger}
          className="max-w-3xl mb-20"
        >
          <motion.div variants={fadeUp} className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-white/[0.03] border border-white/[0.08] mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            <span className="font-mono text-[11px] uppercase tracking-widest text-text-secondary">
              Trading Terminal
            </span>
          </motion.div>
          <motion.h2
            variants={fadeUp}
            className="text-[clamp(2.2rem,5vw,3.75rem)] font-bold tracking-tight text-white leading-[1.08] mb-6"
          >
            Real-time DEX exploration.<br />Built for execution speed.
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-base md:text-lg text-text-secondary leading-relaxed font-normal max-w-2xl"
          >
            Monitor live bonding curves, on-chain holder distribution, and multi-chain liquidity pools across Solana, BNB Chain, and Robinhood with zero latency.
          </motion.p>
        </motion.div>

        {/* Bento Grid Visual Cards (Offsuit / Linear Style) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          
          {/* Card 1: Interactive Curve Progress & Visual Sparkline (8 Cols) */}
          <div className="lg:col-span-8 bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-10 flex flex-col justify-between relative overflow-hidden">
            <div>
              <div className="flex items-center justify-between pb-5 border-b border-white/[0.06] mb-8">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs uppercase tracking-wider text-text-dim">
                    Market Velocity
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono text-[10px] uppercase font-semibold">
                    Live Stream
                  </span>
                </div>
                <span className="font-mono text-xs text-text-dim">
                  Solana / BSC / Robinhood
                </span>
              </div>

              <div className="flex flex-col md:flex-row items-start md:items-end justify-between gap-6 mb-8">
                <div>
                  <div className="text-4xl md:text-5xl font-bold font-mono tracking-tight text-white mb-2">
                    86.4%
                  </div>
                  <div className="text-sm font-mono text-text-secondary">
                    Bonding Curve Completion Velocity
                  </div>
                </div>
                <div className="flex items-center gap-3 font-mono text-xs text-text-muted">
                  <span className="px-3 py-1.5 rounded bg-white/[0.03] border border-white/[0.06] text-white font-medium">
                    Final Stretch
                  </span>
                  <span className="px-3 py-1.5 rounded bg-white/[0.03] border border-white/[0.06]">
                    Migrated Pools
                  </span>
                  <span className="px-3 py-1.5 rounded bg-white/[0.03] border border-white/[0.06]">
                    New Pairs
                  </span>
                </div>
              </div>

              {/* Realistic SVG Curve Graph / Sparkline */}
              <div className="w-full bg-black/60 border border-white/[0.06] rounded-xl p-5 mb-8">
                <div className="flex justify-between items-center text-[10px] font-mono text-text-dim mb-3">
                  <span>CURVE LIQUIDITY TRAJECTORY</span>
                  <span className="text-emerald-400">+144.2% INFLOW</span>
                </div>
                <div className="w-full h-28 relative flex items-end">
                  <svg className="w-full h-full overflow-visible" viewBox="0 0 500 100" preserveAspectRatio="none">
                    <defs>
                      <linearGradient id="curveGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.3" />
                        <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.0" />
                      </linearGradient>
                    </defs>
                    <path
                      d="M 0 80 Q 70 75, 120 60 T 220 55 T 320 30 T 420 20 T 500 8 L 500 100 L 0 100 Z"
                      fill="url(#curveGrad)"
                    />
                    <path
                      d="M 0 80 Q 70 75, 120 60 T 220 55 T 320 30 T 420 20 T 500 8"
                      fill="none"
                      stroke="#8b5cf6"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <div className="flex justify-between text-[10px] font-mono text-text-dim mt-2 pt-2 border-t border-white/[0.04]">
                  <span>Pool Creation</span>
                  <span>50% Reserve</span>
                  <span>Raydium / DEX Migration</span>
                </div>
              </div>

              {/* Live Token Row Mockup */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs">
                <div className="p-3.5 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-white font-semibold">$Doggo</span>
                    <span className="text-accent">86% Curve</span>
                  </div>
                  <div className="text-[10px] text-text-dim">MC: $14.5K | Vol: $51.7K</div>
                </div>
                <div className="p-3.5 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-white font-semibold">$GPU</span>
                    <span className="text-emerald-400">100% Migrated</span>
                  </div>
                  <div className="text-[10px] text-text-dim">MC: $24.9K | Vol: $612K</div>
                </div>
                <div className="p-3.5 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-white font-semibold">$RKST</span>
                    <span className="text-white">Robinhood DEX</span>
                  </div>
                  <div className="text-[10px] text-text-dim">MC: $8.05M | Vol: $4.3M</div>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-8 border-t border-white/[0.06] flex items-center justify-between">
              <span className="font-mono text-xs text-text-dim">
                Multi-Column Directory Explorer
              </span>
              <Link
                href="/dashboard/explore"
                className="font-mono text-xs text-accent hover:text-accent-hover transition-colors uppercase font-medium"
              >
                Launch Terminal &gt;
              </Link>
            </div>
          </div>

          {/* Card 2: Holder Risk & Distribution Telemetry (4 Cols) */}
          <div className="lg:col-span-4 bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-10 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-5 border-b border-white/[0.06] mb-8">
                <span className="font-mono text-xs uppercase tracking-wider text-text-dim">
                  Risk Telemetry
                </span>
                <span className="font-mono text-[10px] text-text-muted uppercase">
                  On-Chain Verified
                </span>
              </div>

              <div className="text-3xl font-bold font-mono tracking-tight text-white mb-2">
                0.4%
              </div>
              <div className="text-xs font-mono text-text-secondary mb-6">
                Developer Wallet Allocation Index
              </div>

              <p className="text-xs text-text-secondary mb-6 leading-relaxed">
                Automated telemetry inspects top 10 wallet concentration, developer holdings, and early sniper percentages before entry.
              </p>

              {/* Distribution Gauges */}
              <div className="space-y-4 font-mono text-xs">
                <div className="p-4 bg-black/60 border border-white/[0.06] rounded-xl space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Top 10 Concentration</span>
                    <span className="text-white font-semibold">15%</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                    <div className="h-full bg-accent rounded-full" style={{ width: "15%" }} />
                  </div>
                </div>

                <div className="p-4 bg-black/60 border border-white/[0.06] rounded-xl space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Dev Holding Share</span>
                    <span className="text-emerald-400 font-semibold">0.4%</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full" style={{ width: "4%" }} />
                  </div>
                </div>

                <div className="p-4 bg-black/60 border border-white/[0.06] rounded-xl space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Sniper Detected Volume</span>
                    <span className="text-text-primary font-semibold">5%</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                    <div className="h-full bg-amber-400 rounded-full" style={{ width: "10%" }} />
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-8 border-t border-white/[0.06]">
              <span className="font-mono text-xs text-text-dim block">
                Non-Custodial Client Verification
              </span>
            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
