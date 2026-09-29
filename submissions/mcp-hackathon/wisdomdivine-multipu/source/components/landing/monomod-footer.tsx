"use client";

import Link from "next/link";
import Image from "next/image";
import { motion, fadeUp, stagger } from "@/components/motion";

export function MonomodFooter() {
  return (
    <motion.footer
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-60px" }}
      variants={stagger}
      className="pt-16 sm:pt-24 pb-12 sm:pb-16 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto"
    >
      {/* Top Banner / Prompt */}
      <motion.div variants={fadeUp} className="mb-6">
        <p className="text-xs font-mono text-neutral-400 uppercase tracking-widest mb-3 sm:mb-4">
          Deploy instantly with zero lockup. Pay only network gas when you launch.
        </p>

        {/* Wide Action Bar */}
        <Link
          href="/launch"
          className="w-full rounded-2xl bg-neutral-900/90 hover:bg-neutral-800 text-white p-5 sm:p-8 flex items-center justify-between group transition-colors cursor-pointer border border-white/[0.04]"
        >
          <span className="text-xl sm:text-3xl md:text-4xl font-normal tracking-tight text-white">
            Get started today
          </span>
          <span className="text-xl sm:text-3xl text-white group-hover:translate-x-2 transition-transform">
            →
          </span>
        </Link>
      </motion.div>

      {/* Large Rounded Container */}
      <motion.div variants={fadeUp} className="rounded-3xl bg-neutral-950 p-6 sm:p-10 lg:p-16 mb-8 border border-white/[0.04]">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 sm:gap-12 lg:gap-8">
          {/* Left: Multipu Logo & Wordmark */}
          <div className="lg:col-span-5 flex flex-col justify-between">
            <div>
              <Link href="/" className="inline-flex items-center gap-3 sm:gap-4 group mb-4">
                <div className="relative w-10 h-10 sm:w-12 sm:h-12 flex-shrink-0">
                  <Image
                    src="/logo.png"
                    alt="Multipu Logo"
                    fill
                    sizes="48px"
                    className="object-contain"
                  />
                </div>
                <span className="text-2xl sm:text-4xl font-bold tracking-tighter text-white font-mono uppercase">
                  MULTIPU
                </span>
              </Link>
              <p className="text-xs text-neutral-400 max-w-xs leading-relaxed font-mono mt-2">
                Decentralized multi-chain token launchpad, liquidity router, and algorithmic DEX terminal.
              </p>
            </div>

            <div className="mt-6 sm:mt-8 flex items-center gap-2 text-xs font-mono text-neutral-500">
              <span>Solana, BNB, Robinhood live</span>
            </div>
          </div>

          {/* Right: 4 Directory Columns */}
          <div className="lg:col-span-7 grid grid-cols-2 sm:grid-cols-4 gap-8">
            {/* Column 1 */}
            <div>
              <div className="text-xs font-mono font-semibold uppercase tracking-wider text-white mb-4">
                Navigation
              </div>
              <div className="flex flex-col gap-3 font-mono text-xs text-neutral-400">
                <Link href="/launch" className="hover:text-white transition-colors">
                  LAUNCHPAD
                </Link>
                <Link href="/dashboard/explore" className="hover:text-white transition-colors">
                  EXPLORE
                </Link>
                <Link href="/dashboard" className="hover:text-white transition-colors">
                  TERMINAL
                </Link>
                <Link href="/dashboard/earnings" className="hover:text-white transition-colors">
                  EARNINGS
                </Link>
              </div>
            </div>

            {/* Column 2 */}
            <div>
              <div className="text-xs font-mono font-semibold uppercase tracking-wider text-white mb-4">
                Launchpads
              </div>
              <div className="flex flex-col gap-3 font-mono text-xs text-neutral-400">
                <Link href="/launch" className="hover:text-white transition-colors">
                  METEORA
                </Link>
                <Link href="/launch" className="hover:text-white transition-colors">
                  PUMP.FUN
                </Link>
                <Link href="/launch" className="hover:text-white transition-colors">
                  PONS
                </Link>
                <Link href="/launch" className="hover:text-white transition-colors">
                  FOUR.MEME
                </Link>
              </div>
            </div>

            {/* Column 3 */}
            <div>
              <div className="text-xs font-mono font-semibold uppercase tracking-wider text-white mb-4">
                Resources
              </div>
              <div className="flex flex-col gap-3 font-mono text-xs text-neutral-400">
                <Link href="/dashboard/api" className="hover:text-white transition-colors">
                  API KEYS
                </Link>
                <Link href="/dashboard" className="hover:text-white transition-colors">
                  X-AGENT
                </Link>
                <Link href="/dashboard" className="hover:text-white transition-colors">
                  OLAXBT
                </Link>
                <a
                  href="https://github.com/wisdomnova/multipu"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  GITHUB
                </a>
              </div>
            </div>

            {/* Column 4 */}
            <div>
              <div className="text-xs font-mono font-semibold uppercase tracking-wider text-white mb-4">
                Community
              </div>
              <div className="flex flex-col gap-3 font-mono text-xs text-neutral-400">
                <a
                  href="https://x.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  @MULTIPU_FUN
                </a>
                <a
                  href="https://t.me"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  TELEGRAM
                </a>
                <Link href="/dashboard" className="hover:text-white transition-colors">
                  DISCORD
                </Link>
              </div>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Bottom Copyright & Disclaimer */}
      <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-mono text-neutral-600">
        <div>(c) 2026 Multipu Protocol. Powered by X-Agent &amp; OlaXBT.</div>
        <div className="text-neutral-500">
          Crafted for decentralized traders and creators.
        </div>
      </motion.div>
    </motion.footer>
  );
}
