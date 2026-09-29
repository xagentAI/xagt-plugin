import { describe, expect, it } from "vitest";

import { BASE_SECURITY_HEADERS, buildContentSecurityPolicy } from "@/lib/security-headers";

describe("BASE_SECURITY_HEADERS", () => {
  it("sets the architecture's mandatory headers plus framing and feature restrictions", () => {
    const map = Object.fromEntries(BASE_SECURITY_HEADERS.map((h) => [h.key, h.value]));
    expect(map).toMatchObject({
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
    });
    expect(map["Permissions-Policy"]).toContain("camera=()");
    expect(Object.keys(map)).not.toContain("Access-Control-Allow-Origin");
  });
});

describe("buildContentSecurityPolicy", () => {
  const nonce = "dGVzdC1ub25jZQ==";
  const production = buildContentSecurityPolicy(nonce, { development: false });

  it("allows only same-origin and nonced scripts, never a wildcard or unsafe-inline", () => {
    expect(production).toContain(`script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`);
    expect(production).not.toContain("*");
    expect(production).not.toContain("unsafe-inline");
    expect(production).not.toContain("unsafe-eval");
  });

  it("locks down the rest of the surface: same-origin connect/styles, no objects, no framing, no base changes", () => {
    for (const directive of [
      "default-src 'self'",
      `style-src 'self' 'nonce-${nonce}'`,
      "connect-src 'self'",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ]) {
      expect(production).toContain(directive);
    }
  });

  it("adds unsafe-eval only in development", () => {
    const development = buildContentSecurityPolicy(nonce, { development: true });
    expect(development).toContain("'unsafe-eval'");
    expect(development.replace(" 'unsafe-eval'", "")).toBe(production);
  });
});
