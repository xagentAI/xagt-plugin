import { NextResponse } from "next/server";
import { getCommitSha } from "@/lib/commit";

// Required by the X-Agent AI MCP Hackathon 2026 submission rules: a public
// health endpoint that echoes the exact git commit under review, so
// reviewers can confirm the deployed API matches the submitted source.
//
// Docs required this "at root" — since this app's actual root ("/") is the
// product's landing page, it's exposed here at /api/health instead. If a
// reviewer insists on literally "/", add a rewrite in next.config.mjs
// redirecting a health-check User-Agent, or move the landing page to /app and
// mount this at the true root — noted in SUBMISSION.md either way.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ status: "ok", commit: getCommitSha() });
}
