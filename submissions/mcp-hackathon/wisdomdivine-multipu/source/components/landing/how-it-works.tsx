"use client";

import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";

const steps = [
  {
    id: "01",
    title: "Link Wallet & Authenticate",
    description: "Connect your Solana or EVM wallet via our secure directory. Authenticate with Google or X to bridge your cross-chain assets into a unified launch environment.",
  },
  {
    id: "02",
    title: "Define Token Parameters",
    description: "Specify supply, liquidity locks, and distribution logic. Our engine validates against the target launchpad's policy constraints in real-time.",
  },
  {
    id: "03",
    title: "Execute Multi-Launch",
    description: "Deploy to Meteora, Bags, or Pump.fun with a single transaction. The protocol handles the complex routing and pool initialization automatically.",
  },
  {
    id: "04",
    title: "Monitor Distribution",
    description: "Track performance across all venues from a central dashboard. Manage creator fees, liquidity health, and secondary market growth metrics.",
  },
];

export function HowItWorks() {
  return (
    <section id="process" className="relative py-24 md:py-32 border-t border-white/[0.05]">
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
            Workflow
          </motion.span>
          <motion.h2 
            variants={fadeUp}
            className="mt-4 text-[clamp(1.75rem,4vw,3rem)] font-bold tracking-tight text-white mb-2"
          >
            The Launch Lifecycle
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-text-secondary max-w-xl text-lg font-light leading-relaxed"
          >
            A streamlined directory for deploying and managing liquid assets.
          </motion.p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-0 border-l border-white/10">
          {steps.map((step, idx) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: idx * 0.1 }}
              className="group p-8 md:p-12 border-r border-t lg:border-t-0 border-white/10 hover:bg-white/[0.01] transition-all flex flex-col justify-between min-h-[400px]"
            >
              <div>
                <div className="text-4xl font-serif text-white/10 group-hover:text-accent/20 transition-colors duration-500 mb-12">
                  {step.id}
                </div>
                <h3 className="text-xl font-normal text-white mb-6 leading-snug tracking-tight group-hover:text-accent transition-colors">
                  {step.title}
                </h3>
                <p className="text-text-secondary text-[15px] leading-relaxed font-light opacity-80 decoration-white/0">
                  {step.description}
                </p>
              </div>
              
              <div className="mt-12 h-[1px] w-8 bg-white/20 group-hover:w-full group-hover:bg-accent/40 transition-all duration-700" />
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
