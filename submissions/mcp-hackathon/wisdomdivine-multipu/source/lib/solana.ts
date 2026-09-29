import { Connection, clusterApiUrl } from "@solana/web3.js";
import { SOLANA_NETWORK } from "@/lib/runtime-config";

/**
 * Solana RPC connection.
 * Uses Helius in production (set NEXT_PUBLIC_SOLANA_RPC_URL in .env).
 * Falls back to devnet for development.
 */
export const SOLANA_RPC_URL =
  process.env.NEXT_PUBLIC_SOLANA_RPC_URL || clusterApiUrl(SOLANA_NETWORK);

export function getConnection() {
  return new Connection(SOLANA_RPC_URL, "confirmed");
}
