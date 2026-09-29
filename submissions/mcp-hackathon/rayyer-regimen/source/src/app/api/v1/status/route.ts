import { cacheStats } from '@/lib/sources/nexus/client';
import { handler } from '@/lib/http';
import { BUILD } from '@/lib/version';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

/**
 * GET /api/v1/status
 *
 * Dependency health, kept OFF /api/health deliberately: liveness must never fail
 * because a third party is having a bad afternoon, and a reviewer verifying the
 * build binding should not be told the service is down when it is the upstream that
 * is. This endpoint is where upstream reachability is reported honestly, including
 * whether the deployment can serve credential-free demo calls at all.
 */
export const GET = handler(async () => {
  const startedAt = Date.now();
  let upstream: { reachable: boolean; detail: string; latencyMs: number | null };

  try {
    const response = await fetch('https://nexus.olaxbt.xyz/api/mcp/health', {
      signal: AbortSignal.timeout(8_000),
    });
    upstream = {
      reachable: response.ok,
      detail: response.ok ? 'OlaXBT Nexus gateway responded to its liveness probe.' : `Gateway returned HTTP ${response.status}.`,
      latencyMs: Date.now() - startedAt,
    };
  } catch {
    upstream = {
      reachable: false,
      detail: 'The OlaXBT Nexus gateway did not respond. Nexus-backed analyses will fail until it does.',
      latencyMs: null,
    };
  }

  return {
    service: BUILD.service,
    slug: BUILD.slug,
    commit: BUILD.commit,
    region: BUILD.region,
    demoKeyConfigured: Boolean(process.env.NEXUS_DEMO_KEY?.trim()),
    upstream,
    pointInTimeCache: cacheStats(),
  };
});
