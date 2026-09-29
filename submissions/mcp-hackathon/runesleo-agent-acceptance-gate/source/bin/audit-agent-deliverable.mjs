#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditDelivery } from '../src/auditor.mjs';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);

if (args.includes('--help') || args.length === 0) {
  printHelp();
  process.exit(args.length === 0 ? 1 : 0);
}

const pretty = args.includes('--pretty');
const useSamples = args.includes('--samples');
const outIndex = args.indexOf('--out');
const outDir = outIndex >= 0 ? path.resolve(process.cwd(), args[outIndex + 1] ?? '') : null;
const files = useSamples
  ? fs.readdirSync(path.join(rootDir, 'sample-inputs'))
      .filter((file) => file.endsWith('.json'))
      .sort()
      .map((file) => path.join(rootDir, 'sample-inputs', file))
  : args.filter((arg) => !arg.startsWith('--') && arg !== (outDir ?? '')).map((file) => path.resolve(process.cwd(), file));

if (outIndex >= 0 && !args[outIndex + 1]) {
  throw new Error('--out requires a directory path');
}

if (!files.length) {
  throw new Error('No input files found');
}

if (outDir) fs.mkdirSync(outDir, { recursive: true });

const outputs = [];
for (const file of files) {
  const input = JSON.parse(fs.readFileSync(file, 'utf8'));
  const audit = auditDelivery(input);
  outputs.push({ input_file: file, audit });

  if (outDir) {
    const base = path.basename(file, '.json');
    fs.writeFileSync(path.join(outDir, `${base}-audit.json`), `${JSON.stringify(audit, null, 2)}\n`);
  }
}

if (!outDir) {
  const payload = useSamples || files.length > 1 ? outputs : outputs[0].audit;
  process.stdout.write(`${JSON.stringify(payload, null, pretty ? 2 : 0)}\n`);
} else {
  for (const output of outputs) {
    process.stdout.write(`wrote ${path.basename(output.input_file, '.json')}-audit.json\n`);
  }
}

function printHelp() {
  process.stdout.write(`Agent Deliverable Auditor prototype

Usage:
  npm run audit -- sample-inputs/01-pmquant-rename.json --pretty
  npm run audit:samples
  node ./bin/audit-agent-deliverable.mjs --samples --out generated-audits

Options:
  --samples   Audit every JSON file in sample-inputs/
  --pretty    Pretty-print JSON output
  --out DIR   Write one audit JSON file per input
  --help      Show this help
`);
}

