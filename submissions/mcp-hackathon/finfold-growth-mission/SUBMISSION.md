# Finfold Growth Mission API

**Submitted via:** `xagt-plugin@0.5.0`
**Submitted at:** 2026-09-02T08:12:39.464Z
**Updated at:** 2026-09-03T11:53:00.000Z

## Capability

- **One-line description:** Turn one public business URL and growth objective into one evidence-bound mission, one publishable asset, one tracked CTA, and an outcome-driven next action.
- **Capability boundary:** Reads one public HTML page, selects one primary growth mission, preserves the model-selected angle and audience, compiles up to three canonical excerpts into a distinct platform-native structure, creates one same-site HTTPS tracked CTA, and accepts attributable outcomes to calculate a verdict and next action. It never renders private pages, bypasses access controls, auto-publishes, modifies external accounts, fabricates missing evidence, or guarantees growth.

## Live API

- **API base URL:** https://api.finfold.app
- **Health-check URL:** https://api.finfold.app/health
- **Deployment proof URL:** https://api.finfold.app/.well-known/xagent-verification.json
- **Authentication:** Bearer review key delivered only through the program's approved private review channel. The raw key is shown once and only its SHA-256 hash is stored.
- **Rate limits / known limits:** The isolated review key allows 100 authenticated calls per UTC day and expires after 2026-10-05. Source fetches accept public HTML/XHTML only, stream at most 1.5 MB, allow at most three redirects, and time out after 10 seconds. Mission creation is synchronous; the current five-platform production run completed 20/20 calls on the first provider attempt with 16,897 ms p50, 22,548 ms p95, and 24,206 ms p99. JavaScript-only or evidence-thin pages fail with typed errors. Anonymous clicks are raw counts and do not count as credible conversion outcomes by themselves.

## Source and reproducibility

- **Source repository:** https://github.com/joeymilano/finfold-growth-mission-api
- **Review commit:** `65a4a545ca74b0e357973de433fd108c375531bc`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm run check`
- **Run locally:** `npx wrangler d1 migrations apply finfold-growth-mission --local && npm run dev` (mission generation uses the configured Workers AI binding; the test suite is fully intercepted and does not require paid inference).
- **Deploy:** Create the D1 database, replace the documented `database_id`, run `npx wrangler d1 migrations apply finfold-growth-mission --remote`, issue a review key with `node scripts/issue-review-key.mjs`, then run `npx wrangler deploy --var "COMMIT_SHA:$(git rev-parse HEAD)"`.
- **Version binding:** The exact commit is injected at deployment. Public `/health` and same-origin `/.well-known/xagent-verification.json` both return `65a4a545ca74b0e357973de433fd108c375531bc`, which is also the public GitHub review commit.

## Verification

See `verification/README.md` for public version proof, an authenticated mission call, MCP discovery, expected output, safe failure behavior, tracking verification, the credential-free five-platform 20-call report, a redacted real mission, and authenticated live MCP discovery evidence under `source/verification/`.

## Security and data handling

- **Data collected:** Request URL, objective, platform, locale, optional target/landing page, extracted evidence snippets, generated mission/asset, aggregate daily clicks, and reviewer-supplied outcome events. The service does not store raw HTML, API keys, IP addresses, or credentials embedded in URLs.
- **Purpose and retention:** Evidence and attributable mission data are retained for 30 days so the service can calculate `won`, `lost`, `inconclusive`, or `running`; scheduled cleanup removes expired records. Hashed review-key usage is retained for quota enforcement.
- **Third parties / outbound network calls:** The Worker fetches only the caller-supplied public source origin and calls Cloudflare Workers AI. Cloudflare Workers, D1, and Workers AI host the service. There are no analytics, ad networks, payment processors, or auto-publishing integrations in the review build.
- **Known risks / restrictions:** Public pages may change after a mission is generated; the stored source digest and exact evidence snippets bind what was reviewed at generation time. SSRF controls reject local/private/special-use targets, credentials, unsafe ports, suspicious redirects, non-HTML, oversized responses, and HTTPS downgrade. Tracked destinations require HTTPS and the source host, its subdomain, or canonical `www`/apex equivalent. Model output is schema-validated, canonicalized to selected source sections, and given one repair attempt before failing closed. Revenue outcomes use one target currency and all outcomes must fall inside the measurement window. Reviewers should record only real outcomes.

## Support

- **Team / builder:** Joey Zhao (Finfold)
- **Contact:** support@finfold.app
- **License / rights:** Joey Zhao owns and authorizes review of the submitted Finfold Growth Mission source under the accompanying all-rights-reserved license and `RIGHTS.md`; third-party packages retain their own licenses.
