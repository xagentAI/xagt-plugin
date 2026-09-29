/**
 * Launchpad service interface.
 *
 * Each launchpad module implements this interface.
 * The launch wizard calls these to build platform-specific transactions.
 */

import type { Connection, PublicKey, Transaction } from "@solana/web3.js";

export interface LaunchConfig {
  /** SPL token mint address (already deployed) */
  mintAddress: PublicKey;
  /** Wallet that owns the token */
  walletPublicKey: PublicKey;
  /** Initial liquidity in SOL */
  initialLiquiditySol: number;
  /** Token amount to seed the pool with */
  tokenAmount: bigint;
}

export interface LaunchResult {
  /** Unsigned transaction(s) to sign */
  transaction: Transaction;
  /** Pool/market address (known before signing) */
  poolAddress: PublicKey;
  /** Estimated fee in SOL */
  estimatedFee: number;
}

export interface LaunchpadService {
  name: string;
  id: "meteora" | "bags" | "pumpfun" | "fourmeme" | "pons" | "sherwood";
  /** Build the unsigned launch transaction */
  createLaunchTransaction(
    connection: Connection,
    config: LaunchConfig
  ): Promise<LaunchResult>;
  /** Get estimated cost in SOL */
  estimateFee(connection: Connection): Promise<number>;
}
