"use client";

import { createPublicClient, encodeFunctionData, http } from "viem";
import {
  ARC_USDC_ADDRESS,
  ERC20_TRANSFER_ABI,
  arcTestnet,
  fromNativeWei,
  toUsdcBaseUnits,
} from "./chain";

/**
 * Gas maths for a payee withdrawal.
 *
 * USDC is the native gas token on Arc, so gas and the money come out of ONE
 * balance. That makes the old fixed 0.01 constant actively wrong: a payee
 * cannot withdraw their whole balance, and how much they must hold back
 * depends on the network at that moment, not on a number we invented.
 */

/** Head-room on the estimate, since gas price can move between quote and send. */
const GAS_MARGIN = 1.25;

export const publicClient = createPublicClient({
  chain: arcTestnet,
  transport: http(),
});

export interface GasQuote {
  /** Estimated fee in USDC (native units are USDC on Arc). */
  feeUsdc: number;
  /** The payee's whole balance, in USDC. */
  balanceUsdc: number;
  /** Most that can actually be sent: balance minus estimated fee. */
  maxSendableUsdc: number;
}

export function encodeUsdcTransfer(to: string, amountUsdc: number): `0x${string}` {
  return encodeFunctionData({
    abi: ERC20_TRANSFER_ABI,
    functionName: "transfer",
    args: [to as `0x${string}`, toUsdcBaseUnits(amountUsdc)],
  });
}

/**
 * Estimates the fee for the real transfer — the actual calldata, from the
 * actual sender — rather than assuming a flat cost.
 *
 * Falls back to a conservative fixed estimate if the node refuses to simulate
 * (which it will if the balance cannot cover the amount being quoted), so the
 * UI can still show a number and a Max instead of failing outright.
 */
export async function quoteGas(
  from: string,
  to: string,
  amountUsdc: number
): Promise<GasQuote> {
  const balanceWei = await publicClient.getBalance({ address: from as `0x${string}` });
  const balanceUsdc = fromNativeWei(balanceWei);

  let feeUsdc: number;
  try {
    const [gas, fees] = await Promise.all([
      publicClient.estimateGas({
        account: from as `0x${string}`,
        to: ARC_USDC_ADDRESS,
        data: encodeUsdcTransfer(to, amountUsdc),
      }),
      publicClient.estimateFeesPerGas(),
    ]);
    const pricePerGas =
      fees.maxFeePerGas ?? fees.gasPrice ?? BigInt(0);
    feeUsdc = fromNativeWei(gas * pricePerGas) * GAS_MARGIN;
  } catch {
    // A typical ERC-20 transfer on Arc used ~74k gas; this is a deliberately
    // generous stand-in used only when simulation is impossible.
    feeUsdc = 0.01;
  }

  return {
    feeUsdc,
    balanceUsdc,
    maxSendableUsdc: Math.max(0, balanceUsdc - feeUsdc),
  };
}

/** Native balance in USDC — the figure the affordability assert compares against. */
export async function nativeBalanceUsdc(address: string): Promise<number> {
  return fromNativeWei(
    await publicClient.getBalance({ address: address as `0x${string}` })
  );
}
