import { buildOpenApiDocument } from '@/lib/openapi';
import { COMMIT } from '@/lib/version';

export const dynamic = 'force-dynamic';

/** GET /api/v1/openapi.json — the machine-readable contract for the REST surface. */
export function GET(request: Request) {
  const origin = new URL(request.url).origin;
  return new Response(JSON.stringify(buildOpenApiDocument(origin), null, 2), {
    status: 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'public, max-age=300',
      ...(COMMIT ? { 'x-source-commit': COMMIT } : {}),
    },
  });
}
