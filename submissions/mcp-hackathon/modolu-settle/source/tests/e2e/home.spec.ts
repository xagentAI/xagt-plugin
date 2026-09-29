import { expect, test } from "@playwright/test";

import { hasHorizontalOverflow } from "./fixtures";

test.describe("home", () => {
  test("loads with Settle positioning, the fixed rail, and a usable form", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") {
        errors.push(message.text());
      }
    });

    const response = await page.goto("/");
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Payment truth for autonomous agents.");
    await expect(page.getByText("The API is the product.")).toBeVisible();
    await expect(page.getByText("Base", { exact: true })).toBeVisible();
    await expect(page.getByText("USDC (native)")).toBeVisible();
    for (const step of ["Declare", "Pay", "Reconcile", "Verify"]) {
      await expect(page.getByText(step, { exact: true })).toBeVisible();
    }

    await expect(page.getByLabel("Expected amount (USDC)")).toBeEditable();
    await expect(page.getByLabel("Recipient address")).toBeEditable();
    await expect(page.getByLabel("Payment window closes")).toBeEditable();
    await expect(page.getByRole("button", { name: "Create payment intent" })).toBeEnabled();
    await expect(page.locator("select")).toHaveCount(0);

    expect(await hasHorizontalOverflow(page)).toBe(false);
    expect(errors).toEqual([]);
  });

  test("serves production security headers and a nonce-based CSP", async ({ page }) => {
    const response = await page.goto("/");
    const headers = response?.headers() ?? {};
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("no-referrer");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-powered-by"]).toBeUndefined();
    expect(headers["access-control-allow-origin"]).toBeUndefined();
    const csp = headers["content-security-policy"] ?? "";
    expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("frame-ancestors 'none'");
    // Every script Next.js emitted carries the request nonce, so the page hydrated under this policy.
    const nonced = await page.locator("script[nonce]").count();
    const scripts = await page.locator("script").count();
    expect(nonced).toBe(scripts);
    await expect(page.getByRole("button", { name: "Create payment intent" })).toBeEnabled();
  });

  test("client-side validation blocks an empty submission without calling the API", async ({ page }) => {
    let apiCalls = 0;
    await page.route("**/v1/**", (route) => {
      apiCalls += 1;
      return route.abort();
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Create payment intent" }).click();
    await expect(page.locator("[data-field-error='amount']")).toBeVisible();
    await expect(page.locator("[data-field-error='recipient']")).toBeVisible();
    expect(apiCalls).toBe(0);
  });
});
