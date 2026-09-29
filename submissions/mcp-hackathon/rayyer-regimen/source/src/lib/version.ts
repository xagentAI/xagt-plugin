/**
 * Build identity.
 *
 * The submission contract requires the live service to report the exact 40-character
 * commit that the reviewed source was built from, on two endpoints, on one origin.
 * Hard-coding that SHA is how submissions drift out of sync with their deployment, so
 * it is read from the platform's own build metadata instead: whatever commit Vercel
 * built is what the service reports. `REVIEW_COMMIT` exists as an escape hatch for
 * self-hosting, and the value is validated rather than trusted.
 */

const SHA_RE = /^[0-9a-f]{40}$/;

export const SUBMISSION_SLUG = 'rayyer-regimen';

function resolveCommit(): string | null {
  const candidates = [process.env.REVIEW_COMMIT, process.env.VERCEL_GIT_COMMIT_SHA];
  for (const value of candidates) {
    const normalised = value?.trim().toLowerCase();
    if (normalised && SHA_RE.test(normalised)) return normalised;
  }
  return null;
}

/** The reviewed commit, or null when the build carries no usable git metadata. */
export const COMMIT: string | null = resolveCommit();

/** Human-readable build info for diagnostics. Never contains secrets. */
export const BUILD = {
  service: 'regimen',
  slug: SUBMISSION_SLUG,
  commit: COMMIT,
  region: process.env.VERCEL_REGION ?? null,
  startedAt: new Date().toISOString(),
} as const;
