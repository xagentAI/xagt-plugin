import * as z from 'zod';
import { runSelfAttack } from '@/lib/engine/self-attack';
import { resolveSource, sourceSelectorSchema } from '@/lib/engine/resolve';
import { enforceDemoRateLimit, handler, parseJsonBody, resolveNexusCredentials } from '@/lib/http';

export const dynamic = 'force-dynamic';
export const maxDuration = 120;

const bodySchema = z.object({
  selector: sourceSelectorSchema,
  options: z
    .object({
      simulations: z.number().int().min(100).max(20_000).default(1_000),
      seed: z.number().int().optional(),
      benchmarkSharpe: z.number().finite().default(0),
    })
    .prefault({}),
});

/**
 * POST /api/v1/self-attack
 *
 * Runs Regimen's verdict against controls whose answer is known in advance: the same
 * returns with the edge removed, and a simulated population of strategies with no
 * edge at all. Publishing this is the point — an evaluation tool that never fails a
 * control is indistinguishable from one that always agrees with you.
 */
export const POST = handler(async (request, { setMode }) => {
  const body = await parseJsonBody(request, bodySchema);

  let credentials = {};
  if (body.selector.source === 'olaxbt-nexus') {
    const resolved = resolveNexusCredentials(request);
    credentials = { apiKey: resolved.apiKey };
    setMode(resolved.mode);
    enforceDemoRateLimit(request, resolved.mode);
  } else {
    setMode('inline');
    enforceDemoRateLimit(request, 'inline');
  }

  const { record } = await resolveSource(body.selector, credentials);
  return { report: runSelfAttack(record, body.options) };
});
