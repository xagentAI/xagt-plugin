import { createExecutionContext, env } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import { GENERATED, REVIEW_KEY, mockOutbound, resetDatabase } from "./fixtures";

const createPayload = {
  sourceUrl: "https://acme.test/",
  objective: "leads",
  platform: "linkedin",
  locale: "en",
};

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const request = new Request(`https://api.finfold.app${path}`, init);
  return worker.fetch(request, env, createExecutionContext());
}

function authorizedHeaders(extra: Record<string, string> = {}): HeadersInit {
  return { authorization: `Bearer ${REVIEW_KEY}`, ...extra };
}

async function createMission(idempotency = "create-test-0001"): Promise<{ response: Response; body: Record<string, any> }> {
  const response = await call("/v1/missions", {
    method: "POST",
    headers: authorizedHeaders({ "content-type": "application/json", "idempotency-key": idempotency }),
    body: JSON.stringify(createPayload),
  });
  return { response, body: (await response.json()) as Record<string, any> };
}

beforeEach(async () => {
  await resetDatabase();
  mockOutbound();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("REST growth mission loop", () => {
  it("exposes source-verifiable health and verification endpoints", async () => {
    const health = await call("/health");
    expect(await health.json()).toEqual({ status: "ok", commit: "1111111111111111111111111111111111111111" });
    const proof = await call("/.well-known/xagent-verification.json");
    expect(await proof.json()).toEqual({
      schemaVersion: 1,
      slug: "finfold-growth-mission",
      commit: "1111111111111111111111111111111111111111",
    });
  });

  it("creates exactly one evidence-bound mission and one tracked asset", async () => {
    const { response, body } = await createMission();
    expect(response.status).toBe(201);
    expect(body.mission.id).toMatch(/^gm_[a-z0-9]{24}$/);
    expect(body.mission.title).toBe("Test one evidence-led message for qualified leads");
    expect(body.mission.hypothesis).toMatch(/^Test whether /);
    expect(body.asset.body).toContain(`https://api.finfold.app/r/${body.tracking.code}`);
    expect(body.asset.body).not.toContain("{{TRACKING_URL}}");
    expect(body.evidence[0].quote).toBe(GENERATED.evidence[0]?.quote);
    expect(body.validation).toMatchObject({ passed: true, evidenceExactMatch: true });
    expect(body.sideEffects).toEqual({ persisted: true, published: false, externalAccountsModified: false });
  });

  it("canonicalizes a model-copied quote from the selected source section", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementationOnce(async () =>
      new Response((await import("./fixtures")).SOURCE_HTML, {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
      }),
    );
    fetchMock.mockImplementationOnce(async () =>
      Response.json({
        choices: [
          {
            message: {
              content: JSON.stringify({
                ...GENERATED,
                asset: { ...GENERATED.asset, body: "A model paraphrase with no source support. {{TRACKING_URL}}" },
                evidence: [
                  { id: "e1", sectionId: "s1", quote: "model copied this incorrectly", confidence: 0.9 },
                  { id: "e2", sectionId: "s4", quote: "model also copied this incorrectly", confidence: 0.9 },
                ],
                claimMap: [{ claim: "A model paraphrase with no source support.", evidenceIds: ["e1"] }],
              }),
            },
          },
        ],
      }),
    );

    const { response, body } = await createMission("canonical-quote-0001");
    expect(response.status).toBe(201);
    expect(body.evidence[0].quote).toBe("Acme Workflow");
    expect(body.asset.body).toContain(GENERATED.evidence[0]?.quote);
    expect(body.asset.body).not.toContain("model paraphrase");
    expect(body.claimMap[0].claim).toBe(GENERATED.evidence[0]?.quote);
    expect(body.claimMap[0].evidenceIds).toEqual(["e2"]);
  });

  it("extracts a schema-valid JSON object from a provider reasoning envelope", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementationOnce(async () =>
      new Response((await import("./fixtures")).SOURCE_HTML, {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
      }),
    );
    fetchMock.mockImplementationOnce(async () =>
      Response.json({
        choices: [{ message: { content: `<think>Choose the strongest section.</think>\n${JSON.stringify(GENERATED)}` } }],
      }),
    );

    const { response, body } = await createMission("reasoning-envelope-0001");
    expect(response.status).toBe(201);
    expect(body.validation).toMatchObject({ passed: true, evidenceExactMatch: true });
  });

  it("replays the same idempotency key and rejects a changed payload", async () => {
    const first = await createMission("same-key-0001");
    const replay = await createMission("same-key-0001");
    expect(replay.response.status).toBe(201);
    expect(replay.response.headers.get("idempotent-replayed")).toBe("true");
    expect(replay.body.mission.id).toBe(first.body.mission.id);

    const conflict = await call("/v1/missions", {
      method: "POST",
      headers: authorizedHeaders({ "content-type": "application/json", "idempotency-key": "same-key-0001" }),
      body: JSON.stringify({ ...createPayload, objective: "signups" }),
    });
    expect(conflict.status).toBe(409);
    expect((await conflict.json()) as object).toMatchObject({ error: { code: "IDEMPOTENCY_CONFLICT" } });
  });

  it("tracks a click, records a deduplicated lead, and reaches won", async () => {
    const created = await createMission();
    const missionId = created.body.mission.id as string;
    const trackingCode = created.body.tracking.code as string;
    const redirect = await call(`/r/${trackingCode}`);
    expect(redirect.status).toBe(302);
    expect(redirect.headers.get("location")).toContain("utm_source=finfold_growth_mission");

    const payload = { eventId: "lead-crm-0001", type: "lead", quantity: 1 };
    const outcome = await call(`/v1/missions/${missionId}/outcomes`, {
      method: "POST",
      headers: authorizedHeaders({ "content-type": "application/json", "idempotency-key": "outcome-key-0001" }),
      body: JSON.stringify(payload),
    });
    const outcomeBody = (await outcome.json()) as Record<string, any>;
    expect(outcome.status).toBe(200);
    expect(outcomeBody.outcome.verdict).toBe("won");
    expect(outcomeBody.attribution).toMatchObject({ clicks: 1, leads: 1 });

    const duplicate = await call(`/v1/missions/${missionId}/outcomes`, {
      method: "POST",
      headers: authorizedHeaders({ "content-type": "application/json", "idempotency-key": "outcome-key-0002" }),
      body: JSON.stringify(payload),
    });
    expect((await duplicate.json()) as object).toMatchObject({ duplicate: true, recorded: false });

    const read = await call(`/v1/missions/${missionId}`, { headers: authorizedHeaders() });
    expect((await read.json()) as object).toMatchObject({ outcome: { verdict: "won", measuredValue: 1 } });
  });

  it("returns lost after the window with attribution below target", async () => {
    const created = await createMission();
    const missionId = created.body.mission.id as string;
    await env.DB.batch([
      env.DB.prepare("UPDATE missions SET target_value = 2, measurement_due_at = ? WHERE id = ?").bind(
        "2026-01-01T00:00:00.000Z",
        missionId,
      ),
      env.DB.prepare("INSERT INTO tracking_daily (mission_id, event_day, clicks) VALUES (?, ?, 1)").bind(
        missionId,
        "2026-09-02",
      ),
    ]);
    const read = await call(`/v1/missions/${missionId}`, { headers: authorizedHeaders() });
    expect((await read.json()) as object).toMatchObject({ outcome: { verdict: "lost", measuredValue: 0 } });
  });

  it("returns inconclusive after the window without credible outcome data", async () => {
    const created = await createMission();
    const missionId = created.body.mission.id as string;
    await env.DB.prepare("UPDATE missions SET measurement_due_at = ? WHERE id = ?")
      .bind("2026-01-01T00:00:00.000Z", missionId)
      .run();
    const read = await call(`/v1/missions/${missionId}`, { headers: authorizedHeaders() });
    expect((await read.json()) as object).toMatchObject({ outcome: { verdict: "inconclusive", measuredValue: 0 } });
  });
});

