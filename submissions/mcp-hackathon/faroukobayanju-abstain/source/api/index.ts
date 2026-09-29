/**
 * Vercel Function entry. Node runtime (the default) — no reason to spend an
 * innovation token on Edge here: nothing in this service is latency-bound and
 * Node gives us the full standard library.
 *
 * vercel.json rewrites every path to this handler so Hono owns routing.
 */
import { handle } from 'hono/vercel';
import { createApp } from '../src/app.js';
import { buildDeps } from '../src/deps.js';

const app = createApp(buildDeps());

export const GET = handle(app);
export const POST = handle(app);
