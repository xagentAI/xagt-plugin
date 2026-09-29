// Standalone smoke: proves our OK-ACCESS HMAC signing is accepted by the OKX
// hosted x402 facilitator, using the read-only `supported` endpoint.
//
// Not part of `npm test` (needs network + real credentials). Run manually:
//   node ./test/x402-facilitator-smoke.mjs
//
// Reads OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE from process.env,
// falling back to .dev.vars in the repo root. Never prints credential values.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { facilitatorRequest } from '../worker/x402.mjs';

function loadDevVars() {
  const path = join(dirname(fileURLToPath(import.meta.url)), '..', '.dev.vars');
  const env = {};
  try {
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (match) env[match[1]] = match[2].replace(/^["']|["']$/g, '');
    }
  } catch {
    // no .dev.vars — rely on process.env only
  }
  return env;
}

const devVars = loadDevVars();
const env = {
  OKX_API_KEY: process.env.OKX_API_KEY || devVars.OKX_API_KEY,
  OKX_SECRET_KEY: process.env.OKX_SECRET_KEY || devVars.OKX_SECRET_KEY,
  OKX_PASSPHRASE: process.env.OKX_PASSPHRASE || devVars.OKX_PASSPHRASE
};

if (!env.OKX_API_KEY || !env.OKX_SECRET_KEY || !env.OKX_PASSPHRASE) {
  console.error('SKIP: OKX credentials not found in env or .dev.vars');
  process.exit(2);
}

try {
  // facilitatorRequest throws on HTTP errors AND on OKX envelope code !== "0",
  // so reaching the lines below means transport auth and the business envelope
  // both succeeded (code === "0").
  const supported = await facilitatorRequest(env, 'GET', '/api/v6/pay/x402/supported');
  const kinds = supported?.kinds ?? [];
  const hasExactXLayer = kinds.some((k) => k.scheme === 'exact' && k.network === 'eip155:196');
  if (!hasExactXLayer) {
    console.error('FAIL: facilitator responded (code=0) but exact/eip155:196 is not in supported kinds.');
    console.error(JSON.stringify(supported, null, 2));
    process.exit(1);
  }
  console.log('PASS facilitator auth accepted (HTTP 200 + envelope code=0) — GET /api/v6/pay/x402/supported data:');
  console.log(JSON.stringify(supported, null, 2));
  console.log('exact/eip155:196 supported: yes');
  process.exit(0);
} catch (error) {
  console.error(`FAIL facilitator request rejected: ${error.message}`);
  if (error.detail) console.error(`detail: ${error.detail}`);
  process.exit(1);
}
