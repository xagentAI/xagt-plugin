export const VERSION = "0.1.0";

export interface Env {
  COMMIT?: string;
  SLUG?: string;
}

type Release = {
  tag_name: string;
  name: string | null;
  body: string | null;
  published_at: string | null;
  html_url: string;
  prerelease: boolean;
  draft: boolean;
};

type ReleaseSummary = {
  tag: string;
  name: string;
  publishedAt: string | null;
  url: string;
  highlights: string[];
  breakingSignals: string[];
};

const GITHUB_REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const BREAKING = /\b(breaking|breaking change|deprecat(?:e|ed|ion)|removed|migration|required action)\b/i;

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=300", ...extraHeaders },
  });
}

export function validateRepo(repo: string | null): string | undefined {
  if (!repo || !GITHUB_REPO.test(repo)) return undefined;
  return repo;
}

export function summarizeRelease(release: Release): ReleaseSummary {
  const lines = (release.body ?? "")
    .split("\n")
    .map((line) => line.replace(/^\s*[-*#]+\s*/, "").trim())
    .filter(Boolean);
  const breakingSignals = lines.filter((line) => BREAKING.test(line)).slice(0, 6);
  const highlights = lines.filter((line) => !BREAKING.test(line)).slice(0, 6);
  return {
    tag: release.tag_name,
    name: release.name ?? release.tag_name,
    publishedAt: release.published_at,
    url: release.html_url,
    highlights,
    breakingSignals,
  };
}

async function github(url: string, fetcher: typeof fetch): Promise<Response> {
  return fetcher(url, { headers: { accept: "application/vnd.github+json", "user-agent": "release-radar-api" } });
}

export async function handle(request: Request, fetcher: typeof fetch = fetch, commit = "UNDEPLOYED", slug = "release-radar"): Promise<Response> {
  const url = new URL(request.url);
  if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405, { allow: "GET" });
  if (url.pathname === "/health") return json({ status: "ok", version: VERSION, commit });
  if (url.pathname === "/.well-known/xagent-verification.json") {
    return json({ schemaVersion: 1, slug, commit });
  }
  if (url.pathname === "/") {
    return json({
      name: "Release Radar API",
      purpose: "Turns public GitHub release notes into concise, agent-ready change signals.",
      endpoints: ["GET /v1/releases?repo=owner/repo", "GET /health"],
      examples: ["/v1/releases?repo=cloudflare/workers-sdk", "/v1/releases?repo=vercel/next.js&limit=3"],
    });
  }
  if (url.pathname !== "/v1/releases") return json({ error: "not_found" }, 404);

  const repo = validateRepo(url.searchParams.get("repo"));
  if (!repo) return json({ error: "invalid_repo", message: "Use repo=owner/repository." }, 400);
  const limitParam = Number(url.searchParams.get("limit") ?? "5");
  const limit = Number.isInteger(limitParam) ? Math.min(Math.max(limitParam, 1), 10) : 5;
  const upstream = await github(`https://api.github.com/repos/${repo}/releases?per_page=${limit}`, fetcher);
  if (!upstream.ok) return json({ error: "github_upstream_error", status: upstream.status }, upstream.status === 404 ? 404 : 502);
  const releases = (await upstream.json()) as Release[];
  return json({ repo, count: releases.length, releases: releases.filter((r) => !r.draft).map(summarizeRelease) });
}

export default {
  fetch: (request: Request, env: Env) => handle(request, fetch, env.COMMIT, env.SLUG),
} satisfies ExportedHandler<Env>;
