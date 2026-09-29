import type { NextConfig } from "next";

import { BASE_SECURITY_HEADERS } from "./src/lib/security-headers";

// API routes declare `export const runtime = "nodejs"` individually; nothing in
// this project may run on the Edge runtime (ARCHITECTURE.md §2). The demo UI's
// Content Security Policy is set per request with a nonce in `src/proxy.ts`.
const nextConfig: NextConfig = {
  poweredByHeader: false,
  headers: async () => [
    {
      source: "/(.*)",
      headers: BASE_SECURITY_HEADERS.map(({ key, value }) => ({ key, value })),
    },
  ],
};

export default nextConfig;
