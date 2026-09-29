/**
 * In-memory sliding-window rate limiter.
 *
 * Production: swap the Map for Redis (ioredis) - same interface.
 * This version works for single-instance Vercel deployments.
 *
 * Usage:
 *   const limiter = createRateLimiter({ windowMs: 60_000, max: 10 });
 *   if (!limiter.check(ip)) return new Response("Too many requests", { status: 429 });
 */

interface RateLimiterOptions {
  /** Window size in ms */
  windowMs: number;
  /** Max requests per window */
  max: number;
}

interface Entry {
  count: number;
  resetAt: number;
}

export function createRateLimiter({ windowMs, max }: RateLimiterOptions) {
  const store = new Map<string, Entry>();

  // Periodic cleanup to prevent memory leaks
  const CLEANUP_INTERVAL = Math.max(windowMs * 2, 60_000);
  let lastCleanup = Date.now();

  function cleanup() {
    const now = Date.now();
    if (now - lastCleanup < CLEANUP_INTERVAL) return;
    lastCleanup = now;
    for (const [key, entry] of store) {
      if (now > entry.resetAt) store.delete(key);
    }
  }

  return {
    /**
     * Returns true if the request is allowed, false if rate-limited.
     */
    check(key: string): boolean {
      cleanup();
      const now = Date.now();
      const entry = store.get(key);

      if (!entry || now > entry.resetAt) {
        store.set(key, { count: 1, resetAt: now + windowMs });
        return true;
      }

      entry.count++;
      if (entry.count > max) return false;
      return true;
    },

    /**
     * Returns rate limit headers for the response.
     */
    headers(key: string): Record<string, string> {
      const entry = store.get(key);
      const remaining = entry ? Math.max(0, max - entry.count) : max;
      const reset = entry ? Math.ceil((entry.resetAt - Date.now()) / 1000) : 0;
      return {
        "X-RateLimit-Limit": max.toString(),
        "X-RateLimit-Remaining": remaining.toString(),
        "X-RateLimit-Reset": reset.toString(),
      };
    },
  };
}

// Pre-configured limiters for different endpoints
export const authLimiter = createRateLimiter({
  windowMs: 60_000, // 1 minute
  max: 10,          // 10 auth attempts per minute
});

export const apiLimiter = createRateLimiter({
  windowMs: 60_000, // 1 minute
  max: 120,         // 120 API calls per minute
});

export const uploadLimiter = createRateLimiter({
  windowMs: 60_000, // 1 minute
  max: 5,           // 5 uploads per minute
});
