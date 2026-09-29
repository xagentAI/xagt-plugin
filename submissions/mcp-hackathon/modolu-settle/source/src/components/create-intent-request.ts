/**
 * Pure helpers behind the create-intent form: client-side pre-validation
 * (a convenience, never a replacement for server validation), request-body
 * construction, and mapping server errors back onto fields.
 */
import type { ApiError, CreatePaymentIntentRequest } from "@/lib/public-api";

export interface CreateIntentFormValues {
  readonly amount: string;
  readonly recipient: string;
  readonly payer: string;
  readonly expiresAt: string;
  readonly externalReference: string;
  readonly requiredConfirmations: string;
}

export type CreateIntentField = keyof CreateIntentFormValues;
export type FieldErrors = Partial<Record<CreateIntentField, string>>;

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const AMOUNT = /^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/;
const MAX_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;

export const DEFAULT_REQUIRED_CONFIRMATIONS = "3";

/** `datetime-local` value (browser local time) → UTC ISO string with a Z suffix, or null when unparsable. */
export function localDateTimeToIso(value: string): string | null {
  if (value === "") {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Default expiry shown in the form: 24 hours from now, in the browser's local `datetime-local` format. */
export function defaultExpiryLocal(now: Date = new Date()): string {
  const target = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}T${pad(target.getHours())}:${pad(target.getMinutes())}`;
}

export function validateCreateIntentForm(values: CreateIntentFormValues, now: Date = new Date()): FieldErrors {
  const errors: FieldErrors = {};
  const amount = values.amount.trim();
  if (amount === "") {
    errors.amount = "Enter the expected amount.";
  } else if (!AMOUNT.test(amount) || Number(amount) === 0) {
    errors.amount = "Use a positive decimal with at most 6 decimal places, e.g. 25.00.";
  }

  const recipient = values.recipient.trim();
  if (recipient === "") {
    errors.recipient = "Enter the recipient address.";
  } else if (!ADDRESS.test(recipient)) {
    errors.recipient = "Must be a 0x-prefixed, 40-character hexadecimal Base address.";
  }

  const payer = values.payer.trim();
  if (payer !== "" && !ADDRESS.test(payer)) {
    errors.payer = "Must be a 0x-prefixed, 40-character hexadecimal Base address.";
  }

  const iso = localDateTimeToIso(values.expiresAt);
  if (iso === null) {
    errors.expiresAt = "Choose when the payment window closes.";
  } else {
    const ms = new Date(iso).getTime();
    if (ms <= now.getTime()) {
      errors.expiresAt = "Expiry must be in the future.";
    } else if (ms > now.getTime() + MAX_LIFETIME_MS) {
      errors.expiresAt = "Expiry can be at most 7 days from now.";
    }
  }

  const confirmations = values.requiredConfirmations.trim();
  if (confirmations !== "" && !/^(?:[1-9]|[1-5][0-9]|6[0-4])$/.test(confirmations)) {
    errors.requiredConfirmations = "Use a whole number between 1 and 64.";
  }

  if (values.externalReference.length > 128) {
    errors.externalReference = "At most 128 characters.";
  }
  return errors;
}

/** Builds the exact `POST /v1/payment-intents` body; optional fields are omitted when blank. */
export function buildCreateIntentRequest(values: CreateIntentFormValues): CreatePaymentIntentRequest {
  const iso = localDateTimeToIso(values.expiresAt);
  const body: {
    chain: "base";
    asset: "USDC";
    amount: string;
    recipient: string;
    expiresAt: string;
    payer?: string;
    externalReference?: string;
    requiredConfirmations?: number;
  } = {
    chain: "base",
    asset: "USDC",
    amount: values.amount.trim(),
    recipient: values.recipient.trim(),
    expiresAt: iso ?? values.expiresAt,
  };
  const payer = values.payer.trim();
  if (payer !== "") {
    body.payer = payer;
  }
  const externalReference = values.externalReference.trim();
  if (externalReference !== "") {
    body.externalReference = externalReference;
  }
  const confirmations = values.requiredConfirmations.trim();
  if (confirmations !== "") {
    body.requiredConfirmations = Number(confirmations);
  }
  return body;
}

const FIELD_NAMES: ReadonlySet<string> = new Set<CreateIntentField>([
  "amount",
  "recipient",
  "payer",
  "expiresAt",
  "externalReference",
  "requiredConfirmations",
]);

/**
 * Attaches a server-side rejection to the fields it names. The API phrases
 * validation problems as `field: reason; field: reason` and address problems
 * as `recipient must be …`; anything else stays a form-level message.
 */
export function mapServerErrorToFields(error: ApiError): { fields: FieldErrors; form: string | null } {
  if (error.code === "INVALID_ADDRESS") {
    const field = error.message.startsWith("payer") ? "payer" : "recipient";
    return { fields: { [field]: error.message }, form: null };
  }
  if (error.code !== "VALIDATION_ERROR") {
    return { fields: {}, form: null };
  }
  const fields: FieldErrors = {};
  const leftovers: string[] = [];
  for (const segment of error.message.split("; ")) {
    const match = /^([A-Za-z]+): (.+)$/.exec(segment);
    if (match !== null && match[1] !== undefined && match[2] !== undefined && FIELD_NAMES.has(match[1])) {
      fields[match[1] as CreateIntentField] = match[2];
    } else {
      leftovers.push(segment);
    }
  }
  return { fields, form: leftovers.length > 0 ? leftovers.join("; ") : null };
}

/** Curl representation of the request the form is about to send. */
export function curlForCreate(origin: string, body: CreatePaymentIntentRequest): string {
  return [
    `curl -X POST ${origin}/v1/payment-intents \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '${JSON.stringify(body, null, 2).replace(/'/g, "'\\''")}'`,
  ].join("\n");
}
