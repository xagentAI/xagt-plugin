import "server-only";

/**
 * Basic CSRF protection for cookie-authenticated APIs.
 * Requires same-origin requests for mutating endpoints.
 */
export function assertTrustedOrigin(request: Request): string | null {
  // Requests using API keys are not cookie-based and are immune to CSRF
  if (request.headers.get("x-api-key")) {
    return null;
  }

  const origin = request.headers.get("origin");
  if (!origin) return null;

  try {
    const originUrl = new URL(origin);
    const forwardedHost = request.headers.get("x-forwarded-host");
    const host = forwardedHost ?? request.headers.get("host");
    if (!host) return null; // If host header missing in certain proxy environments, pass

    const hostWithoutPort = host.split(":")[0].toLowerCase();
    const originHostWithoutPort = originUrl.hostname.toLowerCase();

    // 1. Exact host match
    if (hostWithoutPort === originHostWithoutPort) return null;

    // 2. Allow apex and www subdomain match (e.g. multipu.fun and www.multipu.fun)
    const normalizeDomain = (h: string) => h.replace(/^www\./, "");
    if (normalizeDomain(hostWithoutPort) === normalizeDomain(originHostWithoutPort)) {
      return null;
    }

    // 3. Allow multipu production domains & Vercel deployment hosts
    const isMultipu = (h: string) => h === "multipu.fun" || h.endsWith(".multipu.fun");
    const isVercel = (h: string) => h.endsWith(".vercel.app");

    if (
      (isMultipu(originHostWithoutPort) || isVercel(originHostWithoutPort)) &&
      (isMultipu(hostWithoutPort) || isVercel(hostWithoutPort))
    ) {
      return null;
    }

    // 4. Localhost / Dev
    if (
      (originHostWithoutPort === "localhost" || originHostWithoutPort === "127.0.0.1") &&
      (hostWithoutPort === "localhost" || hostWithoutPort === "127.0.0.1")
    ) {
      return null;
    }

    return "Cross-origin request blocked";
  } catch {
    return null; // Gracefully permit if URL parsing fails on internal routing
  }
}
