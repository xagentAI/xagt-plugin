"use client";

import { useState } from "react";
import Link from "next/link";
import {
  IconCopy,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconWorld,
  IconBrandX,
  IconBrandTelegram,
  IconChartCandle,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";

export interface TerminalToken {
  id: string;
  launchpad: string;
  network: string;
  pool_address: string | null;
  volume_24h: number;
  market_cap: number;
  fdv: number;
  price_usd: number;
  price_change_24h: number;
  time_ago: string;
  category: "trending" | "final_stretch" | "migrated" | "new";
  progress: number;
  dev_holding_pct: number;
  top_10_pct: number;
  snipers_pct: number;
  holders_count: number;
  tokens: {
    id: string;
    name: string;
    symbol: string;
    mint_address: string;
    image_url: string;
    header_url: string | null;
    description: string;
    socials: {
      website?: string;
      twitter?: string;
      telegram?: string;
    };
  };
}

interface TerminalColumnBoardProps {
  columns: {
    final_stretch: TerminalToken[];
    migrated: TerminalToken[];
    new_pairs: TerminalToken[];
  };
  columnCounts?: {
    final_stretch: number;
    migrated: number;
    new_pairs: number;
  };
  pagination?: {
    page: number;
    limit: number;
    totalLaunches: number;
    totalPages: number;
  };
  onPageChange?: (page: number) => void;
  onQuickBuy?: (token: TerminalToken, solAmount: number) => void;
}

function formatUSD(num: number): string {
  if (!num) return "$0";
  if (num >= 1_000_000_000) return `$${(num / 1_000_000_000).toFixed(2)}B`;
  if (num >= 1_000_000) return `$${(num / 1_000_000).toFixed(2)}M`;
  if (num >= 1_000) return `$${(num / 1_000).toFixed(1)}K`;
  return `$${num.toFixed(2)}`;
}

export function TerminalColumnBoard({
  columns,
  columnCounts,
  pagination,
  onPageChange,
  onQuickBuy,
}: TerminalColumnBoardProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [quickBuyAmount, setQuickBuyAmount] = useState<number>(1);

  const handleCopyAddress = (e: React.MouseEvent, address: string, id: string) => {
    e.stopPropagation();
    e.preventDefault();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(address);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  const columnConfig = [
    {
      key: "final_stretch",
      title: "Final Stretch",
      subtitle: "Bonding curve completing",
      totalCount: columnCounts?.final_stretch ?? (columns.final_stretch?.length || 0),
      tokens: columns.final_stretch || [],
    },
    {
      key: "migrated",
      title: "Migrated",
      subtitle: "Raydium and DEX pools",
      totalCount: columnCounts?.migrated ?? (columns.migrated?.length || 0),
      tokens: columns.migrated || [],
    },
    {
      key: "new_pairs",
      title: "New Pairs",
      subtitle: "Recent token launches",
      totalCount: columnCounts?.new_pairs ?? (columns.new_pairs?.length || 0),
      tokens: columns.new_pairs || [],
    },
  ];

  const currentPage = pagination?.page || 1;
  const totalPages = pagination?.totalPages || 1;
  const totalItems = pagination?.totalLaunches || 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Quick Amount Selector Bar */}
      <div className="bg-[#181818] border border-white/[0.04] px-5 py-3.5 rounded-2xl flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-sans font-medium text-neutral-400">Quick Buy Preset:</span>
          {[0.1, 0.5, 1, 5, 10].map((amt) => (
            <button
              key={amt}
              onClick={() => setQuickBuyAmount(amt)}
              className={cn(
                "px-3.5 py-1.5 text-xs font-mono rounded-full transition-colors cursor-pointer",
                quickBuyAmount === amt
                  ? "bg-white text-black font-semibold"
                  : "bg-[#141414] text-neutral-400 hover:text-white border border-white/[0.06]"
              )}
            >
              {amt} SOL
            </button>
          ))}
        </div>

        <div className="text-xs font-mono text-neutral-400 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span>Real-time Decentralized Feed</span>
        </div>
      </div>

      {/* 3 Columns Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {columnConfig.map((col) => (
          <div
            key={col.key}
            className="flex flex-col bg-[#181818] border border-white/[0.04] rounded-2xl overflow-hidden"
          >
            {/* Column Header */}
            <div className="p-5 border-b border-white/[0.04] flex items-center justify-between bg-white/[0.01]">
              <div>
                <h3 className="text-sm font-semibold text-white font-sans">
                  {col.title}
                </h3>
                <p className="text-xs text-neutral-400 font-sans mt-0.5">
                  {col.subtitle}
                </p>
              </div>
              <span className="text-xs font-mono text-neutral-400 bg-white/[0.04] px-2.5 py-1 rounded-full border border-white/[0.04]">
                {col.totalCount}
              </span>
            </div>

            {/* Column Tokens List */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-[500px]">
              {col.tokens.map((item) => {
                const t = item.tokens;
                const isCopied = copiedId === item.id;
                const net = item.network?.toLowerCase() || "";
                const gas = net === "bsc" ? "BNB" : net === "robinhood" ? "ETH" : "SOL";

                return (
                  <div
                    key={item.id}
                    className="p-4 bg-[#141414] hover:bg-[#161616] border border-white/[0.04] hover:border-white/[0.08] rounded-xl transition-all flex flex-col gap-3.5"
                  >
                    {/* Top Row: Thumbnail + Ticker/Name + Price/MC */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-black/40 border border-white/[0.06] flex-shrink-0 overflow-hidden">
                          <img
                            src={t.image_url}
                            alt={t.name}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              (e.target as HTMLImageElement).src = `https://api.dicebear.com/7.x/identicon/svg?seed=${t.symbol}`;
                            }}
                          />
                        </div>

                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-semibold text-white truncate font-sans">
                              {t.name}
                            </span>
                            <button
                              onClick={(e) => handleCopyAddress(e, t.mint_address || item.id, item.id)}
                              className="text-neutral-500 hover:text-neutral-300 transition-colors p-0.5"
                              title="Copy contract address"
                            >
                              {isCopied ? <IconCheck size={12} className="text-emerald-400" /> : <IconCopy size={12} />}
                            </button>
                          </div>

                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs font-mono text-neutral-300">
                              ${t.symbol}
                            </span>
                            <span className="text-[11px] font-mono text-neutral-500">
                              {item.time_ago}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right: MC & Volume */}
                      <div className="text-right flex-shrink-0 font-mono">
                        <div className="text-xs text-white font-medium">
                          MC: {formatUSD(item.market_cap)}
                        </div>
                        <div className="text-[11px] text-neutral-500">
                          Vol: {formatUSD(item.volume_24h)}
                        </div>
                      </div>
                    </div>

                    {/* Middle Row: On-chain Holder Metrics */}
                    <div className="grid grid-cols-4 gap-2 py-2 px-3 bg-[#101010] rounded-lg border border-white/[0.03] text-[10px] font-mono text-neutral-400">
                      <div>
                        <span className="text-neutral-500 block">Holders</span>
                        <span className="text-white">{item.holders_count}</span>
                      </div>
                      <div>
                        <span className="text-neutral-500 block">Top 10</span>
                        <span className="text-neutral-300">{item.top_10_pct}%</span>
                      </div>
                      <div>
                        <span className="text-neutral-500 block">Dev</span>
                        <span className="text-neutral-300">{item.dev_holding_pct}%</span>
                      </div>
                      <div>
                        <span className="text-neutral-500 block">Snipers</span>
                        <span className="text-neutral-300">{item.snipers_pct}%</span>
                      </div>
                    </div>

                    {/* Bonding curve progress bar */}
                    {item.progress > 0 && (
                      <div className="w-full flex flex-col gap-1.5">
                        <div className="flex justify-between text-[10px] font-mono text-neutral-500">
                          <span>Curve Progress</span>
                          <span className="text-emerald-400">{item.progress}%</span>
                        </div>
                        <div className="w-full h-1.5 bg-neutral-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-emerald-400 transition-all duration-300 rounded-full"
                            style={{ width: `${item.progress}%` }}
                          />
                        </div>
                      </div>
                    )}

                    {/* Bottom Row: Social links + Actions */}
                    <div className="flex items-center justify-between pt-2 border-t border-white/[0.04]">
                      {/* Social & DEX Icons */}
                      <div className="flex items-center gap-1 text-neutral-400">
                        {t.socials.website && (
                          <a
                            href={t.socials.website}
                            target="_blank"
                            rel="noreferrer"
                            title="Website"
                            className="p-1.5 hover:text-white hover:bg-white/[0.05] rounded-lg transition-colors"
                          >
                            <IconWorld size={14} />
                          </a>
                        )}
                        {t.socials.twitter && (
                          <a
                            href={t.socials.twitter}
                            target="_blank"
                            rel="noreferrer"
                            title="X (Twitter)"
                            className="p-1.5 hover:text-white hover:bg-white/[0.05] rounded-lg transition-colors"
                          >
                            <IconBrandX size={14} />
                          </a>
                        )}
                        {t.socials.telegram && (
                          <a
                            href={t.socials.telegram}
                            target="_blank"
                            rel="noreferrer"
                            title="Telegram"
                            className="p-1.5 hover:text-white hover:bg-white/[0.05] rounded-lg transition-colors"
                          >
                            <IconBrandTelegram size={14} />
                          </a>
                        )}
                        <a
                          href={`https://dexscreener.com/${item.network.toLowerCase()}/${item.id}`}
                          target="_blank"
                          rel="noreferrer"
                          title="DexScreener"
                          className="p-1.5 hover:text-white hover:bg-white/[0.05] rounded-lg transition-colors"
                        >
                          <IconChartCandle size={14} />
                        </a>
                      </div>

                      {/* Quick Buy & Trade buttons */}
                      <div className="flex items-center gap-2">
                        {onQuickBuy && (
                          <button
                            onClick={() => onQuickBuy(item, quickBuyAmount)}
                            className="px-3 py-1.5 text-xs font-mono text-neutral-300 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] rounded-full border border-white/[0.06] transition-colors cursor-pointer"
                          >
                            Buy {quickBuyAmount} {gas}
                          </button>
                        )}

                        <Link
                          href={`/dashboard/trade/${item.id}?fromPage=${currentPage}`}
                          className="px-4 py-1.5 text-xs font-sans font-semibold text-black bg-white hover:bg-neutral-200 rounded-full transition-colors"
                        >
                          Trade
                        </Link>
                      </div>
                    </div>
                  </div>
                );
              })}

              {col.tokens.length === 0 && (
                <div className="py-16 text-center text-xs font-sans text-neutral-500 bg-[#141414] rounded-xl border border-dashed border-white/[0.04]">
                  No active tokens in this category
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="border border-white/[0.04] bg-[#181818] p-4 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="text-xs font-mono text-neutral-400">
            Showing page {currentPage} of {totalPages} ({totalItems} total tokens)
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange && onPageChange(currentPage - 1)}
              disabled={currentPage === 1}
              className="px-3.5 py-1.5 text-xs font-sans font-medium bg-white/[0.05] hover:bg-white/[0.1] disabled:opacity-30 text-white rounded-full transition-colors flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
            >
              <IconChevronLeft size={14} />
              <span>Previous</span>
            </button>

            {/* Page number buttons */}
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum = i + 1;
                if (totalPages > 5 && currentPage > 3) {
                  pageNum = Math.min(currentPage - 2 + i, totalPages - (4 - i));
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => onPageChange && onPageChange(pageNum)}
                    className={cn(
                      "w-8 h-8 text-xs font-mono rounded-full transition-colors cursor-pointer",
                      currentPage === pageNum
                        ? "bg-white text-black font-semibold"
                        : "bg-[#141414] text-neutral-400 hover:text-white border border-white/[0.06]"
                    )}
                  >
                    {pageNum}
                  </button>
                );
              })}
            </div>

            <button
              onClick={() => onPageChange && onPageChange(currentPage + 1)}
              disabled={currentPage === totalPages}
              className="px-3.5 py-1.5 text-xs font-sans font-medium bg-white/[0.05] hover:bg-white/[0.1] disabled:opacity-30 text-white rounded-full transition-colors flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
            >
              <span>Next</span>
              <IconChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
