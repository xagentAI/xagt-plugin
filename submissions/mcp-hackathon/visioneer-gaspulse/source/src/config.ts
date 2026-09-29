export const GIT_COMMIT = process.env.GIT_COMMIT ?? "unknown";
export const SUBMISSION_SLUG = "visioneer-gaspulse";
export const ETHERSCAN_API_KEY = process.env.ETHERSCAN_API_KEY ?? "";
export const PORT = Number(process.env.PORT ?? 8080);
export const CACHE_TTL_MS = 60_000;
export const GAS_ORACLE_CACHE_TTL_MS = 15_000;
