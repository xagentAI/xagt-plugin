"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";

export function StrategyIntelligence() {
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
              Cross-Chain Intelligence
            </span>
          </motion.div>
          <motion.h2
            variants={fadeUp}
            className="text-[clamp(2.2rem,5vw,3.75rem)] font-bold tracking-tight text-white leading-[1.08] mb-6"
          >
            Multi-chain balances.<br />Strategy intelligence.
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-base md:text-lg text-text-secondary leading-relaxed font-normal max-w-2xl"
          >
            Aggregated liquidity monitoring, algorithmic momentum scoring, and unified multi-chain portfolio tracking in a single interface.
          </motion.p>
        </motion.div>

        {/* 3-Card Rich Layout (Carty / Offsuit Style) */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-mono">
          
          {/* Card 1: Multi-Chain Balance Telemetry */}
          <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-9 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-4 border-b border-white/[0.06] mb-6">
                <span className="text-xs uppercase tracking-wider text-text-dim">
                  Live Balances
                </span>
                <span className="text-[10px] text-accent uppercase font-semibold">
                  3 Networks
                </span>
              </div>

              <div className="text-3xl font-bold font-mono tracking-tight text-white mb-2">
                Unified
              </div>
              <div className="text-xs text-text-secondary mb-6 font-normal">
                Header multi-chain balance monitoring
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl flex items-center justify-between">
                  <div>
                    <span className="text-text-dim text-[10px] uppercase block">Solana Network</span>
                    <span className="text-white font-semibold">SOL Gas Reserve</span>
                  </div>
                  <span className="text-accent font-bold">1.42 SOL</span>
                </div>

                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl flex items-center justify-between">
                  <div>
                    <span className="text-text-dim text-[10px] uppercase block">BNB Smart Chain</span>
                    <span className="text-white font-semibold">BNB Gas Reserve</span>
                  </div>
                  <span className="text-accent font-bold">0.85 BNB</span>
                </div>

                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl flex items-center justify-between">
                  <div>
                    <span className="text-text-dim text-[10px] uppercase block">Robinhood Chain</span>
                    <span className="text-white font-semibold">ETH Gas Reserve</span>
                  </div>
                  <span className="text-accent font-bold">0.05 ETH</span>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-6 border-t border-white/[0.06] text-[11px] text-text-dim">
              Synchronized via direct node RPCs
            </div>
          </div>

          {/* Card 2: OlaXBT Nexus Strategy Engine */}
          <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-9 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-4 border-b border-white/[0.06] mb-6">
                <span className="text-xs uppercase tracking-wider text-text-dim">
                  Signal Engine
                </span>
                <span className="text-[10px] text-emerald-400 uppercase font-semibold">
                  OlaXBT Nexus
                </span>
              </div>

              <div className="text-3xl font-bold font-mono tracking-tight text-white mb-2">
                88 / 100
              </div>
              <div className="text-xs text-text-secondary mb-6 font-normal">
                Momentum breakout confidence score
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl space-y-1.5">
                  <div className="flex justify-between text-[10px] text-text-dim">
                    <span>STRATEGY SIGNAL</span>
                    <span className="text-emerald-400 font-semibold">STRONG BUY</span>
                  </div>
                  <div className="text-white font-medium text-xs">
                    Bonding Curve Inflow Sniper
                  </div>
                  <div className="text-[10px] text-text-dim">
                    +144% volume surge in 5m window
                  </div>
                </div>

                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl space-y-1.5">
                  <div className="flex justify-between text-[10px] text-text-dim">
                    <span>ACCUMULATION</span>
                    <span className="text-accent font-semibold">WHALE INFLOW</span>
                  </div>
                  <div className="text-white font-medium text-xs">
                    Liquidity Concentration Shift
                  </div>
                  <div className="text-[10px] text-text-dim">
                    Low dev share and locked LP verified
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-6 border-t border-white/[0.06] text-[11px] text-text-dim">
              Evaluated on bonding curve velocity
            </div>
          </div>

          {/* Card 3: Non-Custodial Web3 Authentication */}
          <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-9 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-4 border-b border-white/[0.06] mb-6">
                <span className="text-xs uppercase tracking-wider text-text-dim">
                  Security
                </span>
                <span className="text-[10px] text-text-muted uppercase font-semibold">
                  Non-Custodial
                </span>
              </div>

              <div className="text-3xl font-bold font-mono tracking-tight text-white mb-2">
                100%
              </div>
              <div className="text-xs text-text-secondary mb-6 font-normal">
                Direct on-chain wallet settlement
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl">
                  <div className="text-text-dim text-[10px] mb-1 uppercase">Solana Sign-In</div>
                  <div className="text-white font-semibold mb-0.5">SIWS Nonce Challenge</div>
                  <div className="text-text-dim text-[10px]">Cryptographic Phantom/Backpack sign</div>
                </div>

                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl">
                  <div className="text-text-dim text-[10px] mb-1 uppercase">Binance / EVM Sign-In</div>
                  <div className="text-white font-semibold mb-0.5">SIWB Direct Auth</div>
                  <div className="text-text-dim text-[10px]">MetaMask &amp; Trust Wallet compatible</div>
                </div>

                <div className="p-3.5 bg-black/60 border border-white/[0.06] rounded-xl">
                  <div className="text-text-dim text-[10px] mb-1 uppercase">Zero Custody</div>
                  <div className="text-white font-semibold mb-0.5">No Platform Deposit Lock</div>
                  <div className="text-text-dim text-[10px]">Funds stay strictly in user wallets</div>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-6 border-t border-white/[0.06] text-[11px] text-text-dim">
              Encrypted iron-session authentication
            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
