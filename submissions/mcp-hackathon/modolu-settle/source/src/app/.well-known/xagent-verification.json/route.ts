import { getConfig } from "@/lib/config";
import { apiRoute, jsonResponse } from "@/lib/http";
import { buildXagentVerification } from "@/lib/xagent-verification";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Document shape is owned by src/lib/xagent-verification.ts. The commit comes
// from the same validated config value that /health reports.
export const GET = apiRoute("/.well-known/xagent-verification.json", ({ requestId }) =>
  jsonResponse(buildXagentVerification(getConfig()), { requestId }),
);
