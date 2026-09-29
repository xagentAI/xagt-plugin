/**
 * Security header policy (ARCHITECTURE.md §12): Next.js/Vercel defaults plus
 * explicit `X-Content-Type-Options`, `Referrer-Policy` and a restrictive
 * Content Security Policy for the demo UI. Pure so it can be unit-tested and
 * shared by `next.config.ts` (baseline headers on every path) and
 * `src/proxy.ts` (per-request nonce CSP on HTML pages).
 */

export interface HeaderPair {
  readonly key: string;
  readonly value: string;
}

/** Applied to every response, API and UI alike. */
export const BASE_SECURITY_HEADERS: readonly HeaderPair[] = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

export interface CspOptions {
  /** Development needs `'unsafe-eval'` for React's enhanced error stacks; production never does. */
  readonly development: boolean;
}

/**
 * CSP for the demo UI. Scripts and styles are same-origin or carry the
 * request nonce (Next.js attaches it to its own inline bootstrap scripts);
 * `'strict-dynamic'` lets nonced scripts load the chunks they import.
 * API calls are same-origin (`connect-src 'self'`); Basescan links are plain
 * navigations and need no allowance; there are no remote images or fonts;
 * framing is forbidden.
 */
export function buildContentSecurityPolicy(nonce: string, options: CspOptions): string {
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${options.development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  return directives.join("; ");
}
