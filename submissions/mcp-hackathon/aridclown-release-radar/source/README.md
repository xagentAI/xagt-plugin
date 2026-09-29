# Release Radar API

Release Radar turns public GitHub release notes into compact change signals an agent can consume before upgrading a dependency.

## API

`GET /v1/releases?repo=owner/repository&limit=5`

The API reads public GitHub releases, returns the most recent non-draft releases, and separates lines that signal breaking changes, removals, deprecations, migrations, or required action from ordinary highlights.

Examples:

```sh
curl 'http://localhost:8787/v1/releases?repo=cloudflare/workers-sdk&limit=3'
curl 'http://localhost:8787/v1/compare?repo=vercel/next.js&base=v16.4.0-canary.33&head=v16.4.0-canary.34'
curl 'http://localhost:8787/openapi.json'
curl 'http://localhost:8787/health'
```

## Run and test

```sh
npm install
npm test
npm run check
npm run dev
```

## Deployment

Pass the reviewed 40-character Git commit at deployment time. The health and X-Agent verification endpoints report that same value.

```sh
npx wrangler deploy --var COMMIT:<40-character-git-commit>
```
