# Verification evidence

## Prerequisites

- Review commit: `d1b84e00cb87b7e8811a020f497855b67bc00303`
- API base URL: `https://kele0929.github.io/v1`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://kele0929.github.io/health.json
```

Expected response:

```json
{"status":"ok","commit":"d1b84e00cb87b7e8811a020f497855b67bc00303"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://kele0929.github.io/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"kele0929-venueclock","commit":"d1b84e00cb87b7e8811a020f497855b67bc00303"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error https://kele0929.github.io/v1/resolve/xnys/2026-09-04.json
```

Expected success (Friday, regular session 09:30–16:00 America/New_York):

```json
{"venue":"xnys","mic":"XNYS","name":"New York Stock Exchange","date":"2026-09-04","timezone":"America/New_York","weekday":"Friday","closed":false,"status":"open","holiday":null,"sessions":[{"id":"pre","label":"pre-market","open":"2026-09-04T04:00:00-04:00","close":"2026-09-04T09:30:00-04:00","openUtc":"2026-09-04T08:00:00.000Z","closeUtc":"2026-09-04T13:30:00.000Z","earlyClose":false},{"id":"regular","label":"regular","open":"2026-09-04T09:30:00-04:00","close":"2026-09-04T16:00:00-04:00","openUtc":"2026-09-04T13:30:00.000Z","closeUtc":"2026-09-04T20:00:00.000Z","earlyClose":false},{"id":"post","label":"after-hours","open":"2026-09-04T16:00:00-04:00","close":"2026-09-04T20:00:00-04:00","openUtc":"2026-09-04T20:00:00.000Z","closeUtc":"2026-09-05T00:00:00.000Z","earlyClose":false}]}
```

Safe failure (Labor Day 2026, market closed — still JSON, HTTP 200):

```bash
curl --fail --silent --show-error https://kele0929.github.io/v1/resolve/xnys/2026-09-07.json
```

```json
{"venue":"xnys","mic":"XNYS","name":"New York Stock Exchange","date":"2026-09-07","timezone":"America/New_York","weekday":"Monday","closed":true,"status":"holiday","holiday":{"type":"closed","name":"Labor Day"},"sessions":[]}
```

On the Node server (`npm start`), unknown venues return HTTP 404 JSON `{"error":"not_found",...}` and invalid dates return HTTP 400 JSON. Those dynamic error bodies are not files on GitHub Pages.
