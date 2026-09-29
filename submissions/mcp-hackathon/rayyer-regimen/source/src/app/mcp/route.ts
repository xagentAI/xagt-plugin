import { createMcpHandler } from '@modelcontextprotocol/server';
import { buildServer, type ServerDeps } from '@/lib/mcp/server';
import { NEXUS_KEY_HEADER, originRejection } from '@/lib/http';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

/**
 * The MCP endpoint.
 *
 * Under revision 2026-07-28 a server exposes ONE path accepting POST; GET and DELETE
 * are refused with 405 so a client can tell this apart from a legacy HTTP+SSE server.
 * The SDK handler implements that, so every verb is handed to it.
 *
 * Credentials arrive as a transport header rather than a tool argument. The current
 * spec is explicit that secrets must not travel through form-mode elicitation, and a
 * key sitting in a tool argument would end up in model context and in client logs.
 * A deployment-wide demo key backs it so a reviewer can exercise every tool without
 * holding an account; which of the two is in play is reported by /api/v1/status.
 */
function depsFor(request: Request): ServerDeps {
  const supplied = request.headers.get(NEXUS_KEY_HEADER)?.trim();
  if (supplied) return { nexusApiKey: supplied, credentialSource: 'caller' };

  const demo = process.env.NEXUS_DEMO_KEY?.trim();
  if (demo) return { nexusApiKey: demo, credentialSource: 'demo' };

  return { nexusApiKey: null, credentialSource: 'none' };
}

async function serve(request: Request): Promise<Response> {
  const rejected = originRejection(request);
  if (rejected) return rejected;

  const deps = depsFor(request);
  const handler = createMcpHandler(() => buildServer(deps));
  try {
    return await handler.fetch(request);
  } finally {
    await handler.close();
  }
}

export const POST = serve;
export const GET = serve;
export const DELETE = serve;
