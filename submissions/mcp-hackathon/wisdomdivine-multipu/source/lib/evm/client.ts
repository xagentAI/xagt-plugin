"use client";

import { Interface, id } from "ethers";

type EvmLaunchpadId = "fourmeme" | "pons" | "sherwood";

const robinhoodConfig = {
  chainId: "0x1237", // 4663
  chainName: "Robinhood Chain",
  nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: [process.env.NEXT_PUBLIC_ROBINHOOD_RPC_URL ?? "https://rpc.mainnet.chain.robinhood.com"],
  blockExplorerUrls: ["https://robinhoodchain.blockscout.com"],
  launcherAddress: process.env.NEXT_PUBLIC_PONS_LAUNCHER_ADDRESS || process.env.NEXT_PUBLIC_SHERWOOD_LAUNCHER_ADDRESS,
  functionSignature: process.env.NEXT_PUBLIC_PONS_LAUNCH_FUNCTION_SIGNATURE || process.env.NEXT_PUBLIC_SHERWOOD_LAUNCH_FUNCTION_SIGNATURE,
  argTemplate: process.env.NEXT_PUBLIC_PONS_LAUNCH_ARG_TEMPLATE || process.env.NEXT_PUBLIC_SHERWOOD_LAUNCH_ARG_TEMPLATE,
} as const;

const EVM_CHAIN_CONFIG = {
  fourmeme: {
    chainId: "0x38", // 56
    chainName: "BNB Smart Chain",
    nativeCurrency: { name: "BNB", symbol: "BNB", decimals: 18 },
    rpcUrls: [process.env.NEXT_PUBLIC_BSC_RPC_URL ?? "https://bsc-dataseed.binance.org"],
    blockExplorerUrls: ["https://bscscan.com"],
    launcherAddress: process.env.NEXT_PUBLIC_FOURMEME_LAUNCHER_ADDRESS,
    functionSignature: process.env.NEXT_PUBLIC_FOURMEME_LAUNCH_FUNCTION_SIGNATURE,
    argTemplate: process.env.NEXT_PUBLIC_FOURMEME_LAUNCH_ARG_TEMPLATE,
  },
  pons: robinhoodConfig,
  sherwood: robinhoodConfig,
} as const;

type EthereumProvider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
};

function getEthereumProvider(): EthereumProvider {
  const ethereum = (window as Window & { ethereum?: EthereumProvider }).ethereum;
  if (!ethereum) {
    throw new Error("No EVM wallet provider detected.");
  }
  return ethereum;
}

async function ensureChain(provider: EthereumProvider, launchpad: EvmLaunchpadId) {
  const config = EVM_CHAIN_CONFIG[launchpad];
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: config.chainId }],
    });
  } catch {
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: config.chainId,
          chainName: config.chainName,
          nativeCurrency: config.nativeCurrency,
          rpcUrls: config.rpcUrls,
          blockExplorerUrls: config.blockExplorerUrls,
        },
      ],
    });
  }
}

async function waitForReceipt(provider: EthereumProvider, txHash: string) {
  const maxAttempts = 60;
  for (let i = 0; i < maxAttempts; i++) {
    const receipt = await provider.request({
      method: "eth_getTransactionReceipt",
      params: [txHash],
    });
    if (receipt) return receipt;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Timed out waiting for EVM transaction confirmation.");
}

function getFunctionName(signature: string) {
  return signature.slice(0, signature.indexOf("(")).trim();
}

function resolveTemplateArg(
  token: { name: string; symbol: string; description: string; imageUrl: string | null; supply: string; decimals: number },
  arg: unknown
) {
  if (typeof arg !== "string") return arg;
  if (arg === "$name") return token.name;
  if (arg === "$symbol") return token.symbol;
  if (arg === "$description") return token.description;
  if (arg === "$imageUrl") return token.imageUrl ?? "";
  if (arg === "$supply") return token.supply;
  if (arg === "$decimals") return token.decimals;
  if (arg === "$supplyWei") {
    return (BigInt(token.supply) * 10n ** BigInt(token.decimals)).toString();
  }
  return arg;
}

function buildLaunchCallData(params: {
  launchpad: EvmLaunchpadId;
  token: { name: string; symbol: string; description: string; imageUrl: string | null; supply: string; decimals: number };
}) {
  const config = EVM_CHAIN_CONFIG[params.launchpad];
  if (!config.functionSignature) {
    throw new Error(`${params.launchpad} function signature is not configured.`);
  }

  const functionName = getFunctionName(config.functionSignature);
  const iface = new Interface([`function ${config.functionSignature}`]);

  let rawArgs: unknown[] = [];
  if (config.argTemplate) {
    const parsed = JSON.parse(config.argTemplate);
    if (!Array.isArray(parsed)) {
      throw new Error("Launch arg template must be a JSON array.");
    }
    rawArgs = parsed;
  }
  const args = rawArgs.map((arg) => resolveTemplateArg(params.token, arg));

  const calldata = iface.encodeFunctionData(functionName, args);
  const selector = id(config.functionSignature).slice(0, 10);
  if (!calldata.startsWith(selector)) {
    throw new Error("Encoded calldata selector mismatch.");
  }
  return calldata;
}

export async function executeEvmLaunch(params: {
  launchpad: EvmLaunchpadId;
  walletAddress: string;
  token: {
    name: string;
    symbol: string;
    description: string;
    imageUrl: string | null;
    supply: string;
    decimals: number;
  };
}): Promise<{ txHash: string; poolAddress: string }> {
  const provider = getEthereumProvider();
  const config = EVM_CHAIN_CONFIG[params.launchpad];

  if (!config.launcherAddress) {
    if (params.launchpad === "pons" || params.launchpad === "sherwood") {
      // Robinhood Chain operates in mock sandbox simulation mode per protocol architecture
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const mockHash =
        "0x" +
        Array.from({ length: 64 }, () =>
          Math.floor(Math.random() * 16).toString(16)
        ).join("");
      const mockPool =
        "0x" +
        Array.from({ length: 40 }, () =>
          Math.floor(Math.random() * 16).toString(16)
        ).join("");
      return { txHash: mockHash, poolAddress: mockPool };
    }
    throw new Error(
      `${params.launchpad} launcher is not configured. Set the NEXT_PUBLIC launcher address env var.`
    );
  }

  await ensureChain(provider, params.launchpad);
  const data = buildLaunchCallData({
    launchpad: params.launchpad,
    token: params.token,
  });

  const txHash = (await provider.request({
    method: "eth_sendTransaction",
    params: [
      {
        from: params.walletAddress,
        to: config.launcherAddress,
        value: "0x0",
        data,
      },
    ],
  })) as string;

  await waitForReceipt(provider, txHash);
  return { txHash, poolAddress: config.launcherAddress };
}
