/**
 * Next.js Proxy (Node runtime): generates a per-request nonce and sets the
 * demo UI's Content Security Policy. Only HTML pages are matched; API routes,
 * health, verification and static assets are excluded (they carry the
 * baseline headers from `next.config.ts` and serve no scripts).
 */
import { NextResponse, type NextRequest } from "next/server";

import { buildContentSecurityPolicy } from "@/lib/security-headers";

export function proxy(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildContentSecurityPolicy(nonce, { development: process.env.NODE_ENV === "development" });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    // Everything except API routes, well-known files and Next.js internals/assets.
    "/((?!v1/|health|\\.well-known/|_next/static|_next/image|favicon\\.ico).*)",
  ],
};
