import { expect, test } from "@playwright/test";

import { EVIDENCE_ROW, INTENT_ID, PAID, PAYER, RECIPIENT, hasHorizontalOverflow, intentFixture, scriptApi } from "./fixtures";

test.describe("create → inspect → reconcile", () => {
  test("creating an intent redirects to the inspector, which reconciles to paid with evidence", async ({ page }) => {
    let reconciles = 0;
    const { calls } = await scriptApi(page, {
      intent: intentFixture(),
      evidence: [],
      reconcile: () => {
        reconciles += 1;
        return reconciles === 1 ? { intent: intentFixture({ status: "detected", matchConfidence: "exact_payer" }), evidence: [{ ...EVIDENCE_ROW, confirmations: 1 }] } : { intent: PAID, evidence: [EVIDENCE_ROW] };
      },
    });

    await page.goto("/");
    await page.getByLabel("Expected amount (USDC)").fill("25.00");
    await page.getByLabel("Recipient address").fill(RECIPIENT);
    await page.getByLabel("Payer address").fill(PAYER);
    await page.getByLabel("External reference").fill("INV-204");
    await page.getByRole("button", { name: "Create payment intent" }).click();

    await page.waitForURL(`**/inspect/${INTENT_ID}`);
    expect(calls[0]).toBe("POST /v1/payment-intents");

    // Pending state straight from the API.
    await expect(page.locator("[data-status='pending']").first()).toBeVisible();
    await expect(page.getByText("No matching payment has been observed yet.")).toBeVisible();
    await expect(page.getByText("No matching onchain evidence observed yet.")).toBeVisible();
    const summary = page.locator("dl").first();
    await expect(summary).toContainText("25.00");
    await expect(summary).toContainText("0.00");

    // Manual reconcile → detected with one under-confirmed transfer.
    await page.getByRole("button", { name: "Reconcile now" }).click();
    await expect(page.locator("[data-status='detected']").first()).toBeVisible();
    await expect(page.locator("[data-association='matched']").filter({ visible: true }).first()).toBeVisible();

    // Second reconcile → paid; amounts and paidAt update; polling caption reports the stop.
    await page.getByRole("button", { name: "Reconcile now" }).click();
    await expect(page.locator("[data-status='paid']").first()).toBeVisible();
    await expect(page.getByText("The payment obligation has been satisfied.")).toBeVisible();
    await expect(summary).toContainText("Received25.00");
    await expect(summary).toContainText("Remaining0.00");
    await expect(page.getByText("Final status reached", { exact: false })).toBeVisible();
    await expect(page.locator(`a[href="https://basescan.org/tx/${EVIDENCE_ROW.transactionHash}"]`).first()).toHaveAttribute("rel", /noopener/);
    await expect(page.getByText("2026-09-17 22:43:23 UTC").first()).toBeVisible();

    expect(calls.filter((call) => call.includes("/reconcile"))).toHaveLength(2);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test("a server validation error is shown on the field and the entered values are kept", async ({ page }) => {
    await scriptApi(page, {
      intent: intentFixture(),
      evidence: [],
      create: { status: 400, body: { error: { code: "INVALID_ADDRESS", message: "recipient must be a valid Base address", retryable: false } } },
    });
    await page.goto("/");
    await page.getByLabel("Expected amount (USDC)").fill("25.00");
    await page.getByLabel("Recipient address").fill(RECIPIENT);
    await page.getByLabel("External reference").fill("INV-204");
    await page.getByRole("button", { name: "Create payment intent" }).click();
    await expect(page.locator("[data-field-error='recipient']")).toHaveText("recipient must be a valid Base address");
    await expect(page.getByLabel("External reference")).toHaveValue("INV-204");
    await expect(page).toHaveURL(/\/$/);
  });

  test("an unknown intent shows the not-found state with a way back", async ({ page }) => {
    await scriptApi(page, { intent: intentFixture(), evidence: [] });
    await page.goto("/inspect/pi_DOESNOTEXISTAAAAAAAAAAAAAAAAAAAA");
    await expect(page.getByRole("heading", { name: "Payment intent not found" })).toBeVisible();
    await page.getByRole("link", { name: "Create a payment intent" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});
