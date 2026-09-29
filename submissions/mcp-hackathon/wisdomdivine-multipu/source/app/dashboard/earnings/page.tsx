"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import { IconTrendingUp, IconArrowUpRight } from "@tabler/icons-react";
import { useApi } from "@/hooks/use-api";
import { StatsSkeleton, ListSkeleton } from "@/components/skeleton";
import { DataError } from "@/components/error-boundary";

interface EarningEntry {
  id: string;
  amount: number;
  launchpad: string;
  token_id: string;
  tx_signature: string | null;
  created_at: string;
}

interface EarningsResponse {
  earnings: EarningEntry[];
  summary: {
    total: number;
    byLaunchpad: Record<string, number>;
    count: number;
  };
}

const launchpadImages: Record<string, string> = {
  meteora: "/meteora.png",
  bags: "/bags.png",
  pumpfun: "/pumpfun.png",
};

const launchpadNames: Record<string, string> = {
  meteora: "Meteora",
  bags: "Bags",
  pumpfun: "Pump.fun",
};

function timeAgo(dateStr: string) {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function EarningsPage() {
  // Fetch different time periods
  const {
    data: allData,
    loading: allLoading,
    error: allError,
    refetch,
  } = useApi<EarningsResponse>("/api/earnings?period=all");
  const { data: todayData } = useApi<EarningsResponse>(
    "/api/earnings?period=24h"
  );
  const { data: weekData } = useApi<EarningsResponse>(
    "/api/earnings?period=7d"
  );
  const { data: monthData } = useApi<EarningsResponse>(
    "/api/earnings?period=30d"
  );

  const totalAll = allData?.summary?.total || 0;
  const totalToday = todayData?.summary?.total || 0;
  const totalWeek = weekData?.summary?.total || 0;
  const totalMonth = monthData?.summary?.total || 0;
  const byLaunchpad = allData?.summary?.byLaunchpad || {};
  const recentEarnings = allData?.earnings?.slice(0, 10) || [];

  // Build per-launchpad sections
  const launchpadSections = Object.entries(byLaunchpad).map(([id, total]) => ({
    id,
    name: launchpadNames[id] || id,
    image: launchpadImages[id] || "/meteora.png",
    totalEarnings: total,
    todayEarnings:
      todayData?.summary?.byLaunchpad?.[id] || 0,
  }));

  const loading = allLoading;
  const error = allError;

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto">
      {/* Header */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={stagger}
        className="mb-8"
      >
        <motion.div variants={fadeUp}>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
            Earnings
          </h1>
          <p className="mt-1 text-sm text-neutral-400 font-sans">
            Creator fees and protocol revenue from all launchpads.
          </p>
        </motion.div>
      </motion.div>

      {loading && (
        <div className="space-y-6">
          <StatsSkeleton count={4} />
          <ListSkeleton count={3} />
        </div>
      )}

      {error && !loading && <DataError message={error} onRetry={refetch} />}

      {!loading && !error && (
        <>
          {/* Summary Metric Cards */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
          >
            {[
              {
                label: "Total Earnings",
                value: totalAll,
                period: "all time",
                positive: totalAll > 0,
              },
              {
                label: "Today",
                value: totalToday,
                period: "last 24 hours",
                positive: totalToday > 0,
              },
              {
                label: "This Week",
                value: totalWeek,
                period: "last 7 days",
                positive: totalWeek > 0,
              },
              {
                label: "This Month",
                value: totalMonth,
                period: "last 30 days",
                positive: totalMonth > 0,
              },
            ].map((stat) => (
              <motion.div
                key={stat.label}
                variants={fadeUp}
                className="bg-[#181818] rounded-2xl p-5 border border-white/[0.04] flex flex-col justify-between"
              >
                <div>
                  <span className="text-[11px] font-sans font-medium text-neutral-400 uppercase tracking-wider block">
                    {stat.label}
                  </span>
                  <div className="flex items-baseline gap-1.5 mt-2">
                    <span className="text-2xl md:text-3xl font-bold font-mono text-white tracking-tight">
                      {stat.value.toFixed(2)}
                    </span>
                    <span className="text-xs font-mono text-neutral-400">
                      SOL
                    </span>
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-white/[0.04] flex items-center justify-between text-xs font-mono">
                  <span className="text-neutral-500">{stat.period}</span>
                  {stat.positive ? (
                    <span className="text-emerald-400 font-medium flex items-center gap-0.5">
                      <IconArrowUpRight size={12} />
                      +{stat.value.toFixed(2)} SOL
                    </span>
                  ) : (
                    <span className="text-neutral-500">0.00 SOL</span>
                  )}
                </div>
              </motion.div>
            ))}
          </motion.div>

          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            {/* Earnings by launchpad */}
            <motion.div
              initial="hidden"
              animate="visible"
              variants={stagger}
              className="lg:col-span-3 bg-[#181818] rounded-2xl p-6 border border-white/[0.04]"
            >
              <motion.div variants={fadeUp} className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="text-sm font-semibold text-white font-sans">
                    By Launchpad
                  </h2>
                  <p className="text-xs text-neutral-400 font-sans mt-0.5">
                    Accumulated creator revenue across decentralized pools
                  </p>
                </div>
                <span className="text-xs font-mono text-neutral-400 bg-white/[0.04] px-2.5 py-1 rounded-full border border-white/[0.04]">
                  {launchpadSections.length} pools
                </span>
              </motion.div>

              {launchpadSections.length > 0 ? (
                <div className="space-y-3">
                  {launchpadSections.map((pad) => (
                    <motion.div
                      key={pad.id}
                      variants={fadeUp}
                      className="bg-[#141414] rounded-xl p-4 border border-white/[0.04] hover:border-white/[0.08] transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3.5">
                          <div className="relative w-10 h-10 rounded-xl overflow-hidden bg-black/40 border border-white/[0.06] flex-shrink-0">
                            <Image
                              src={pad.image}
                              alt={pad.name}
                              fill
                              className="object-cover"
                            />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-white font-sans">
                                {pad.name}
                              </span>
                              {pad.todayEarnings > 0 && (
                                <span className="text-[10px] font-mono text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full flex items-center gap-0.5">
                                  <IconArrowUpRight size={10} />
                                  +{pad.todayEarnings.toFixed(2)} SOL today
                                </span>
                              )}
                            </div>
                            <span className="text-xs font-mono text-neutral-500 block mt-0.5">
                              ID: {pad.id}
                            </span>
                          </div>
                        </div>

                        <div className="text-right">
                          <div className="text-base font-bold font-mono text-white">
                            {pad.totalEarnings.toFixed(2)} SOL
                          </div>
                          <div className="text-[11px] font-mono text-neutral-500">
                            total earned
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="bg-[#141414] rounded-xl p-10 text-center border border-dashed border-white/[0.06]">
                  <IconTrendingUp
                    size={28}
                    className="text-neutral-500 mx-auto mb-3"
                  />
                  <p className="text-sm text-neutral-300 font-sans font-medium">
                    No earnings recorded yet
                  </p>
                  <p className="text-xs text-neutral-500 font-sans mt-1 max-w-sm mx-auto">
                    Creator fees will appear here once your tokens begin trading on Meteora, Bags, or Pump.fun.
                  </p>
                </div>
              )}
            </motion.div>

            {/* Recent activity */}
            <motion.div
              initial="hidden"
              animate="visible"
              variants={stagger}
              className="lg:col-span-2 bg-[#181818] rounded-2xl p-6 border border-white/[0.04]"
            >
              <motion.div variants={fadeUp} className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="text-sm font-semibold text-white font-sans">
                    Recent Activity
                  </h2>
                  <p className="text-xs text-neutral-400 font-sans mt-0.5">
                    Latest settled transaction events
                  </p>
                </div>
              </motion.div>

              {recentEarnings.length > 0 ? (
                <motion.div
                  variants={fadeUp}
                  className="space-y-2.5"
                >
                  {recentEarnings.map((tx) => (
                    <div
                      key={tx.id}
                      className="bg-[#141414] rounded-xl p-3.5 border border-white/[0.04] hover:border-white/[0.08] transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
                            <IconArrowUpRight size={14} className="text-emerald-400" />
                          </div>
                          <div>
                            <span className="text-xs font-semibold text-white font-sans block">
                              Creator fee
                            </span>
                            <span className="text-[11px] text-neutral-500 font-mono mt-0.5 block">
                              {launchpadNames[tx.launchpad] || tx.launchpad} · {timeAgo(tx.created_at)}
                            </span>
                          </div>
                        </div>

                        <span className="font-mono text-xs font-semibold text-emerald-400">
                          +{tx.amount.toFixed(4)} SOL
                        </span>
                      </div>
                    </div>
                  ))}
                </motion.div>
              ) : (
                <div className="bg-[#141414] rounded-xl p-8 text-center border border-dashed border-white/[0.06]">
                  <p className="text-xs text-neutral-400 font-sans">
                    No recent transaction activity.
                  </p>
                </div>
              )}
            </motion.div>
          </div>
        </>
      )}
    </div>
  );
}
