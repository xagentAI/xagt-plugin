/**
 * viem-typed Base / native USDC constants for the chain integration layer.
 * The canonical values live in `src/domain/payment-intent.ts`; this module
 * binds them to viem's chain definition and ABI types and asserts they agree.
 */
import { getAddress, parseAbi, type Address, type Chain } from "viem";
import { base } from "viem/chains";

import { CHAIN_ID, USDC_TOKEN_ADDRESS } from "@/domain/payment-intent";

if (base.id !== CHAIN_ID) {
  throw new Error(`viem Base chain id ${base.id} does not match architecture constant ${CHAIN_ID}`);
}

/** viem chain definition for Base mainnet (chain id 8453). */
export const BASE_CHAIN: Chain = base;

/** Native Circle USDC on Base, EIP-55 checksummed for RPC filters. */
export const USDC_CONTRACT_ADDRESS: Address = getAddress(USDC_TOKEN_ADDRESS);

/** ERC-20 Transfer event; the only log the reconciliation adapter will ever read. */
export const ERC20_TRANSFER_EVENT_ABI = parseAbi([
  "event Transfer(address indexed from, address indexed to, uint256 value)",
]);
