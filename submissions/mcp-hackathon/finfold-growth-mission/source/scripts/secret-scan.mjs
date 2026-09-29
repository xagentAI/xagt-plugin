import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";

const root = process.cwd();
const excluded = new Set([".git", ".wrangler", "benchmark-results", "coverage", "dist", "node_modules"]);
const patterns = [
  { name: "private key", pattern: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/ },
  { name: "OpenAI-style secret", pattern: /\bsk-[A-Za-z0-9_-]{24,}\b/ },
  { name: "GitHub token", pattern: /\bgh[opsu]_[A-Za-z0-9]{30,}\b/ },
  { name: "Google API key", pattern: /\bAIza[0-9A-Za-z_-]{30,}\b/ },
  { name: "Cloudflare API token assignment", pattern: /CLOUDFLARE_API_TOKEN\s*=\s*[^\s<][^\s]{12,}/ },
];

async function filesAt(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory() && excluded.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await filesAt(path)));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

const findings = [];
for (const path of await filesAt(root)) {
  const name = relative(root, path);
  if (name === "package-lock.json") continue;
  const text = await readFile(path, "utf8").catch(() => "");
  for (const rule of patterns) {
    if (rule.pattern.test(text)) findings.push(`${name}: ${rule.name}`);
  }
}

if (findings.length) {
  console.error(`Potential secrets found:\n${findings.join("\n")}`);
  process.exit(1);
}
console.log("Secret scan passed: no high-confidence credentials detected.");
