"use client";

import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { useWalletBalances } from "@/hooks/use-wallet-balances";
import { executeOnChainSwap } from "@/lib/trade/dex-swap";
import { InsufficientBalanceModal } from "@/components/ui/insufficient-balance-modal";
import type { ExecutedTrade } from "./trade-history";

interface TradeFormProps {
  launch: {
    id: string;
    launchpad: string;
    network: string;
    pool_address: string | null;
    tokens?: {
      name: string;
      symbol: string;
      mint_address: string | null;
    };
  };
  onTradeSuccess: (trade?: ExecutedTrade) => void;
}

export function TradeForm({ launch, onTradeSuccess }: TradeFormProps) {
  const { connection } = useConnection();
  const { publicKey, signTransaction } = useWallet();
  const { balances, solAddress, evmAddress } = useWalletBalances();

  const [activeTab, setActiveTab] = useState<"buy" | "sell">("buy");
  const [payAmount, setPayAmount] = useState("");
  const [slippage, setSlippage] = useState("1.0");
  const [loading, setLoading] = useState(false);
  const [insufficientModalOpen, setInsufficientModalOpen] = useState(false);

  const tokenSymbol = launch.tokens?.symbol || "TOKEN";

  // Determine gas token symbol and network
  const rawNetwork = launch.network.toLowerCase();
  const chain = (rawNetwork === "bsc" || rawNetwork === "robinhood" ? rawNetwork : "solana") as
    | "solana"
    | "bsc"
    | "robinhood";
  const gasSymbol = chain === "bsc" ? "BNB" : chain === "robinhood" ? "ETH" : "SOL";

  // Current balance for target chain
  const currentChainBalance =
    chain === "bsc"
      ? balances.bsc.balance
      : chain === "robinhood"
      ? balances.robinhood.balance
      : balances.solana.balance;

  const relevantWalletAddress =
    chain === "bsc" || chain === "robinhood" ? evmAddress : solAddress;

  const exchangeRate = 1000000;

  const handleAmountChange = (val: string) => {
    if (val === "" || /^\d*\.?\d*$/.test(val)) {
      setPayAmount(val);
    }
  };

  const calculatedOutput = () => {
    const num = parseFloat(payAmount || "0");
    if (activeTab === "buy") {
      return (num * exchangeRate).toLocaleString();
    } else {
      return (num / exchangeRate).toFixed(6);
    }
  };

  const handleSwap = async (e: React.FormEvent) => {
    e.preventDefault();
    const amountNum = parseFloat(payAmount || "0");
    if (!payAmount || amountNum <= 0) {
      toast.error("Please enter a valid amount");
      return;
    }

    // Balance check: if buying with native gas token, ensure wallet has enough funds
    if (activeTab === "buy" && amountNum > currentChainBalance) {
      setInsufficientModalOpen(true);
      return;
    }

    setLoading(true);
    try {
      const amountReceiveNum =
        activeTab === "buy" ? amountNum * exchangeRate : amountNum / exchangeRate;

      // Execute real on-chain swap transaction signed by the connected wallet
      toast.info(`Initiating ${chain.toUpperCase()} swap...`);

      const onChainResult = await executeOnChainSwap({
        chain,
        type: activeTab,
        amount: amountNum,
        tokenMint: launch.tokens?.mint_address,
        poolAddress: launch.pool_address,
        solanaConnection: connection,
        solanaPublicKey: publicKey,
        solanaSignTransaction: signTransaction,
        evmAddress,
      });

      const txHash = onChainResult.txHash;

      // Record swap & royalty in database with real txHash
      const res = await fetch("/api/trade/swap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          launchId: launch.id,
          type: activeTab,
          amountPay: amountNum,
          amountReceive: amountReceiveNum,
          txSignature: txHash,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to finalize swap record");
      }

      const outputVal = parseFloat(payAmount || "0") * (activeTab === "buy" ? exchangeRate : 1 / exchangeRate);
      const executedTrade: ExecutedTrade = {
        id: txHash,
        type: activeTab,
        amountPay: parseFloat(payAmount),
        amountReceive: outputVal,
        wallet: relevantWalletAddress
          ? `${relevantWalletAddress.substring(0, 4)}...${relevantWalletAddress.substring(relevantWalletAddress.length - 4)}`
          : "You",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        txHash,
        explorerUrl: onChainResult.explorerUrl,
      };

      toast.success(
        `Swapped ${payAmount} ${activeTab === "buy" ? gasSymbol : tokenSymbol} (${onChainResult.route})`
      );
      setPayAmount("");
      onTradeSuccess(executedTrade);
    } catch (err: any) {
      const msg = err.message || "Failed to complete swap";
      if (
        msg.toLowerCase().includes("insufficient") ||
        msg.toLowerCase().includes("debit an account")
      ) {
        setInsufficientModalOpen(true);
      } else {
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="bg-[#181818] p-6 rounded-2xl flex flex-col gap-5">
        {/* Tabs */}
        <div className="grid grid-cols-2 bg-[#141414] p-1 rounded-full">
          <button
            type="button"
            onClick={() => {
              setActiveTab("buy");
              setPayAmount("");
            }}
            className={cn(
              "py-2 text-center text-xs font-sans font-medium transition-colors rounded-full cursor-pointer",
              activeTab === "buy"
                ? "bg-white text-black font-semibold"
                : "text-neutral-400 hover:text-white"
            )}
          >
            Buy
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("sell");
              setPayAmount("");
            }}
            className={cn(
              "py-2 text-center text-xs font-sans font-medium transition-colors rounded-full cursor-pointer",
              activeTab === "sell"
                ? "bg-white text-black font-semibold"
                : "text-neutral-400 hover:text-white"
            )}
          >
            Sell
          </button>
        </div>

        <form onSubmit={handleSwap} className="flex flex-col gap-4">
          {/* Input Field with Live Available Balance */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-[11px] font-sans font-medium">
              <span className="text-neutral-400 uppercase tracking-wider">
                Pay Amount ({activeTab === "buy" ? gasSymbol : tokenSymbol})
              </span>
              <span className="text-neutral-400 font-mono text-[10px]">
                Bal: {currentChainBalance.toFixed(4)} {gasSymbol}
              </span>
            </div>
            <div className="bg-[#141414] p-3.5 rounded-xl flex items-center justify-between">
              <input
                type="text"
                value={payAmount}
                onChange={(e) => handleAmountChange(e.target.value)}
                placeholder="0.0"
                className="bg-transparent text-white text-sm font-mono outline-none w-full"
              />
              <span className="text-xs text-neutral-400 font-mono font-medium">
                {activeTab === "buy" ? gasSymbol : tokenSymbol}
              </span>
            </div>
          </div>

          {/* Estimated Output Field */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] text-neutral-400 uppercase tracking-wider font-sans font-medium">
              Receive Amount ({activeTab === "buy" ? tokenSymbol : gasSymbol})
            </span>
            <div className="bg-[#141414] p-3.5 rounded-xl flex items-center justify-between">
              <div className="text-white text-sm font-mono font-medium">
                {calculatedOutput()}
              </div>
              <span className="text-xs text-neutral-400 font-mono font-medium">
                {activeTab === "buy" ? tokenSymbol : gasSymbol}
              </span>
            </div>
          </div>

          {/* Slippage Settings */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] text-neutral-400 uppercase tracking-wider font-sans font-medium">
              Slippage Tolerance (%)
            </span>
            <div className="grid grid-cols-4 gap-2">
              {["0.5", "1.0", "3.0"].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSlippage(s)}
                  className={cn(
                    "py-1.5 text-center text-xs font-mono rounded-full transition-colors cursor-pointer",
                    slippage === s
                      ? "bg-white text-black font-semibold"
                      : "bg-[#141414] text-neutral-400 hover:text-white"
                  )}
                >
                  {s}%
                </button>
              ))}
              <input
                type="text"
                value={slippage}
                onChange={(e) => setSlippage(e.target.value)}
                placeholder="Custom"
                className="bg-[#141414] text-center text-xs text-white rounded-full font-mono outline-none py-1.5"
              />
            </div>
          </div>

          {/* Submit Swap Button */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 text-center text-xs font-sans font-semibold bg-white hover:bg-neutral-200 text-black rounded-full transition-colors cursor-pointer disabled:opacity-50 mt-1"
          >
            {loading
              ? "Confirming on-chain..."
              : `Swap to ${activeTab === "buy" ? tokenSymbol : gasSymbol}`}
          </button>
        </form>
      </div>

      <InsufficientBalanceModal
        isOpen={insufficientModalOpen}
        onClose={() => setInsufficientModalOpen(false)}
        requiredAmount={payAmount || "0.01"}
        currentBalance={currentChainBalance.toFixed(4)}
        symbol={gasSymbol}
        walletAddress={relevantWalletAddress}
        actionName="swap"
      />
    </>
  );
}
