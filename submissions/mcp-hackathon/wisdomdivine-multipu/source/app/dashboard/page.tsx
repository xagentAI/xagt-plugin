"use client";

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import {
  IconExternalLink,
  IconCopy,
  IconChevronDown,
  IconArrowRight,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/use-api";
import { StatsSkeleton, ListSkeleton } from "@/components/skeleton";
import { DataError } from "@/components/error-boundary";
import { ExposureTimelineChart } from "@/components/dashboard/exposure-timeline-chart";
import { toast } from "sonner";

interface DashboardToken {
  id: string;
  name: string;
  symbol: string;
  mint_address: string | null;
  image_url?: string | null;
  supply: string;
  status: string;
  created_at: string;
  launches: {
    id: string;
    launchpad: string;
    status: string;
    pool_address: string | null;
  }[];
}

interface DashboardData {
  stats: {
    totalTokens: number;
    tokensChange?: string;
    tokensChangeColor?: string;
    activeLaunches: number;
    launchesChange?: string;
    launchesChangeColor?: string;
    totalEarnings: number;
    earningsChange?: string;
    earningsChangeColor?: string;
    earningsToday: number;
    launchpadsUsed: string[];
    launchpadsChange?: string;
    launchpadsChangeColor?: string;
  };
  exposure?: {
    total: string;
    change: string;
    period: string;
    points: { date: string; value: number }[];
  };
  tokens: DashboardToken[];
  recentEarnings: {
    id: string;
    amount: number;
    launchpad: string;
    created_at: string;
  }[];
}

const launchpadImages: Record<string, string> = {
  meteora: "/meteora.png",
  bags: "/bags.png",
  pumpfun: "/pumpfun.png",
  fourmeme: "/four-meme.png",
  pons: "/pons.png",
};

const launchpadNames: Record<string, string> = {
  meteora: "Meteora",
  bags: "Bags",
  pumpfun: "Pump.fun",
  fourmeme: "Four.meme",
  pons: "Pons",
};

function formatAddress(addr: string | null) {
  if (!addr) return "—";
  return `${addr.slice(0, 4)}...${addr.slice(-4)}`;
}

function timeAgo(dateStr: string) {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function DashboardPage() {
  const { data, loading, error, refetch } = useApi<DashboardData>("/api/dashboard");
  const [selectedToken, setSelectedToken] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "name" | "launches">("newest");
  const [sortOpen, setSortOpen] = useState(false);

  const stats = data?.stats;
  const rawTokens = data?.tokens || [];
  const [hasAutoOpened, setHasAutoOpened] = useState(false);

  useEffect(() => {
    if (!hasAutoOpened && rawTokens.length > 0) {
      setSelectedToken(rawTokens[0].id);
      setHasAutoOpened(true);
    }
  }, [rawTokens, hasAutoOpened]);

  const toggleToken = (id: string) => {
    setSelectedToken((prev) => (prev === id ? null : id));
  };

  const tokens = useMemo(() => {
    const list = [...rawTokens];
    if (sortBy === "newest") {
      list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    } else if (sortBy === "oldest") {
      list.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    } else if (sortBy === "name") {
      list.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "launches") {
      list.sort((a, b) => (b.launches?.length || 0) - (a.launches?.length || 0));
    }
    return list;
  }, [rawTokens, sortBy]);

  const statItems = [
    {
      label: "Total Tokens",
      value: stats?.totalTokens !== undefined ? stats.totalTokens.toString() : tokens.length.toString(),
      change: stats?.tokensChange || (tokens.length ? `+${tokens.length} new` : "none"),
      changeColor: stats?.tokensChangeColor || "text-neutral-400",
    },
    {
      label: "Active Launches",
      value: stats?.activeLaunches !== undefined ? stats.activeLaunches.toString() : "0",
      change: stats?.launchesChange || "no launches",
      changeColor: stats?.launchesChangeColor || "text-neutral-400",
    },
    {
      label: "Total Earnings",
      value: `${(stats?.totalEarnings !== undefined ? stats.totalEarnings : 0).toFixed(2)} SOL`,
      change: stats?.earningsChange || "0.00 SOL",
      changeColor: stats?.earningsChangeColor || "text-neutral-400",
    },
    {
      label: "Launchpads Used",
      value: stats?.launchpadsUsed !== undefined ? stats.launchpadsUsed.length.toString() : "0",
      change: stats?.launchpadsChange || "none",
      changeColor: stats?.launchpadsChangeColor || "text-neutral-400",
    },
  ];

  return (
    <div className="p-6 md:p-10 max-w-[1400px]">
      {/* Header */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={stagger}
        className="mb-8"
      >
        <motion.div
          variants={fadeUp}
          className="flex items-center justify-between"
        >
          <div>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
              Overview
            </h1>
            <p className="mt-1 text-sm text-neutral-400 font-sans">
              Tracking multi-chain launches, DEX terminal, and live earnings.
            </p>
          </div>
          <Link
            href="/launch"
            className="hidden md:inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
          >
            Launch Token
          </Link>
        </motion.div>
      </motion.div>

      {/* Loading Skeleton */}
      {loading && (
        <>
          <StatsSkeleton count={4} />
          <ListSkeleton count={3} />
        </>
      )}

      {/* Error State */}
      {error && !loading && (
        <DataError message={error} onRetry={refetch} />
      )}

      {/* Content */}
      {!loading && !error && (
        <>
          {/* Top Metric Cards matching Screenshot */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
          >
            {statItems.map((stat) => (
              <motion.div
                key={stat.label}
                variants={fadeUp}
                className="bg-[#181818] rounded-2xl p-5 sm:p-6 flex flex-col justify-between min-h-[150px] hover:bg-[#1f1f1f] transition-colors"
              >
                <div className="text-neutral-400 font-medium text-xs sm:text-sm font-sans">
                  {stat.label}
                </div>

                <div className="my-2">
                  <span className="text-3xl sm:text-4xl font-semibold font-mono tracking-tight text-white">
                    {stat.value}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs font-mono pt-1">
                  <span className="text-neutral-500">last 30 days</span>
                  <span className={cn("font-medium", stat.changeColor)}>
                    {stat.change}
                  </span>
                </div>
              </motion.div>
            ))}
          </motion.div>

          {/* Exposure Timeline Card using recharts and connected to backend data */}
          <motion.div variants={fadeUp}>
            <ExposureTimelineChart initialData={data?.exposure} />
          </motion.div>

          {/* Tokens Section in Matte Rounded Container */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="rounded-2xl bg-[#181818] p-6 sm:p-8"
          >
            <motion.div
              variants={fadeUp}
              className="flex items-center justify-between mb-6 relative"
            >
              <h2 className="text-base font-semibold text-white font-sans">
                Your Tokens
              </h2>

              {/* Sort Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setSortOpen(!sortOpen)}
                  className="font-mono text-xs text-neutral-400 hover:text-white transition-colors flex items-center gap-2 px-3 py-1.5 bg-white/[0.04] hover:bg-white/[0.08] rounded-xl cursor-pointer"
                >
                  <span>Sort: <strong className="text-white uppercase">{sortBy}</strong></span>
                  <IconChevronDown size={12} className={cn(sortOpen && "rotate-180 transition-transform")} />
                </button>

                {sortOpen && (
                  <div className="absolute right-0 top-full mt-2 z-30 w-36 bg-[#212121] rounded-xl p-1 font-mono text-xs">
                    {(["newest", "oldest", "name", "launches"] as const).map((s) => (
                      <button
                        key={s}
                        onClick={() => {
                          setSortBy(s);
                          setSortOpen(false);
                        }}
                        className={cn(
                          "w-full text-left px-3 py-2 uppercase tracking-wider text-[11px] rounded-lg transition-colors cursor-pointer",
                          sortBy === s
                            ? "bg-white/[0.1] text-white font-semibold"
                            : "text-neutral-400 hover:text-white hover:bg-white/[0.04]"
                        )}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>

            {tokens.length > 0 ? (
              <motion.div
                variants={fadeUp}
                className="space-y-3"
              >
                {tokens.map((token) => {
                  const totalLive = (token.launches || []).filter(
                    (l) => l.status === "live"
                  ).length;
                  const isExpanded = selectedToken === token.id;
                  const isPending = token.status === "pending" || totalLive === 0;

                  return (
                    <div
                      key={token.id}
                      className="rounded-xl p-5 bg-[#141414] border border-white/[0.04] hover:border-white/[0.08] transition-all"
                    >
                      <div
                        onClick={() => toggleToken(token.id)}
                        className="w-full flex items-center justify-between cursor-pointer select-none gap-4"
                      >
                        <div className="flex items-center gap-3.5 min-w-0 flex-1">
                          <div className="relative w-10 h-10 rounded-xl bg-white/[0.05] border border-white/[0.08] flex items-center justify-center flex-shrink-0 overflow-hidden">
                            {token.image_url ? (
                              <Image
                                src={token.image_url}
                                alt={token.name}
                                fill
                                sizes="40px"
                                className="object-cover"
                              />
                            ) : (
                              <span className="font-mono text-xs font-semibold text-white">
                                {token.symbol?.slice(0, 3) || "TK"}
                              </span>
                            )}
                          </div>

                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-semibold text-white truncate">
                                {token.name}
                              </span>
                              <span className="font-mono text-xs text-neutral-400">
                                ${token.symbol}
                              </span>
                              <span className="font-mono text-[11px] px-2 py-0.5 text-neutral-300 bg-white/[0.06] rounded-full capitalize">
                                {token.status}
                              </span>
                            </div>
                            <div className="flex items-center gap-3 mt-1 font-mono text-[11px] text-neutral-500">
                              <span>{formatAddress(token.mint_address)}</span>
                              <span>{timeAgo(token.created_at)}</span>
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-3 flex-shrink-0">
                          {isPending ? (
                            <Link
                              href={`/launch?resume=${token.id}`}
                              onClick={(e) => e.stopPropagation()}
                              className="hidden sm:inline-flex items-center px-3 py-1 bg-white text-black text-xs font-semibold rounded-lg hover:bg-neutral-200 transition-colors cursor-pointer font-sans"
                            >
                              Launch
                            </Link>
                          ) : (
                            <div className="hidden sm:flex items-center gap-1.5">
                              {token.launches.map((launch) => (
                                <div
                                  key={launch.id}
                                  className="flex items-center gap-1.5 px-2 py-0.5 bg-white/[0.04] rounded text-xs font-mono text-neutral-300"
                                >
                                  <span
                                    className={cn(
                                      "w-1.5 h-1.5 rounded-full",
                                      launch.status === "live"
                                        ? "bg-emerald-400"
                                        : "bg-amber-400"
                                    )}
                                  />
                                  <span>
                                    {launchpadNames[launch.launchpad] ||
                                      launch.launchpad}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}

                          <div className="text-right font-mono text-xs text-neutral-400">
                            {totalLive} live
                          </div>

                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleToken(token.id);
                            }}
                            className="p-1 text-neutral-400 hover:text-white transition-colors cursor-pointer"
                            aria-label={isExpanded ? "Collapse token details" : "Expand token details"}
                          >
                            <IconChevronDown
                              size={16}
                              className={cn(
                                "transition-transform",
                                isExpanded && "rotate-180 text-white"
                              )}
                            />
                          </button>
                        </div>
                      </div>

                      {/* Expandable Token Details Panel */}
                      <AnimatePresence>
                        {isExpanded && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            className="mt-5 pt-5 border-t border-white/[0.06]"
                          >
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {/* Token Details Card */}
                              <div className="bg-[#181818] rounded-xl p-5 border border-white/[0.04] space-y-4">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-semibold text-neutral-300 font-sans tracking-wide">
                                    Token Details
                                  </span>
                                  <Link
                                    href="/dashboard/tokens"
                                    className="text-xs text-neutral-400 hover:text-white transition-colors flex items-center gap-1 font-sans"
                                  >
                                    <span>Manage in Tokens</span>
                                    <IconArrowRight size={12} />
                                  </Link>
                                </div>

                                <div className="space-y-2.5">
                                  {[
                                    {
                                      label: "Address",
                                      value: formatAddress(token.mint_address),
                                      raw: token.mint_address,
                                    },
                                    {
                                      label: "Supply",
                                      value: Number(token.supply).toLocaleString(),
                                    },
                                    {
                                      label: "Created",
                                      value: timeAgo(token.created_at),
                                    },
                                    {
                                      label: "Status",
                                      value: token.status,
                                    },
                                  ].map((row) => (
                                    <div
                                      key={row.label}
                                      className="flex items-center justify-between text-xs font-mono"
                                    >
                                      <span className="text-neutral-400">
                                        {row.label}
                                      </span>
                                      <span className="text-white font-medium flex items-center gap-1.5">
                                        {row.value}
                                        {row.label === "Address" && row.raw && (
                                          <IconCopy
                                            size={12}
                                            className="text-neutral-400 hover:text-white cursor-pointer"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              navigator.clipboard.writeText(row.raw!);
                                              toast.success("Mint Address copied!");
                                            }}
                                          />
                                        )}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>

                              {/* Launches & DEX Pools Card */}
                              <div className="bg-[#181818] rounded-xl p-5 border border-white/[0.04] flex flex-col justify-between">
                                <div>
                                  <div className="text-xs font-semibold text-neutral-300 font-sans tracking-wide mb-3">
                                    Launches &amp; DEX Pools
                                  </div>

                                  {token.launches && token.launches.length > 0 ? (
                                    <div className="space-y-2">
                                      {token.launches.map((launch) => (
                                        <div
                                          key={launch.id}
                                          className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]"
                                        >
                                          <div className="flex items-center gap-2">
                                            <div className="relative w-5 h-5 rounded-md overflow-hidden">
                                              <Image
                                                src={
                                                  launchpadImages[launch.launchpad] ||
                                                  "/meteora.png"
                                                }
                                                alt={launch.launchpad}
                                                fill
                                                className="object-cover"
                                              />
                                            </div>
                                            <span className="text-xs font-medium text-white capitalize">
                                              {launchpadNames[launch.launchpad] ||
                                                launch.launchpad}
                                            </span>
                                            <span
                                              className={cn(
                                                "text-[10px] font-mono px-1.5 py-0.2 rounded-full",
                                                launch.status === "live"
                                                  ? "bg-emerald-500/10 text-emerald-400"
                                                  : "bg-amber-500/10 text-amber-400"
                                              )}
                                            >
                                              {launch.status}
                                            </span>
                                          </div>
                                          <div className="flex items-center gap-2">
                                            {launch.status === "live" && (
                                              <Link
                                                href={`/dashboard/trade/${launch.id}`}
                                                className="text-xs font-mono text-white hover:underline px-2 py-0.5 rounded bg-white/[0.06] cursor-pointer"
                                              >
                                                Trade
                                              </Link>
                                            )}
                                            <span className="font-mono text-xs text-neutral-400">
                                              {formatAddress(launch.pool_address)}
                                            </span>
                                            {launch.pool_address && (
                                              <IconExternalLink
                                                size={12}
                                                className="text-neutral-400 hover:text-white cursor-pointer"
                                              />
                                            )}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="py-2">
                                      <p className="text-xs text-neutral-400 font-sans leading-relaxed">
                                        No active pools dispatched yet for this token.
                                      </p>
                                    </div>
                                  )}
                                </div>

                                {(!token.launches || token.launches.length === 0) && (
                                  <div className="pt-3">
                                    <Link
                                      href={`/launch?resume=${token.id}`}
                                      className="px-4 py-2 bg-white text-black hover:bg-neutral-200 text-xs font-semibold rounded-xl transition-colors cursor-pointer inline-flex items-center font-sans"
                                    >
                                      Dispatch to Launchpads
                                    </Link>
                                  </div>
                                )}
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  );
                })}
              </motion.div>
            ) : (
              <div className="rounded-xl border border-white/[0.06] p-12 text-center bg-[#141414]">
                <h3 className="text-base font-semibold text-white mb-2 font-sans">
                  No tokens yet
                </h3>
                <p className="text-sm text-neutral-400 mb-6 font-sans">
                  Launch your first token to get started.
                </p>
                <Link
                  href="/launch"
                  className="inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
                >
                  Launch Token
                </Link>
              </div>
            )}
          </motion.div>
        </>
      )}
    </div>
  );
}
