import { describe, expect, it } from "vitest";

import {
  buildCreateIntentRequest,
  curlForCreate,
  defaultExpiryLocal,
  localDateTimeToIso,
  mapServerErrorToFields,
  validateCreateIntentForm,
  type CreateIntentFormValues,
} from "@/components/create-intent-request";

const NOW = new Date("2026-09-18T12:00:00.000Z");
const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PAYER = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045";

const valid: CreateIntentFormValues = {
  amount: "25.00",
  recipient: RECIPIENT,
  payer: PAYER,
  expiresAt: "2026-09-19T12:00",
  externalReference: "INV-204",
  requiredConfirmations: "3",
};

describe("buildCreateIntentRequest", () => {
  it("produces the exact POST /v1/payment-intents body with fixed chain and asset", () => {
    const body = buildCreateIntentRequest(valid);
    expect(body).toEqual({
      chain: "base",
      asset: "USDC",
      amount: "25.00",
      recipient: RECIPIENT,
      payer: PAYER,
      expiresAt: new Date("2026-09-19T12:00").toISOString(),
      externalReference: "INV-204",
      requiredConfirmations: 3,
    });
    expect(body.expiresAt.endsWith("Z")).toBe(true);
    expect(Object.keys(body)).toEqual(["chain", "asset", "amount", "recipient", "expiresAt", "payer", "externalReference", "requiredConfirmations"]);
  });

  it("omits blank optional fields and trims whitespace", () => {
    const body = buildCreateIntentRequest({ ...valid, payer: " ", externalReference: "", requiredConfirmations: "", amount: " 1 " });
    expect(body).not.toHaveProperty("payer");
    expect(body).not.toHaveProperty("externalReference");
    expect(body).not.toHaveProperty("requiredConfirmations");
    expect(body.amount).toBe("1");
  });
});

describe("validateCreateIntentForm", () => {
  it("accepts a valid form", () => {
    expect(validateCreateIntentForm(valid, NOW)).toEqual({});
  });

  it.each<[Partial<CreateIntentFormValues>, keyof CreateIntentFormValues]>([
    [{ amount: "" }, "amount"],
    [{ amount: "0" }, "amount"],
    [{ amount: "1e3" }, "amount"],
    [{ amount: "1.1234567" }, "amount"],
    [{ recipient: "" }, "recipient"],
    [{ recipient: "0xRecipient" }, "recipient"],
    [{ payer: "0x12" }, "payer"],
    [{ expiresAt: "" }, "expiresAt"],
    [{ expiresAt: "2026-09-18T11:59" }, "expiresAt"],
    [{ expiresAt: "2026-10-01T12:00" }, "expiresAt"],
    [{ requiredConfirmations: "0" }, "requiredConfirmations"],
    [{ requiredConfirmations: "65" }, "requiredConfirmations"],
    [{ requiredConfirmations: "2.5" }, "requiredConfirmations"],
    [{ externalReference: "x".repeat(129) }, "externalReference"],
  ])("flags %j on %s", (override, field) => {
    const errors = validateCreateIntentForm({ ...valid, ...override }, NOW);
    expect(Object.keys(errors)).toEqual([field]);
  });

  it("treats a blank payer and confirmations as optional", () => {
    expect(validateCreateIntentForm({ ...valid, payer: "", requiredConfirmations: "" }, NOW)).toEqual({});
  });
});

describe("mapServerErrorToFields", () => {
  it("splits the API's field-prefixed validation message onto fields", () => {
    const mapped = mapServerErrorToFields({
      code: "VALIDATION_ERROR",
      message: "amount: must be greater than zero; expiresAt: must be in the future",
      retryable: false,
      status: 400,
    });
    expect(mapped).toEqual({ fields: { amount: "must be greater than zero", expiresAt: "must be in the future" }, form: null });
  });

  it("keeps unattributable segments as a form-level message", () => {
    const mapped = mapServerErrorToFields({ code: "VALIDATION_ERROR", message: "unknown field(s): tokenAddress", retryable: false, status: 400 });
    expect(mapped).toEqual({ fields: {}, form: "unknown field(s): tokenAddress" });
  });

  it("attaches INVALID_ADDRESS to recipient or payer", () => {
    expect(mapServerErrorToFields({ code: "INVALID_ADDRESS", message: "payer must be a valid Base address", retryable: false, status: 400 }).fields).toEqual({
      payer: "payer must be a valid Base address",
    });
    expect(mapServerErrorToFields({ code: "INVALID_ADDRESS", message: "recipient must be a valid Base address", retryable: false, status: 400 }).fields).toEqual({
      recipient: "recipient must be a valid Base address",
    });
  });

  it("leaves other codes to the form-level notice", () => {
    expect(mapServerErrorToFields({ code: "UPSTREAM_UNAVAILABLE", message: "x", retryable: true, status: 503 })).toEqual({ fields: {}, form: null });
  });
});

describe("helpers", () => {
  it("converts local datetime input to a UTC ISO string and rejects garbage", () => {
    expect(localDateTimeToIso("2026-09-19T12:00")).toBe(new Date("2026-09-19T12:00").toISOString());
    expect(localDateTimeToIso("")).toBeNull();
    expect(localDateTimeToIso("nope")).toBeNull();
  });

  it("defaults expiry to 24 hours ahead in datetime-local format", () => {
    const value = defaultExpiryLocal(NOW);
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(new Date(value).getTime() - NOW.getTime()).toBe(24 * 60 * 60 * 1000);
  });

  it("renders a curl with the current origin and the exact body", () => {
    const curl = curlForCreate("https://settle.example", buildCreateIntentRequest(valid));
    expect(curl).toContain("curl -X POST https://settle.example/v1/payment-intents");
    expect(curl).toContain('"chain": "base"');
    expect(curl).not.toContain("localhost");
  });
});
