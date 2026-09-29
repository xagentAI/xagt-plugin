"use client";

import { useState } from "react";
import { IconX } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { useWalletBalances } from "@/hooks/use-wallet-balances";
import { InsufficientBalanceModal } from "@/components/ui/insufficient-balance-modal";
import { executeOnChainSwap } from "@/lib/trade/dex-swap";
import { toast } from "sonner";

interface QuickBuyModalProps {
  token: any;
  initialAmount?: number;
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export function QuickBuyModal({
  token,
  initialAmount = 1,
  isOpen,
  onClose,
  onSuccess,
}: QuickBuyModalProps) {
  const { connection } = useConnection();
  const { publicKey, signTransaction } = useWallet();
  const { balances, solAddress, evmAddress } = useWalletBalances();

  const [amount, setAmount] = useState<number>(initialAmount);
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [insufficientModalOpen, setInsufficientModalOpen] = useState(false);

  if (!isOpen || !token) return null;

  const rawNetwork = (token.network || "").toLowerCase();
  const chain = (rawNetwork === "bsc" || rawNetwork === "robinhood" ? rawNetwork : "solana") as
    | "solana"
    | "bsc"
    | "robinhood";
  const gas = chain === "bsc" ? "BNB" : chain === "robinhood" ? "ETH" : "SOL";

  const currentChainBalance =
    chain === "bsc"
      ? balances.bsc.balance
      : chain === "robinhood"
      ? balances.robinhood.balance
      : balances.solana.balance;

  const relevantWalletAddress =
    chain === "bsc" || chain === "robinhood" ? evmAddress : solAddress;

  const estimatedReceive = (amount * 45000).toLocaleString();

  const handleExecuteBuy = async () => {
    if (amount <= 0) {
      toast.error("Please enter a valid amount");
      return;
    }

    if (amount > currentChainBalance) {
      setInsufficientModalOpen(true);
      return;
    }

    setLoading(true);
    setStatus("idle");
    setErrorMessage("");

    try {
      const tokenMint = token.tokens?.mint_address || token.mint_address || token.address;
      const poolAddress = token.pool_address || token.poolAddress;

      toast.info(`Signing ${chain.toUpperCase()} swap...`);

      const onChainResult = await executeOnChainSwap({
        chain,
        type: "buy",
        amount,
        tokenMint,
        poolAddress,
        solanaConnection: connection,
        solanaPublicKey: publicKey,
        solanaSignTransaction: signTransaction,
        evmAddress,
      });

      const txHash = onChainResult.txHash;

      const res = await fetch("/api/trade/swap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          launchId: token.id,
          type: "buy",
          amountPay: amount,
          amountReceive: amount * 45000,
          txSignature: txHash,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Swap record update failed");
      }

      setStatus("success");
      toast.success(`Bought with ${amount} ${gas} (${onChainResult.route})`);
      if (onSuccess) onSuccess();
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err: any) {
      const msg = err.message || "Failed to execute buy order";
      if (
        msg.toLowerCase().includes("insufficient") ||
        msg.toLowerCase().includes("debit an account")
      ) {
        setInsufficientModalOpen(true);
      } else {
        setStatus("error");
        setErrorMessage(msg);
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
        <div className="w-full max-w-sm bg-[#161616] rounded-2xl p-6 flex flex-col gap-4 shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between pb-1">
            <div>
              <h3 className="text-base font-medium text-white font-sans">
                Buy ${token.tokens?.symbol || token.symbol}
              </h3>
              <p className="text-[11px] text-neutral-400 font-mono mt-0.5">{chain.toUpperCase()}</p>
            </div>
            <button
              onClick={onClose}
              className="text-neutral-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/[0.05]"
              aria-label="Close"
            >
              <IconX size={16} />
            </button>
          </div>

          {/* Token Summary */}
          <div className="flex items-center gap-3 p-3 bg-[#111111] rounded-xl">
            <img
              src={token.tokens?.image_url || token.image_url}
              alt=""
              className="w-9 h-9 rounded-lg object-cover bg-black/40"
              onError={(e) => {
                (e.target as HTMLImageElement).src = `https://api.dicebear.com/7.x/identicon/svg?seed=${token.tokens?.symbol || "token"}`;
              }}
            />
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-white font-sans truncate">
                {token.tokens?.name || token.name}
              </div>
              <div className="text-[11px] text-neutral-400 font-mono mt-0.5">
                ${token.tokens?.symbol || token.symbol}
              </div>
            </div>
          </div>

          {/* Amount Input */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-[11px] font-sans font-medium">
              <span className="text-neutral-400 uppercase tracking-wider">
                Pay Amount ({gas})
              </span>
              <span className="text-neutral-400 font-mono text-[10px]">
                Bal: {currentChainBalance.toFixed(4)} {gas}
              </span>
            </div>
            <div className="bg-[#111111] p-3.5 rounded-xl flex items-center justify-between">
              <input
                type="number"
                step="0.05"
                min="0.01"
                value={amount}
                onChange={(e) => setAmount(Math.max(0.01, parseFloat(e.target.value) || 0))}
                className="bg-transparent text-white text-sm font-mono outline-none w-full"
              />
              <span className="text-xs text-neutral-400 font-mono font-medium">{gas}</span>
            </div>

            {/* Preset Buttons */}
            <div className="grid grid-cols-4 gap-1.5 mt-1">
              {[0.1, 0.5, 1, 5].map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setAmount(preset)}
                  className={cn(
                    "py-1.5 text-xs font-mono rounded-full transition-colors cursor-pointer",
                    amount === preset
                      ? "bg-white text-black font-semibold"
                      : "bg-[#111111] text-neutral-400 hover:text-white"
                  )}
                >
                  {preset}
                </button>
              ))}
            </div>
          </div>

          {/* Estimated Output */}
          <div className="bg-[#111111] p-3 rounded-xl text-xs font-mono flex justify-between items-center">
            <span className="text-neutral-400">Est. Output:</span>
            <span className="text-white font-medium">
              ~{estimatedReceive} ${token.tokens?.symbol || token.symbol}
            </span>
          </div>

          {/* Status Feedback */}
          {status === "success" && (
            <div className="p-2.5 bg-white/[0.04] rounded-xl text-xs text-neutral-200 font-mono text-center">
              Swap confirmed on-chain
            </div>
          )}

          {status === "error" && (
            <div className="p-2.5 bg-white/[0.04] rounded-xl text-xs text-neutral-300 font-mono text-center">
              {errorMessage}
            </div>
          )}

          {/* Submit Button */}
          <button
            onClick={handleExecuteBuy}
            disabled={loading || status === "success"}
            className="w-full py-2.5 text-xs font-sans font-medium bg-white hover:bg-neutral-200 disabled:opacity-50 text-black rounded-xl transition-colors cursor-pointer mt-1"
          >
            {loading ? "Confirming on-chain..." : status === "success" ? "Confirmed" : `Buy with ${amount} ${gas}`}
          </button>
        </div>
      </div>

      <InsufficientBalanceModal
        isOpen={insufficientModalOpen}
        onClose={() => setInsufficientModalOpen(false)}
        requiredAmount={amount.toString()}
        currentBalance={currentChainBalance.toFixed(4)}
        symbol={gas}
        walletAddress={relevantWalletAddress}
        actionName="quick buy"
      />
    </>
  );
}
