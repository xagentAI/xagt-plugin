"use client";

import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import {
  IconExternalLink,
  IconCopy,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/use-api";
import { StatsSkeleton, ListSkeleton } from "@/components/skeleton";
import { DataError } from "@/components/error-boundary";
import { toast } from "sonner";

interface Launch {
  id: string;
  launchpad: string;
  status: string;
  pool_address: string | null;
  initial_liquidity: number | null;
  launch_tx: string | null;
  launched_at: string | null;
  created_at: string;
  token: {
    name: string;
    symbol: string;
    mint_address: string | null;
    image_url?: string | null;
  };
}

interface LaunchesResponse {
  launches: Launch[];
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

function timeAgo(dateStr: string | null) {
  if (!dateStr) return "—";
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function LaunchesPage() {
  const { data, loading, error, refetch } =
    useApi<LaunchesResponse>("/api/launches");

  const launches = data?.launches || [];
  const liveCount = launches.filter((l) => l.status === "live").length;
  const pendingCount = launches.filter((l) => l.status === "pending").length;

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
              Launches
            </h1>
            <p className="mt-1 text-sm text-neutral-400 font-sans">
              Track all your launchpad deployments.
            </p>
          </div>
          <Link
            href="/launch"
            className="hidden md:inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
          >
            New Launch
          </Link>
        </motion.div>
      </motion.div>

      {loading && (
        <>
          <StatsSkeleton count={3} />
          <ListSkeleton count={4} />
        </>
      )}

      {error && !loading && (
        <DataError message={error} onRetry={refetch} />
      )}

      {!loading && !error && (
        <>
          {/* Status summary - 3 Rounded Matte Cards matching Overview */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8"
          >
            {[
              {
                label: "Total Launches",
                value: launches.length.toString(),
                sub: "across all launchpads",
                color: "text-white",
              },
              {
                label: "Live Pools",
                value: liveCount.toString(),
                sub: "active trading markets",
                color: "text-emerald-400",
              },
              {
                label: "Pending Deployments",
                value: pendingCount.toString(),
                sub: "draft & processing",
                color: "text-amber-400",
              },
            ].map((stat) => (
              <motion.div
                key={stat.label}
                variants={fadeUp}
                className="bg-[#181818] rounded-2xl p-5 sm:p-6 flex flex-col justify-between min-h-[130px] border border-white/[0.04] hover:bg-[#1f1f1f] transition-colors"
              >
                <span className="text-xs text-neutral-400 font-medium font-sans">
                  {stat.label}
                </span>
                <span className={cn("text-3xl sm:text-4xl font-semibold font-mono tracking-tight my-2", stat.color)}>
                  {stat.value}
                </span>
                <span className="text-xs font-mono text-neutral-500">
                  {stat.sub}
                </span>
              </motion.div>
            ))}
          </motion.div>

          {/* Launches list */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="space-y-3"
          >
            <motion.div
              variants={fadeUp}
              className="flex items-center justify-between mb-2"
            >
              <h2 className="text-base font-semibold text-white font-sans">
                All Launches
              </h2>
            </motion.div>

            {launches.map((launch) => {
              const isLive = launch.status === "live";

              return (
                <motion.div
                  key={launch.id}
                  variants={fadeUp}
                  className="bg-[#181818] rounded-2xl p-5 sm:p-6 border border-white/[0.04] hover:border-white/[0.08] transition-all"
                >
                  <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                    <div className="relative w-12 h-12 rounded-xl bg-white/[0.05] border border-white/[0.08] flex items-center justify-center flex-shrink-0 overflow-hidden">
                      <Image
                        src={
                          launch.token?.image_url ||
                          launchpadImages[launch.launchpad] ||
                          "/meteora.png"
                        }
                        alt={launch.token?.name || launch.launchpad}
                        fill
                        className="object-cover"
                      />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-base font-semibold text-white font-sans">
                          {launch.token?.name || "Unnamed Token"}
                        </span>
                        {launch.token?.symbol && (
                          <span className="font-mono text-xs text-neutral-400">
                            ${launch.token.symbol}
                          </span>
                        )}
                        <span className="font-mono text-[11px] px-2.5 py-0.5 rounded-full bg-white/[0.06] text-neutral-300 capitalize">
                          {launchpadNames[launch.launchpad] || launch.launchpad}
                        </span>
                        <span
                          className={cn(
                            "text-[10px] font-mono px-2 py-0.5 rounded-full",
                            isLive
                              ? "bg-emerald-500/10 text-emerald-400"
                              : "bg-amber-500/10 text-amber-400"
                          )}
                        >
                          {launch.status}
                        </span>
                      </div>

                      <div className="flex items-center gap-4 text-xs text-neutral-400 font-mono flex-wrap">
                        <span className="flex items-center gap-1.5">
                          <span>Pool: {formatAddress(launch.pool_address)}</span>
                          {launch.pool_address && (
                            <IconCopy
                              size={12}
                              className="text-neutral-400 hover:text-white cursor-pointer"
                              onClick={() => {
                                navigator.clipboard.writeText(launch.pool_address!);
                                toast.success("Pool Address copied!");
                              }}
                            />
                          )}
                        </span>
                        {launch.initial_liquidity !== null && (
                          <span>
                            Liquidity: {launch.initial_liquidity} SOL
                          </span>
                        )}
                        <span>{timeAgo(launch.launched_at || launch.created_at)}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end mt-3 sm:mt-0 pt-3 sm:pt-0 border-t sm:border-t-0 border-white/[0.04]">
                      {isLive && (
                        <Link
                          href={`/dashboard/trade/${launch.id}`}
                          className="px-4 py-1.5 rounded-xl bg-white text-black hover:bg-neutral-200 text-xs font-semibold font-sans transition-colors cursor-pointer"
                        >
                          Trade
                        </Link>
                      )}

                      {launch.pool_address && (
                        <a
                          href={`https://explorer.solana.com/address/${launch.pool_address}?cluster=${process.env.NEXT_PUBLIC_SOLANA_NETWORK || "devnet"}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="p-1.5 text-neutral-400 hover:text-white rounded-lg transition-colors"
                          title="View on Solana Explorer"
                        >
                          <IconExternalLink size={16} />
                        </a>
                      )}
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </motion.div>

          {launches.length === 0 && (
            <div className="bg-[#181818] rounded-2xl p-12 text-center border border-white/[0.04]">
              <h3 className="text-base font-semibold text-white mb-2 font-sans">
                No launches yet
              </h3>
              <p className="text-sm text-neutral-400 mb-6 font-sans">
                Deploy a token and push it to a launchpad.
              </p>
              <Link
                href="/launch"
                className="inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
              >
                Launch Token
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  );
}
