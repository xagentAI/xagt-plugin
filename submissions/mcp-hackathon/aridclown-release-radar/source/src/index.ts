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

type ComparePayload = {
  status: string;
  ahead_by: number;
  behind_by: number;
  total_commits: number;
  html_url: string;
  commits: Array<{ sha: string; commit: { message: string } }>;
  files?: Array<{ filename: string; status: string; additions: number; deletions: number }>;
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

export function fileArea(path: string): "dependencies" | "configuration" | "documentation" | "tests" | "source" | "other" {
  if (/(^|\/)(package-lock\.json|package\.json|pnpm-lock\.yaml|yarn\.lock|requirements.*\.txt|go\.mod|Cargo\.toml)$/i.test(path)) return "dependencies";
  if (/(^|\/)(\.github\/|wrangler\.|dockerfile|compose\.|.*\.config\.|tsconfig\.|eslint\.)/i.test(path)) return "configuration";
  if (/(^|\/)(docs\/|readme|changelog|license)/i.test(path)) return "documentation";
  if (/(^|\/)(__tests__\/|test\/|tests\/|.*\.(test|spec)\.)/i.test(path)) return "tests";
  if (/\.(ts|tsx|js|jsx|py|go|rs|java|rb|php|cs)$/i.test(path)) return "source";
  return "other";
}

export function summarizeCompare(payload: ComparePayload) {
  const files = payload.files ?? [];
  const byArea = Object.fromEntries(["dependencies", "configuration", "documentation", "tests", "source", "other"].map((area) => [area, 0]));
  for (const file of files) byArea[fileArea(file.filename)] += 1;
  return {
    comparisonUrl: payload.html_url,
    aheadBy: payload.ahead_by,
    behindBy: payload.behind_by,
    commitCount: payload.total_commits,
    changedFileCount: files.length,
    changedFilesByArea: byArea,
    commits: payload.commits.slice(0, 20).map(({ sha, commit }) => ({ sha: sha.slice(0, 12), subject: commit.message.split("\n")[0] })),
    changedFiles: files.slice(0, 100).map((file) => ({ path: file.filename, status: file.status, additions: file.additions, deletions: file.deletions, area: fileArea(file.filename) })),
  };
}

function openApi(origin: string) {
  return {
    openapi: "3.1.0",
    info: { title: "Release Radar API", version: VERSION, description: "Public GitHub release and comparison intelligence for upgrade-planning agents." },
    servers: [{ url: origin }],
    paths: {
      "/v1/releases": { get: { summary: "List release signals", parameters: [{ name: "repo", in: "query", required: true, schema: { type: "string", pattern: "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$" } }, { name: "limit", in: "query", schema: { type: "integer", minimum: 1, maximum: 10, default: 5 } }], responses: { "200": { description: "Release summaries" }, "400": { description: "Invalid repository" } } } },
      "/v1/compare": { get: { summary: "Plan an upgrade from two Git refs", parameters: [{ name: "repo", in: "query", required: true, schema: { type: "string" } }, { name: "base", in: "query", required: true, schema: { type: "string" } }, { name: "head", in: "query", required: true, schema: { type: "string" } }], responses: { "200": { description: "Commit and changed-file plan" }, "400": { description: "Invalid request" } } } },
    },
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
  if (url.pathname === "/openapi.json") return json(openApi(url.origin));
  if (url.pathname === "/") {
    return json({
      name: "Release Radar API",
      purpose: "Turns public GitHub release notes into concise, agent-ready change signals.",
      endpoints: ["GET /v1/releases?repo=owner/repo", "GET /v1/compare?repo=owner/repo&base=ref&head=ref", "GET /openapi.json", "GET /health"],
      examples: ["/v1/releases?repo=cloudflare/workers-sdk", "/v1/compare?repo=cloudflare/workers-sdk&base=wrangler@4.132.0&head=wrangler@4.133.0"],
    });
  }
  if (url.pathname !== "/v1/releases" && url.pathname !== "/v1/compare") return json({ error: "not_found" }, 404);

  const repo = validateRepo(url.searchParams.get("repo"));
  if (!repo) return json({ error: "invalid_repo", message: "Use repo=owner/repository." }, 400);
  if (url.pathname === "/v1/compare") {
    const base = url.searchParams.get("base");
    const head = url.searchParams.get("head");
    if (!base || !head || base.length > 120 || head.length > 120) return json({ error: "invalid_refs", message: "Use base and head Git refs." }, 400);
    const upstream = await github(`https://api.github.com/repos/${repo}/compare/${encodeURIComponent(base)}...${encodeURIComponent(head)}`, fetcher);
    if (!upstream.ok) return json({ error: "github_upstream_error", status: upstream.status }, upstream.status === 404 ? 404 : 502);
    return json({ repo, base, head, ...summarizeCompare(await upstream.json() as ComparePayload) });
  }
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
