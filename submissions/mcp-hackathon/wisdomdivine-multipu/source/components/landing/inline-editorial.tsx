"use client";

import Link from "next/link";
import { motion, fadeUp, stagger, scaleIn } from "@/components/motion";

export function InlineEditorial() {
  return (
    <motion.section
      id="editorial"
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={stagger}
      className="relative py-16 sm:py-24 md:py-36 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto overflow-hidden"
    >
      {/* Perfectly Balanced Dot Matrix Background Pattern */}
      <div className="absolute inset-0 bg-[radial-gradient(rgba(255,255,255,0.18)_1.1px,transparent_1.1px)] [background-size:22px_22px] pointer-events-none opacity-40 [mask-image:radial-gradient(ellipse_at_center,black_80%,transparent_100%)] z-0" />
      {/* Top Tag */}
      <motion.div variants={fadeUp} className="flex items-center gap-3 mb-8 sm:mb-10">
        <span className="font-mono text-xs text-neutral-500">01</span>
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-neutral-900 text-neutral-300 text-xs font-mono">
          <span>About</span>
          <span className="text-orange-500 font-bold">✱</span>
          <span>Multipu</span>
        </div>
      </motion.div>

      {/* Running Headline with Inline Editorial Pills & SVGs */}
      <motion.div variants={fadeUp} className="mb-14 sm:mb-20 md:mb-28 max-w-5xl">
        <h2 className="text-2xl sm:text-4xl md:text-5xl lg:text-6xl font-normal tracking-tight text-white leading-[1.3] md:leading-[1.25] break-words">
          Our protocol{" "}
          <span className="inline-flex items-center justify-center align-middle w-7 h-7 sm:w-10 sm:h-10 rounded-xl bg-orange-600 text-white font-bold text-base sm:text-lg mx-1 sm:mx-1.5 flex-shrink-0">
            +
          </span>{" "}
          has been deploying{" "}
          <span className="inline-flex items-center justify-center align-middle w-6 h-6 sm:w-8 sm:h-8 text-white mx-1 flex-shrink-0">
            {/* Lightning bolt SVG */}
            <svg viewBox="0 0 24 24" className="w-full h-full fill-current">
              <path d="M13 2L3 14h8l-2 8 10-12h-8l2-8z" />
            </svg>
          </span>{" "}
          simultaneous multi-pad liquidity for{" "}
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 sm:px-4 sm:py-1.5 rounded-xl bg-orange-600 text-white text-xs sm:text-base font-semibold align-middle mx-1 flex-shrink-0">
            <span>✱</span>
            <span>Multipu</span>
          </span>{" "}
          6 ecosystems. A platform of 100K+{" "}
          <span className="inline-flex items-center justify-center align-middle w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-white mx-1 text-black text-[10px] font-bold flex-shrink-0">
            ●
          </span>{" "}
          creators.
        </h2>
      </motion.div>

      {/* 3-Card Showcase */}
      <motion.div variants={stagger} className="grid grid-cols-1 md:grid-cols-3 gap-6 sm:gap-8 md:gap-10">
        {/* Card 1: Constant monitoring */}
        <motion.div variants={scaleIn} className="flex flex-col">
          <div className="w-full h-72 sm:h-80 rounded-3xl bg-[#14201c] p-6 sm:p-8 flex flex-col items-center justify-between relative overflow-hidden group hover:bg-[#182823] transition-colors">
            {/* Concentric radar circles & Asterisk Star */}
            <div className="relative w-36 h-36 sm:w-40 sm:h-40 flex items-center justify-center mt-2">
              <div className="absolute w-36 h-36 rounded-full bg-white/[0.03]" />
              <div className="absolute w-24 h-24 rounded-full bg-white/[0.05]" />
              {/* 8-spoke Asterisk Star */}
              <div className="text-4xl font-bold text-orange-500 select-none group-hover:scale-110 transition-transform">
                ✱
              </div>
            </div>

            {/* Split capsule pill labels */}
            <div className="flex items-center w-full max-w-[240px] rounded-full overflow-hidden bg-neutral-900/90 text-xs font-mono">
              <div className="flex-1 py-2 px-3 text-center bg-orange-600 text-white font-medium">
                Solana
              </div>
              <div className="flex-1 py-2 px-3 text-center text-neutral-300">
                Robinhood
              </div>
            </div>
          </div>

          <div className="mt-6">
            <h3 className="text-xl font-bold text-white mb-2">
              Constant monitoring
            </h3>
            <p className="text-sm text-neutral-400 leading-relaxed">
              Track bonding curves, DEX liquidity pools, and creator earnings across all venues in real time.
            </p>
          </div>
        </motion.div>

        {/* Card 2: AI-based execution */}
        <motion.div variants={scaleIn} className="flex flex-col">
          {/* Top Pill Action */}
          <Link
            href="/dashboard"
            className="w-full py-4 px-6 rounded-2xl bg-orange-600 hover:bg-orange-700 text-white flex items-center justify-between font-mono text-xs font-bold tracking-wider uppercase mb-3 transition-colors cursor-pointer group"
          >
            <span>LAUNCH ENGINE</span>
            <span className="w-6 h-6 rounded-full bg-black flex items-center justify-center text-white text-xs group-hover:translate-x-1 transition-transform">
              →
            </span>
          </Link>

          <div className="w-full h-[260px] rounded-3xl bg-[#14201c] p-6 flex flex-col items-center justify-center relative overflow-hidden group hover:bg-[#182823] transition-colors">
            {/* Avatar with Detective Hat illustration & Asterisk */}
            <div className="relative flex flex-col items-center justify-center mb-4">
              {/* Minimalist Hat SVG */}
              <svg viewBox="0 0 80 40" className="w-20 h-10 fill-neutral-400 mb-[-6px] z-10">
                <path d="M25,25 Q40,5 55,25 L75,28 Q78,30 75,32 L5,32 Q2,30 5,28 Z" />
              </svg>
              {/* Avatar circle with Asterisk */}
              <div className="w-16 h-16 rounded-full bg-white/10 flex items-center justify-center">
                <span className="text-2xl font-bold text-orange-500 group-hover:rotate-45 transition-transform duration-300">✱</span>
              </div>
            </div>

            {/* Powered by X-Agent tag */}
            <div className="px-4 py-1.5 rounded-full bg-white/5 text-orange-400 font-mono text-xs font-semibold">
              Powered by X-Agent
            </div>
          </div>

          <div className="mt-6">
            <h3 className="text-xl font-bold text-white mb-2">
              Autonomous X-Agent execution
            </h3>
            <p className="text-sm text-neutral-400 leading-relaxed">
              Powered by the X-Agent autonomous framework and OlaXBT market momentum signals to detect volume surges and execute optimal bonding curve arbitrage.
            </p>
          </div>
        </motion.div>

        {/* Card 3: Automatic triage */}
        <motion.div variants={scaleIn} className="flex flex-col">
          <div className="w-full h-80 rounded-3xl bg-[#14201c] p-8 flex flex-col items-center justify-between relative overflow-hidden group hover:bg-[#182823] transition-colors">
            {/* Rotating circular SVG text surrounding the Asterisk Star */}
            <div className="relative w-36 h-36 flex items-center justify-center mt-2">
              <svg viewBox="0 0 100 100" className="w-full h-full animate-spin-slow">
                <path
                  id="circularPath"
                  d="M 50, 50 m -36, 0 a 36,36 0 1,1 72,0 a 36,36 0 1,1 -72,0"
                  fill="none"
                />
                <text className="text-[7.5px] font-mono uppercase tracking-[2px] fill-neutral-400">
                  <textPath href="#circularPath">
                    Cross-Chain Routing Cross-Chain Routing
                  </textPath>
                </text>
              </svg>
              <div className="absolute text-2xl font-bold text-orange-500">
                ✱
              </div>
            </div>

            {/* Floating pill capsules */}
            <div className="flex flex-wrap gap-2 justify-center w-full">
              <span className="px-3 py-1 rounded-full bg-white/10 text-neutral-300 font-mono text-[11px]">
                Meteora
              </span>
              <span className="px-3 py-1 rounded-full bg-white/10 text-neutral-300 font-mono text-[11px]">
                Pump.fun
              </span>
              <span className="px-3 py-1 rounded-full bg-white/10 text-neutral-300 font-mono text-[11px]">
                Pons
              </span>
            </div>
          </div>

          <div className="mt-6">
            <h3 className="text-xl font-bold text-white mb-2">
              Automatic triage
            </h3>
            <p className="text-sm text-neutral-400 leading-relaxed">
              Neutralize launch friction and seed pool liquidity without human intervention.
            </p>
          </div>
        </motion.div>
      </motion.div>
    </motion.section>
  );
}
