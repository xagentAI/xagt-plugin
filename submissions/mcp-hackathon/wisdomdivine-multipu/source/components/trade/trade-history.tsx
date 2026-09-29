"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export interface ExecutedTrade {
  id: string;
  type: "buy" | "sell";
  amountPay: number;
  amountReceive?: number;
  volumeUsd?: number;
  wallet: string;
  timestamp: string;
  txHash?: string;
  explorerUrl?: string;
}

interface TradeHistoryProps {
  launchId: string;
  gasSymbol: string;
  pairAddress?: string | null;
  network?: string;
  sessionTrades?: ExecutedTrade[];
  txns24h?: { buys: number; sells: number };
}

export function TradeHistory({
  launchId,
  gasSymbol,
  pairAddress,
  network,
  sessionTrades = [],
  txns24h,
}: TradeHistoryProps) {
  const [activeTab, setActiveTab] = useState<"all" | "session">("all");
  const [liveTrades, setLiveTrades] = useState<ExecutedTrade[]>([]);
  const [loading, setLoading] = useState(true);

  const total24h = (txns24h?.buys || 0) + (txns24h?.sells || 0);

  // Fetch live on-chain trades
  useEffect(() => {
    let isSubscribed = true;

    const fetchLiveTrades = async () => {
      try {
        const query = new URLSearchParams();
        if (pairAddress) query.set("pairAddress", pairAddress);
        if (network) query.set("network", network);

        const res = await fetch(`/api/launches/${launchId}/trades?${query.toString()}`);
        if (!res.ok) {
          if (isSubscribed) setLoading(false);
          return;
        }

        const data = await res.json();
        if (isSubscribed) {
          if (Array.isArray(data?.trades) && data.trades.length > 0) {
            setLiveTrades(data.trades);
          }
          setLoading(false);
        }
      } catch {
        if (isSubscribed) setLoading(false);
      }
    };

    fetchLiveTrades();
    // Poll every 12 seconds for real-time transaction updates
    const pollInterval = setInterval(fetchLiveTrades, 12000);

    return () => {
      isSubscribed = false;
      clearInterval(pollInterval);
    };
  }, [launchId, pairAddress, network]);

  const displayedTrades = activeTab === "session" ? sessionTrades : liveTrades;

  return (
    <div className="bg-[#181818] p-6 rounded-2xl flex flex-col gap-4">
      {/* Header Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white font-sans">
            Trade Activity
          </h3>
          <p className="text-xs text-neutral-400 font-sans mt-0.5">
            Verified on-chain executions and session order flow
          </p>
        </div>

        {/* Tab Controls & 24h Summary */}
        <div className="flex items-center gap-2">
          {total24h > 0 && (
            <span className="text-[11px] font-mono text-neutral-400 hidden sm:inline-block mr-2">
              24h: {txns24h?.buys || 0} buys / {txns24h?.sells || 0} sells
            </span>
          )}

          <div className="flex items-center gap-1 bg-[#121212] p-0.5 rounded-lg">
            <button
              onClick={() => setActiveTab("all")}
              className={cn(
                "text-[10px] font-mono uppercase px-2.5 py-1 rounded transition-colors cursor-pointer",
                activeTab === "all"
                  ? "bg-white text-black font-semibold"
                  : "text-neutral-400 hover:text-white"
              )}
            >
              All On-Chain
            </button>
            <button
              onClick={() => setActiveTab("session")}
              className={cn(
                "text-[10px] font-mono uppercase px-2.5 py-1 rounded transition-colors cursor-pointer",
                activeTab === "session"
                  ? "bg-white text-black font-semibold"
                  : "text-neutral-400 hover:text-white"
              )}
            >
              My Session ({sessionTrades.length})
            </button>
          </div>
        </div>
      </div>

      {/* Trades List */}
      {displayedTrades.length > 0 ? (
        <div className="flex flex-col gap-2 max-h-[360px] overflow-y-auto pr-1">
          {displayedTrades.map((trade) => (
            <div
              key={trade.id}
              className="bg-[#141414] rounded-xl p-3 flex items-center justify-between transition-colors hover:bg-white/[0.02]"
            >
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "uppercase tracking-wider text-[10px] font-mono font-semibold px-2 py-0.5 rounded",
                    trade.type === "buy"
                      ? "text-[#22c55e] bg-[#22c55e]/10"
                      : "text-[#ef4444] bg-[#ef4444]/10"
                  )}
                >
                  {trade.type}
                </span>
                <span className="font-mono text-xs text-neutral-300">
                  {trade.wallet}
                </span>
              </div>

              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-white font-medium">
                  {trade.volumeUsd !== undefined && trade.volumeUsd > 0
                    ? `$${trade.volumeUsd.toFixed(2)}`
                    : `${trade.amountPay.toFixed(4)} ${gasSymbol}`}
                </span>

                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-neutral-500">
                    {trade.timestamp}
                  </span>
                  {trade.explorerUrl && (
                    <a
                      href={trade.explorerUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] font-mono text-neutral-400 hover:text-white underline"
                    >
                      tx
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-[#141414] rounded-xl p-6 text-center">
          <p className="text-xs font-mono text-neutral-400">
            {loading && activeTab === "all"
              ? "Fetching live on-chain trades..."
              : activeTab === "session"
              ? "No trades executed in this session yet. Orders submitted above settle on-chain and appear here with block explorer receipts."
              : "No recent on-chain transactions indexed for this pool yet."}
          </p>
        </div>
      )}
    </div>
  );
}
