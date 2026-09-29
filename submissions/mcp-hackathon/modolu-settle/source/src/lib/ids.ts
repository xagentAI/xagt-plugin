import { randomBytes } from "node:crypto";

/** Cryptographically random, URL-safe identifier body of `byteLength` bytes. */
export function randomBase64Url(byteLength: number): string {
  return randomBytes(byteLength).toString("base64url");
}

/** Per-request correlation ID surfaced as `X-Request-Id` and in every log line. */
export function newRequestId(): string {
  return `req_${randomBase64Url(16)}`;
}

/** 192 bits of randomness = 24 bytes = 32 base64url characters. */
const PAYMENT_INTENT_ID_RANDOM_BYTES = 24;
const PAYMENT_INTENT_ID_PATTERN = /^pi_[A-Za-z0-9_-]{32}$/;

/**
 * Public payment intent ID: `pi_` + 192 bits of cryptographic randomness,
 * base64url encoded (35 characters). Possession of the ID is the capability
 * to read the intent, so IDs are never sequential or derived from time
 * (ARCHITECTURE.md §4.1, §10).
 */
export function newPaymentIntentId(): string {
  return `pi_${randomBase64Url(PAYMENT_INTENT_ID_RANDOM_BYTES)}`;
}

export function isPaymentIntentId(value: unknown): value is string {
  return typeof value === "string" && PAYMENT_INTENT_ID_PATTERN.test(value);
}
