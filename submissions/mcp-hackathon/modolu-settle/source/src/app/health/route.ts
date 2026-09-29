import { getConfig } from "@/lib/config";
import { apiRoute, jsonResponse } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export interface HealthResponse {
  readonly status: "ok";
  readonly service: "settle";
  readonly environment: string;
  /** Exact 40-character deployed git commit SHA; `null` outside a deployment. */
  readonly commit: string | null;
  readonly timestamp: string;
}

export const GET = apiRoute("/health", ({ requestId }) => {
  const config = getConfig();
  const body: HealthResponse = {
    status: "ok",
    service: "settle",
    environment: config.deploymentEnv,
    commit: config.commitSha,
    timestamp: new Date().toISOString(),
  };
  return jsonResponse(body, { requestId });
});
