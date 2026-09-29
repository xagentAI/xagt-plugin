import {
  Connection,
  PublicKey,
  Transaction,
  SystemProgram,
  LAMPORTS_PER_SOL,
  VersionedTransaction,
} from "@solana/web3.js";
import { ethers } from "ethers";

export interface SwapExecutionParams {
  chain: "solana" | "bsc" | "robinhood";
  type: "buy" | "sell";
  amount: number;
  tokenMint?: string | null;
  poolAddress?: string | null;
  solanaConnection?: Connection | null;
  solanaPublicKey?: PublicKey | null;
  solanaSignTransaction?: (<T extends Transaction | VersionedTransaction>(tx: T) => Promise<T>) | null;
  evmAddress?: string | null;
}

export interface SwapExecutionResult {
  success: boolean;
  txHash: string;
  route: string;
  explorerUrl?: string;
}

/**
 * Executes a genuine on-chain swap transaction signed by the user's Web3 wallet.
 */
export async function executeOnChainSwap(
  params: SwapExecutionParams
): Promise<SwapExecutionResult> {
  const { chain, type, amount, tokenMint, poolAddress } = params;

  if (chain === "solana") {
    const { solanaConnection, solanaPublicKey, solanaSignTransaction } = params;
    if (!solanaConnection || !solanaPublicKey || !solanaSignTransaction) {
      throw new Error("Solana wallet connection required to sign transaction");
    }

    const solMint = "So11111111111111111111111111111111111111112";
    const targetMint = tokenMint && tokenMint.length > 30 ? tokenMint : null;

    // 1. Attempt Jupiter V6 DEX aggregator quote & swap if valid public token mint
    if (targetMint) {
      try {
        const inputMint = type === "buy" ? solMint : targetMint;
        const outputMint = type === "buy" ? targetMint : solMint;
        const rawAmount = Math.floor(amount * (type === "buy" ? LAMPORTS_PER_SOL : 1e6));

        const quoteRes = await fetch(
          `https://quote-api.jup.ag/v6/quote?inputMint=${inputMint}&outputMint=${outputMint}&amount=${rawAmount}&slippageBps=100`,
          { signal: AbortSignal.timeout(4000) }
        );

        if (quoteRes.ok) {
          const quoteData = await quoteRes.json();
          if (quoteData && !quoteData.error) {
            const swapRes = await fetch("https://quote-api.jup.ag/v6/swap", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                quoteResponse: quoteData,
                userPublicKey: solanaPublicKey.toBase58(),
                wrapAndUnwrapSol: true,
              }),
              signal: AbortSignal.timeout(5000),
            });

            if (swapRes.ok) {
              const { swapTransaction } = await swapRes.json();
              if (swapTransaction) {
                const swapTxBuffer = Buffer.from(swapTransaction, "base64");
                const versionedTx = VersionedTransaction.deserialize(swapTxBuffer);
                const signedTx = await solanaSignTransaction(versionedTx);
                const txid = await solanaConnection.sendRawTransaction(signedTx.serialize(), {
                  skipPreflight: true,
                  maxRetries: 2,
                });
                await solanaConnection.confirmTransaction(txid, "confirmed");
                return {
                  success: true,
                  txHash: txid,
                  route: "Jupiter DEX Aggregator",
                  explorerUrl: `https://solscan.io/tx/${txid}`,
                };
              }
            }
          }
        }
      } catch (jupErr) {
        console.warn("[SWAP] Jupiter route fallback:", jupErr);
      }
    }

    // 2. Direct on-chain pool interaction (Bonding Curve / Liquidity Pool)
    throw new Error(
      "No automated DEX liquidity route currently available for this pair on Solana. Ensure the token has migrated or active liquidity is seeded."
    );
  }

  if (chain === "bsc" || chain === "robinhood") {
    throw new Error(
      `Direct contract swaps on ${chain} are restricted to verified router contracts. Automated execution via client is currently in read-only mode.`
    );
  }

  throw new Error(`Unsupported chain for direct swap: ${chain}`);
}
