/**
 * Deterministic API fixtures for the browser smoke suite. Shapes mirror the
 * public contracts in `src/validation/*` exactly; they live only in tests.
 */
import type { Page, Route } from "@playwright/test";

export const INTENT_ID = "pi_E2EAAAAAAAAAAAAAAAAAAAAAAAAAAAA1";
export const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
export const PAYER = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045";
export const TX_HASH = "0x7db45d69dbb848f50002285f04946b2004388f6823d6ecd3387276141561b0f5";

export interface IntentFixture {
  id: string;
  status: string;
  externalReference: string | null;
  chain: "base";
  asset: "USDC";
  expectedAmount: string;
  receivedAmount: string;
  remainingAmount: string;
  recipient: string;
  payer: string | null;
  requiredConfirmations: number;
  matchConfidence: string;
  paidAt: string | null;
  createdAt: string;
  expiresAt: string;
}

export function intentFixture(overrides: Partial<IntentFixture> = {}): IntentFixture {
  return {
    id: INTENT_ID,
    status: "pending",
    externalReference: "INV-204",
    chain: "base",
    asset: "USDC",
    expectedAmount: "25.00",
    receivedAmount: "0.00",
    remainingAmount: "25.00",
    recipient: RECIPIENT,
    payer: PAYER,
    requiredConfirmations: 3,
    matchConfidence: "none",
    paidAt: null,
    createdAt: "2026-09-18T04:00:00.000Z",
    expiresAt: "2026-09-19T04:00:00.000Z",
    ...overrides,
  };
}

export const PAID = intentFixture({
  status: "paid",
  receivedAmount: "25.00",
  remainingAmount: "0.00",
  matchConfidence: "exact_payer",
  paidAt: "2026-09-17T22:43:23.000Z",
});

export const PARTIAL = intentFixture({ status: "partial", receivedAmount: "15.00", remainingAmount: "10.00", matchConfidence: "exact_payer" });

export const EVIDENCE_ROW = {
  transactionHash: TX_HASH,
  logIndex: 4,
  blockNumber: "51447828",
  from: PAYER,
  to: RECIPIENT,
  amount: "25.00",
  confirmations: 25,
  blockTimestamp: "2026-09-17T22:43:23.000Z",
  association: "matched",
};

export const UPSTREAM_UNAVAILABLE = {
  error: { code: "UPSTREAM_UNAVAILABLE", message: "Blockchain provider is temporarily unavailable", retryable: true },
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify(body) });
}

export interface ApiScript {
  intent: IntentFixture;
  evidence: unknown[];
  /** Called on each POST …/reconcile; return the new intent (and optionally evidence) or an error status/body. */
  reconcile?: () => { intent?: IntentFixture; evidence?: unknown[]; status?: number; body?: unknown };
  create?: { status: number; body: unknown };
}

/** Intercepts every public API call the pages make and answers from the script. */
export async function scriptApi(page: Page, script: ApiScript): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  let intent = script.intent;
  let evidence = script.evidence;
  await page.route("**/v1/payment-intents**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push(`${request.method()} ${url.pathname}${url.search}`);

    if (request.method() === "POST" && url.pathname === "/v1/payment-intents") {
      const reply = script.create ?? { status: 201, body: intent };
      return json(route, reply.body, reply.status);
    }
    if (request.method() === "POST" && url.pathname.endsWith("/reconcile")) {
      const outcome = script.reconcile?.() ?? { intent };
      if (outcome.status !== undefined) {
        return json(route, outcome.body, outcome.status);
      }
      intent = outcome.intent ?? intent;
      evidence = outcome.evidence ?? evidence;
      return json(route, intent);
    }
    if (request.method() === "GET" && url.pathname.endsWith("/evidence")) {
      return json(route, { evidence, nextCursor: null });
    }
    if (request.method() === "GET" && url.pathname === `/v1/payment-intents/${intent.id}`) {
      return json(route, intent);
    }
    return json(route, { error: { code: "INTENT_NOT_FOUND", message: "Payment intent not found", retryable: false } }, 404);
  });
  return { calls };
}

/** True when the document is wider than the viewport (horizontal scrolling). */
export function hasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
}
