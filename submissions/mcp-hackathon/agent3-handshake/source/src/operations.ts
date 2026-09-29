/**
 * The five capabilities, written once and served through both doors (REST and
 * MCP) so the two can never drift apart.
 */

import { buildCallSpec, type CallSpecResult } from "./callspec.js";
import {
  type Defect,
  inspect,
  normalizePayment,
  operationId,
  resourceId,
} from "./normalize.js";
import { type RawResource, type Snapshot, fetchResources } from "./registry.js";

const CACHE_TTL_MS = Number(process.env.HANDSHAKE_CACHE_TTL_MS ?? 120_000);

let cached: Snapshot | null = null;
let cachedAt = 0;
let refreshCount = 0;

/**
 * One upstream read serves every caller for the cache window. This is what
 * makes the capability free to hammer: a reviewer calling it ten thousand
 * times over the review period costs the same as calling it once.
 */
export async function snapshot(force = false): Promise<Snapshot> {
  const now = Date.now();
  if (!force && cached && now - cachedAt < CACHE_TTL_MS) return cached;
  const fresh = await fetchResources();
  cached = fresh;
  cachedAt = now;
  refreshCount += 1;
  return fresh;
}

export function cacheStats() {
  return {
    ageSeconds: cached ? Math.round((Date.now() - cachedAt) / 1000) : null,
    ttlSeconds: Math.round(CACHE_TTL_MS / 1000),
    refreshCount,
  };
}

function find(resources: RawResource[], wanted: string): RawResource | null {
  for (const resource of resources) {
    if (resourceId(resource) === wanted) return resource;
    if (resource.name === wanted) return resource;
  }
  return null;
}

function severityCounts(defects: Defect[]) {
  return {
    blockers: defects.filter((d) => d.severity === "blocker").length,
    warnings: defects.filter((d) => d.severity === "warning").length,
  };
}

export interface AuditRow {
  resourceId: string;
  name: string | null;
  type: string | null;
  operationCount: number;
  callable: boolean;
  blockers: Defect[];
  warnings: Defect[];
  payment: ReturnType<typeof normalizePayment>;
}

/** Every entry in the registry, with whether a call can be built from it. */
export async function auditRegistry() {
  const snap = await snapshot();
  const rows: AuditRow[] = snap.resources.map((resource) => {
    const defects = inspect(resource);
    const counts = severityCounts(defects);
    return {
      resourceId: resourceId(resource),
      name: resource.name ?? null,
      type: resource.resource_type ?? null,
      operationCount: Array.isArray(resource.operations) ? resource.operations.length : 0,
      callable: counts.blockers === 0,
      blockers: defects.filter((d) => d.severity === "blocker"),
      warnings: defects.filter((d) => d.severity === "warning"),
      payment: normalizePayment(resource.payment),
    };
  });

  const byCode: Record<string, number> = {};
  for (const row of rows) {
    for (const defect of [...row.blockers, ...row.warnings]) {
      byCode[defect.code] = (byCode[defect.code] ?? 0) + 1;
    }
  }

  return {
    provenance: {
      source: snap.source,
      fetchedAt: snap.fetchedAt,
      digest: snap.digest,
      ...cacheStats(),
    },
    totals: {
      entries: rows.length,
      callable: rows.filter((r) => r.callable).length,
      blocked: rows.filter((r) => !r.callable).length,
    },
    defectsByCode: byCode,
    entries: rows,
  };
}

/** Everything published about one entry, normalized. */
export async function describeEntry(wanted: string) {
  const snap = await snapshot();
  const resource = find(snap.resources, wanted);
  if (!resource) {
    return {
      found: false as const,
      requested: wanted,
      available: snap.resources.map((r) => ({ resourceId: resourceId(r), name: r.name ?? null })),
    };
  }
  const defects = inspect(resource);
  const operations = (Array.isArray(resource.operations) ? resource.operations : []).map(
    (operation, index) => ({
      operationId: operationId(operation, index),
      name: operation.name ?? null,
      method: operation.bindings?.http?.method ?? null,
      path: operation.bindings?.http?.path ?? null,
      hasInputSchema: Boolean(operation.inputSchema),
    }),
  );
  return {
    found: true as const,
    resourceId: resourceId(resource),
    name: resource.name ?? null,
    description: resource.description ?? null,
    type: resource.resource_type ?? null,
    operations,
    payment: normalizePayment(resource.payment),
    blockers: defects.filter((d) => d.severity === "blocker"),
    warnings: defects.filter((d) => d.severity === "warning"),
  };
}

/** The request a caller would send, or a refusal naming what is missing. */
export async function planCall(
  wantedResource: string,
  wantedOperation: string,
): Promise<
  | { found: false; requested: string; available: Array<{ resourceId: string; name: string | null }> }
  | ({ found: true } & CallSpecResult)
> {
  const snap = await snapshot();
  const resource = find(snap.resources, wantedResource);
  if (!resource) {
    return {
      found: false,
      requested: wantedResource,
      available: snap.resources.map((r) => ({ resourceId: resourceId(r), name: r.name ?? null })),
    };
  }
  return { found: true, ...buildCallSpec(resource, wantedOperation) };
}

/**
 * The payment field read both ways, side by side.
 *
 * This exists because the registry publishes the payment kind under two
 * different keys, and a caller that reads only one of them gets `undefined`
 * for the other half of the registry — which is indistinguishable from "free".
 */
export async function paymentReadings() {
  const snap = await snapshot();
  const rows = snap.resources.map((resource) => {
    const payment = resource.payment ?? {};
    const normalized = normalizePayment(resource.payment);
    return {
      resourceId: resourceId(resource),
      name: resource.name ?? null,
      readingModeOnly: typeof payment.mode === "string" ? payment.mode : null,
      readingModelOnly: typeof payment.model === "string" ? payment.model : null,
      statedVia: normalized.statedVia,
      resolvedKind: normalized.kind,
      amount: normalized.amount,
      currency: normalized.currency,
      gateway: normalized.gateway,
    };
  });
  const missedByModeReader = rows.filter((r) => r.readingModeOnly === null && r.statedVia !== "none");
  const missedByModelReader = rows.filter(
    (r) => r.readingModelOnly === null && r.statedVia !== "none",
  );
  return {
    provenance: { source: snap.source, fetchedAt: snap.fetchedAt, digest: snap.digest },
    summary: {
      entries: rows.length,
      statedUnderMode: rows.filter((r) => r.statedVia === "mode").length,
      statedUnderModel: rows.filter((r) => r.statedVia === "model").length,
      statedNowhere: rows.filter((r) => r.statedVia === "none").length,
      missedByAModeOnlyReader: missedByModeReader.length,
      missedByAModelOnlyReader: missedByModelReader.length,
    },
    entries: rows,
  };
}

/** What the registry looked like when we read it, for pinning a review. */
export async function registrySnapshot() {
  const snap = await snapshot();
  return {
    source: snap.source,
    fetchedAt: snap.fetchedAt,
    digest: snap.digest,
    entryCount: snap.resources.length,
    entryIds: snap.resources.map((r) => resourceId(r)),
    ...cacheStats(),
  };
}
