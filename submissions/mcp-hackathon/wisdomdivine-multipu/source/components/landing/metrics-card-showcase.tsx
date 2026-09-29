"use client";

import Link from "next/link";
import { motion, fadeUp, stagger, scaleIn } from "@/components/motion";

export function MetricsCardShowcase() {
  return (
    <motion.section
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={stagger}
      className="py-16 sm:py-24 md:py-36 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto"
    >
      {/* Top Floating Pill Navigation */}
      <motion.div variants={fadeUp} className="flex justify-center mb-10 sm:mb-12">
        <div className="inline-flex items-center gap-4 sm:gap-6 px-5 sm:px-6 py-2 rounded-full bg-neutral-900 text-neutral-300 text-xs font-mono border border-white/[0.06]">
          <span className="text-neutral-500 font-bold">≡</span>
          <span className="font-semibold text-white tracking-wider uppercase">MULTIPU</span>
          <Link
            href="/dashboard/explore"
            className="flex items-center gap-1.5 text-accent hover:text-white transition-colors"
          >
            <span>↗</span>
            <span>Signals</span>
          </Link>
        </div>
      </motion.div>

      {/* Two Side-by-Side Cards */}
      <motion.div variants={stagger} className="grid grid-cols-1 lg:grid-cols-12 gap-6 md:gap-8">
        {/* Left Card: Deep Dark Plum Metrics Card */}
        <motion.div variants={scaleIn} className="lg:col-span-7 rounded-3xl sm:rounded-[36px] bg-[#120b18] p-6 sm:p-10 lg:p-14 flex flex-col justify-between min-h-0 lg:min-h-[400px] border border-white/[0.04]">
          <div>
            {/* Top platform tag */}
            <div className="flex items-center gap-2 mb-8 sm:mb-12">
              <span className="w-2.5 h-2.5 rounded-xs bg-purple-500 flex-shrink-0" />
              <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                THE MULTIPU PLATFORM
              </span>
            </div>

            {/* Split Metrics */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 sm:gap-8">
              <div>
                <div className="text-xs font-mono text-neutral-400 mb-2">
                  Launchpad Cost Reduction*
                </div>
                <div className="text-5xl sm:text-6xl lg:text-7xl font-bold font-mono text-[#c4c1f0] tracking-tight">
                  33%
                </div>
              </div>

              <div>
                <div className="text-xs font-mono text-neutral-400 mb-2">
                  Time to Multi-Deploy (seconds)*
                </div>
                <div className="text-5xl sm:text-6xl lg:text-7xl font-bold font-mono text-white tracking-tight">
                  &lt;1s
                </div>
              </div>
            </div>
          </div>

          <div className="text-[11px] font-mono text-neutral-600 mt-8 sm:mt-10">
            *Simultaneous cross-chain routing on Solana, BNB Chain, and Robinhood Chain.
          </div>
        </motion.div>

        {/* Right Card: Soft Lavender Card */}
        <motion.div variants={scaleIn} className="lg:col-span-5 rounded-3xl sm:rounded-[36px] bg-[#b6b3e8] text-[#120b18] p-6 sm:p-10 lg:p-14 flex flex-col justify-between min-h-0 lg:min-h-[400px]">
          <div>
            <h3 className="text-2xl sm:text-4xl font-normal tracking-tight text-[#120b18] leading-[1.15] mb-4">
              Accelerating Liquidity in Decentralized Finance
            </h3>

            <p className="text-sm text-[#120b18]/80 leading-relaxed max-w-sm">
              We deploy across Solana, BNB Smart Chain, and Robinhood Chain powered by X-Agent autonomous execution and OlaXBT strategy intelligence.
            </p>
          </div>

          <div className="pt-6 sm:pt-8">
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-3 px-5 py-3 rounded-xl bg-[#120b18] text-white hover:bg-[#20152a] text-xs font-mono transition-colors cursor-pointer hover:scale-105 active:scale-95 duration-200"
            >
              <span className="w-5 h-5 rounded-sm bg-white/10 flex items-center justify-center text-xs">
                ↗
              </span>
              <span>View Strategies</span>
            </Link>
          </div>
        </motion.div>
      </motion.div>
    </motion.section>
  );
}
