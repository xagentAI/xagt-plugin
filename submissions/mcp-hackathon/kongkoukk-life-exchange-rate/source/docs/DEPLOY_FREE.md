# Free deployment preparation: Vercel Hobby

Prepared for a personal, noncommercial hackathon demonstration. Use the Hobby plan only; do not enable a Pro trial, paid integrations or extra paid resources. No model API, database, GPU or EIA key is required to run the judging demo. Deployment has not happened yet.

## Account and deployment steps

1. Sign in to GitHub as KongkouKK. Publish this complete source project to the chosen public repository after reviewing the contents.
2. Create a Vercel personal Hobby account using the official signup flow. The user completes account terms and authorizes GitHub access for this project.
3. Import the actual project repository into Vercel. Keep the repository root as the root directory. The app uses the FastAPI framework, root app.py and the existing pyproject.toml/uv.lock.
4. Keep automatic system environment-variable exposure enabled. GitHub deployments supply VERCEL_GIT_COMMIT_SHA; the app returns that actual source revision. The public origin comes from VERCEL_PROJECT_PRODUCTION_URL, or an explicitly configured PUBLIC_BASE_URL.
5. Confirm the production deployment is publicly callable without Vercel login. Leave protected previews private; review uses only the production URL.
6. Verify production health/proof against the current official validator, which uses a 60-second request timeout and does not follow redirects or retry. Our additional hosted smoke check uses a stricter 10-second target. Then verify the deterministic REST call and real MCP client against /mcp/. Record the actual production URL and SHA before filling submission.json.

## Constraints

Hobby is free for personal, noncommercial projects within its quotas. Quota exhaustion can make the service unavailable until limits reset; it does not authorize a paid upgrade. A function request is configured for at most 30 seconds. We use stateless MCP JSON responses and do not require long-lived sessions. Vercel currently supports FastAPI lifespan startup/shutdown; shutdown cleanup has a 500 ms platform budget. Actual hosted MCP behavior must still be tested.

Render Free remains an alternative, but it sleeps after 15 idle minutes and may take about one minute to wake. That leaves little margin within X-Agent's current 60-second request timeout. Vercel Hobby is the default for this submission; actual cold-start behavior still requires hosted verification.

Sources checked 2026-09-15:
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/plans/hobby
- https://vercel.com/docs/environment-variables/system-environment-variables
- https://render.com/docs/free
- https://github.com/xagentAI/xagt-plugin/blob/main/scripts/validate-submission.mjs
