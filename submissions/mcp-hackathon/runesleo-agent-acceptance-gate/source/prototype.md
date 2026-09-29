# Local Prototype

Status: local_only

## What this prototype does

This is a deterministic local auditor for the `Agent Deliverable Auditor` ASP concept.

It reads a JSON delivery packet and returns the response shape defined in `service-spec.md`:

- `verdict`
- `score`
- dimension scores
- missing evidence
- risks
- positive evidence
- seller questions
- next gate
- buyer summary
- evaluator notes
- machine flags

It does not call OKX, OpenAI, a wallet, a payment endpoint, or any external API.

## Commands

Run all sample audits:

```bash
npm run audit:samples
```

Run one input:

```bash
npm run audit -- sample-inputs/01-pmquant-rename.json --pretty
```

Write generated audit JSON files:

```bash
node ./bin/audit-agent-deliverable.mjs --samples --out generated-audits
```

Run the local sample test:

```bash
npm test
```

Start the local HTTP demo/API:

```bash
npm run serve
```

Then open:

```text
http://127.0.0.1:8787/
```

Local endpoints:

```text
GET  /health
GET  /api/sample-audits
POST /audit-agent-deliverable
```

Example API call:

```bash
curl -sS http://127.0.0.1:8787/audit-agent-deliverable \
  -H 'content-type: application/json' \
  --data-binary @sample-inputs/01-pmquant-rename.json
```

## Current limitation

This prototype is intentionally rule-based. It checks structure, validation gaps, deferred release checks, hard-gate signals, dirty state, guard-triggered stops, and read-only boundaries.

It is not yet a semantic judge. The next useful step is to test whether the rule output is already valuable enough for Leo's own worker acceptance flow. Only after that should an LLM-assisted mode be considered.