describe("auth scopes, expiry, quota, and redaction", () => {
  it("rejects expired keys", async () => {
    await resetDatabase("mission:read", { expiresAt: "2025-01-01T00:00:00.000Z" });
    const response = await call("/v1/missions/gm_aaaaaaaaaaaaaaaaaaaaaaaa", { headers: authorizedHeaders() });
    expect((await response.json()) as object).toMatchObject({ error: { code: "KEY_EXPIRED" } });
  });

  it("enforces scopes", async () => {
    await resetDatabase("mission:read");
    const response = await call("/v1/missions", {
      method: "POST",
      headers: authorizedHeaders({ "content-type": "application/json", "idempotency-key": "scope-key-0001" }),
      body: JSON.stringify(createPayload),
    });
    expect((await response.json()) as object).toMatchObject({ error: { code: "SCOPE_DENIED" } });
  });

  it("enforces the daily call limit", async () => {
    await resetDatabase("mission:read", { dailyLimit: 1 });
    await call("/v1/missions/gm_aaaaaaaaaaaaaaaaaaaaaaaa", { headers: authorizedHeaders() });
    const second = await call("/v1/missions/gm_aaaaaaaaaaaaaaaaaaaaaaaa", { headers: authorizedHeaders() });
    expect(second.status).toBe(429);
    expect((await second.json()) as object).toMatchObject({ error: { code: "RATE_LIMITED" } });
  });

  it("never logs a supplied bearer token", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const secret = "ff_gm_should_never_appear_in_logs";
    await call("/v1/missions/gm_aaaaaaaaaaaaaaaaaaaaaaaa", {
      headers: { authorization: `Bearer ${secret}` },
    });
    expect(log.mock.calls.flat().join(" ")).not.toContain(secret);
  });
});
