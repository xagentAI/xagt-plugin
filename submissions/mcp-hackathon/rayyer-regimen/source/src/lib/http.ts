import * as z from 'zod';
import { RegimenError, toRegimenError } from '@/lib/errors';
import { COMMIT } from '@/lib/version';

/**
 * Shared plumbing for the REST surface.
 *
 * Success and failure share one envelope shape so a caller writes one parser, and
 * every response carries the build commit and a request id — the two things you need
 * to correlate a report someone pastes at you with what the service was actually
 * running at the time.
 */

export const NEXUS_KEY_HEADER = 'x-nexus-key';
const REQUEST_ID_HEADER = 'x-request-id';

/** Rough per-minute ceiling for anonymous demo traffic, per source address. */
const DEMO_REQUESTS_PER_MINUTE = 20;

export interface ResponseMeta {
  readonly requestId: string;
  readonly commit: string | null;
  readonly durationMs: number;
  readonly mode: 'byo_key' | 'demo' | 'inline';
}

function newRequestId(): string {
  return globalThis.crypto.randomUUID();
}

export function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...(COMMIT ? { 'x-source-commit': COMMIT } : {}),
      ...init.headers,
    },
  });
}

/**
 * Resolve which Nexus credentials a request runs under.
 *
 * A caller's own key always wins. Falling back to the service key is what makes the
 * endpoints runnable by a reviewer with no account at all; it is only enabled when
 * the deployment actually has one configured, and it is reported in every response so
 * nobody mistakes demo output for their own strategy's.
 */
export function resolveNexusCredentials(request: Request): { apiKey: string; mode: 'byo_key' | 'demo' } {
  const supplied = request.headers.get(NEXUS_KEY_HEADER)?.trim();
  if (supplied) return { apiKey: supplied, mode: 'byo_key' };

  const demoKey = process.env.NEXUS_DEMO_KEY?.trim();
  if (demoKey) return { apiKey: demoKey, mode: 'demo' };

  throw new RegimenError('missing_credentials', 'No Nexus API key was supplied and this deployment has no demo key.', {
    remedy: `Send your own key in the \`${NEXUS_KEY_HEADER}\` header. Keys are issued in Nexus Studio under Profile → API keys.`,
  });
}

/** In-memory, per-instance demo throttle. Best effort by design; not a security control. */
const demoHits = new Map<string, { count: number; windowStart: number }>();

export function enforceDemoRateLimit(request: Request, mode: 'byo_key' | 'demo' | 'inline'): void {
  if (mode === 'byo_key') return;
  const who = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown';
  const now = Date.now();
  const entry = demoHits.get(who);
  if (!entry || now - entry.windowStart > 60_000) {
    demoHits.set(who, { count: 1, windowStart: now });
    return;
  }
  entry.count += 1;
  if (entry.count > DEMO_REQUESTS_PER_MINUTE) {
    throw new RegimenError('rate_limited', 'Demo requests are limited per minute from one address.', {
      details: { limitPerMinute: DEMO_REQUESTS_PER_MINUTE },
      remedy: `Send your own Nexus key in \`${NEXUS_KEY_HEADER}\` to run without the shared demo limit.`,
    });
  }
}

export async function parseJsonBody<T>(request: Request, schema: z.ZodType<T>): Promise<T> {
  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    throw new RegimenError('invalid_input', 'The request body is not valid JSON.', {
      remedy: 'Send a JSON object with `content-type: application/json`.',
    });
  }

  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new RegimenError('invalid_input', 'The request body does not match the expected shape.', {
      details: {
        issues: parsed.error.issues.slice(0, 20).map((issue) => ({
          path: issue.path.join('.') || '(root)',
          message: issue.message,
        })),
      },
      remedy: 'See GET /api/v1/openapi.json for the request schemas.',
    });
  }
  return parsed.data;
}

/**
 * Wrap a handler so every route shares the same envelope, error mapping and timing.
 * A handler either returns its payload or throws; it never builds a Response itself.
 */
export function handler<T>(
  run: (request: Request, context: { requestId: string; setMode: (mode: ResponseMeta['mode']) => void }) => Promise<T>,
) {
  return async (request: Request): Promise<Response> => {
    const requestId = newRequestId();
    const startedAt = Date.now();
    let mode: ResponseMeta['mode'] = 'inline';

    const rejected = originRejection(request);
    if (rejected) return rejected;

    try {
      const data = await run(request, { requestId, setMode: (next) => (mode = next) });
      const meta: ResponseMeta = { requestId, commit: COMMIT, durationMs: Date.now() - startedAt, mode };
      return jsonResponse({ data, meta }, { headers: { [REQUEST_ID_HEADER]: requestId } });
    } catch (caught) {
      const error = toRegimenError(caught);
      const meta: ResponseMeta = { requestId, commit: COMMIT, durationMs: Date.now() - startedAt, mode };
      return jsonResponse(
        { ...error.toJSON(), meta },
        { status: error.status, headers: { [REQUEST_ID_HEADER]: requestId } },
      );
    }
  };
}

/**
 * DNS-rebinding protection.
 *
 * A browser on an attacker's page can point a hostname at this service and issue
 * cross-origin requests carrying whatever the victim's browser would attach. The
 * MCP transport specification requires servers to validate `Origin` and refuse
 * anything unrecognised, so that check lives here and is applied by every entry point.
 *
 * Non-browser clients — which is most MCP clients, and every `curl` a reviewer will
 * run — send no `Origin` at all, and are allowed through. Only a PRESENT and
 * unrecognised origin is refused.
 */
const ALLOWED_ORIGIN_HOSTS: ReadonlySet<string> = new Set([
  'regimen-nu.vercel.app',
  'regimen-rayyer220s-projects.vercel.app',
  'localhost',
  '127.0.0.1',
]);

export function originRejection(request: Request): Response | null {
  const origin = request.headers.get('origin');
  if (!origin) return null;

  let host: string;
  try {
    host = new URL(origin).hostname;
  } catch {
    return forbidden('The Origin header is not a valid URL.');
  }

  // The deployment's own host is always acceptable, including preview URLs, so the
  // check keeps working when Vercel assigns a new hostname.
  const selfHost = (() => {
    try {
      return new URL(request.url).hostname;
    } catch {
      return null;
    }
  })();

  if (host === selfHost || ALLOWED_ORIGIN_HOSTS.has(host)) return null;

  return forbidden(`Requests from origin ${origin} are not accepted.`);
}

function forbidden(message: string): Response {
  return jsonResponse(
    { error: { code: 'invalid_input', message, retryable: false } },
    { status: 403 },
  );
}
