import { BUILD, COMMIT } from '@/lib/version';

export const dynamic = 'force-dynamic';

/**
 * Liveness + build binding.
 *
 * Reviewers call this to tie the running service to the reviewed commit, so it stays
 * dependency-free: no upstream call, no database, nothing that can make a healthy
 * process look unhealthy. Upstream reachability is reported by /api/v1/status instead.
 */
export function GET() {
  const body = {
    status: 'ok' as const,
    commit: COMMIT,
    service: BUILD.service,
    slug: BUILD.slug,
    uptimeSeconds: Math.round(process.uptime()),
  };

  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...(COMMIT ? { 'x-source-commit': COMMIT } : {}),
    },
  });
}
