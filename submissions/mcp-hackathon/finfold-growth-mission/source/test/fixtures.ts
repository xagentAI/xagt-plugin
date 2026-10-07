import { sha256Hex } from "../src/crypto";
import { DEMO_KEY_ID } from "../src/demo";
import { vi } from "vitest";

export const REVIEW_KEY = "ff_gm_test_review_key_123456789";

export const SOURCE_HTML = `<!doctype html>
<html>
  <head>
    <title>Acme Workflow</title>
    <meta name="description" content="A focused workspace for independent product teams.">
  </head>
  <body>
    <h1>Acme helps independent teams ship faster.</h1>
    <p>Plan work, review customer evidence, and coordinate launches in one calm workspace.</p>
    <p>Teams can start with a public project brief and invite collaborators when they are ready.</p>
  </body>
</html>`;

export const GENERATED = {
  mission: {
    title: "Invite independent teams to test one calmer launch workflow",
    hypothesis: "A concrete workflow message will help independent product teams recognize the value before they commit to a new workspace.",
    audience: "Independent product teams planning a launch",
    primaryMetric: "leads",
    platform: "linkedin",
  },
  asset: {
    format: "LinkedIn post",
    title: "A calmer launch workflow",
    body:
      "Plan work, review customer evidence, and coordinate launches in one calm workspace. Explore the workflow: {{TRACKING_URL}}",
    cta: "Explore the workflow",
  },
  evidence: [
    {
      id: "e1",
      sectionId: "s4",
      quote: "Plan work, review customer evidence, and coordinate launches in one calm workspace.",
      confidence: 0.99,
    },
  ],
  claimMap: [
    {
      claim: "Plan work, review customer evidence, and coordinate launches in one calm workspace.",
      evidenceIds: ["e1"],
    },
  ],
};

export async function resetDatabase(scopes = "mission:create mission:read outcome:write", options: { expiresAt?: string; dailyLimit?: number } = {}): Promise<void> {
  const { env } = await import("cloudflare:test");
  await env.DB.batch([
    env.DB.prepare("DELETE FROM outcome_events"),
    env.DB.prepare("DELETE FROM tracking_daily"),
    env.DB.prepare("DELETE FROM missions"),
    env.DB.prepare("DELETE FROM idempotency_records"),
    env.DB.prepare("DELETE FROM api_key_usage"),
    env.DB.prepare("DELETE FROM api_keys"),
  ]);
  await env.DB.prepare(
    "INSERT INTO api_keys (id, token_hash, label, scopes, daily_limit, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(
      "key_test",
      await sha256Hex(REVIEW_KEY),
      "test-reviewer",
      scopes,
      options.dailyLimit ?? 50,
      options.expiresAt ?? "2027-01-01T00:00:00.000Z",
      "2026-09-02T00:00:00.000Z",
    )
    .run();
  await env.DB.prepare(
    "INSERT INTO api_keys (id, token_hash, label, scopes, daily_limit, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(
      DEMO_KEY_ID,
      await sha256Hex("ff_gm_demo_key_hash_only_token_never_issued"),
      "public-demo",
      "mission:create mission:read",
      1,
      "2027-01-01T00:00:00.000Z",
      "2026-09-02T00:00:00.000Z",
    )
    .run();
}

function generatedForPlatform(platform: string) {
  if (platform === "linkedin") return GENERATED;
  return { ...GENERATED, mission: { ...GENERATED.mission, platform } };
}

export function mockOutbound(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url === "https://acme.test/") {
        return new Response(SOURCE_HTML, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
      }
      if (url === "https://llm.test/v1/chat/completions") {
        const rawBody =
          typeof init?.body === "string"
            ? init.body
            : input instanceof Request
              ? await input.clone().text()
              : "";
        const requested =
          rawBody.match(/"requestedPlatform":"(auto|linkedin|x|reddit|xiaohongshu|wechat)"/)?.[1] ?? "linkedin";
        const content = JSON.stringify(generatedForPlatform(requested === "auto" ? "linkedin" : requested));
        return Response.json({ choices: [{ message: { content } }] });
      }
      throw new Error(`Unexpected outbound request: ${url}`);
    }),
  );
}
