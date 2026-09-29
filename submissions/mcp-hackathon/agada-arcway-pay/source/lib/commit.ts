/**
 * Resolves the current deployment's git commit hash for X-Agent's hackathon
 * verification requirements (both the health-check endpoint and the
 * .well-known verification JSON must echo the exact commit being reviewed).
 *
 * On Vercel, `VERCEL_GIT_COMMIT_SHA` is injected automatically at build and
 * runtime — no setup needed once this repo is connected to a Vercel project
 * via git. For any other host (or local `npm run build`), set GIT_COMMIT_SHA
 * yourself, e.g.:
 *   GIT_COMMIT_SHA=$(git rev-parse HEAD) npm run build
 *
 * Falls back to a clearly-fake all-zero hash so the endpoints still return
 * *something* well-formed in local dev without either variable set — replace
 * this with a real commit before submitting, since reviewers check it.
 */
export function getCommitSha(): string {
  const sha = process.env.VERCEL_GIT_COMMIT_SHA || process.env.GIT_COMMIT_SHA;
  if (sha && /^[0-9a-f]{40}$/i.test(sha)) return sha.toLowerCase();
  return "0".repeat(40);
}
