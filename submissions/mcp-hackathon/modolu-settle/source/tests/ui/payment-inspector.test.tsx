// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PaymentInspector } from "@/components/payment-inspector";
import { PaymentStatusHero, StatusBadge } from "@/components/payment-status";
import { POLL_INTERVAL_MS } from "@/components/inspector-polling";
import { STATUS_COPY, type EvidenceItemResponse, type PaymentIntentResponse, type PaymentStatus } from "@/lib/public-api";

const ID = "pi_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PAYER = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045";
const OTHER = "0x1111111111111111111111111111111111111111";

function intent(overrides: Partial<PaymentIntentResponse> = {}): PaymentIntentResponse {
  return {
    id: ID,
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

function evidenceRow(overrides: Partial<EvidenceItemResponse> = {}): EvidenceItemResponse {
  return {
    transactionHash: `0x${"7db4".repeat(16)}`,
    logIndex: 4,
    blockNumber: "51447828",
    from: PAYER,
    to: RECIPIENT,
    amount: "25.00",
    confirmations: 25,
    blockTimestamp: "2026-09-17T22:43:23.000Z",
    association: "matched",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

type Route = { method: string; path: RegExp; reply: () => Response };

/** Minimal fake of the public API: each request is answered by the first matching route. */
function fakeApi(routes: Route[]) {
  const calls: Array<{ method: string; url: string }> = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ method, url });
    const route = routes.find((candidate) => candidate.method === method && candidate.path.test(url));
    if (route === undefined) {
      throw new Error(`unexpected request ${method} ${url}`);
    }
    return route.reply();
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

const GET_INTENT = /\/v1\/payment-intents\/pi_[^/?]+$/;
const GET_EVIDENCE = /\/evidence\?limit=100$/;
const POST_RECONCILE = /\/reconcile$/;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("status presentation", () => {
  it.each(Object.keys(STATUS_COPY) as PaymentStatus[])("renders %s with a label, explanation and glyph", (status) => {
    render(
      <>
        <PaymentStatusHero status={status} reconciling={false} />
        <StatusBadge status={status} />
      </>,
    );
    const copy = STATUS_COPY[status];
    expect(screen.getAllByText(copy.label).length).toBeGreaterThan(0);
    expect(screen.getByText(copy.explanation)).toBeTruthy();
    expect(document.querySelectorAll(`[data-status="${status}"]`).length).toBe(2);
    cleanup();
  });
});

describe("PaymentInspector", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it("loads the intent and evidence through the public API and shows the API-provided amounts", async () => {
    const { calls } = fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ status: "partial", receivedAmount: "15.00", remainingAmount: "10.00" })) },
      { method: "GET", path: GET_EVIDENCE, reply: () => jsonResponse({ evidence: [evidenceRow({ amount: "15.00" })], nextCursor: null }) },
    ]);
    render(<PaymentInspector id={ID} />);

    await screen.findByText(STATUS_COPY.partial.explanation);
    expect(screen.getAllByText("INV-204").length).toBeGreaterThan(0);
    const summary = screen.getByText("Expected").closest("dl") as HTMLElement;
    expect(within(summary).getByText("25.00")).toBeTruthy();
    expect(within(summary).getByText("15.00")).toBeTruthy();
    expect(within(summary).getByText("10.00")).toBeTruthy();
    await screen.findAllByText(/0x7db47db4/);
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      `GET /v1/payment-intents/${ID}`,
      `GET /v1/payment-intents/${ID}/evidence?limit=100`,
    ]);
  });

  it("shows the not-found state with a way back for an unknown or malformed id", async () => {
    fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse({ error: { code: "INTENT_NOT_FOUND", message: "Payment intent not found", retryable: false } }, 404) },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByRole("heading", { name: /payment intent not found/i });
    expect(screen.getByRole("link", { name: /create a payment intent/i }).getAttribute("href")).toBe("/");
  });

  it("Reconcile now POSTs to the reconcile endpoint, replaces the resource and refreshes evidence", async () => {
    let reconciled = false;
    const { calls } = fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent()) },
      {
        method: "GET",
        path: GET_EVIDENCE,
        reply: () => jsonResponse({ evidence: reconciled ? [evidenceRow()] : [], nextCursor: null }),
      },
      {
        method: "POST",
        path: POST_RECONCILE,
        reply: () => {
          reconciled = true;
          return jsonResponse(intent({ status: "paid", receivedAmount: "25.00", remainingAmount: "0.00", matchConfidence: "exact_payer", paidAt: "2026-09-17T22:43:23.000Z" }));
        },
      },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.pending.explanation);
    expect(screen.getByText(/no matching onchain evidence observed yet/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /reconcile now/i }));
    await screen.findByText(STATUS_COPY.paid.explanation);
    await screen.findAllByText(/0x7db47db4/);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
    expect(screen.getByText(/final status reached/i)).toBeTruthy();
  });

  it("renders matched, candidate and orphaned evidence with their labels and explorer links", async () => {
    fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ status: "ambiguous", payer: null, matchConfidence: "ambiguous" })) },
      {
        method: "GET",
        path: GET_EVIDENCE,
        reply: () =>
          jsonResponse({
            evidence: [
              evidenceRow({ transactionHash: `0x${"a".repeat(64)}`, association: "candidate", from: OTHER, amount: "100.00" }),
              evidenceRow({ transactionHash: `0x${"b".repeat(64)}`, association: "candidate", amount: "5.00" }),
              evidenceRow({ transactionHash: `0x${"c".repeat(64)}`, association: "orphaned", amount: "1.00" }),
            ],
            nextCursor: null,
          }),
      },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.ambiguous.explanation);
    await waitFor(() => expect(document.querySelectorAll('tr[data-association="candidate"]')).toHaveLength(2));
    expect(document.querySelectorAll('tr[data-association="orphaned"]')).toHaveLength(1);
    const link = document.querySelector(`a[href="https://basescan.org/tx/0x${"a".repeat(64)}"]`) as HTMLAnchorElement;
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("ambiguous: received stays the API's 0.00 even though candidate rows sum to 105.00", async () => {
    fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ status: "ambiguous", payer: null, matchConfidence: "ambiguous", receivedAmount: "0.00", remainingAmount: "25.00" })) },
      {
        method: "GET",
        path: GET_EVIDENCE,
        reply: () =>
          jsonResponse({
            evidence: [
              evidenceRow({ transactionHash: `0x${"a".repeat(64)}`, association: "candidate", from: OTHER, amount: "100.00" }),
              evidenceRow({ transactionHash: `0x${"b".repeat(64)}`, association: "candidate", amount: "5.00" }),
            ],
            nextCursor: null,
          }),
      },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.ambiguous.explanation);
    await waitFor(() => expect(document.querySelectorAll('tr[data-association="candidate"]')).toHaveLength(2));
    const summary = screen.getByText("Received").closest("dl") as HTMLElement;
    expect(within(summary).getByText("0.00")).toBeTruthy();
    expect(within(summary).queryByText("105.00")).toBeNull();
    expect(screen.getByText("Not declared — single-sender matching")).toBeTruthy();
  });

  it("polls the reconcile endpoint every 7 seconds while pending and stops once terminal", async () => {
    let postCount = 0;
    const { calls } = fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent()) },
      { method: "GET", path: GET_EVIDENCE, reply: () => jsonResponse({ evidence: [], nextCursor: null }) },
      {
        method: "POST",
        path: POST_RECONCILE,
        reply: () => {
          postCount += 1;
          return jsonResponse(intent(postCount >= 2 ? { status: "paid", receivedAmount: "25.00", remainingAmount: "0.00" } : { status: "detected" }));
        },
      },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.pending.explanation);
    expect(screen.getByText(/auto-reconciling every 7 seconds/i)).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 50);
    });
    await screen.findByText(STATUS_COPY.detected.explanation);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 50);
    });
    await screen.findByText(STATUS_COPY.paid.explanation);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
    });
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(2);
    expect(screen.getByText(/automatic reconciliation stopped/i)).toBeTruthy();
  });

  it.each<PaymentStatus>(["paid", "overpaid", "expired", "ambiguous"])("does not poll at all for a %s intent", async (status) => {
    const { calls } = fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ status })) },
      { method: "GET", path: GET_EVIDENCE, reply: () => jsonResponse({ evidence: [], nextCursor: null }) },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY[status].explanation);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
    });
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("keeps the previous payment state on an upstream failure and explains retryability", async () => {
    fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ status: "partial", receivedAmount: "15.00", remainingAmount: "10.00" })) },
      { method: "GET", path: GET_EVIDENCE, reply: () => jsonResponse({ evidence: [evidenceRow({ amount: "15.00" })], nextCursor: null }) },
      {
        method: "POST",
        path: POST_RECONCILE,
        reply: () => jsonResponse({ error: { code: "UPSTREAM_UNAVAILABLE", message: "Blockchain provider is temporarily unavailable", retryable: true } }, 503),
      },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.partial.explanation);
    fireEvent.click(screen.getByRole("button", { name: /reconcile now/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Blockchain evidence unavailable");
    expect(alert.textContent).toContain("Retryable");
    expect(alert.textContent).toContain("not a “no payment found” result");
    expect(screen.getByText(STATUS_COPY.partial.explanation)).toBeTruthy();
    const summary = screen.getByText("Received").closest("dl") as HTMLElement;
    expect(within(summary).getByText("15.00")).toBeTruthy();
    expect(screen.getAllByText(/0x7db47db4/).length).toBeGreaterThan(0);
  });

  it("pauses automatic reconciliation after three consecutive failures and a manual retry re-arms it", async () => {
    const { calls } = fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent()) },
      { method: "GET", path: GET_EVIDENCE, reply: () => jsonResponse({ evidence: [], nextCursor: null }) },
      { method: "POST", path: POST_RECONCILE, reply: () => jsonResponse({ error: { code: "UPSTREAM_UNAVAILABLE", message: "down", retryable: true } }, 503) },
    ]);
    render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.pending.explanation);
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 50);
      });
    }
    await screen.findByText(/paused after 3 consecutive failures/i);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
    });
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: /reconcile now/i }));
    await waitFor(() => expect(calls.filter((call) => call.method === "POST")).toHaveLength(4));
  });
});

describe("XSS safety (Milestone 5)", () => {
  it("renders a hostile externalReference and addresses as inert text", async () => {
    const hostile = "<script>alert(1)</script><img src=x onerror=alert(2)>";
    fakeApi([
      { method: "GET", path: GET_INTENT, reply: () => jsonResponse(intent({ externalReference: hostile })) },
      {
        method: "GET",
        path: GET_EVIDENCE,
        reply: () => jsonResponse({ evidence: [evidenceRow({ transactionHash: "<b>not a hash</b>", from: "<i>x</i>", to: RECIPIENT })], nextCursor: null }),
      },
    ]);
    const { container } = render(<PaymentInspector id={ID} />);
    await screen.findByText(STATUS_COPY.pending.explanation);
    await waitFor(() => expect(screen.getAllByText(hostile).length).toBeGreaterThan(0));
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("i")).toBeNull();
    // A malformed hash is shown as text, not turned into an explorer link.
    expect(container.querySelector("a[href*='basescan.org/tx/']")).toBeNull();
    expect(container.innerHTML).toContain("&lt;script&gt;");
  });
});
