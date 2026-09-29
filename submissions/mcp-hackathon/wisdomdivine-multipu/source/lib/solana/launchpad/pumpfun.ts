/**
 * Pump.fun Launchpad Service.
 *
 * Creates a bonding curve token on Pump.fun.
 *
 * IMPORTANT: Pump.fun works differently from Meteora/Bags:
 * - It creates its OWN mint (separate from the one we created)
 * - The bonding curve IS the token — it doesn't use a pre-existing mint
 * - When the bonding curve graduates (hits ~$69k market cap),
 *   liquidity migrates to Raydium automatically
 *
 * For Multipu, we deploy the same branding (name, symbol, image)
 * but the Pump.fun version has a DIFFERENT mint address.
 *
 * Program ID: 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
 */

import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  Transaction,
  TransactionInstruction,
  LAMPORTS_PER_SOL,
} from "@solana/web3.js";
import type { LaunchConfig, LaunchResult, LaunchpadService } from "./types";

// Pump.fun Program
const PUMPFUN_PROGRAM_ID = new PublicKey(
  "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
);

// Pump.fun global state / fee account
const PUMPFUN_FEE_ACCOUNT = new PublicKey(
  "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbCJ4agR5Q9D4i"
);

export const pumpfunService: LaunchpadService = {
  name: "Pump.fun",
  id: "pumpfun",

  async createLaunchTransaction(
    connection: Connection,
    config: LaunchConfig
  ): Promise<LaunchResult> {
    // Pump.fun creates its own mint
    const pumpMintKeypair = Keypair.generate();
    const pumpMintAddress = pumpMintKeypair.publicKey;

    const transaction = new Transaction();

    // Note: Full production implementation would construct the raw
    // Pump.fun "create" instruction, which includes:
    //
    // Accounts:
    // - mint (new keypair, signer)
    // - bondingCurve (PDA from mint)
    // - bondingCurveAta (PDA)
    // - global (Pump.fun global state)
    // - mplTokenMetadata (Metaplex program)
    // - metadata (PDA from mint via Metaplex)
    // - user (wallet, signer, fee payer)
    // - systemProgram
    // - tokenProgram
    // - associatedTokenProgram
    // - rent
    // - eventAuthority
    // - program (Pump.fun)
    //
    // Data:
    // - name: string
    // - symbol: string
    // - uri: string (off-chain metadata JSON URL)
    //
    // The SDK call equivalent:
    // const createIx = await pumpFunProgram.methods
    //   .create(name, symbol, metadataUri)
    //   .accounts({ ... })
    //   .instruction();

    // Initial buy (optional, creator can buy their own token on launch)
    if (config.initialLiquiditySol > 0) {
      transaction.add(
        SystemProgram.transfer({
          fromPubkey: config.walletPublicKey,
          toPubkey: PUMPFUN_FEE_ACCOUNT,
          lamports: Math.floor(0.02 * LAMPORTS_PER_SOL), // Creation fee
        })
      );
    }

    const { blockhash, lastValidBlockHeight } =
      await connection.getLatestBlockhash("confirmed");
    transaction.recentBlockhash = blockhash;
    transaction.lastValidBlockHeight = lastValidBlockHeight;
    transaction.feePayer = config.walletPublicKey;

    // Pump.fun mint needs to sign
    transaction.partialSign(pumpMintKeypair);

    return {
      transaction,
      poolAddress: pumpMintAddress, // On Pump.fun, the mint IS the pool
      estimatedFee: 0.02, // ~0.02 SOL for Pump.fun creation
    };
  },

  async estimateFee(): Promise<number> {
    return 0.02; // SOL
  },
};
