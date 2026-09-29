import { describe, expect, it, vi } from "vitest";
import { createService } from "../src/service.js";
import { evidence } from "./fixtures.js";

const COMMIT = "0123456789abcdef0123456789abcdef01234567";

function service(fetchEvidence = vi.fn(async () => evidence())) {
  return {
    fetchEvidence,
    handle: createService(
      { reviewCommit: COMMIT, sourceRepository: "https://github.com/fzlzjerry/bountyproof" },
      {
        fetchEvidence,
        now: () => new Date("2026-09-08T05:30:00.000Z"),
        randomUUID: () => "deterministic-request-id",
      },
    ),
  };
}

describe("BountyProof HTTP service", () => {
  it("exposes health and exact X-Agent deployment proof", async () => {
    const { handle } = service();
    const health = await handle(new Request("https://api.example/health"));
    expect(health.status).toBe(200);
    expect(health.headers.get("x-source-commit")).toBe(COMMIT);
    expect(await health.json()).toEqual({
      status: "ok",
      service: "bountyproof",
      version: "0.1.0",
      commit: COMMIT,
      checkedAt: "2026-09-08T05:30:00.000Z",
    });

    const proof = await handle(new Request("https://api.example/.well-known/xagent-verification.json"));
    expect(await proof.json()).toEqual({ schemaVersion: 1, slug: "morax-bountyproof", commit: COMMIT });
  });

  it("checks one issue and caches identical evidence queries", async () => {
    const { handle, fetchEvidence } = service();
    const body = JSON.stringify({
      issueUrl: "https://github.com/example/project/issues/42",
      expectedRewardUsd: 100,
      expectedPlatform: "Algora",
    });
    const first = await handle(new Request("https://api.example/v1/check", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    }));
    expect(first.status).toBe(200);
    expect(first.headers.get("x-bountyproof-cache")).toBe("MISS");
    expect((await first.json()) as { verdict: string }).toMatchObject({ verdict: "PROCEED_TO_MAINTAINER_CONFIRMATION" });

    const second = await handle(new Request("https://api.example/v1/check", {
      method: "POST",
      headers: { "content-type": "application/json", "x-request-id": "second-request" },
      body,
    }));
    expect(second.headers.get("x-bountyproof-cache")).toBe("HIT");
    expect(second.headers.get("x-request-id")).toBe("second-request");
    expect((await second.json()) as { requestId: string }).toMatchObject({ requestId: "second-request" });
    expect(fetchEvidence).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["text/plain", "{}", 415, "CONTENT_TYPE_REQUIRED"],
    ["application/json", "not-json", 400, "INVALID_JSON"],
    ["application/json", "[]", 400, "OBJECT_REQUIRED"],
    ["application/json", '{"issueUrl":"https://evil.example/a"}', 400, "INVALID_ISSUE_URL"],
    ["application/json", '{"issueUrl":"https://github.com/example/project/issues/42","extra":true}', 400, "UNKNOWN_FIELDS"],
  ])("returns a structured client error for %s %#", async (contentType, body, status, code) => {
    const { handle } = service();
    const response = await handle(new Request("https://api.example/v1/check", {
      method: "POST",
      headers: { "content-type": contentType },
      body,
    }));
    expect(response.status).toBe(status);
    const value = (await response.json()) as { error: { code: string; requestId: string } };
    expect(value.error.code).toBe(code);
    expect(value.error.requestId).toBe("deterministic-request-id");
  });

  it("rejects oversized bodies before calling GitHub", async () => {
    const { handle, fetchEvidence } = service();
    const response = await handle(new Request("https://api.example/v1/check", {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": "20000" },
      body: JSON.stringify({ issueUrl: "https://github.com/example/project/issues/42" }),
    }));
    expect(response.status).toBe(413);
    expect(fetchEvidence).not.toHaveBeenCalled();
  });
});
