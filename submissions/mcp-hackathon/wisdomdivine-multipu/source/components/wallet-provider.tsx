"use client";

import { useMemo } from "react";
import {
  ConnectionProvider,
  WalletProvider,
} from "@solana/wallet-adapter-react";
import { PhantomWalletAdapter } from "@solana/wallet-adapter-wallets";
import { SOLANA_RPC_URL } from "@/lib/solana";

/**
 * Wraps the app with Solana wallet providers.
 * - ConnectionProvider: gives every child access to the Solana RPC connection
 * - WalletProvider: manages wallet state (connect, disconnect, sign)
 *
 * autoConnect=true means if the user previously connected,
 * it reconnects on page load without a prompt.
 */
export function SolanaProvider({ children }: { children: React.ReactNode }) {
  const wallets = useMemo(() => [new PhantomWalletAdapter()], []);

  return (
    <ConnectionProvider endpoint={SOLANA_RPC_URL}>
      <WalletProvider wallets={wallets} autoConnect>
        {children}
      </WalletProvider>
    </ConnectionProvider>
  );
}
