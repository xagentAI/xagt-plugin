"use client";

import { useState } from "react";
import { IconCopy, IconCheck, IconX } from "@tabler/icons-react";
import { toast } from "sonner";

interface InsufficientBalanceModalProps {
  isOpen: boolean;
  onClose: () => void;
  requiredAmount?: string;
  currentBalance?: string;
  symbol: string;
  walletAddress?: string | null;
  actionName?: string;
}

export function InsufficientBalanceModal({
  isOpen,
  onClose,
  requiredAmount,
  currentBalance = "0.00",
  symbol,
  walletAddress,
  actionName = "transaction",
}: InsufficientBalanceModalProps) {
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (!walletAddress) return;
    navigator.clipboard.writeText(walletAddress);
    setCopied(true);
    toast.success("Address copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const truncatedAddress = walletAddress
    ? `${walletAddress.slice(0, 8)}...${walletAddress.slice(-6)}`
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-sm bg-[#161616] rounded-2xl p-6 flex flex-col gap-4 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between pb-1">
          <h3 className="text-base font-medium text-white font-sans">
            Insufficient balance
          </h3>
          <button
            onClick={onClose}
            className="text-neutral-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/[0.05]"
            aria-label="Close"
          >
            <IconX size={16} />
          </button>
        </div>

        {/* Message */}
        <p className="text-xs text-neutral-400 leading-relaxed font-sans">
          Your wallet does not have enough {symbol} to complete this {actionName}. You need additional funds to cover transaction fees and order size.
        </p>

        {/* Balance Breakdown */}
        <div className="bg-[#101010] p-3.5 rounded-xl flex flex-col gap-2 font-mono text-xs">
          {requiredAmount && (
            <div className="flex items-center justify-between text-neutral-300">
              <span className="text-neutral-500 font-sans text-[11px]">Required</span>
              <span>{requiredAmount} {symbol}</span>
            </div>
          )}
          <div className="flex items-center justify-between text-neutral-300">
            <span className="text-neutral-500 font-sans text-[11px]">Available</span>
            <span>{currentBalance} {symbol}</span>
          </div>
        </div>

        {/* Wallet Address to Fund */}
        {walletAddress && (
          <div className="bg-[#101010] p-3 rounded-xl flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-[10px] text-neutral-500 font-sans">Deposit to wallet</div>
              <div className="text-xs font-mono text-neutral-300 truncate mt-0.5">
                {truncatedAddress}
              </div>
            </div>
            <button
              onClick={handleCopy}
              className="p-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-neutral-300 hover:text-white transition-colors flex-shrink-0"
              title="Copy wallet address"
            >
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            </button>
          </div>
        )}

        {/* Actions */}
        <div className="pt-2">
          <button
            onClick={onClose}
            className="w-full py-2.5 rounded-xl bg-white hover:bg-neutral-200 text-black text-xs font-medium transition-colors cursor-pointer text-center font-sans"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
