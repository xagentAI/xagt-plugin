import { describe, expect, it } from "vitest";

import { USDC_TOKEN_ADDRESS } from "@/domain/payment-intent";
import { normalizeAddress, toChecksumAddress } from "@/lib/addresses";

const USDC_CHECKSUM = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";

describe("normalizeAddress", () => {
  it("lowercases a valid checksummed address", () => {
    expect(normalizeAddress(USDC_CHECKSUM)).toBe(USDC_TOKEN_ADDRESS);
  });

  it("accepts all-lowercase hex", () => {
    expect(normalizeAddress(USDC_TOKEN_ADDRESS)).toBe(USDC_TOKEN_ADDRESS);
  });

  it.each([
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02914", // bad EIP-55 checksum
    `0x${USDC_TOKEN_ADDRESS.slice(2).toUpperCase()}`, // all-uppercase fails viem's strict checksum rule
    "833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", // missing 0x
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA0291", // 39 hex chars
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA029133", // 41 hex chars
    "0xZZ3589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "vitalik.eth",
    "",
    " 0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    42,
    null,
  ])("rejects %j", (value) => {
    expect(normalizeAddress(value)).toBeNull();
  });
});

describe("toChecksumAddress", () => {
  it("presents a stored lowercase address in EIP-55 form", () => {
    expect(toChecksumAddress(USDC_TOKEN_ADDRESS)).toBe(USDC_CHECKSUM);
  });
});
