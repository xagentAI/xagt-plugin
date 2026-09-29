"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { IconWallet, IconArrowLeft, IconShieldCheck, IconCpu, IconSparkles } from "@tabler/icons-react";
import { SignInModal } from "@/components/signin-modal";
import { useAuth } from "@/hooks/use-auth";

export default function SignInPage() {
  const router = useRouter();
  const { session } = useAuth();
  const [modalOpen, setModalOpen] = useState(true);

  // If already authenticated, redirect straight to dashboard
  useEffect(() => {
    if (session.isLoggedIn) {
      router.replace("/dashboard");
    }
  }, [session.isLoggedIn, router]);

  return (
    <div className="min-h-screen bg-black text-white relative flex flex-col justify-between overflow-hidden selection:bg-accent selection:text-white">
      {/* Background ambient lighting and subtle grid */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_40%,#000_70%,transparent_100%)] pointer-events-none" />
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[350px] bg-gradient-to-tr from-accent/20 via-purple-600/10 to-transparent blur-[120px] rounded-full pointer-events-none" />

      {/* Top Header */}
      <header className="relative z-10 w-full max-w-6xl mx-auto px-6 py-6 flex items-center justify-between">
        <Link
          href="/"
          className="flex items-center gap-3 text-white/70 hover:text-white transition-colors group"
        >
          <div className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center group-hover:border-white/20 transition-all">
            <IconArrowLeft size={16} className="group-hover:-translate-x-0.5 transition-transform" />
          </div>
          <span className="text-xs font-mono tracking-wider uppercase">Back to Home</span>
        </Link>

        <div className="flex items-center gap-2.5">
          <Image
            src="/logo.png"
            alt="Multipu"
            width={28}
            height={28}
            className="w-7 h-7 rounded-lg object-contain"
          />
          <span className="font-bold text-sm tracking-tight text-white">multipu</span>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="relative z-10 flex-1 flex items-center justify-center px-4 py-12">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-md text-center"
        >
          {/* Logo badge */}
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-white/[0.04] border border-white/[0.08] shadow-2xl mb-6 relative group">
            <div className="absolute inset-0 bg-accent/20 rounded-2xl blur-xl opacity-40 group-hover:opacity-70 transition-opacity" />
            <Image
              src="/logo.png"
              alt="Multipu"
              width={40}
              height={40}
              className="w-10 h-10 object-contain relative z-10"
            />
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white mb-2">
            Access Multipu Terminal
          </h1>
          <p className="text-sm text-neutral-400 max-w-sm mx-auto mb-8 leading-relaxed">
            Connect your Solana or EVM wallet to enter your dashboard, run trading agents, and launch multi-chain tokens.
          </p>

          {/* Trigger button (if modal was closed) */}
          <div className="flex flex-col gap-3">
            <button
              onClick={() => setModalOpen(true)}
              className="w-full py-3.5 px-6 rounded-2xl bg-accent hover:bg-accent/90 text-white font-semibold text-sm shadow-xl shadow-accent/20 hover:scale-[1.01] active:scale-[0.99] transition-all flex items-center justify-center gap-2.5 cursor-pointer"
            >
              <IconWallet size={18} />
              <span>Connect Wallet to Continue</span>
            </button>
          </div>
        </motion.div>
      </main>


      {/* Sign In Modal */}
      <SignInModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        redirectTo="/dashboard"
      />
    </div>
  );
}
