export const SLUG = "bhrigu-bitcoin-research-state-api";
export const SCHEMA = "bhrigu_bitcoin_research_state_v0_1";

export function runtimeCommit() {
  return process.env.BHRIGU_COMMIT || process.env.VERCEL_GIT_COMMIT_SHA || "LOCAL_DEV";
}

export function healthPayload() {
  return { status: "ok", commit: runtimeCommit() };
}

export function verificationPayload() {
  return { schemaVersion: 1, slug: SLUG, commit: runtimeCommit() };
}
