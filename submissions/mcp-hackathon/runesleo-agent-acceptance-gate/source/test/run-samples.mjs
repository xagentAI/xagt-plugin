import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditDelivery } from '../src/auditor.mjs';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sampleInputDir = path.join(rootDir, 'sample-inputs');
const sampleOutputDir = path.join(rootDir, 'sample-outputs');

const cases = [
  ['01-pmquant-rename.json', '01-pmquant-rename-audit.json', ['deferred_build', 'public_release_gate']],
  ['02-t310-governance-update.json', '02-t310-governance-update-audit.json', ['deferred_build', 'protocol_tension']],
  ['03-alkanes-red-stop.json', '03-alkanes-red-stop-audit.json', ['guard_triggered', 'task_failed_safely']],
  ['04-dashboard-curation-readout.json', '04-dashboard-curation-readout-audit.json', ['dirty_state', 'deferred_build']],
  ['05-claude-science-readout.json', '05-claude-science-readout-audit.json', ['read_only_delivery', 'hard_gates_declared']]
];

let failures = 0;

for (const [inputFile, expectedFile, requiredFlags] of cases) {
  const input = JSON.parse(fs.readFileSync(path.join(sampleInputDir, inputFile), 'utf8'));
  const expected = JSON.parse(fs.readFileSync(path.join(sampleOutputDir, expectedFile), 'utf8'));
  const actual = auditDelivery(input);

  const errors = [];
  if (actual.schema_version !== '0.1') errors.push('schema_version mismatch');
  if (actual.verdict !== expected.verdict) errors.push(`verdict ${actual.verdict} != expected ${expected.verdict}`);
  if (typeof actual.score !== 'number' || actual.score < 0 || actual.score > 100) errors.push(`invalid score ${actual.score}`);
  for (const key of ['missing', 'risks', 'positive_evidence', 'questions_for_seller', 'machine_flags']) {
    if (!Array.isArray(actual[key])) errors.push(`${key} is not an array`);
  }
  for (const flag of requiredFlags) {
    if (!actual.machine_flags.includes(flag)) errors.push(`missing required flag ${flag}`);
  }

  if (errors.length) {
    failures += 1;
    console.error(`FAIL ${inputFile}`);
    for (const error of errors) console.error(`  - ${error}`);
  } else {
    console.log(`PASS ${inputFile}: ${actual.verdict} score=${actual.score}`);
  }
}

if (failures) {
  console.error(`${failures} sample audit case(s) failed`);
  process.exit(1);
}

console.log('All sample audit cases passed');

