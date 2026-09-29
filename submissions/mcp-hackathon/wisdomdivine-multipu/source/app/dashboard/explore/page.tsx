"use client";

import { useEffect, useRef, useState } from "react";
import { IconSearch, IconRefresh } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { TerminalColumnBoard } from "@/components/explore/terminal-column-board";
import { QuickBuyModal } from "@/components/explore/quick-buy-modal";

export default function ExplorePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [activeChain, setActiveChain] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const [error, setError] = useState<string | null>(null);

  const isFirstMount = useRef(true);

  // Quick Buy Modal state
  const [modalToken, setModalToken] = useState<any>(null);
  const [modalAmount, setModalAmount] = useState<number>(1);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const fetchExploreData = async (query = search, chain = activeChain, pageNum = page, showSpinner = true) => {
    if (showSpinner) setLoading(true);
    setIsRefreshing(true);
    try {
      const qParam = query ? `q=${encodeURIComponent(query)}` : "";
      const chainParam = chain !== "all" ? `chain=${encodeURIComponent(chain)}` : "";
      const pageParam = `page=${pageNum}`;
      const params = [qParam, chainParam, pageParam].filter(Boolean).join("&");
      const url = `/api/launches/explore?${params}`;

      const res = await fetch(url);
      if (!res.ok) {
        throw new Error("Failed to fetch explore directory");
      }
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err: any) {
      setError(err.message || "An error occurred while loading explore directory.");
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  // Restore pagination, chain, and search from URL or sessionStorage on mount
  useEffect(() => {
    if (typeof window === "undefined") return;

    const urlParams = new URLSearchParams(window.location.search);
    const urlPage = parseInt(urlParams.get("page") || "", 10);
    const savedPage = parseInt(sessionStorage.getItem("explore_page") || "", 10);
    const targetPage = !isNaN(urlPage) && urlPage > 0 ? urlPage : (!isNaN(savedPage) && savedPage > 0 ? savedPage : 1);

    const urlChain = urlParams.get("chain") || "all";
    const urlSearch = urlParams.get("q") || "";

    if (targetPage !== 1) setPage(targetPage);
    if (urlChain !== "all") setActiveChain(urlChain);
    if (urlSearch) setSearch(urlSearch);

    fetchExploreData(urlSearch, urlChain, targetPage);
    isFirstMount.current = false;
  }, []);

  // Subsequent updates on activeChain or page change
  useEffect(() => {
    if (isFirstMount.current) return;
    fetchExploreData(search, activeChain, page);
  }, [activeChain, page]);

  // Synchronize browser history and popstate for back/forward buttons
  useEffect(() => {
    const handlePopState = () => {
      const urlParams = new URLSearchParams(window.location.search);
      const p = parseInt(urlParams.get("page") || "1", 10);
      const newPage = !isNaN(p) && p > 0 ? p : 1;
      const c = urlParams.get("chain") || "all";
      const q = urlParams.get("q") || "";

      setPage(newPage);
      setActiveChain(c);
      setSearch(q);
      sessionStorage.setItem("explore_page", String(newPage));
      fetchExploreData(q, c, newPage, false);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const handleSearchChange = (val: string) => {
    setSearch(val);
    setPage(1);
    if (typeof window !== "undefined") {
      sessionStorage.setItem("explore_page", "1");
      const url = new URL(window.location.href);
      if (val) url.searchParams.set("q", val);
      else url.searchParams.delete("q");
      url.searchParams.delete("page");
      window.history.replaceState(null, "", url.toString());
    }
    fetchExploreData(val, activeChain, 1, false);
  };

  const handleChainChange = (chain: string) => {
    setActiveChain(chain);
    setPage(1);
    if (typeof window !== "undefined") {
      sessionStorage.setItem("explore_page", "1");
      const url = new URL(window.location.href);
      if (chain !== "all") url.searchParams.set("chain", chain);
      else url.searchParams.delete("chain");
      url.searchParams.delete("page");
      window.history.pushState(null, "", url.toString());
    }
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    if (typeof window !== "undefined") {
      sessionStorage.setItem("explore_page", String(newPage));
      const url = new URL(window.location.href);
      if (newPage > 1) {
        url.searchParams.set("page", String(newPage));
      } else {
        url.searchParams.delete("page");
      }
      window.history.pushState(null, "", url.toString());
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleQuickBuy = (token: any, solAmount: number) => {
    setModalToken(token);
    setModalAmount(solAmount);
    setIsModalOpen(true);
  };

  const chains = [
    { id: "all", label: "All Chains" },
    { id: "solana", label: "Solana" },
    { id: "bsc", label: "BNB Chain" },
    { id: "robinhood", label: "Robinhood" },
  ];

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
          Trade &amp; Explore
        </h1>
        <p className="mt-1 text-sm text-neutral-400 font-sans">
          Real-time token discovery, bonding curves, and decentralized execution across Solana, BNB, and Robinhood.
        </p>
      </div>

      {/* Toolbar: Chain Selector & Search */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
        {/* Chain Selector */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 md:pb-0">
          {chains.map((chain) => (
            <button
              key={chain.id}
              onClick={() => handleChainChange(chain.id)}
              className={cn(
                "px-4 py-2 text-xs font-sans rounded-full transition-colors whitespace-nowrap cursor-pointer",
                activeChain === chain.id
                  ? "bg-white text-black font-semibold"
                  : "bg-[#181818] text-neutral-400 hover:text-white border border-white/[0.06]"
              )}
            >
              {chain.label}
            </button>
          ))}
        </div>

        {/* Search & Refresh */}
        <div className="flex items-center gap-2.5 w-full md:w-88">
          <div className="relative flex-1">
            <IconSearch
              size={15}
              className="absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-500"
            />
            <input
              type="text"
              placeholder="Search by name or symbol..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full bg-[#181818] border border-white/[0.08] focus:border-white/30 rounded-full pl-10 pr-4 py-2 text-xs text-white placeholder:text-neutral-500 font-mono transition-colors focus:outline-none"
            />
          </div>

          <button
            onClick={() => fetchExploreData(search, activeChain, page, false)}
            disabled={isRefreshing}
            className="p-2.5 bg-[#181818] border border-white/[0.06] hover:bg-white/[0.08] text-neutral-400 hover:text-white rounded-full transition-colors cursor-pointer flex-shrink-0"
            title="Refresh"
          >
            <IconRefresh
              size={15}
              className={cn(isRefreshing && "animate-spin text-white")}
            />
          </button>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="py-24 text-center text-xs text-neutral-500 font-mono bg-[#181818] rounded-2xl border border-white/[0.04]">
          Loading live trading pairs...
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="py-12 text-center text-xs text-red-400 font-sans bg-[#181818] border border-red-500/20 p-6 rounded-2xl">
          {error}
        </div>
      )}

      {/* Main Terminal Content */}
      {!loading && !error && data && (
        <TerminalColumnBoard
          columns={
            data.terminal_columns || {
              final_stretch: [],
              migrated: [],
              new_pairs: [],
            }
          }
          columnCounts={data.column_counts}
          pagination={data.pagination}
          onPageChange={handlePageChange}
          onQuickBuy={handleQuickBuy}
        />
      )}

      {/* Quick Buy Modal Dialog */}
      <QuickBuyModal
        isOpen={isModalOpen}
        token={modalToken}
        initialAmount={modalAmount}
        onClose={() => setIsModalOpen(false)}
        onSuccess={() => fetchExploreData(search, activeChain, page, false)}
      />
    </div>
  );
}
