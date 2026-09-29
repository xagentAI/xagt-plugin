/**
 * Browser-side client for Settle's public REST API. The demo UI uses exactly
 * the endpoints an external agent uses (ARCHITECTURE.md §3, §6, §19): no
 * privileged path, no server-side shortcut. Safe to import from client
 * components — it has no server-only dependencies.
 */
import type { PaymentStatus, TransferAssociation } from "@/domain/payment-intent";
import type { ErrorCode, ErrorEnvelope } from "@/lib/errors";
import type { EvidenceItemResponse, EvidenceResponse } from "@/validation/evidence";
import type { PaymentIntentResponse } from "@/validation/payment-intents";

export type { EvidenceItemResponse, EvidenceResponse, PaymentIntentResponse, PaymentStatus, TransferAssociation };

/** `NETWORK_ERROR` is client-side only: the request never produced an API response. */
export type ApiErrorCode = ErrorCode | "NETWORK_ERROR";

export interface ApiError {
  readonly code: ApiErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly status: number | null;
}

export type ApiResult<T> = { readonly ok: true; readonly data: T } | { readonly ok: false; readonly error: ApiError };

const KNOWN_CODES: ReadonlySet<string> = new Set<ApiErrorCode>([
  "VALIDATION_ERROR",
  "INVALID_ADDRESS",
  "UNSUPPORTED_CHAIN",
  "UNSUPPORTED_ASSET",
  "INTENT_NOT_FOUND",
  "RATE_LIMITED",
  "UPSTREAM_UNAVAILABLE",
  "UPSTREAM_INVALID_RESPONSE",
  "INTERNAL_ERROR",
]);

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && typeof (error as { code?: unknown }).code === "string";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { accept: "application/json", ...init.headers } });
  } catch {
    return {
      ok: false,
      error: { code: "NETWORK_ERROR", message: "Could not reach Settle.", retryable: true, status: null },
    };
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok) {
    return { ok: true, data: body as T };
  }
  if (isErrorEnvelope(body) && KNOWN_CODES.has(body.error.code)) {
    return {
      ok: false,
      error: { code: body.error.code, message: body.error.message, retryable: body.error.retryable, status: response.status },
    };
  }
  return {
    ok: false,
    error: {
      code: "INTERNAL_ERROR",
      message: "Settle returned an unexpected response.",
      retryable: response.status >= 500,
      status: response.status,
    },
  };
}

export interface CreatePaymentIntentRequest {
  readonly chain: "base";
  readonly asset: "USDC";
  readonly amount: string;
  readonly recipient: string;
  readonly expiresAt: string;
  readonly payer?: string;
  readonly externalReference?: string;
  readonly requiredConfirmations?: number;
}

export const publicApi = {
  createPaymentIntent(body: CreatePaymentIntentRequest): Promise<ApiResult<PaymentIntentResponse>> {
    return request<PaymentIntentResponse>("/v1/payment-intents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  getPaymentIntent(id: string): Promise<ApiResult<PaymentIntentResponse>> {
    return request<PaymentIntentResponse>(`/v1/payment-intents/${encodeURIComponent(id)}`);
  },
  reconcilePaymentIntent(id: string): Promise<ApiResult<PaymentIntentResponse>> {
    return request<PaymentIntentResponse>(`/v1/payment-intents/${encodeURIComponent(id)}/reconcile`, { method: "POST" });
  },
  getEvidence(id: string, limit = 100): Promise<ApiResult<EvidenceResponse>> {
    return request<EvidenceResponse>(`/v1/payment-intents/${encodeURIComponent(id)}/evidence?limit=${limit}`);
  },
};

/** Statuses after which the obligation cannot change without new canonical evidence; polling stops here. */
export const TERMINAL_STATUSES: ReadonlySet<PaymentStatus> = new Set<PaymentStatus>(["paid", "overpaid", "expired", "ambiguous"]);

export function isTerminalStatus(status: PaymentStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export interface StatusCopy {
  readonly label: string;
  readonly explanation: string;
  /** Short glyph so the state never relies on colour alone. */
  readonly glyph: string;
}

export const STATUS_COPY: Readonly<Record<PaymentStatus, StatusCopy>> = {
  pending: { label: "Pending", explanation: "No matching payment has been observed yet.", glyph: "○" },
  detected: {
    label: "Detected",
    explanation: "A matching transfer exists but has not reached the required confirmation depth.",
    glyph: "◔",
  },
  partial: { label: "Partial", explanation: "Part of the expected payment has been confirmed.", glyph: "◑" },
  paid: { label: "Paid", explanation: "The payment obligation has been satisfied.", glyph: "●" },
  overpaid: { label: "Overpaid", explanation: "Confirmed payment exceeds the declared amount.", glyph: "⊕" },
  expired: { label: "Expired", explanation: "The payment window ended before the obligation was satisfied.", glyph: "⊘" },
  ambiguous: {
    label: "Ambiguous",
    explanation: "Multiple plausible senders were observed and Settle cannot determine the payer with certainty.",
    glyph: "◈",
  },
};

export interface AssociationCopy {
  readonly label: string;
  readonly explanation: string;
}

export const ASSOCIATION_COPY: Readonly<Record<TransferAssociation, AssociationCopy>> = {
  matched: { label: "Matched", explanation: "Verified evidence associated with the obligation." },
  candidate: { label: "Candidate", explanation: "Observed evidence that cannot yet be deterministically associated." },
  orphaned: { label: "Orphaned", explanation: "Previously observed evidence that is no longer canonical." },
};

export interface ErrorCopy {
  readonly title: string;
  readonly detail: string;
}

/** User-facing framing per stable code; the server message is shown alongside when it is a request problem. */
export function describeApiError(error: ApiError): ErrorCopy {
  switch (error.code) {
    case "VALIDATION_ERROR":
      return { title: "Request rejected", detail: error.message };
    case "INVALID_ADDRESS":
      return { title: "Invalid address", detail: error.message };
    case "UNSUPPORTED_CHAIN":
    case "UNSUPPORTED_ASSET":
      return { title: "Unsupported rail", detail: "Settle currently reconciles native USDC on Base only." };
    case "INTENT_NOT_FOUND":
      return { title: "Payment intent not found", detail: "No payment intent exists with this ID." };
    case "RATE_LIMITED":
      return { title: "Too many requests", detail: "Settle is rate-limiting this client. Wait a moment and retry." };
    case "UPSTREAM_UNAVAILABLE":
      return {
        title: "Blockchain evidence unavailable",
        detail:
          "Settle could not retrieve evidence from Base right now. The last known payment state is shown unchanged; this is not a “no payment found” result. Retry shortly.",
      };
    case "UPSTREAM_INVALID_RESPONSE":
      return {
        title: "Blockchain evidence unusable",
        detail:
          "The blockchain provider returned data Settle could not verify. The last known payment state is shown unchanged. Retry shortly.",
      };
    case "NETWORK_ERROR":
      return { title: "Could not reach Settle", detail: "Check your connection and retry." };
    case "INTERNAL_ERROR":
    default:
      return { title: "Settle hit an internal error", detail: "Nothing was changed. Retry, and report this if it persists." };
  }
}
