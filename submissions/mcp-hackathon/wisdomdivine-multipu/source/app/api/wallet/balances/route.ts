import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { Connection, PublicKey } from "@solana/web3.js";
import { SOLANA_RPC_URL } from "@/lib/solana";

const BSC_RPC = process.env.NEXT_PUBLIC_BSC_RPC_URL || "https://bsc-dataseed.binance.org";
const ROBINHOOD_RPC = process.env.NEXT_PUBLIC_ROBINHOOD_RPC_URL || "https://rpc.mainnet.chain.robinhood.com";

async function fetchEvmBalance(rpcUrl: string, address: string): Promise<number> {
  try {
    const res = await fetch(rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "eth_getBalance",
        params: [address, "latest"],
        id: 1,
      }),
      cache: "no-store",
    });
    if (!res.ok) return 0;
    const json = await res.json();
    if (!json.result) return 0;
    const wei = BigInt(json.result);
    // Convert wei to ether float (keep 6 decimals precision)
    const divisor = BigInt(10 ** 12);
    const inMicro = Number(wei / divisor);
    return inMicro / 1e6;
  } catch (err) {
    console.warn(`[Balances] EVM fetch failed for ${rpcUrl}:`, err);
    return 0;
  }
}

async function fetchSolanaBalance(address: string): Promise<number> {
  try {
    const pubkey = new PublicKey(address);
    const connection = new Connection(SOLANA_RPC_URL, "confirmed");
    const lamports = await connection.getBalance(pubkey);
    return lamports / 1e9;
  } catch (err) {
    console.warn("[Balances] Solana fetch failed:", err);
    return 0;
  }
}

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const { searchParams } = new URL(request.url);
  const solAddressQuery = searchParams.get("solAddress");
  const evmAddressQuery = searchParams.get("evmAddress");

  const auth = await getAuth(request);

  // Determine active solana and EVM addresses
  let solAddress = solAddressQuery;
  let evmAddress = evmAddressQuery;

  if (auth.isLoggedIn && auth.walletAddress) {
    if (auth.walletKind === "solana" && !solAddress) {
      solAddress = auth.walletAddress;
    } else if (auth.walletKind === "evm" && !evmAddress) {
      evmAddress = auth.walletAddress;
    }
  }

  const results = {
    solana: {
      symbol: "SOL",
      name: "Solana",
      chain: "solana",
      address: solAddress || null,
      balance: 0,
      connected: Boolean(solAddress),
    },
    bsc: {
      symbol: "BNB",
      name: "BNB Chain",
      chain: "bsc",
      address: evmAddress || null,
      balance: 0,
      connected: Boolean(evmAddress),
    },
    robinhood: {
      symbol: "ETH",
      name: "Robinhood",
      chain: "robinhood",
      address: evmAddress || null,
      balance: 0,
      connected: Boolean(evmAddress),
    },
  };

  const tasks: Promise<void>[] = [];

  if (solAddress) {
    tasks.push(
      fetchSolanaBalance(solAddress).then((bal) => {
        results.solana.balance = bal;
      })
    );
  }

  if (evmAddress) {
    tasks.push(
      fetchEvmBalance(BSC_RPC, evmAddress).then((bal) => {
        results.bsc.balance = bal;
      }),
      fetchEvmBalance(ROBINHOOD_RPC, evmAddress).then((bal) => {
        results.robinhood.balance = bal;
      })
    );
  }

  await Promise.allSettled(tasks);

  return Response.json({
    success: true,
    balances: results,
    timestamp: Date.now(),
  });
}
