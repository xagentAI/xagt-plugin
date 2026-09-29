/**
 * Builds the request an agent would actually send, from what the registry
 * publishes — or refuses, naming what is missing.
 *
 * The refusal is the product as much as the success case. A call spec that
 * quietly filled in a guessed method or a guessed base URL would be
 * indistinguishable from one the registry really supports, and the caller
 * would only find out by sending it.
 */

import {
  type Defect,
  type NormalizedPayment,
  inspect,
  normalizePayment,
  operationId,
  resolveInterface,
  resourceId,
} from "./normalize.js";
import type { RawOperation, RawResource } from "./registry.js";

export interface CallSpec {
  resourceId: string;
  resourceName: string | null;
  operationId: string;
  operationName: string | null;
  method: string;
  url: string;
  headers: Record<string, string>;
  /** JSON Schema for the body, as published. Null when the entry omits it. */
  bodySchema: unknown | null;
  requiredFields: string[];
  payment: NormalizedPayment;
  /**
   * Warnings do not stop the call, but the caller should see them before
   * sending. Blockers never appear here — they make `buildCallSpec` refuse.
   */
  warnings: Defect[];
}

export interface CallSpecRefusal {
  resourceId: string;
  resourceName: string | null;
  operationId: string | null;
  /** Why this cannot be turned into a request. Never empty. */
  blockers: Defect[];
  warnings: Defect[];
}

export type CallSpecResult =
  | { ok: true; spec: CallSpec }
  | { ok: false; refusal: CallSpecRefusal };

function joinUrl(base: string, path: string): string {
  const left = base.replace(/\/+$/, "");
  const right = path.startsWith("/") ? path : `/${path}`;
  return `${left}${right}`;
}

function requiredOf(schema: unknown): string[] {
  const required = (schema as { required?: unknown })?.required;
  return Array.isArray(required) ? required.filter((x): x is string => typeof x === "string") : [];
}

export function findOperation(
  resource: RawResource,
  wanted: string,
): { operation: RawOperation; index: number } | null {
  const operations = Array.isArray(resource.operations) ? resource.operations : [];
  for (let index = 0; index < operations.length; index += 1) {
    if (operationId(operations[index], index) === wanted) {
      return { operation: operations[index], index };
    }
  }
  return null;
}

export function buildCallSpec(resource: RawResource, wantedOperation: string): CallSpecResult {
  const id = resourceId(resource);
  const name = resource.name ?? null;
  const all = inspect(resource);

  const found = findOperation(resource, wantedOperation);
  if (!found) {
    const available = (Array.isArray(resource.operations) ? resource.operations : []).map(
      (operation, index) => operationId(operation, index),
    );
    return {
      ok: false,
      refusal: {
        resourceId: id,
        resourceName: name,
        operationId: null,
        blockers: [
          {
            code: "operation_not_found",
            severity: "blocker",
            field: "operations",
            detail: `this entry publishes no operation "${wantedOperation}"; it publishes ${
              available.length === 0 ? "none" : available.map((x) => `"${x}"`).join(", ")
            }`,
          },
        ],
        warnings: all.filter((defect) => defect.severity === "warning"),
      },
    };
  }

  const { operation, index } = found;
  // Only the defects that belong to this operation, plus the entry-wide ones.
  const scoped = all.filter(
    (defect) => !/^operations\[\d+\]/.test(defect.field) || defect.field.startsWith(`operations[${index}]`),
  );
  const blockers = scoped.filter((defect) => defect.severity === "blocker");
  const warnings = scoped.filter((defect) => defect.severity === "warning");

  if (blockers.length > 0) {
    return {
      ok: false,
      refusal: {
        resourceId: id,
        resourceName: name,
        operationId: operationId(operation, index),
        blockers,
        warnings,
      },
    };
  }

  const interfaces = Array.isArray(resource.interfaces) ? resource.interfaces : [];
  // `inspect` already established every interface resolves; take the first.
  const base = resolveInterface(interfaces[0] as Record<string, unknown>).baseUrl;
  if (base === null) {
    // Unreachable: a null base is a blocker above. Kept as an explicit
    // invariant rather than a silent fallback.
    throw new Error("invariant: interface resolved during inspection but not here");
  }

  const http = operation.bindings?.http ?? {};
  const headers: Record<string, string> = {};
  if (http.contentType) headers["content-type"] = http.contentType;

  const payment = normalizePayment(resource.payment);
  if (payment.kind === "priced" && payment.gateway) {
    // X402 carries the payment in a request header; the caller supplies the
    // value, we state that it is required and where it settles.
    headers["x-payment"] = "<x402 payment payload>";
  }

  return {
    ok: true,
    spec: {
      resourceId: id,
      resourceName: name,
      operationId: operationId(operation, index),
      operationName: operation.name ?? null,
      method: (http.method ?? "POST").toUpperCase(),
      url: joinUrl(base, http.path as string),
      headers,
      bodySchema: operation.inputSchema ?? null,
      requiredFields: requiredOf(operation.inputSchema),
      payment,
      warnings,
    },
  };
}
