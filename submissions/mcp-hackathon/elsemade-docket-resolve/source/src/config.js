import { createAuthConfig } from "./auth.js";
import {
  fixtureEvidenceAllowHosts,
  fixtureEvidenceFetcher,
  fixtureEvidenceResolver,
} from "./evidence/fixture.js";

export function deploymentConfig(environment = process.env) {
  const auth = createAuthConfig(environment);
  const fixtureEvidence = environment.NODE_ENV !== "production"
    && !auth.required
    && environment.DOCKET_EVIDENCE_FIXTURE !== "false"
    && environment.DOCKET_EVIDENCE_FIXTURE === "true";
  const configuredEvidenceAllowHosts = (environment.DOCKET_EVIDENCE_ALLOW_HOSTS ?? "")
    .split(",")
    .map((host) => host.trim().toLowerCase())
    .filter(Boolean);
  const publicRateLimitPerMinute = Number.parseInt(environment.DOCKET_PUBLIC_RATE_LIMIT_PER_MINUTE ?? "30", 10);
  if (!Number.isInteger(publicRateLimitPerMinute) || publicRateLimitPerMinute < 1 || publicRateLimitPerMinute > 10_000) {
    throw new Error("DOCKET_PUBLIC_RATE_LIMIT_PER_MINUTE must be an integer from 1 to 10000.");
  }
  return {
    commit:
      environment.XAGT_COMMIT ??
      environment.VERCEL_GIT_COMMIT_SHA ??
      environment.RENDER_GIT_COMMIT ??
      "development",
    slug: environment.XAGT_SLUG ?? "elsemade-docket-resolve",
    allowedOrigin: environment.ALLOWED_ORIGIN ?? "*",
    auth,
    storagePath: environment.DOCKET_STORAGE_PATH ?? "data/docket-store.json",
    evidenceAllowHosts: configuredEvidenceAllowHosts.length > 0
      ? configuredEvidenceAllowHosts
      : fixtureEvidence ? fixtureEvidenceAllowHosts : [],
    evidenceRequireAllowlist: auth.required
      || environment.NODE_ENV === "production"
      || environment.DOCKET_EVIDENCE_REQUIRE_ALLOWLIST === "true",
    evidenceFetcher: fixtureEvidence ? fixtureEvidenceFetcher : undefined,
    evidenceResolver: fixtureEvidence ? fixtureEvidenceResolver : undefined,
    evidenceFixture: fixtureEvidence,
    publicRateLimitPerMinute,
  };
}
