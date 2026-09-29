"use client";

import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";

const featureGroups = [
  {
    label: "Token Deploy",
    title: "One-Click Token Creation",
    description: "Deploy your SPL or EVM token with custom name, symbol, supply, and metadata. No CLI needed.",
    link: "EXPLORE TOKENROOM >"
  },
  {
    label: "Multi-Launch",
    title: "Multi-Launchpad Push",
    description: "Select Meteora, Bags, Pump.fun, Four.meme or Pons. Auto-fill details and launch simultaneously.",
    link: "EXPLORE POLARIS >"
  },
  {
    label: "Meme Swaps",
    title: "Instant Meme Swapping",
    description: "Manually trade any live token on Solana and BSC directly with client wallets, featuring minimal price chart feeds.",
    link: "EXPLORE EXPLORER >"
  },
  {
    label: "Earnings & Security",
    title: "Revenue & Wallet Auth",
    description: "Track creator fees, protocol earnings, and secure wallet-native login with zero password requirements.",
    items: [
      { label: "LIVE DEPLOYMENT STATUS >" },
      { label: "FAST SWAP EXECUTION >" },
      { label: "REAL-TIME MONITORING >" }
    ]
  }
];

export function Features() {
  return (
    <section id="features" className="relative py-24 md:py-32 border-t border-white/[0.05]">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-100px" }}
          variants={stagger}
          className="mb-20"
        >
          <motion.span
            variants={fadeUp}
            className="font-mono text-xs text-accent uppercase tracking-widest"
          >
            Features
          </motion.span>
          <motion.h2
            variants={fadeUp}
            className="mt-4 text-[clamp(1.75rem,4vw,3rem)] font-bold tracking-tight text-white mb-2"
          >
            Everything you need to launch
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-text-secondary max-w-xl text-lg font-light leading-relaxed"
          >
            From token creation to multi-platform distribution - all from one
            dashboard.
          </motion.p>
        </motion.div>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-50px" }}
          variants={stagger}
          className="grid grid-cols-1 md:grid-cols-4 border-l border-white/10"
        >
          {featureGroups.map((group, idx) => (group.items ? (
            <motion.div
              key={idx}
              variants={fadeUp}
              className="px-8 py-12 border-r border-white/10 flex flex-col min-h-[460px] bg-white/[0.01] hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex-1">
                <h3 className="text-3xl font-normal text-white mb-6 leading-snug tracking-tight">
                  {group.label}
                </h3>
                <p className="text-text-secondary text-[15px] leading-relaxed mb-10 pr-4 font-light opacity-80">
                  {group.description}
                </p>
                <div className="h-px w-full bg-white/10 mb-10" />
              </div>
              
              <div className="flex flex-col gap-4">
                {group.items.map((item, i) => (
                  <button 
                    key={i} 
                    className="text-left font-mono text-[10px] tracking-[0.25em] text-white/60 hover:text-accent transition-colors uppercase whitespace-nowrap"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key={idx}
              variants={fadeUp}
              className="px-8 py-12 border-r border-white/10 flex flex-col min-h-[460px] bg-white/[0.01] hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex-1">
                <div className="flex justify-between items-start mb-6">
                  <h3 className="text-3xl font-normal text-white leading-snug tracking-tight">
                    {group.label}
                  </h3>
                  <div className="w-10 h-10 border border-white/10 rounded-sm relative flex items-center justify-center scale-90 opacity-40">
                    {idx === 0 && <div className="absolute inset-1 border border-white/10" />}
                    {idx === 1 && <div className="w-4 h-4 bg-white/5 rounded-full border border-white/20" />}
                    {idx === 2 && <div className="w-6 h-3 border border-white/20 rotate-45" />}
                  </div>
                </div>
                
                <p className="text-text-secondary text-[15px] leading-relaxed mb-10 pr-4 font-light opacity-80">
                  {group.description}
                </p>
                <div className="h-px w-full bg-white/10 mb-10" />
              </div>

              <button className="text-left font-mono text-[10px] tracking-[0.25em] text-white/60 hover:text-accent transition-colors uppercase">
                {group.link || `EXPLORE ${group.label.split(' ')[0]} >`}
              </button>
            </motion.div>
          )))}
        </motion.div>
      </div>
    </section>
  );
}
