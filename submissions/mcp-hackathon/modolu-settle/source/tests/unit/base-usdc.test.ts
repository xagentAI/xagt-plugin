import { describe, expect, it } from "vitest";

import { CHAIN_ID, USDC_DECIMALS, USDC_TOKEN_ADDRESS } from "@/domain/payment-intent";
import { BASE_CHAIN, ERC20_TRANSFER_EVENT_ABI, USDC_CONTRACT_ADDRESS } from "@/integrations/chain/base-usdc";

describe("Base / USDC constants", () => {
  it("pin the architecture's network constants", () => {
    expect(CHAIN_ID).toBe(8453);
    expect(BASE_CHAIN.id).toBe(8453);
    expect(USDC_DECIMALS).toBe(6);
    expect(USDC_TOKEN_ADDRESS).toBe("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913");
    expect(USDC_CONTRACT_ADDRESS).toBe("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913");
  });

  it("declares only the ERC-20 Transfer event", () => {
    expect(ERC20_TRANSFER_EVENT_ABI).toHaveLength(1);
    expect(ERC20_TRANSFER_EVENT_ABI[0]).toMatchObject({ type: "event", name: "Transfer" });
  });
});
