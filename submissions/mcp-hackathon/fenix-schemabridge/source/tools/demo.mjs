import { readFile } from 'node:fs/promises';
import worker from '../src/worker.mjs';

for (const file of ['csv-request.json', 'json-request.json', 'invalid-request.json']) {
  const body = await readFile(new URL(`../fixtures/${file}`, import.meta.url), 'utf8');
  const response = await worker.fetch(new Request('http://localhost/v1/transform', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body,
  }));
  process.stdout.write(`${file} -> HTTP ${response.status}\n${JSON.stringify(await response.json(), null, 2)}\n`);
}
const health = await worker.fetch(new Request('http://localhost/health'));
process.stdout.write(`Unconfigured local health -> HTTP ${health.status}\n${await health.text()}\n`);
