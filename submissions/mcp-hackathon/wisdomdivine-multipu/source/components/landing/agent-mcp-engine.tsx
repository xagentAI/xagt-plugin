"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";

export function AgentMcpEngine() {
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
              Agent Infrastructure
            </span>
          </motion.div>
          <motion.h2
            variants={fadeUp}
            className="text-[clamp(2.2rem,5vw,3.75rem)] font-bold tracking-tight text-white leading-[1.08] mb-6"
          >
            Autonomous execution.<br />Native MCP integration.
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="text-base md:text-lg text-text-secondary leading-relaxed font-normal max-w-2xl"
          >
            Connect any AI agent or terminal script directly to live on-chain liquidity via standard Model Context Protocol (v2024-11-05).
          </motion.p>
        </motion.div>

        {/* Linear-Style Agent Command & Workflow Mockup (Full Width) */}
        <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-10 mb-10 overflow-hidden">
          
          {/* Mockup Header Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-white/[0.06] mb-8 font-mono text-xs">
            <div className="flex items-center gap-3">
              <span className="text-text-dim uppercase tracking-wider">MCP Protocol:</span>
              <span className="text-white font-semibold">multipu-mcp (v1.0.0)</span>
            </div>
            <div className="flex items-center gap-4 text-text-dim text-[11px]">
              <span>JSON-RPC stdio</span>
              <span className="w-1 h-1 rounded-full bg-emerald-500" />
              <span className="text-emerald-400">Streamable Connection</span>
            </div>
          </div>

          {/* Interactive Agent Terminal Simulation Slice */}
          <div className="bg-black/70 border border-white/[0.06] rounded-xl p-5 md:p-7 font-mono text-xs space-y-4">
            
            {/* Input Command Line */}
            <div className="flex items-start gap-3 text-text-secondary pb-3 border-b border-white/[0.04]">
              <span className="text-accent font-bold">&gt;</span>
              <span className="text-white font-semibold">
                mcp.execute(action: &quot;multipu_swap_tokens&quot;, launchId: &quot;7f89b1&quot;, mevShield: true)
              </span>
            </div>

            {/* Trace Step 1 */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] p-3 rounded bg-white/[0.02] border border-white/[0.04]">
              <div className="flex items-center gap-2.5 text-text-secondary">
                <span className="text-text-dim font-bold">[01]</span>
                <span className="text-white font-medium">KeeperHub Off-Chain Dry-Run</span>
                <span className="text-text-dim">Simulating transaction state</span>
              </div>
              <span className="text-emerald-400 font-semibold uppercase text-[10px]">
                Gas Estimated: 0.000005 SOL (Passed)
              </span>
            </div>

            {/* Trace Step 2 */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] p-3 rounded bg-white/[0.02] border border-white/[0.04]">
              <div className="flex items-center gap-2.5 text-text-secondary">
                <span className="text-text-dim font-bold">[02]</span>
                <span className="text-white font-medium">OlaXBT Nexus Intelligence</span>
                <span className="text-text-dim">Evaluating momentum breakout</span>
              </div>
              <span className="text-accent font-semibold uppercase text-[10px]">
                Score 88/100 (Strong Buy)
              </span>
            </div>

            {/* Trace Step 3 */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] p-3 rounded bg-white/[0.02] border border-white/[0.04]">
              <div className="flex items-center gap-2.5 text-text-secondary">
                <span className="text-text-dim font-bold">[03]</span>
                <span className="text-white font-medium">Private Mempool Shield</span>
                <span className="text-text-dim">Direct validator inclusion</span>
              </div>
              <span className="text-emerald-400 font-semibold uppercase text-[10px]">
                Zero Sandwich Risk
              </span>
            </div>

          </div>

        </div>

        {/* 2-Column Detailed Capability Grid (Linear Style) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
          {/* Column 1: Deterministic Launches */}
          <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-9 flex flex-col justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-accent mb-3">
                Workflow Reliability
              </div>
              <h3 className="text-xl font-bold text-white mb-3">
                Deterministic token creation across 3 chains
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed mb-6 font-normal">
                Deploy tokens simultaneously to Pump.fun (Solana), Four.meme (BSC), and Pons (Robinhood Chain) without fragmented tooling or browser prompts.
              </p>

              {/* Protocol Spec Rows */}
              <div className="space-y-2.5 font-mono text-xs">
                <div className="p-3 bg-black/50 border border-white/[0.05] rounded flex justify-between items-center">
                  <span className="text-text-secondary">Solana Cluster</span>
                  <span className="text-white font-medium">Pump.fun &amp; Raydium</span>
                </div>
                <div className="p-3 bg-black/50 border border-white/[0.05] rounded flex justify-between items-center">
                  <span className="text-text-secondary">BNB Smart Chain</span>
                  <span className="text-white font-medium">Four.meme &amp; PancakeSwap</span>
                </div>
                <div className="p-3 bg-black/50 border border-white/[0.05] rounded flex justify-between items-center">
                  <span className="text-text-secondary">Robinhood Chain</span>
                  <span className="text-white font-medium">Pons Protocol</span>
                </div>
              </div>
            </div>

            <div className="pt-6 mt-6 border-t border-white/[0.06] flex items-center justify-between font-mono text-xs">
              <span className="text-text-dim">Single-Transaction Orchestration</span>
              <Link href="/launch" className="text-accent hover:text-accent-hover uppercase font-medium">
                Create Token &gt;
              </Link>
            </div>
          </div>

          {/* Column 2: Programmatic Developer API */}
          <div className="bg-[#090a0f] border border-white/[0.08] rounded-2xl p-7 md:p-9 flex flex-col justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-accent mb-3">
                API &amp; Agent Tooling
              </div>
              <h3 className="text-xl font-bold text-white mb-3">
                Developer API keys and webhook streams
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed mb-6 font-normal">
                Generate programmatic access keys to query token registries, inspect multi-chain balances, and automate trading bot executions.
              </p>

              {/* Code Snippet Mockup */}
              <div className="p-4 bg-black/60 border border-white/[0.05] rounded font-mono text-xs space-y-1.5 text-text-dim">
                <div className="text-text-muted">curl -X POST https://multipu.fun/api/trade/swap \</div>
                <div className="pl-4 text-text-secondary">-H &quot;x-api-key: mp_live_...&quot; \</div>
                <div className="pl-4 text-text-secondary">-d &#39;&#123;&quot;launchId&quot;:&quot;...&quot;, &quot;amountPay&quot;: 1.5&#125;&#39;</div>
              </div>
            </div>

            <div className="pt-6 mt-6 border-t border-white/[0.06] flex items-center justify-between font-mono text-xs">
              <span className="text-text-dim">Encrypted Iron-Session Auth</span>
              <Link href="/dashboard/api" className="text-accent hover:text-accent-hover uppercase font-medium">
                View API Docs &gt;
              </Link>
            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
