import { COMMIT, SUBMISSION_SLUG } from '@/lib/version';

export const dynamic = 'force-dynamic';

/**
 * Deployment proof, served at /.well-known/xagent-verification.json via a rewrite.
 * Binds this origin to one submission slug and one commit.
 */
export function GET() {
  const body = {
    schemaVersion: 1 as const,
    slug: SUBMISSION_SLUG,
    commit: COMMIT,
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
