/**
 * Local server. `node --experimental-strip-types src/server.ts`
 * Used for the demo and for curl-based verification evidence.
 */
import { serve } from '@hono/node-server';
import { createApp } from './app.js';
import { buildDeps } from './deps.js';

const port = Number(process.env['PORT'] ?? 3000);
serve({ fetch: createApp(buildDeps()).fetch, port }, (info) => {
  console.log(`abstain listening on http://localhost:${info.port}`);
});
