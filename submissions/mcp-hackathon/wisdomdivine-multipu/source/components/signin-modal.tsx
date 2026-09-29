"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { IconX, IconLoader2, IconWallet } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useWallet } from "@solana/wallet-adapter-react";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "sonner";

import { useRouter } from "next/navigation";

interface SignInModalProps {
  isOpen: boolean;
  onClose: () => void;
  redirectTo?: string;
}

export function SignInModal({ isOpen, onClose, redirectTo }: SignInModalProps) {
  const router = useRouter();
  const { wallets, connecting, select } = useWallet();
  const { connectEvmWallet, signInWithSolana, signInWithEvm, signInDemo, session } = useAuth();
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);

  // Prevent scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
      document.body.style.paddingRight = "var(--scrollbar-gutter, 0px)";
    } else {
      document.body.style.overflow = "";
      document.body.style.paddingRight = "";
    }
    return () => {
      document.body.style.overflow = "";
      document.body.style.paddingRight = "";
    };
  }, [isOpen]);

  // Close modal when successfully signed in and optionally redirect
  useEffect(() => {
    if (session.isLoggedIn && isOpen) {
      const timer = setTimeout(() => {
        onClose();
        setSelectedMethod(null);
        setIsConnecting(false);
        if (redirectTo) {
          router.push(redirectTo);
        }
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [session.isLoggedIn, isOpen, onClose, redirectTo, router]);

  const handleSolanaSignIn = async () => {
    if (wallets.length === 0) {
      toast.error("No Solana wallet detected. Install Phantom or another compatible wallet.");
      return;
    }

    setSelectedMethod("solana");
    setIsConnecting(true);

    try {
      // Select wallet (prefer Phantom if available)
      const phantomWallet = wallets.find(w => w.adapter.name === "Phantom");
      const walletToSelect = phantomWallet?.adapter.name || wallets[0].adapter.name;
      
      select(walletToSelect);

      // Wait for wallet selection + connection
      await new Promise(resolve => setTimeout(resolve, 800));

      // Then sign in
      await signInWithSolana();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to sign in with Solana";
      toast.error(message);
      setIsConnecting(false);
      setSelectedMethod(null);
    }
  };

  const handleBscSignIn = async () => {
    setSelectedMethod("bsc");
    setIsConnecting(true);

    try {
      // Connect and sign in
      await connectEvmWallet();
      await signInWithEvm();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to sign in with BSC";
      toast.error(message);
      setIsConnecting(false);
      setSelectedMethod(null);
    }
  };

  const handleDemoSignIn = async () => {
    setSelectedMethod("demo");
    setIsConnecting(true);
    try {
      const demoAddress = "DemoSolanaWalletAddress111111111111111111";
      await signInDemo(demoAddress);
      toast.success("Successfully signed in with Demo Wallet");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to sign in with Demo";
      toast.error(message);
      setIsConnecting(false);
      setSelectedMethod(null);
    }
  };

  const authMethods = [
    {
      id: "solana",
      label: "Solana Wallet",
      description: "Connect Phantom, Solflare & Backpack",
      onClick: handleSolanaSignIn,
      isPrimary: true,
      icon: <IconWallet className="w-5 h-5 text-[#14F195]" />,
    },
    {
      id: "bsc",
      label: "EVM / BSC Wallet",
      description: "Connect MetaMask, Rabby & WalletConnect",
      onClick: handleBscSignIn,
      isPrimary: true,
      icon: <IconWallet className="w-5 h-5 text-[#F3BA2F]" />,
    },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100] w-screen h-screen overflow-hidden">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/80 backdrop-blur-md"
          />

          {/* Modal Container */}
          <div className="absolute inset-0 flex items-center justify-center p-4 pointer-events-none">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="relative w-full max-w-[400px] pointer-events-auto"
            >
              {/* Outer Glow */}
              <div className="absolute -inset-1 bg-gradient-to-r from-accent/20 to-accent/10 rounded-[28px] blur-2xl opacity-50" />
              
              <div className="relative border border-white/10 rounded-3xl bg-[#0a0a0a] shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="relative px-8 pt-10 pb-6 text-center">
                  <button
                    onClick={onClose}
                    disabled={isConnecting}
                    className="absolute top-6 right-6 p-2 text-text-muted hover:text-white hover:bg-white/5 rounded-full transition-all"
                  >
                    <IconX size={18} />
                  </button>
                  
                  <h2 className="text-2xl font-bold text-white tracking-tight">Welcome back</h2>
                  <p className="text-[15px] text-text-secondary mt-2 leading-relaxed">
                    Choose a secure way to access <br/> your multipu dashboard
                  </p>
                </div>

                {/* Content */}
                <div className="px-8 pb-10">
                  <div className="flex flex-col gap-3">
                    {authMethods.map((method) => (
                      <button
                        key={method.id}
                        onClick={method.onClick}
                        disabled={isConnecting}
                        className={cn(
                          "relative group w-full flex items-center gap-4 p-4 rounded-2xl transition-all duration-300",
                          "border border-white/[0.05] hover:border-white/20",
                          "bg-white/[0.02] hover:bg-white/[0.06]",
                          "disabled:opacity-50 disabled:cursor-not-allowed"
                        )}
                      >
                        <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center border border-white/5 group-hover:border-white/10 transition-colors">
                          {isConnecting && selectedMethod === method.id ? (
                            <IconLoader2 size={20} className="animate-spin text-accent" />
                          ) : (
                             method.icon
                          )}
                        </div>
                        
                        <div className="flex-1 text-left">
                          <div className="text-[15px] font-semibold text-white">
                            {method.label}
                          </div>
                          <div className="text-[13px] text-text-muted mt-0.5">
                            {method.description}
                          </div>
                        </div>

                        {/* Hover arrow */}
                        <div className="opacity-0 group-hover:opacity-100 translate-x-1 group-hover:translate-x-0 transition-all text-white/30">
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M6 12L10 8L6 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Footer */}
                <div className="px-8 py-5 border-t border-white/[0.05] bg-white/[0.02]">
                  <p className="text-[12px] text-text-muted text-center leading-relaxed px-4">
                    By accessing, you agree to our <span className="text-white hover:underline cursor-pointer">Terms</span> and acknowledge our <span className="text-white hover:underline cursor-pointer">Privacy Policy</span>
                  </p>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      )}
    </AnimatePresence>
  );
}
