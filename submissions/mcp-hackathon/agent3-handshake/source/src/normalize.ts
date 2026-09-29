/**
 * Turns a registry entry into something a caller can act on, and names every
 * place where the entry does not support that.
 *
 * Design rule: never invent a value. When the registry does not say something,
 * the result says "not stated" and the entry carries a blocker. A plausible
 * default here would read exactly like a real answer to the agent calling us,
 * which is the failure this capability exists to prevent.
 */

import type { RawOperation, RawResource } from "./registry.js";

/** Hosts whose registrations have lapsed, so anything pointing at them is unreachable. */
export const RETIRED_HOSTS = ["agent3.space", "agent3.me"] as const;

export type Severity = "blocker" | "warning";

export interface Defect {
  code: string;
  severity: Severity;
  field: string;
  detail: string;
}

export type PaymentKind = "free" | "priced" | "not_stated";

export interface NormalizedPayment {
  kind: PaymentKind;
  /** Price per call in USD when the entry states one. */
  amount: number | null;
  currency: string | null;
  /** Where the payment would be settled, when stated. */
  gateway: string | null;
  supportsX402: boolean | null;
  /**
   * Which spelling the entry actually used. Kept because the two spellings are
   * the defect: a caller that reads only one of them silently sees nothing.
   */
  statedVia: "model" | "mode" | "none";
  raw: Record<string, unknown>;
}

/**
 * 🔴 The registry stores the payment kind under two different keys.
 * Reading only `mode` misses the rows that use `model`, and the miss is silent:
 * `undefined` is indistinguishable from "this entry is free".
 */
export function normalizePayment(raw: Record<string, unknown> | undefined): NormalizedPayment {
  const payment = raw ?? {};
  const viaMode = typeof payment.mode === "string" ? (payment.mode as string) : null;
  const viaModel = typeof payment.model === "string" ? (payment.model as string) : null;
  const stated = viaMode ?? viaModel;
  const statedVia: NormalizedPayment["statedVia"] = viaMode ? "mode" : viaModel ? "model" : "none";

  const amount = typeof payment.amount === "number" ? (payment.amount as number) : null;
  const currency = typeof payment.currency === "string" ? (payment.currency as string) : null;
  const gateway = typeof payment.gateway === "string" ? (payment.gateway as string) : null;
  const supportsX402 =
    typeof payment.supportsX402 === "boolean" ? (payment.supportsX402 as boolean) : null;

  let kind: PaymentKind;
  if (stated === null) kind = "not_stated";
  else if (stated.toLowerCase() === "free") kind = "free";
  else kind = "priced";

  // An entry that names a price of zero is still free; one that names a
  // non-zero price without a currency is priced but underspecified.
  if (kind === "priced" && amount === 0) kind = "free";

  return { kind, amount, currency, gateway, supportsX402, statedVia, raw: payment };
}

/** True when the URL's host is one of the lapsed registrations. */
export function pointsAtRetiredHost(url: string): string | null {
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  for (const retired of RETIRED_HOSTS) {
    if (host === retired || host.endsWith(`.${retired}`)) return retired;
  }
  return null;
}

export interface ResolvedInterface {
  /** Absolute base URL, or null when the entry only gave a relative path. */
  baseUrl: string | null;
  type: string | null;
  protocol: string | null;
  rawUrl: string | null;
}

