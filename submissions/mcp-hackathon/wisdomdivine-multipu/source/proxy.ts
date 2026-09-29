import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Next.js Edge Proxy & Route Guard — runs BEFORE every request.
 *
 * Responsibilities:
 * Request tracing & security headers (x-request-id)
 *
 * Note: User authentication is managed seamlessly via Web3 wallet sessions
 * and verified per API route without disruptive route bounces.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // ─── Route Guard: Unauthenticated Dashboard Access ───
  if (pathname === "/dashboard" || pathname.startsWith("/dashboard/")) {
    const sessionCookie = request.cookies.get("multipu_session");
    if (!sessionCookie?.value) {
      const url = request.nextUrl.clone();
      url.pathname = "/signin";
      return NextResponse.redirect(url);
    }
  }

  // ─── Request Tracing & Security Headers ───────────
  const response = NextResponse.next();

  response.headers.set("x-request-id", crypto.randomUUID());

  return response;
}

// Backward-compatibility export for Next.js middleware runner
export const middleware = proxy;

export const config = {
  matcher: [
    // Match all paths except static files and Next.js internals
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
