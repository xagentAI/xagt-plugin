"use client";

import { useState, useEffect, useCallback } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { useAuth } from "@/hooks/use-auth";

export interface ChainBalanceInfo {
  symbol: string;
  name: string;
  chain: "solana" | "bsc" | "robinhood";
  address: string | null;
  balance: number;
  connected: boolean;
}

export interface BalancesState {
  solana: ChainBalanceInfo;
  bsc: ChainBalanceInfo;
  robinhood: ChainBalanceInfo;
}

const defaultBalances: BalancesState = {
  solana: {
    symbol: "SOL",
    name: "Solana",
    chain: "solana",
    address: null,
    balance: 0,
    connected: false,
  },
  bsc: {
    symbol: "BNB",
    name: "BNB Chain",
    chain: "bsc",
    address: null,
    balance: 0,
    connected: false,
  },
  robinhood: {
    symbol: "ETH",
    name: "Robinhood",
    chain: "robinhood",
    address: null,
    balance: 0,
    connected: false,
  },
};

export function useWalletBalances() {
  const { publicKey } = useWallet();
  const { session, evmAddress } = useAuth();
  const [balances, setBalances] = useState<BalancesState>(defaultBalances);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const solAddress =
    publicKey?.toBase58() ||
    (session.isLoggedIn && session.walletKind === "solana" ? session.walletAddress : null);

  const evmAddr =
    evmAddress ||
    (session.isLoggedIn && session.walletKind === "evm" ? session.walletAddress : null);

  const fetchBalances = useCallback(async (showLoading = false) => {
    if (showLoading) setIsLoading(true);
    try {
      const params = new URLSearchParams();
      if (solAddress) params.set("solAddress", solAddress);
      if (evmAddr) params.set("evmAddress", evmAddr);

      const res = await fetch(`/api/wallet/balances?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (data.balances) {
          setBalances(data.balances);
          setLastUpdated(Date.now());
        }
      }
    } catch (err) {
      console.warn("Failed to fetch wallet balances:", err);
    } finally {
      setIsLoading(false);
    }
  }, [solAddress, evmAddr]);

  useEffect(() => {
    fetchBalances(true);
    // Refresh balances every 25 seconds
    const interval = setInterval(() => {
      fetchBalances(false);
    }, 25000);
    return () => clearInterval(interval);
  }, [fetchBalances]);

  return {
    balances,
    isLoading,
    lastUpdated,
    refresh: () => fetchBalances(true),
    solAddress,
    evmAddress: evmAddr,
  };
}