export function resolveInterface(entry: Record<string, unknown> | undefined): ResolvedInterface {
  const rawUrl = typeof entry?.url === "string" ? (entry.url as string) : null;
  const type = typeof entry?.type === "string" ? (entry.type as string) : null;
  const protocol = typeof entry?.protocol === "string" ? (entry.protocol as string) : null;
  let baseUrl: string | null = null;
  if (rawUrl && /^https?:\/\//i.test(rawUrl)) baseUrl = rawUrl.replace(/\/+$/, "");
  return { baseUrl, type, protocol, rawUrl };
}

export function operationId(operation: RawOperation, index: number): string {
  return operation.id ?? operation.name ?? `operation_${index}`;
}

export function resourceId(resource: RawResource): string {
  return resource.resource_id ?? resource.id ?? "";
}

/**
 * Everything wrong with one entry, as a caller would experience it.
 * A blocker means "you cannot complete a call from what is published here".
 */
export function inspect(resource: RawResource): Defect[] {
  const defects: Defect[] = [];
  const interfaces = Array.isArray(resource.interfaces) ? resource.interfaces : [];

  if (interfaces.length === 0) {
    defects.push({
      code: "no_interface",
      severity: "blocker",
      field: "interfaces",
      detail: "the entry publishes no interface, so there is no address to call",
    });
  }

  interfaces.forEach((entry, index) => {
    const resolved = resolveInterface(entry as Record<string, unknown>);
    if (!resolved.rawUrl) {
      defects.push({
        code: "interface_without_url",
        severity: "blocker",
        field: `interfaces[${index}].url`,
        detail: "interface carries no url",
      });
      return;
    }
    if (!resolved.baseUrl) {
      defects.push({
        code: "relative_interface_url",
        severity: "blocker",
        field: `interfaces[${index}].url`,
        detail: `url "${resolved.rawUrl}" is relative, so an external caller has no host to resolve it against`,
      });
      return;
    }
    const retired = pointsAtRetiredHost(resolved.baseUrl);
    if (retired) {
      defects.push({
        code: "interface_on_retired_host",
        severity: "blocker",
        field: `interfaces[${index}].url`,
        detail: `url points at ${retired}, whose registration has lapsed`,
      });
    }
  });

  const payment = normalizePayment(resource.payment);
  if (payment.statedVia === "none") {
    defects.push({
      code: "payment_kind_not_stated",
      severity: "blocker",
      field: "payment",
      detail:
        "neither payment.mode nor payment.model is present, so a caller cannot tell whether this costs money",
    });
  } else if (payment.statedVia === "model") {
    defects.push({
      code: "payment_kind_under_legacy_key",
      severity: "warning",
      field: "payment.model",
      detail:
        'the payment kind is published under "model"; a caller that reads "mode" finds nothing there and would treat a priced entry as free',
    });
  }

  if (payment.kind === "priced") {
    if (payment.currency === null) {
      defects.push({
        code: "price_without_currency",
        severity: "warning",
        field: "payment.currency",
        detail: `amount ${payment.amount} is published without a currency`,
      });
    }
    if (payment.gateway === null) {
      defects.push({
        code: "price_without_gateway",
        severity: "blocker",
        field: "payment.gateway",
        detail: "a price is published but no settlement address is, so the call cannot be paid for",
      });
    } else {
      const retired = pointsAtRetiredHost(payment.gateway);
      if (retired) {
        defects.push({
          code: "gateway_on_retired_host",
          severity: "blocker",
          field: "payment.gateway",
          detail: `the settlement gateway points at ${retired}, whose registration has lapsed, so this priced call cannot be paid for`,
        });
      }
    }
  }

  const operations = Array.isArray(resource.operations) ? resource.operations : [];
  if (operations.length === 0) {
    defects.push({
      code: "no_operations",
      severity: "blocker",
      field: "operations",
      detail: "the entry publishes no operations, so there is nothing to invoke",
    });
  }

  operations.forEach((operation, index) => {
    const id = operationId(operation, index);
    const http = operation.bindings?.http;
    if (!http) {
      defects.push({
        code: "operation_without_binding",
        severity: "blocker",
        field: `operations[${index}].bindings.http`,
        detail: `operation "${id}" publishes no http binding, so there is no path or method to call`,
      });
      return;
    }
    if (!http.path) {
      defects.push({
        code: "binding_without_path",
        severity: "blocker",
        field: `operations[${index}].bindings.http.path`,
        detail: `operation "${id}" has an http binding with no path`,
      });
    }
    if (!http.method) {
      defects.push({
        code: "binding_without_method",
        severity: "warning",
        field: `operations[${index}].bindings.http.method`,
        detail: `operation "${id}" does not state a method`,
      });
    }
    if (!operation.inputSchema) {
      defects.push({
        code: "operation_without_input_schema",
        severity: "warning",
        field: `operations[${index}].inputSchema`,
        detail: `operation "${id}" publishes no input schema, so a caller has to guess the body`,
      });
    }
  });

  return defects;
}
