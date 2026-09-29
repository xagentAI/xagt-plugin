"use client";

import Link from "next/link";
import { motion, fadeUp, stagger, scaleIn } from "@/components/motion";

const launchpads = [
  {
    symbol: "METEORA",
    name: "Dynamic AMM & Multi-Token Liquidity Pools",
    metricLabel: "Active Pools",
    metricValue: "1,420+",
    href: "/launch",
  },
  {
    symbol: "PUMP.FUN",
    name: "Instant Bonding Curve Deployment & Seeding",
    metricLabel: "Graduation Rate",
    metricValue: "98.4%",
    href: "/launch",
  },
  {
    symbol: "PONS",
    name: "Robinhood Chain High-Throughput Launchpad",
    metricLabel: "Block Time",
    metricValue: "0.25s",
    href: "/launch",
  },
  {
    symbol: "FOUR.MEME",
    name: "BNB Smart Chain Low-Gas Memecoin Ecosystem",
    metricLabel: "Tx Finality",
    metricValue: "3.0s",
    href: "/launch",
  },
];

export function ProductList() {
  return (
    <motion.section
      id="launchpads"
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={stagger}
      className="py-16 sm:py-24 md:py-36 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto scroll-mt-24"
    >
      {/* Lilac product list container */}
      <motion.div variants={fadeUp} className="rounded-3xl sm:rounded-[40px] bg-[#aba6d8] text-[#140e28] p-6 sm:p-10 md:p-14 lg:p-20 overflow-hidden">
        {/* Top Eyebrow */}
        <div className="text-xs font-mono uppercase tracking-widest text-[#140e28]/70 mb-3">
          Multipu Protocols
        </div>

        {/* Headline */}
        <h2 className="text-3xl sm:text-5xl lg:text-6xl font-normal tracking-tight text-[#140e28] mb-10 sm:mb-14">
          Explore our launchpads
        </h2>

        {/* List Rows */}
        <motion.div variants={stagger} className="flex flex-col">
          {launchpads.map((pad) => (
            <motion.div
              key={pad.symbol}
              variants={fadeUp}
              className="py-6 sm:py-8 flex flex-col md:flex-row md:items-center justify-between gap-5 sm:gap-6 border-t border-black/10 first:border-t-0 hover:bg-black/5 px-3 sm:px-4 rounded-2xl transition-colors"
            >
              {/* Left Column: Symbol and Full Name */}
              <div className="flex items-start md:items-center gap-3 sm:gap-4">
                <span className="text-sm text-[#140e28]/60 font-mono tracking-tighter select-none mt-1 md:mt-0">
                  ▶▶
                </span>
                <div>
                  <div className="text-2xl sm:text-4xl font-bold tracking-tight font-mono text-[#140e28]">
                    {pad.symbol}
                  </div>
                  <div className="text-xs sm:text-sm text-[#140e28]/80 mt-1">
                    {pad.name}
                  </div>
                </div>
              </div>

              {/* Right Column: Metric and Action Button */}
              <div className="flex items-center justify-between sm:justify-start gap-4 sm:gap-8 md:gap-12 w-full md:w-auto mt-2 md:mt-0">
                <div className="text-left md:text-right">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-[#140e28]/60">
                    {pad.metricLabel}
                  </div>
                  <div className="text-xl sm:text-2xl font-bold font-mono text-[#140e28]">
                    {pad.metricValue}
                  </div>
                </div>

                <Link
                  href={pad.href}
                  className="px-5 sm:px-6 py-2.5 sm:py-3 rounded-none bg-[#140e28] hover:bg-[#221844] text-white text-xs font-mono uppercase tracking-wider transition-colors cursor-pointer"
                >
                  View Details
                </Link>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </motion.div>

      {/* Bottom Dark Banner */}
      <motion.div variants={scaleIn} className="mt-8 rounded-3xl sm:rounded-[40px] bg-[#140e28] text-white p-6 sm:p-10 md:p-14 lg:p-16 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 sm:gap-8 relative overflow-hidden">
        <div>
          <h3 className="text-2xl sm:text-4xl lg:text-5xl font-normal tracking-tight text-white mb-2 sm:mb-3">
            Ready to launch?
          </h3>
          <p className="text-sm text-neutral-400 max-w-md">
            Deploy your token contract across all decentralized liquidity pools in seconds.
          </p>
        </div>

        <div className="flex items-center gap-4 relative z-10 w-full sm:w-auto">
          <Link
            href="/launch"
            className="w-full sm:w-auto text-center px-8 py-3.5 rounded-full bg-white text-[#140e28] font-semibold text-xs font-mono uppercase tracking-wider hover:bg-neutral-200 transition-colors cursor-pointer hover:scale-105 active:scale-95 duration-200"
          >
            Launch Token
          </Link>
        </div>

        {/* Abstract Low-Poly Angular Triangles SVG */}
        <div className="absolute right-0 top-0 bottom-0 w-80 pointer-events-none opacity-20 hidden md:block">
          <svg viewBox="0 0 300 200" className="w-full h-full fill-white">
            <polygon points="100,0 200,100 150,200" />
            <polygon points="200,0 300,100 250,200" />
            <polygon points="150,200 300,200 250,100" />
          </svg>
        </div>
      </motion.div>
    </motion.section>
  );
}
