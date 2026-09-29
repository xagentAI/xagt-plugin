"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import { IconArrowRight } from "@tabler/icons-react";
import { useAuth } from "@/hooks/use-auth";
import { SignInModal } from "@/components/signin-modal";

export function CTA() {
  const { session } = useAuth();
  const router = useRouter();
  const [showSignInModal, setShowSignInModal] = useState(false);

  const handleStartLaunching = () => {
    if (session.isLoggedIn) {
      router.push("/launch");
    } else {
      setShowSignInModal(true);
    }
  };

  return (
    <section className="relative py-24 md:py-32 dot-grid overflow-hidden">
      {/* Gradient orb */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-accent/[0.06] blur-[100px] pointer-events-none" />

      <motion.div
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: "-100px" }}
        variants={stagger}
        className="relative z-10 mx-auto max-w-[1400px] px-6 md:px-10"
      >
        <div className="border border-border bg-background p-8 sm:p-12 md:p-20 text-center relative overflow-hidden">
          {/* Corner accents */}
          <div className="absolute top-0 left-0 w-12 h-12 border-l border-t border-accent/30" />
          <div className="absolute top-0 right-0 w-12 h-12 border-r border-t border-accent/30" />
          <div className="absolute bottom-0 left-0 w-12 h-12 border-l border-b border-accent/30" />
          <div className="absolute bottom-0 right-0 w-12 h-12 border-r border-b border-accent/30" />

          <motion.span
            variants={fadeUp}
            className="font-mono text-xs text-accent uppercase tracking-widest"
          >
            Ready to launch?
          </motion.span>
          <motion.h2
            variants={fadeUp}
            className="mt-6 text-[clamp(1.75rem,4vw,3rem)] font-bold tracking-tight max-w-2xl mx-auto"
          >
            Deploy your token to multiple launchpads in minutes
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="mt-4 text-text-secondary max-w-lg mx-auto text-lg"
          >
            Connect your wallet, create your token, choose your launchpads, and
            go live. It&apos;s that simple.
          </motion.p>
          <motion.div
            variants={fadeUp}
            className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <button
              onClick={handleStartLaunching}
              className="group inline-flex items-center gap-2 px-8 py-4 text-sm font-semibold bg-accent hover:bg-accent-hover text-white rounded-full transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_12px_32px_rgba(139,92,246,0.35)] cursor-pointer"
            >
              Start Launching
              <IconArrowRight
                size={16}
                className="group-hover:translate-x-0.5 transition-transform"
              />
            </button>
          </motion.div>
        </div>
      </motion.div>

      <SignInModal
        isOpen={showSignInModal}
        onClose={() => setShowSignInModal(false)}
        redirectTo="/launch"
      />
    </section>
  );
}
