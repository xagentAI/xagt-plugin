/**
 * Token creation service.
 *
 * Builds SPL token mint transactions client-side.
 * The wallet adapter signs them — no private keys touch the server.
 *
 * Flow:
 * 1. createMintTransaction() → builds unsigned tx
 * 2. Wallet signs it
 * 3. Send + confirm with Solana RPC
 * 4. createMetadata() → attaches Metaplex token metadata
 */

import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  Transaction,
  LAMPORTS_PER_SOL,
} from "@solana/web3.js";
import {
  TOKEN_PROGRAM_ID,
  MINT_SIZE,
  createInitializeMintInstruction,
  getMinimumBalanceForRentExemptMint,
  createAssociatedTokenAccountInstruction,
  getAssociatedTokenAddress,
  createMintToInstruction,
} from "@solana/spl-token";

export interface TokenConfig {
  name: string;
  symbol: string;
  decimals: number;
  supply: string; // raw amount as string (before decimals)
  description?: string;
  imageUrl?: string;
}

export interface MintResult {
  mintKeypair: Keypair;
  transaction: Transaction;
  ataAddress: PublicKey;
}

/**
 * Build an unsigned transaction that:
 * 1. Creates a new mint account
 * 2. Initializes it with the given decimals
 * 3. Creates the ATA for the wallet
 * 4. Mints the full supply to the wallet's ATA
 *
 * The caller signs with both the wallet and the mint keypair.
 */
export async function createMintTransaction(
  connection: Connection,
  walletPublicKey: PublicKey,
  config: TokenConfig
): Promise<MintResult> {
  const mintKeypair = Keypair.generate();
  const mintRent = await getMinimumBalanceForRentExemptMint(connection);

  // Associated Token Account for the wallet
  const ata = await getAssociatedTokenAddress(
    mintKeypair.publicKey,
    walletPublicKey
  );

  // Supply = user amount * 10^decimals
  const supplyBigInt = BigInt(config.supply) * BigInt(10 ** config.decimals);

  const transaction = new Transaction().add(
    // 1. Create the mint account
    SystemProgram.createAccount({
      fromPubkey: walletPublicKey,
      newAccountPubkey: mintKeypair.publicKey,
      space: MINT_SIZE,
      lamports: mintRent,
      programId: TOKEN_PROGRAM_ID,
    }),

    // 2. Initialize the mint
    createInitializeMintInstruction(
      mintKeypair.publicKey,
      config.decimals,
      walletPublicKey, // mint authority
      walletPublicKey, // freeze authority
      TOKEN_PROGRAM_ID
    ),

    // 3. Create ATA for the wallet
    createAssociatedTokenAccountInstruction(
      walletPublicKey, // payer
      ata,
      walletPublicKey, // owner
      mintKeypair.publicKey
    ),

    // 4. Mint the full supply to the ATA
    createMintToInstruction(
      mintKeypair.publicKey,
      ata,
      walletPublicKey, // mint authority
      supplyBigInt
    )
  );

  // Set recent blockhash + fee payer
  const { blockhash, lastValidBlockHeight } =
    await connection.getLatestBlockhash("confirmed");
  transaction.recentBlockhash = blockhash;
  transaction.lastValidBlockHeight = lastValidBlockHeight;
  transaction.feePayer = walletPublicKey;

  // The mint keypair must partially sign
  transaction.partialSign(mintKeypair);

  return {
    mintKeypair,
    transaction,
    ataAddress: ata,
  };
}

/**
 * Confirm a transaction with retries and timeout.
 */
export async function confirmTransaction(
  connection: Connection,
  signature: string,
  blockhash: string,
  lastValidBlockHeight: number
): Promise<boolean> {
  const confirmation = await connection.confirmTransaction(
    {
      signature,
      blockhash,
      lastValidBlockHeight,
    },
    "confirmed"
  );

  if (confirmation.value.err) {
    throw new Error(
      `Transaction failed: ${JSON.stringify(confirmation.value.err)}`
    );
  }

  return true;
}

/**
 * Get the estimated cost of minting a token.
 * Returns cost in SOL.
 */
export async function estimateMintCost(
  connection: Connection
): Promise<number> {
  const mintRent = await getMinimumBalanceForRentExemptMint(connection);
  // Mint rent + ATA rent + tx fees (~0.01 SOL buffer)
  const ataRent = 0.00203928 * LAMPORTS_PER_SOL; // Typical ATA rent
  const txFees = 0.000015 * LAMPORTS_PER_SOL; // ~3 signatures worth

  return (mintRent + ataRent + txFees) / LAMPORTS_PER_SOL;
}
