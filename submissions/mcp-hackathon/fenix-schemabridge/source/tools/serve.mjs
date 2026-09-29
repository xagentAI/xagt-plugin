import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import worker from '../src/worker.mjs';
import { LIMITS } from '../src/transform.mjs';

// An exact map keeps the local adapter from exposing repository files.
const localAssetFiles = new Map([
  ['/assets/schema-sculpture.png', new URL('../public/assets/schema-sculpture.png', import.meta.url)],
  ['/assets/fonts/instrument-sans-latin.woff2', new URL('../public/assets/fonts/instrument-sans-latin.woff2', import.meta.url)],
  ['/assets/fonts/instrument-serif-latin.woff2', new URL('../public/assets/fonts/instrument-serif-latin.woff2', import.meta.url)],
  ['/assets/fonts/instrument-serif-italic-latin.woff2', new URL('../public/assets/fonts/instrument-serif-italic-latin.woff2', import.meta.url)],
]);
export const localAssets = {
  async fetch(request) {
    const file = localAssetFiles.get(new URL(request.url).pathname);
    if (!file) return new Response(null, { status: 404 });
    if (!['GET', 'HEAD'].includes(request.method)) return new Response(null, { status: 405, headers: { allow: 'GET, HEAD' } });
    let bytes;
    try { bytes = await readFile(file); }
    catch { return new Response(null, { status: 404 }); }
    return new Response(request.method === 'HEAD' ? null : bytes, { headers: {
      'content-type': file.pathname.endsWith('.woff2') ? 'font/woff2' : 'image/png',
      'content-length': String(bytes.byteLength),
    } });
  },
};

export function makeServer(env = {}) {
  const localEnv = { ASSETS: localAssets, ...env };
  return createServer((incoming, outgoing) => {
    let bytes = 0, overLimit = false;
    const chunks = [];
    incoming.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > LIMITS.bodyBytes) {
        overLimit = true;
        chunks.length = 0;
      } else if (!overLimit) chunks.push(chunk);
    });
    incoming.on('error', () => {
      if (!outgoing.headersSent) outgoing.writeHead(400);
      outgoing.end();
    });
    incoming.on('end', async () => {
      if (overLimit) {
        outgoing.writeHead(413, { 'content-type': 'application/json', 'cache-control': 'no-store' });
        outgoing.end(JSON.stringify({ ok: false, error: { code: 'BODY_LIMIT', message: 'Request body exceeds 32 KiB.' } }));
        return;
      }
      try {
        const method = incoming.method;
        const body = !['GET', 'HEAD'].includes(method) ? Buffer.concat(chunks) : undefined;
        const request = new Request(new URL(incoming.url, 'http://127.0.0.1'), { method, headers: incoming.headers, body });
        const response = await worker.fetch(request, localEnv);
        outgoing.writeHead(response.status, Object.fromEntries(response.headers));
        outgoing.end(Buffer.from(await response.arrayBuffer()));
      } catch {
        if (!outgoing.headersSent) outgoing.writeHead(400, { 'content-type': 'application/json' });
        outgoing.end(JSON.stringify({ ok: false, error: { code: 'INVALID_HTTP_REQUEST', message: 'The local HTTP adapter could not read this request.' } }));
      }
    });
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? 8787);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be between 1 and 65535.');
  makeServer({ REVIEW_COMMIT: process.env.REVIEW_COMMIT, PROJECT_SLUG: process.env.PROJECT_SLUG })
    .listen(port, '127.0.0.1', () => process.stdout.write(`SchemaBridge local API: http://127.0.0.1:${port}\n`));
}
