import { expect, test } from "@playwright/test";

import { EVIDENCE_ROW, PARTIAL, UPSTREAM_UNAVAILABLE, hasHorizontalOverflow, scriptApi } from "./fixtures";

test.describe("upstream failure", () => {
  test("a 503 on reconcile keeps the previous partial state and evidence visible and offers a retry", async ({ page }) => {
    let fail = true;
    const { calls } = await scriptApi(page, {
      intent: PARTIAL,
      evidence: [{ ...EVIDENCE_ROW, amount: "15.00" }],
      reconcile: () => (fail ? { status: 503, body: UPSTREAM_UNAVAILABLE } : { intent: PARTIAL }),
    });

    await page.goto(`/inspect/${PARTIAL.id}`);
    await expect(page.locator("[data-status='partial']").first()).toBeVisible();
    await page.getByRole("button", { name: "Reconcile now" }).click();

    const notice = page.locator("[data-error-code='UPSTREAM_UNAVAILABLE']");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("Blockchain evidence unavailable");
    await expect(notice).toContainText("not a “no payment found” result");
    await expect(notice).toContainText("Retryable");
    await expect(notice).not.toContainText("alchemy");
    await expect(notice).not.toContainText("http");

    // Previous state is untouched.
    await expect(page.locator("[data-status='partial']").first()).toBeVisible();
    await expect(page.locator("dl").first()).toContainText("15.00");
    await expect(page.locator("[data-association='matched']").filter({ visible: true }).first()).toBeVisible();

    // Retry succeeds and clears the notice.
    fail = false;
    await notice.getByRole("button", { name: "Retry" }).click();
    await expect(notice).toHaveCount(0);
    await expect(page.locator("[data-status='partial']").first()).toBeVisible();
    expect(calls.filter((call) => call.includes("/reconcile")).length).toBeGreaterThanOrEqual(2);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });
});
