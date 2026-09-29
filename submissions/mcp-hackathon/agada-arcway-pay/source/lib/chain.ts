import { defineChain } from "viem";

/**
 * Arc testnet, defined locally because viem does not ship it.
 *
 * Values verified against the live RPC rather than copied from docs:
 * `eth_chainId` returns 0x4cef52 (5042002), and the USDC contract at
 * 0x3600…0000 answers `balanceOf` with 6-decimal amounts.
 *
 * USDC IS THE NATIVE GAS TOKEN HERE. `eth_getBalance` and the ERC-20
 * `balanceOf` report the same holding at different precisions — 18 decimals
 * native, 6 as the token. That is not a quirk to work around; it is the whole
 * reason a payee can sign their own withdrawal the moment they are paid,
 * without anyone topping them up with a separate gas asset first.
 *
 * It also means gas is deducted from the same balance as the money, so a payee
 * can never withdraw 100% of their balance.
 */
export const ARC_TESTNET_ID = 5042002;

export const ARC_TESTNET_RPC =
  process.env.NEXT_PUBLIC_USDC_RPC_URL ?? "https://rpc.testnet.arc.network";

export const ARC_USDC_ADDRESS =
  (process.env.NEXT_PUBLIC_USDC_TOKEN_ADDRESS as `0x${string}`) ??
  "0x3600000000000000000000000000000000000000";

/** USDC carries 6 decimals as a token; the native balance is reported at 18. */
export const USDC_DECIMALS = 6;
export const NATIVE_DECIMALS = 18;

export const arcTestnet = defineChain({
  id: ARC_TESTNET_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: NATIVE_DECIMALS },
  rpcUrls: { default: { http: [ARC_TESTNET_RPC] } },
  testnet: true,
});

/** The single ERC-20 method this app needs to encode. */
export const ERC20_TRANSFER_ABI = [
  {
    type: "function",
    name: "transfer",
    stateMutability: "nonpayable",
    inputs: [
      { name: "to", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
] as const;

/** Human USDC -> 6-decimal base units, without going through a float. */
export function toUsdcBaseUnits(amount: number): bigint {
  const [whole, frac = ""] = amount.toFixed(USDC_DECIMALS).split(".");
  return BigInt(whole + frac.padEnd(USDC_DECIMALS, "0"));
}

/**
 * Native 18-decimal wei -> human USDC, for comparing gas against balance.
 * Written with `BigInt(10) ** …` rather than a `10n` literal so the project's
 * ES2017 target is left alone — not worth a tsconfig change for one line.
 */
export function fromNativeWei(wei: bigint): number {
  const scale = BigInt(10) ** BigInt(NATIVE_DECIMALS);
  const whole = wei / scale;
  const frac = wei % scale;
  return Number(whole) + Number(frac) / 10 ** NATIVE_DECIMALS;
}
