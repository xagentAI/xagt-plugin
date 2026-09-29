import "server-only";

import { JsonRpcProvider, getAddress, id } from "ethers";

type EvmNetwork = "bsc" | "robinhood";

const providers = new Map<EvmNetwork, JsonRpcProvider>();

export function areEvmLaunchAdaptersEnabled() {
  return process.env.ENABLE_EVM_LAUNCH_ADAPTERS === "true";
}

function getRpcUrl(network: EvmNetwork) {
  if (network === "robinhood") {
    return process.env.ROBINHOOD_RPC_URL || "https://rpc.mainnet.chain.robinhood.com";
  }
  return process.env.BSC_RPC_URL;
}

function getExpectedLauncherAddress(network: EvmNetwork) {
  if (network === "robinhood") {
    return process.env.NEXT_PUBLIC_PONS_LAUNCHER_ADDRESS || process.env.NEXT_PUBLIC_SHERWOOD_LAUNCHER_ADDRESS;
  }
  return process.env.NEXT_PUBLIC_FOURMEME_LAUNCHER_ADDRESS;
}

function getExpectedFunctionSignature(network: EvmNetwork) {
  if (network === "robinhood") {
    return process.env.NEXT_PUBLIC_PONS_LAUNCH_FUNCTION_SIGNATURE || process.env.NEXT_PUBLIC_SHERWOOD_LAUNCH_FUNCTION_SIGNATURE;
  }
  return process.env.NEXT_PUBLIC_FOURMEME_LAUNCH_FUNCTION_SIGNATURE;
}

function getEvmProvider(network: EvmNetwork) {
  const existing = providers.get(network);
  if (existing) return existing;

  const rpcUrl = getRpcUrl(network);
  if (!rpcUrl) {
    throw new Error(`Missing RPC URL for ${network} launch adapter`);
  }
  const provider = new JsonRpcProvider(rpcUrl);
  providers.set(network, provider);
  return provider;
}

export async function verifyEvmLaunchTransaction(params: {
  network: EvmNetwork;
  walletAddress: string;
  txHash: string;
}) {
  const isSandbox = process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_APP_PHASE !== "mainnet";
  if (
    isSandbox &&
    (params.txHash.startsWith("mock-") ||
      params.txHash.startsWith("sim_") ||
      params.txHash.startsWith("0xmock") ||
      params.walletAddress.toLowerCase().includes("demo") ||
      params.network === "robinhood")
  ) {
    return;
  }

  if (!areEvmLaunchAdaptersEnabled()) {
    throw new Error(
      "EVM launch adapters are disabled. Set ENABLE_EVM_LAUNCH_ADAPTERS=true when ready."
    );
  }

  const provider = getEvmProvider(params.network);
  const receipt = await provider.getTransactionReceipt(params.txHash);
  if (!receipt) {
    throw new Error("Launch transaction not found on configured EVM network");
  }
  if (receipt.status !== 1) {
    throw new Error("Launch transaction failed on EVM network");
  }

  const tx = await provider.getTransaction(params.txHash);
  if (!tx?.from) {
    throw new Error("Unable to resolve signer for EVM launch transaction");
  }

  if (getAddress(tx.from) !== getAddress(params.walletAddress)) {
    throw new Error("EVM launch transaction signer does not match wallet");
  }

  const expectedTo = getExpectedLauncherAddress(params.network);
  if (!expectedTo) {
    throw new Error("Expected launcher contract is not configured for EVM verification.");
  }
  if (!tx.to || getAddress(tx.to) !== getAddress(expectedTo)) {
    throw new Error("EVM launch transaction target contract does not match expected launcher.");
  }

  const expectedSignature = getExpectedFunctionSignature(params.network);
  if (!expectedSignature) {
    throw new Error("Expected launch function signature is not configured for EVM verification.");
  }
  const selector = id(expectedSignature).slice(0, 10).toLowerCase();
  const txData = (tx.data ?? "").toLowerCase();
  if (!txData.startsWith(selector)) {
    throw new Error("EVM launch transaction function selector mismatch.");
  }
}
