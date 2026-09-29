import { NextResponse } from "next/server";
import { getCommitSha } from "@/lib/commit";

/**
 * Required by the X-Agent AI MCP Hackathon 2026 submission rules:
 *   GET /.well-known/xagent-verification.json
 *   -> { schemaVersion: 1, slug: "<team>-<project-slug>", commit: "<sha>" }
 *
 * Update SLUG below to match the exact submission folder name you use under
 * submissions/mcp-hackathon/<team>-<project-slug>/ in the fork/PR.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SLUG = "agada-arcway-pay";

export async function GET() {
  return NextResponse.json({
    schemaVersion: 1,
    slug: SLUG,
    commit: getCommitSha(),
  });
}
