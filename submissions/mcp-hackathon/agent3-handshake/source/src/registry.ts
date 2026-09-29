/**
 * The ONLY module that knows the Agent3 hub's field names.
 *
 * Everything downstream works on the normalized shapes defined here, so a
 * change in the hub's wire format lands in exactly one file.
 *
 * Upstream is read-only and public: no API key is required for the endpoints
 * used here, which is deliberate — the capability must stay callable by anyone
 * for the whole review window without a credential that can expire.
 */

export const HUB_BASE =
  process.env.AGENT3_HUB_BASE ?? "https://a2a-hub-chi.vercel.app";

/** One callable operation as the hub publishes it. */
export interface RawOperation {
  id?: string;
  name?: string;
  description?: string;
  bindings?: { http?: { path?: string; method?: string; contentType?: string } };
  inputSchema?: unknown;
  outputSchema?: unknown;
}

/** One registry entry as the hub publishes it. */
export interface RawResource {
  resource_id?: string;
  id?: string;
  name?: string;
  description?: string;
  resource_type?: string;
  visibility?: string;
  provider?: unknown;
  version?: string;
  tags?: unknown;
  categories?: unknown;
  interfaces?: Array<Record<string, unknown>>;
  operations?: RawOperation[];
  /**
   * 🔴 Two incompatible spellings live in this one field across the registry:
   * some rows carry `{model, amount}` and others `{mode, supportsX402, ...}`.
   * `normalizePayment` is the only place allowed to reconcile them.
   */
  payment?: Record<string, unknown>;
  deployment?: Record<string, unknown>;
  access?: unknown;
  data_boundary?: unknown;
  documentation_url?: string;
  total_calls?: number;
  success_rate?: number | null;
  p95_latency?: number | null;
}

export interface Snapshot {
  resources: RawResource[];
  fetchedAt: string;
  /** sha256 over the canonical form of the payload, so a reviewer can pin it. */
  digest: string;
  source: string;
}

import { createHash } from "node:crypto";

/** Stable stringify so the digest does not move when key order does. */
function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return `{${keys
    .map((k) => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`)
    .join(",")}}`;
}

export function digestOf(resources: RawResource[]): string {
  return createHash("sha256").update(canonical(resources)).digest("hex");
}

/**
 * The hub wraps its list in `data`, and has shipped both a bare array and an
 * object holding the array. Accept both rather than guessing one.
 */
export function unwrapList(payload: unknown): RawResource[] {
  const data = (payload as { data?: unknown })?.data;
  if (Array.isArray(data)) return data as RawResource[];
  if (data && typeof data === "object") {
    for (const value of Object.values(data as Record<string, unknown>)) {
      if (Array.isArray(value)) return value as RawResource[];
    }
  }
  if (Array.isArray(payload)) return payload as RawResource[];
  throw new Error("registry payload did not contain a list");
}

export async function fetchResources(timeoutMs = 15_000): Promise<Snapshot> {
  const url = `${HUB_BASE}/api/resources?limit=200`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) throw new Error(`registry responded ${response.status}`);
    const resources = unwrapList(await response.json());
    return {
      resources,
      fetchedAt: new Date().toISOString(),
      digest: digestOf(resources),
      source: url,
    };
  } finally {
    clearTimeout(timer);
  }
}
