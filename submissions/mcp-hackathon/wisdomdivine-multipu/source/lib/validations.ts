import { z } from "zod";

const launchpadIds = ["meteora", "bags", "pumpfun", "fourmeme", "pons", "sherwood"] as const;

// ─── Solana Address Validator ──────────────────────
const solanaAddress = z
  .string()
  .refine(
    (val) =>
      /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(val) ||
      val.startsWith("mock-") ||
      val.startsWith("sim_"),
    "Invalid Solana address"
  );
const evmAddress = z
  .string()
  .refine(
    (val) =>
      /^0x[a-fA-F0-9]{40}$/i.test(val) ||
      val.startsWith("0xmock") ||
      val.startsWith("mock-"),
    "Invalid EVM address"
  );
const txHash = z
  .string()
  .refine(
    (val) =>
      /^0x([A-Fa-f0-9]{64})$/.test(val) ||
      val.startsWith("0xmock") ||
      val.startsWith("mock-") ||
      val.startsWith("sim_"),
    "Invalid EVM tx hash"
  );
const solanaSignature = z
  .string()
  .refine(
    (val) =>
      /^[1-9A-HJ-NP-Za-km-z]{32,128}$/.test(val) ||
      val.startsWith("mock-") ||
      val.startsWith("sim_"),
    "Invalid Solana signature"
  );
const launchAddress = z.union([solanaAddress, evmAddress]);
const chainTx = z.union([solanaSignature, txHash]);

// ─── Token Creation ────────────────────────────────
export const createTokenSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(32, "Name must be 32 chars or less")
    .trim(),
  symbol: z
    .string()
    .min(1, "Symbol is required")
    .max(10, "Symbol must be 10 chars or less")
    .toUpperCase()
    .trim(),
  supply: z
    .string()
    .regex(/^\d+$/, "Supply must be a whole number")
    .refine((s) => BigInt(s) > 0n, "Supply must be greater than 0")
    .refine(
      (s) => BigInt(s) <= 1_000_000_000_000_000n,
      "Supply exceeds maximum (1 quadrillion)"
    ),
  decimals: z.coerce.number().int().min(0).max(9).default(9),
  description: z.string().max(500, "Description too long").optional().default(""),
  imageUrl: z.string().url().optional().nullable(),
});

export type CreateTokenInput = z.infer<typeof createTokenSchema>;

// ─── Update Pending Token ──────────────────────────
export const updatePendingTokenSchema = z.object({
  tokenId: z.string().uuid(),
  name: z
    .string()
    .min(1, "Name is required")
    .max(32, "Name must be 32 chars or less")
    .trim()
    .optional(),
  symbol: z
    .string()
    .min(1, "Symbol is required")
    .max(10, "Symbol must be 10 chars or less")
    .toUpperCase()
    .trim()
    .optional(),
  supply: z
    .string()
    .regex(/^\d+$/, "Supply must be a whole number")
    .refine((s) => BigInt(s) > 0n, "Supply must be greater than 0")
    .refine(
      (s) => BigInt(s) <= 1_000_000_000_000_000n,
      "Supply exceeds maximum (1 quadrillion)"
    )
    .optional(),
  decimals: z.coerce.number().int().min(0).max(9).optional(),
  description: z.string().max(500, "Description too long").optional(),
  imageUrl: z.string().url().optional().nullable(),
});

export type UpdatePendingTokenInput = z.infer<typeof updatePendingTokenSchema>;

// ─── Confirm Token Mint ────────────────────────────
export const confirmTokenSchema = z.object({
  tokenId: z.string().uuid(),
  mintAddress: solanaAddress,
  mintTx: z.string().min(1),
});

export type ConfirmTokenInput = z.infer<typeof confirmTokenSchema>;

// ─── Create Launch ─────────────────────────────────
export const createLaunchSchema = z.object({
  tokenId: z.string().uuid(),
  launchpad: z.enum(launchpadIds),
  initialLiquidity: z.coerce.number().positive().optional(),
});

export type CreateLaunchInput = z.infer<typeof createLaunchSchema>;

// ─── Confirm Launch ────────────────────────────────
export const confirmLaunchSchema = z.object({
  launchId: z.string().uuid(),
  poolAddress: launchAddress,
  launchTx: chainTx,
  initialLiquidity: z.coerce.number().nonnegative().optional(),
});

export type ConfirmLaunchInput = z.infer<typeof confirmLaunchSchema>;

// ─── Record Earning ────────────────────────────────
export const recordEarningSchema = z.object({
  tokenId: z.string().uuid(),
  launchId: z.string().uuid(),
  launchpad: z.enum(launchpadIds),
  amountSol: z.coerce.number().positive(),
  feeType: z.enum(["creator_fee", "lp_fee", "referral"]).default("creator_fee"),
  txSignature: z.string().optional(),
});

export type RecordEarningInput = z.infer<typeof recordEarningSchema>;

// ─── Image Upload ──────────────────────────────────
export const MAX_IMAGE_SIZE = 5 * 1024 * 1024; // 5MB
export const ALLOWED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
] as const;
