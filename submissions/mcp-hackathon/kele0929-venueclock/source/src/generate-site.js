import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { listVenues } from "./calendar.js";
import { SLUG, route } from "./http.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = process.argv.includes("--out")
  ? process.argv[process.argv.indexOf("--out") + 1]
  : join(ROOT, "site");
const commit = process.env.REVIEW_COMMIT;
if (!commit || !/^[a-f0-9]{40}$/i.test(commit)) {
  throw new Error("REVIEW_COMMIT must be the 40-character source commit SHA");
}

async function writeJson(relPath, body) {
  const full = join(outDir, relPath);
  await mkdir(dirname(full), { recursive: true });
  await writeFile(full, `${JSON.stringify(body)}\n`, "utf8");
}

function bodyOf(path) {
  const result = route(new URL(path, "http://venueclock.local"), { commit });
  if (result.status !== 200) throw new Error(`${path} -> ${result.status} ${JSON.stringify(result.body)}`);
  return result.body;
}

const venues = listVenues();
const dates = [];
for (let cursor = new Date(Date.UTC(2026, 0, 1)); cursor.getUTCFullYear() === 2026; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
  const y = cursor.getUTCFullYear();
  const m = String(cursor.getUTCMonth() + 1).padStart(2, "0");
  const d = String(cursor.getUTCDate()).padStart(2, "0");
  dates.push(`${y}-${m}-${d}`);
}

await mkdir(outDir, { recursive: true });
await writeFile(join(outDir, ".nojekyll"), "", "utf8");
await writeJson("health.json", bodyOf("/health.json"));
await writeJson(".well-known/xagent-verification.json", bodyOf("/.well-known/xagent-verification.json"));
await writeJson("v1/index.json", bodyOf("/v1"));
await writeJson("v1/venues.json", bodyOf("/v1/venues.json"));
await writeJson("mcp/tools.json", bodyOf("/mcp/tools.json"));

for (const venue of venues) {
  await writeJson(`v1/venues/${venue.id}.json`, bodyOf(`/v1/venues/${venue.id}.json`));
  for (const date of dates) {
    await writeJson(`v1/resolve/${venue.id}/${date}.json`, bodyOf(`/v1/resolve/${venue.id}/${date}.json`));
  }
}

const index = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VenueClock — agent-callable market session calendar</title>
  <style>
    :root { color-scheme: dark; }
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background: #0b0f14; color: #e8eef4; }
    main { max-width: 760px; margin: 0 auto; padding: 48px 20px 80px; }
    a { color: #7dffc3; }
    code, pre { font-family: ui-monospace, SFMono-Regular, monospace; }
    pre { background: #141b22; padding: 14px 16px; overflow: auto; border-radius: 8px; }
    h1 { font-size: 2rem; margin: 0 0 8px; }
    .muted { color: #9aa8b5; }
  </style>
</head>
<body>
  <main>
    <p class="muted">X-Agent MCP Hackathon 2026 · Open Innovation · ${SLUG}</p>
    <h1>VenueClock</h1>
    <p>Deterministic market-session calendar for AI agents. Returns pre-market, regular, after-hours, holiday, weekend, and the next open or close for NYSE, Nasdaq, LSE, and 24/7 crypto.</p>
    <p>Commit <code>${commit}</code></p>
    <h2>Live calls</h2>
    <pre>curl -sS https://kele0929.github.io/health.json
curl -sS https://kele0929.github.io/.well-known/xagent-verification.json
curl -sS https://kele0929.github.io/v1/venues.json
curl -sS https://kele0929.github.io/v1/resolve/xnys/2026-09-04.json</pre>
    <p>MCP tools: <a href="/mcp/tools.json">/mcp/tools.json</a>. Local stdio server: <code>node src/mcp.js</code>.</p>
    <p>Source: <a href="https://github.com/kele0929/venueclock">github.com/kele0929/venueclock</a></p>
  </main>
</body>
</html>
`;
await writeFile(join(outDir, "index.html"), index, "utf8");
process.stdout.write(`wrote ${outDir} commit=${commit} venues=${venues.length} days=${dates.length}\n`);
