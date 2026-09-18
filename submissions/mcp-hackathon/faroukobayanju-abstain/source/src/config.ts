/**
 * Deployment identity and secrets.
 *
 * The commit sha is load-bearing for two hard gates:
 *   GET /health                              → { status, commit }
 *   GET /.well-known/xagent-verification.json → { slug, commit }
 * Both must report the EXACT 40-character commit that the reviewed source
 * corresponds to. Vercel sets VERCEL_GIT_COMMIT_SHA on git-connected deploys.
 */
/** MUST match the submission directory name: submissions/mcp-hackathon/<slug>/ */
export const PROJECT_SLUG = 'faroukobayanju-abstain';

/** Required by the automated online gate. */
export const SCHEMA_VERSION = 1;

export function commitSha(env: NodeJS.ProcessEnv = process.env): string {
  return env['VERCEL_GIT_COMMIT_SHA'] ?? env['COMMIT_SHA'] ?? 'unknown';
}

/** A commit that would actually satisfy the gate: 40 lowercase hex characters. */
export function isReviewableCommit(sha: string): boolean {
  return /^[0-9a-f]{40}$/.test(sha);
}

export function writeKey(env: NodeJS.ProcessEnv = process.env): string {
  return env['ABSTAIN_WRITE_KEY'] ?? '';
}

/**
 * Constant-time comparison. A length-sensitive `===` on a credential leaks
 * length and early-mismatch position through timing; this is cheap to do right.
 */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
