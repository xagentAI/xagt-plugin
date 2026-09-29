"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { IconX, IconLogout, IconLoader2 } from "@tabler/icons-react";

interface DisconnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  walletAddress?: string | null;
  walletKind?: string | null;
}

export function DisconnectModal({
  isOpen,
  onClose,
  onConfirm,
  walletAddress,
  walletKind,
}: DisconnectModalProps) {
  const [isDisconnecting, setIsDisconnecting] = useState(false);

  // Prevent background scrolling when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const handleConfirm = async () => {
    try {
      setIsDisconnecting(true);
      await onConfirm();
    } catch (err) {
      console.error("Disconnect error:", err);
    } finally {
      setIsDisconnecting(false);
      onClose();
    }
  };

  const formattedAddress = walletAddress
    ? `${walletAddress.slice(0, 6)}...${walletAddress.slice(-4)}`
    : null;

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm"
          />

          {/* Modal Card */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="relative z-10 w-full max-w-[420px] bg-[#0c0c0e]/95 backdrop-blur-2xl border border-white/[0.08] shadow-[0_24px_60px_-12px_rgba(0,0,0,0.9)] rounded-2xl sm:rounded-3xl p-6 sm:p-7 overflow-hidden font-[family-name:var(--font-geist-sans)] select-none"
          >
            {/* Close Button */}
            <button
              onClick={onClose}
              disabled={isDisconnecting}
              className="absolute top-5 right-5 p-1.5 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer disabled:opacity-50"
              aria-label="Close modal"
            >
              <IconX size={16} />
            </button>

            {/* Header Icon */}
            <div className="w-12 h-12 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-4">
              <IconLogout size={22} />
            </div>

            <h3 className="text-base sm:text-lg font-bold text-white tracking-tight leading-snug">
              Disconnect Session
            </h3>

            {/* Content & Account Summary */}
            <p className="text-xs sm:text-sm text-neutral-400 leading-relaxed mt-2 font-[family-name:var(--font-geist-sans)]">
              Are you sure you want to disconnect? Your session will be invalidated and you will be taken to sign in again.
            </p>

            {formattedAddress && (
              <div className="flex items-center justify-between p-3 bg-white/[0.03] border border-white/[0.06] rounded-xl my-4">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0 animate-pulse" />
                  <span className="font-mono text-xs text-white truncate font-medium">
                    {formattedAddress}
                  </span>
                </div>
                {walletKind && (
                  <span className="font-mono text-[10px] text-neutral-400 uppercase tracking-wider bg-white/[0.04] px-2 py-0.5 rounded-md border border-white/[0.04]">
                    {walletKind}
                  </span>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={onClose}
                disabled={isDisconnecting}
                className="px-4 py-2.5 rounded-xl border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] text-neutral-300 hover:text-white font-medium text-xs transition-colors cursor-pointer disabled:opacity-50 font-[family-name:var(--font-geist-sans)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={isDisconnecting}
                className="px-4.5 py-2.5 rounded-xl font-semibold text-xs bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-600/20 hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1.5 font-[family-name:var(--font-geist-sans)]"
              >
                {isDisconnecting ? (
                  <>
                    <IconLoader2 size={13} className="animate-spin" />
                    Disconnecting...
                  </>
                ) : (
                  <>
                    <IconLogout size={14} />
                    Disconnect
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
