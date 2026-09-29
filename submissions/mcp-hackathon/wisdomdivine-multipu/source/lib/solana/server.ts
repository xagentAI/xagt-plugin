import "server-only";

import { Connection, PublicKey } from "@solana/web3.js";
import { MINT_SIZE, TOKEN_PROGRAM_ID } from "@solana/spl-token";
import { SOLANA_RPC_URL } from "@/lib/solana";

let sharedConnection: Connection | null = null;

export function getServerSolanaConnection() {
  if (!sharedConnection) {
    sharedConnection = new Connection(SOLANA_RPC_URL, "confirmed");
  }
  return sharedConnection;
}

function hasWalletSigner(parsedTx: Awaited<
  ReturnType<Connection["getParsedTransaction"]>
>, walletAddress: string) {
  if (!parsedTx) return false;
  return parsedTx.transaction.message.accountKeys.some((key) => {
    return key.signer && key.pubkey.toBase58() === walletAddress;
  });
}

export async function verifyMintConfirmationOnChain(params: {
  walletAddress: string;
  mintAddress: string;
  signature: string;
}) {
  const isDevSandbox = process.env.NODE_ENV !== "production";
  if (
    isDevSandbox &&
    (params.signature.startsWith("mock-") ||
      params.signature.startsWith("sim_") ||
      params.mintAddress.startsWith("mock-") ||
      params.walletAddress.toLowerCase().includes("demo"))
  ) {
    return;
  }

  const connection = getServerSolanaConnection();
  const parsedTx = await connection.getParsedTransaction(params.signature, {
    maxSupportedTransactionVersion: 0,
    commitment: "confirmed",
  });

  if (!parsedTx) {
    throw new Error("Mint transaction not found on configured Solana network");
  }

  if (parsedTx.meta?.err) {
    throw new Error("Mint transaction failed on-chain");
  }

  if (!hasWalletSigner(parsedTx, params.walletAddress)) {
    throw new Error("Mint transaction signer does not match authenticated wallet");
  }

  const mintInfo = await connection.getAccountInfo(new PublicKey(params.mintAddress), "confirmed");
  if (!mintInfo) {
    throw new Error("Mint account does not exist on configured Solana network");
  }
  if (!mintInfo.owner.equals(TOKEN_PROGRAM_ID) || mintInfo.data.length !== MINT_SIZE) {
    throw new Error("Provided mint address is not a valid SPL mint account");
  }
}

export async function verifyLaunchConfirmationOnChain(params: {
  walletAddress: string;
  signature: string;
}) {
  const isDevSandbox = process.env.NODE_ENV !== "production";
  if (
    isDevSandbox &&
    (params.signature.startsWith("mock-") ||
      params.signature.startsWith("sim_") ||
      params.signature.startsWith("0xmock") ||
      params.walletAddress.toLowerCase().includes("demo"))
  ) {
    return;
  }

  const connection = getServerSolanaConnection();
  const parsedTx = await connection.getParsedTransaction(params.signature, {
    maxSupportedTransactionVersion: 0,
    commitment: "confirmed",
  });

  if (!parsedTx) {
    throw new Error("Launch transaction not found on configured Solana network");
  }

  if (parsedTx.meta?.err) {
    throw new Error("Launch transaction failed on-chain");
  }

  if (!hasWalletSigner(parsedTx, params.walletAddress)) {
    throw new Error(
      "Launch transaction signer does not match authenticated wallet"
    );
  }
}
