"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import { useAuth } from "@/hooks/use-auth";
import { SignInModal } from "@/components/signin-modal";

export function Hero() {
  const { session } = useAuth();
  const router = useRouter();
  const [showSignInModal, setShowSignInModal] = useState(false);
  const [targetDestination, setTargetDestination] = useState<string>("/launch");

  const handleActionClick = (destination: string) => {
    if (session.isLoggedIn) {
      router.push(destination);
    } else {
      setTargetDestination(destination);
      setShowSignInModal(true);
    }
  };

  return (
    <section className="relative min-h-[90vh] flex items-center pt-24 pb-20 border-b border-white/[0.05]">
      {/* Background patterns */}
      <div className="absolute inset-0 z-0 bg-white/[0.01]" />
      <div className="absolute top-0 right-0 w-1/3 h-full border-l border-white/[0.05] z-0 hidden lg:block" />

      <div className="relative z-10 mx-auto max-w-[1400px] px-4 sm:px-6 md:px-10 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-0 border-l border-white/10">
          
          {/* Main Content Column */}
          <div className="lg:col-span-3 px-4 sm:px-8 py-14 sm:py-20 md:py-32 border-r border-white/10 flex flex-col justify-center">
            <motion.div
              initial="hidden"
              animate="visible"
              variants={stagger}
            >
              <motion.span
                variants={fadeUp}
                className="font-mono text-xs text-accent uppercase tracking-[0.3em] mb-6 sm:mb-8 block"
              >
                Protocol v1.0
              </motion.span>
              
              <motion.h1
                variants={fadeUp}
                className="text-[clamp(2rem,7vw,5.5rem)] font-normal leading-[1.0] tracking-tight text-white mb-8 sm:mb-10 max-w-4xl"
              >
                Deploy once. <br/> Launch &amp; Trade everywhere.
              </motion.h1>

              <motion.p
                variants={fadeUp}
                className="text-base sm:text-lg md:text-xl text-text-secondary max-w-xl leading-relaxed font-light mb-10 sm:mb-12 opacity-80"
              >
                The multi-launchpad control plane and trading hub for Web3 memes. 
                Deploy across Solana, BSC, and Robinhood Chain, search live markets, 
                and manually swap tokens instantly.
              </motion.p>

              <motion.div
                variants={fadeUp}
                className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4"
              >
                <button
                  onClick={() => handleActionClick("/launch")}
                  className="px-6 sm:px-8 py-3.5 sm:py-4 bg-white text-black text-[11px] font-mono tracking-[0.2em] font-bold hover:bg-accent hover:text-white transition-all text-center uppercase cursor-pointer"
                >
                  Start Launching &gt;
                </button>
                <button
                  onClick={() => handleActionClick("/dashboard/explore")}
                  className="px-6 sm:px-8 py-3.5 sm:py-4 border border-white/20 text-white text-[11px] font-mono tracking-[0.2em] hover:bg-white/5 transition-all text-center uppercase cursor-pointer"
                >
                  Explore &amp; Trade
                </button>
              </motion.div>
            </motion.div>

            {/* Mobile Metrics (shown below CTAs on small screens, hidden on lg) */}
            <div className="grid grid-cols-2 gap-0 border-t border-white/10 mt-12 lg:hidden">
              {[
                { value: "03", label: "Launchpads", detail: "Active integrations" },
                { value: "1-Click", label: "Deploy", detail: "Zero CLI required" },
                { value: "Real-time", label: "Tracking", detail: "Live node sync" },
                { value: "Fast", label: "Execution", detail: "Solana optimized" },
              ].map((stat, i) => (
                <motion.div
                  key={`mobile-${stat.label}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 + (i * 0.1) }}
                  className="p-5 flex flex-col border-b border-r border-white/10 bg-white/[0.01]"
                >
                  <div className="text-2xl font-serif text-white mb-1 tracking-tighter">
                    {stat.value}
                  </div>
                  <div className="text-[10px] font-mono text-white/40 uppercase tracking-[0.2em] mb-1">
                    {stat.label}
                  </div>
                  <div className="text-[10px] text-text-secondary font-light opacity-60">
                    {stat.detail}
                  </div>
                </motion.div>
              ))}
            </div>
          </div>

          {/* Metrics Column — desktop only */}
          <div className="lg:col-span-1 border-r border-white/10 flex-col divide-y divide-white/10 hidden lg:flex">
            {[
              { value: "03", label: "Launchpads", detail: "Active integrations" },
              { value: "1-Click", label: "Deploy", detail: "Zero CLI required" },
              { value: "Real-time", label: "Tracking", detail: "Live node sync" },
              { value: "Fast", label: "Execution", detail: "Solana optimized" },
            ].map((stat, i) => (
              <motion.div 
                key={stat.label}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.4 + (i * 0.1) }}
                className="p-8 flex-1 flex flex-col justify-center bg-white/[0.01] hover:bg-white/[0.02] transition-colors group"
              >
                <div className="text-3xl font-serif text-white mb-2 group-hover:text-accent transition-colors tracking-tighter">
                  {stat.value}
                </div>
                <div className="text-[10px] font-mono text-white/40 uppercase tracking-[0.2em] mb-4">
                  {stat.label}
                </div>
                <div className="text-[11px] text-text-secondary font-light opacity-60 leading-relaxed">
                  {stat.detail}
                </div>
              </motion.div>
            ))}
          </div>

        </div>
      </div>

      {/* Auth Modal for protected actions */}
      <SignInModal
        isOpen={showSignInModal}
        onClose={() => setShowSignInModal(false)}
        redirectTo={targetDestination}
      />
    </section>
  );
}
