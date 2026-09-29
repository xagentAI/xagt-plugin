"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { TradeForm } from "@/components/trade/trade-form";
import { TradeHistory, ExecutedTrade } from "@/components/trade/trade-history";
import { CandlestickChart } from "@/components/trade/candlestick-chart";
import { IconArrowLeft, IconRefresh, IconCopy, IconCheck } from "@tabler/icons-react";

interface TokenData {
  id: string;
  name: string;
  symbol: string;
  mint_address: string | null;
  supply: string;
  decimals: number;
}

interface LaunchData {
  id: string;
  launchpad: string;
  network: string;
  pool_address: string | null;
  pair_address?: string | null;
  chain_id?: string | null;
  volume_24h: number;
  market_cap?: number;
  price_usd?: number;
  price_native?: number;
  price_change_24h?: number;
  txns_24h?: { buys: number; sells: number };
  initial_liquidity: number | null;
  tokens: TokenData;
}

export default function TradePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [launch, setLaunch] = useState<LaunchData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedContract, setCopiedContract] = useState(false);
  const [sessionTrades, setSessionTrades] = useState<ExecutedTrade[]>([]);

  const fetchDetails = async () => {
    try {
      const res = await fetch(`/api/launches/${id}`);
      if (!res.ok) {
        throw new Error("Failed to fetch launch details");
      }
      const data = await res.json();
      setLaunch(data.launch);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
    // Poll live DEX data every 12 seconds without random fluctuations
    const pollInterval = setInterval(() => {
      fetchDetails();
    }, 12000);
    return () => clearInterval(pollInterval);
  }, [id]);

  const handleTradeSuccess = (trade?: ExecutedTrade) => {
    if (trade) {
      setSessionTrades((prev) => [trade, ...prev]);
    }
    fetchDetails();
  };

  const handleCopy = (address: string) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(address);
      setCopiedContract(true);
      setTimeout(() => setCopiedContract(false), 2000);
    }
  };

  const handleBackToExplore = () => {
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      const fromPage = urlParams.get("fromPage") || sessionStorage.getItem("explore_page");
      if (window.history.length > 1) {
        window.history.back();
      } else {
        window.location.href =
          fromPage && fromPage !== "1"
            ? `/dashboard/explore?page=${fromPage}`
            : "/dashboard/explore";
      }
    }
  };

  if (loading) {
    return (
      <div className="p-6 md:p-10 max-w-[1400px] mx-auto flex items-center justify-center min-h-[50vh]">
        <div className="text-xs text-neutral-500 font-mono">Loading trade terminal...</div>
      </div>
    );
  }

  if (error || !launch) {
    return (
      <div className="p-6 md:p-10 max-w-[1400px] mx-auto flex flex-col gap-4 max-w-md">
        <div className="text-xs text-red-400 font-mono bg-[#181818] p-5 rounded-2xl">
          {error || "Launch details not found."}
        </div>
        <button
          onClick={handleBackToExplore}
          className="text-xs text-white hover:text-neutral-300 font-sans flex items-center gap-1.5 cursor-pointer"
        >
          <IconArrowLeft size={14} /> Back to Trade &amp; Explore
        </button>
      </div>
    );
  }

  const token = launch.tokens;
  const rawNetwork = launch.network.toLowerCase();
  const gasSymbol = rawNetwork === "bsc" ? "BNB" : rawNetwork === "robinhood" ? "ETH" : "SOL";
  const currentPrice = launch.price_usd || launch.price_native || 0;
  const pairAddress = launch.pair_address || launch.pool_address;
  const chainId = launch.chain_id || (rawNetwork === "bsc" ? "bsc" : "solana");

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto flex flex-col gap-6">
      {/* Navigation Toolbar */}
      <div className="flex items-center justify-between">
        <button
          onClick={handleBackToExplore}
          className="text-xs text-neutral-400 hover:text-white bg-[#181818] hover:bg-white/[0.06] px-3.5 py-1.5 rounded-full transition-colors font-sans flex items-center gap-1.5 cursor-pointer"
        >
          <IconArrowLeft size={14} />
          <span>Back to Explore</span>
        </button>
        <button
          onClick={fetchDetails}
          className="text-xs text-neutral-400 hover:text-white bg-[#181818] hover:bg-white/[0.06] px-3.5 py-1.5 rounded-full transition-colors font-sans flex items-center gap-1.5 cursor-pointer"
        >
          <IconRefresh size={14} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Title & Info Banner */}
      <div className="bg-[#181818] p-6 rounded-2xl flex flex-col gap-5">
        <div className="flex items-center gap-3 flex-wrap justify-between">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
              {token.name}
            </h1>
            <span className="font-mono text-xs text-neutral-300 px-2.5 py-0.5 rounded-full bg-white/[0.06]">
              ${token.symbol}
            </span>
          </div>

          {currentPrice > 0 && (
            <div className="font-mono text-xs px-3 py-1 rounded-full bg-[#141414] text-neutral-300 font-semibold">
              Price: {currentPrice < 0.0001 ? `$${currentPrice.toFixed(8)}` : `$${currentPrice.toFixed(4)}`}
            </div>
          )}
        </div>
        
        {/* Metadata Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4">
          <div className="bg-[#141414] rounded-xl p-3">
            <span className="text-[10px] font-sans font-medium uppercase tracking-wider text-neutral-500 block">
              Launchpad
            </span>
            <span className="text-xs font-mono font-medium text-white block mt-1">
              {launch.launchpad}
            </span>
          </div>
          <div className="bg-[#141414] rounded-xl p-3">
            <span className="text-[10px] font-sans font-medium uppercase tracking-wider text-neutral-500 block">
              Network
            </span>
            <span className="text-xs font-mono font-medium text-white block mt-1 capitalize">
              {launch.network}
            </span>
          </div>
          <div className="bg-[#141414] rounded-xl p-3">
            <span className="text-[10px] font-sans font-medium uppercase tracking-wider text-neutral-500 block">
              Contract
            </span>
            <div className="flex items-center justify-between gap-1.5 mt-1">
              <span className="text-xs font-mono font-medium text-white truncate select-all">
                {pairAddress ? `${pairAddress.substring(0, 6)}...${pairAddress.substring(pairAddress.length - 4)}` : "None"}
              </span>
              {pairAddress && (
                <button
                  onClick={() => handleCopy(pairAddress)}
                  className="text-neutral-500 hover:text-white transition-colors p-0.5"
                  title="Copy address"
                >
                  {copiedContract ? <IconCheck size={12} className="text-emerald-400" /> : <IconCopy size={12} />}
                </button>
              )}
            </div>
          </div>
          <div className="bg-[#141414] rounded-xl p-3">
            <span className="text-[10px] font-sans font-medium uppercase tracking-wider text-neutral-500 block">
              24h Volume
            </span>
            <span className="text-xs font-mono font-medium text-white block mt-1">
              ${Number(launch.volume_24h || 0).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left/Middle Column - Chart & Trade History */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          <CandlestickChart
            currentPrice={currentPrice}
            priceDirection="flat"
            gasSymbol={gasSymbol}
            pairAddress={pairAddress}
            chainId={chainId}
            tokenSymbol={token.symbol}
          />

          {/* Trade History Widget */}
          <TradeHistory
            launchId={launch.id}
            gasSymbol={gasSymbol}
            pairAddress={pairAddress}
            network={rawNetwork}
            sessionTrades={sessionTrades}
            txns24h={launch.txns_24h}
          />
        </div>

        {/* Right Column - Trade Panel & Token Info */}
        <div className="flex flex-col gap-6">
          <TradeForm launch={launch} onTradeSuccess={handleTradeSuccess} />
          
          {/* Mini Stats Card */}
          <div className="bg-[#181818] p-6 rounded-2xl flex flex-col gap-4">
            <div className="text-xs font-sans font-medium uppercase tracking-wider text-neutral-400">
              Launch Details
            </div>
            <div className="flex flex-col gap-2.5">
              <div className="bg-[#141414] rounded-xl p-3 flex justify-between items-center text-xs font-mono">
                <span className="text-neutral-400">Total Supply</span>
                <span className="text-white font-medium">{Number(token.supply).toLocaleString()}</span>
              </div>
              <div className="bg-[#141414] rounded-xl p-3 flex justify-between items-center text-xs font-mono">
                <span className="text-neutral-400">Market Cap</span>
                <span className="text-white font-medium">
                  {launch.market_cap ? `$${Number(launch.market_cap).toLocaleString()}` : "Pending"}
                </span>
              </div>
              <div className="bg-[#141414] rounded-xl p-3 flex justify-between items-center text-xs font-mono">
                <span className="text-neutral-400">Token Decimals</span>
                <span className="text-white font-medium">{token.decimals}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
