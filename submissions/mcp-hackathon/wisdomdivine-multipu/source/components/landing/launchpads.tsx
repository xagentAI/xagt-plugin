"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import { useEffect, useState } from "react";

const launchpads = [
  {
    name: "Meteora",
    chain: "Solana",
    description: "Solana's premier liquidity layer. Dynamic pools, DLMM, and capital-efficient token launches.",
    status: "Supported",
    image: "/meteora.png",
    features: [
      "Dynamic liquidity pools",
      "DLMM integration",
      "Creator fee tracking",
      "Auto-fill token details",
    ],
  },
  {
    name: "Bags",
    chain: "Solana",
    description: "Community-driven degen launchpad. Fast launches, meme-friendly, and built for the culture.",
    status: "Supported",
    image: "/bags.png",
    features: [
      "Quick launch setup",
      "Meme-token optimized",
      "Community features",
      "Creator earnings dashboard",
    ],
  },
  {
    name: "Pump.fun",
    chain: "Solana",
    description: "The viral token launcher. Dead-simple bonding curves, instant tradability, and massive reach.",
    status: "Supported",
    image: "/pumpfun.png",
    features: [
      "Bonding curve launches",
      "Instant tradability",
      "Viral distribution",
      "Low barrier to entry",
    ],
  },
  {
    name: "Four.meme",
    chain: "BSC",
    description: "BNB Smart Chain meme launchpad with live wallet-based execution and policy controls.",
    status: "Supported",
    image: "/four-meme.png",
    features: [
      "BNB Chain target",
      "Launchpad policy controls",
      "Schema + analytics mapping",
      "ABI-verified launch execution",
    ],
  },
  {
    name: "Pons",
    chain: "Robinhood Chain",
    description: "Robinhood Chain L2 meme launchpad featuring time-prioritized sequencing and 24/7 liquidity trading.",
    status: "Supported",
    image: "/pons.png",
    features: [
      "Robinhood Chain target",
      "Arbitrum Orbit stack speed",
      "Time-prioritized sequencing",
      "24/7 liquidity trading",
    ],
  },
];

export function Launchpads() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <section id="launchpads" className="relative py-24 md:py-32 border-t border-white/[0.05] overflow-hidden">
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
            Integrations
          </motion.span>
          <motion.h2
            variants={fadeUp}
            className="mt-4 text-[clamp(1.75rem,4vw,3rem)] font-bold tracking-tight text-white mb-2"
          >
            Supported Launchpads
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-text-secondary max-w-xl text-lg font-light leading-relaxed"
          >
            Multi-launchpad control plane with staged integrations.
          </motion.p>
        </motion.div>
      </div>

      <div className="relative">
        <div className="flex overflow-x-auto no-scrollbar pb-10 px-4 sm:px-6 md:px-10 gap-0 border-l border-white/10 mx-auto max-w-[1400px]">
          {launchpads.map((pad, idx) => (
            <motion.div
              key={pad.name}
              initial={{ opacity: 0, x: 20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: idx * 0.1 }}
              className="flex-shrink-0 w-[280px] sm:w-[320px] md:w-[380px] px-6 sm:px-8 py-10 sm:py-12 border-r border-white/10 flex flex-col min-h-[560px] sm:min-h-[600px] bg-white/[0.01] hover:bg-white/[0.02] transition-colors group"
            >
              <div className="flex-1">
                <div className="relative w-full h-32 mb-8 overflow-hidden rounded-xl border border-white/5 bg-white/[0.02]">
                  {mounted && (
                    <Image
                      src={pad.image}
                      alt={pad.name}
                      fill
                      className="object-cover opacity-60 group-hover:opacity-100 transition-opacity duration-500"
                    />
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-[#0a0a0a] to-transparent opacity-80" />
                </div>

                <div className="flex justify-between items-start mb-6">
                  <div>
                    <span className="font-mono text-[10px] tracking-[0.2em] text-accent uppercase block mb-1">
                      {pad.chain}
                    </span>
                    <h3 className="text-3xl font-normal text-white leading-snug tracking-tight">
                      {pad.name}
                    </h3>
                  </div>
                  <div className="px-2 py-1 border border-white/10 rounded-sm">
                    <span className="font-mono text-[9px] tracking-widest text-white/40 uppercase">
                      {pad.status}
                    </span>
                  </div>
                </div>
                
                <p className="text-text-secondary text-[15px] leading-relaxed mb-10 font-light opacity-80 h-20 overflow-hidden line-clamp-3">
                  {pad.description}
                </p>
                
                <div className="h-px w-full bg-white/10 mb-8" />
                
                <ul className="space-y-3">
                  {pad.features.map((feature, fIdx) => (
                    <li key={fIdx} className="flex items-start gap-3 group/item text-[13px] text-text-secondary font-light">
                      <span className="text-accent/60 mt-0.5 text-xs">▸</span>
                      <span className="group-hover/item:text-white transition-colors">
                        {feature}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-12">
                <button className="text-left font-mono text-[10px] tracking-[0.25em] text-white/60 hover:text-accent transition-colors uppercase">
                  VIEW INTEGRATION {" >"}
                </button>
              </div>
            </motion.div>
          ))}
          
          <div className="flex-shrink-0 w-20 md:w-40 border-r border-white/10" />
        </div>
        
        <div className="absolute inset-y-0 right-0 w-32 bg-gradient-to-l from-[#0a0a0a] to-transparent pointer-events-none" />
      </div>
    </section>
  );
}
