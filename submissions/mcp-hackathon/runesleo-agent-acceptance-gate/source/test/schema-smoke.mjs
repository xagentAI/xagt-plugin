import fs from 'node:fs';

const files = [
  'discovery/agent-service.json',
  'discovery/mcp-tool-manifest.json',
  'schemas/agent-transaction-assessment.schema.json',
  'sample-inputs/06-agent-budget-spend-precall.json',
  'sample-outputs/06-agent-budget-spend-precall-assessment.json'
];

for (const file of files) {
  JSON.parse(fs.readFileSync(file, 'utf8'));
  console.log(`PASS json ${file}`);
}

