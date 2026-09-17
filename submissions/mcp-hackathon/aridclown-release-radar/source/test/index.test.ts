import { describe, expect, it } from "vitest";
import { handle, summarizeRelease, validateRepo } from "../src/index";

describe("release radar", () => {
  it("accepts only owner/repository inputs", () => {
    expect(validateRepo("cloudflare/workers-sdk")).toBe("cloudflare/workers-sdk");
    expect(validateRepo("https://github.com/cloudflare/workers-sdk")).toBeUndefined();
    expect(validateRepo("bad repo")).toBeUndefined();
  });

  it("pulls explicit breaking signals from release notes", () => {
    const result = summarizeRelease({ tag_name: "v2", name: null, body: "# v2\n- Added caching\n- Breaking change: old config was removed", published_at: null, html_url: "https://example.test", prerelease: false, draft: false });
    expect(result.highlights).toEqual(["v2", "Added caching"]);
    expect(result.breakingSignals).toEqual(["Breaking change: old config was removed"]);
  });

  it("returns structured public GitHub release data", async () => {
    const fetcher: typeof fetch = async () => new Response(JSON.stringify([{ tag_name: "v1", name: "First", body: "- Added endpoint", published_at: "2026-09-01T00:00:00Z", html_url: "https://github.com/o/r/releases/v1", prerelease: false, draft: false }]));
    const response = await handle(new Request("https://example.test/v1/releases?repo=o/r"), fetcher);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ repo: "o/r", count: 1, releases: [{ tag: "v1", highlights: ["Added endpoint"] }] });
  });
});
