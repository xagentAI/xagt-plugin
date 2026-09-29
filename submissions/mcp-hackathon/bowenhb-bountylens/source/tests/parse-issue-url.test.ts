import { describe, expect, it } from "vitest";

import { InvalidIssueUrlError, parseIssueUrl } from "../src/github/parse-issue-url.js";

describe("parseIssueUrl", () => {
  it("parses a standard public GitHub issue URL", () => {
    expect(parseIssueUrl("https://github.com/xagentAI/xagt-plugin/issues/42")).toEqual({
      owner: "xagentAI",
      repo: "xagt-plugin",
      issueNumber: 42,
      canonicalUrl: "https://github.com/xagentAI/xagt-plugin/issues/42",
    });
  });

  it("accepts a trailing slash, query string, and fragment", () => {
    expect(parseIssueUrl("https://github.com/owner/repo/issues/7/?tab=activity#comment")).toEqual({
      owner: "owner",
      repo: "repo",
      issueNumber: 7,
      canonicalUrl: "https://github.com/owner/repo/issues/7",
    });
  });

  it.each([
    "not-a-url",
    "http://github.com/owner/repo/issues/1",
    "https://github.com.example.com/owner/repo/issues/1",
    "https://www.github.com/owner/repo/issues/1",
    "https://user@github.com/owner/repo/issues/1",
    "https://github.com:444/owner/repo/issues/1",
  ])("rejects a non-public or look-alike GitHub URL: %s", (input) => {
    expect(() => parseIssueUrl(input)).toThrow(InvalidIssueUrlError);
  });

  it.each([
    "https://github.com/owner/repo",
    "https://github.com/owner/repo/pull/1",
    "https://github.com/owner/repo/issues",
    "https://github.com/owner/repo/issues/0",
    "https://github.com/owner/repo/issues/-1",
    "https://github.com/owner/repo/issues/1/extra",
    "https://github.com/owner%2Frepo/project/issues/1",
  ])("rejects a path that is not one canonical issue reference: %s", (input) => {
    expect(() => parseIssueUrl(input)).toThrow(InvalidIssueUrlError);
  });

  it("rejects an issue number larger than JavaScript can represent safely", () => {
    expect(() =>
      parseIssueUrl("https://github.com/owner/repo/issues/999999999999999999999999"),
    ).toThrow("outside the supported range");
  });
});
