import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  REPOSITORY, VALIDATION_WORKFLOW, RECEIPT_MARKER,
  createGitHubClient, readPull, submissionSlug, receiptBody,
  acknowledgeSubmission, materializeSubmission, validatePull, workflowSummary,
  archiveRef, archiveValidatedRun, verifySealSource
} from "../scripts/submission-lifecycle.mjs";

const base = "a".repeat(40);
const head = "b".repeat(40);
const merge = "c".repeat(40);
const sourceCommit = "d".repeat(40);
const treeHashes = ["1", "2", "3"].map((value) => value.repeat(40));
const slug = "team-example";
const prefix = `/repos/${REPOSITORY}`;
const project = `submissions/mcp-hackathon/${slug}`;
const temporaryDirectories = [];

async function temporary() {
  const directory = await mkdtemp(join(tmpdir(), "xagt-lifecycle-test-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

function pull(overrides = {}) {
  return {
    number: 33, state: "open", changed_files: 1, merged: false,
    base: { sha: base, ref: "main", repo: { full_name: REPOSITORY } },
    head: { sha: head, ref: "entry", repo: { full_name: "participant/fork" } },
    ...overrides
  };
}

function packageFiles() {
  return {
    "SUBMISSION.md": "# Example\nSetup instructions for a test fixture.\n",
    "RIGHTS.md": "# Rights\nThe author permits archiving and review.\n",
    "source/index.js": "throw new Error('SUBMITTED CODE MUST NEVER EXECUTE');\n",
    "source/package.json": JSON.stringify({ scripts: { postinstall: "exit 99" } }),
    "verification/README.md": "# Health\ncurl https://example.com/health\n",
    "submission.json": JSON.stringify({
      schemaVersion: 1, name: "Example", slug,
      sourceRepository: "https://github.com/participant/project",
      reviewCommit: sourceCommit, apiBaseUrl: "https://example.com",
      healthCheckUrl: "https://example.com/health",
      deploymentProofUrl: "https://example.com/.well-known/xagent-verification.json"
    })
  };
}

// Every request is a mock. Unexpected requests fail, including attempts to read
// participant repositories during sealing or to modify participant branches.
function fixture() {
  const state = {
    pull: pull(), files: [{ filename: `${project}/source/index.js`, status: "added" }],
    comments: [], refs: new Map(), content: packageFiles(),
    mutateEntries: (entries) => entries, truncated: false,
    corruptBlob: false, mutatePullRead: null,
    run: {
      id: 42, repository: { full_name: REPOSITORY }, path: VALIDATION_WORKFLOW,
      event: "pull_request", status: "completed", conclusion: "success", head_sha: head,
      head_branch: "entry", head_repository: { full_name: "participant/fork" }
    },
    associated: null, treeForCommit: {}, failPost: false, persistBeforePostError: false
  };
  let pullReads = 0;
  function blobs() {
    return Object.entries(state.content).map(([path, content]) => {
      const bytes = Buffer.from(content);
      const hash = createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
      return { path, sha: hash, size: bytes.length, mode: "100644", type: "blob", bytes };
    });
  }
  const api = {
    list: vi.fn(async (path) => {
      if (path === `${prefix}/pulls/33/files`) return structuredClone(state.files);
      if (path === `${prefix}/issues/33/comments`) return structuredClone(state.comments);
      if (path === `${prefix}/commits/${head}/pulls`) return structuredClone(state.associated ?? [state.pull]);
      throw new Error(`Unexpected list: ${path}`);
    }),
    request: vi.fn(async (path, options = {}) => {
      if (options.method === "POST") {
        if (path === `${prefix}/issues/33/comments`) {
          if (!state.failPost || state.persistBeforePostError) {
            state.comments.push({ body: options.body.body, user: { login: "github-actions[bot]" }, html_url: "https://github.com/receipt" });
          }
          if (state.failPost) throw new Error("lost POST response");
          return state.comments.at(-1);
        }
        if (path === `${prefix}/git/refs`) {
          const ref = options.body.ref.replace(/^refs\//, "");
          if (!state.failPost || state.persistBeforePostError) {
            state.refs.set(ref, { ref: options.body.ref, object: { sha: options.body.sha } });
          }
          if (state.failPost) throw new Error("lost POST response");
          return state.refs.get(ref);
        }
        throw new Error(`Unexpected mutation: ${path}`);
      }
      if (path === `${prefix}/pulls/33`) {
        pullReads += 1;
        return structuredClone(state.mutatePullRead?.(pullReads, state.pull) ?? state.pull);
      }
      if (path === `${prefix}/actions/runs/42`) return structuredClone(state.run);
      if (path.startsWith(`${prefix}/git/ref/`)) {
        const ref = path.slice(`${prefix}/git/ref/`.length);
        if (state.refs.has(ref)) return structuredClone(state.refs.get(ref));
        throw Object.assign(new Error("missing ref"), { status: 404 });
      }
      if (path.startsWith(`${prefix}/git/blobs/`)) {
        const blob = blobs().find((item) => path.endsWith(item.sha));
        if (!blob) throw new Error("unexpected blob");
        const bytes = state.corruptBlob ? Buffer.alloc(blob.size, 88) : blob.bytes;
        return { encoding: "base64", content: bytes.toString("base64") };
      }
      if (path === `${prefix}/git/trees/${treeHashes[2]}?recursive=1`) {
        const entries = blobs().map(({ bytes, ...entry }) => entry);
        return { truncated: state.truncated, tree: state.mutateEntries(entries) };
      }
      for (const commit of [head, base, merge]) {
        if (path === `${prefix}/git/trees/${commit}`) {
          return { tree: [{ path: "submissions", type: "tree", mode: "040000", sha: state.treeForCommit[commit] ?? treeHashes[0] }] };
        }
      }
      if (path === `${prefix}/git/trees/${treeHashes[0]}`) return { tree: [{ path: "mcp-hackathon", type: "tree", mode: "040000", sha: treeHashes[1] }] };
      if (path === `${prefix}/git/trees/${treeHashes[1]}`) return { tree: [{ path: slug, type: "tree", mode: "040000", sha: treeHashes[2] }] };
      if (path === `${prefix}/git/trees/${"e".repeat(40)}`) return { tree: [{ path: "mcp-hackathon", type: "tree", mode: "040000", sha: "f".repeat(40) }] };
      if (path === `${prefix}/git/trees/${"f".repeat(40)}`) return { tree: [{ path: slug, type: "tree", mode: "040000", sha: "9".repeat(40) }] };
      throw new Error(`Unexpected request: ${path}`);
    })
  };
  return { state, api, writes: () => api.request.mock.calls.filter(([, options]) => options?.method === "POST") };
}

function onlineOptions(scratchRoot) {
  return {
    scratchRoot,
    validationOptions: {
      commitVerifier: vi.fn(async () => undefined),
      jsonRequester: vi.fn(async (url) => ({
        headers: {}, body: url.endsWith("/health")
          ? { status: "ok", commit: sourceCommit }
          : { schemaVersion: 1, slug, commit: sourceCommit }
      }))
    }
  };
}

describe("English receipts", () => {
  it("explains check failures without making a review decision or rendering injected content", () => {
    const message = new Error("Missing <img src=x onerror=alert(1)>\n[details](https://evil.invalid)");
    const summary = workflowSummary("validate", undefined, message);
    expect(summary).toContain("not completed");
    expect(summary).toContain("not eligibility approval");
    expect(summary).toContain("need maintainer attention");
    expect(summary).not.toContain("<img");
    expect(summary).toContain("&lt;img");
    expect(workflowSummary("archive", { status: "archived-not-reviewed", checks: ["source inspected"] })).toContain("source inspected");
  });
  it("acknowledges once without promising review acceptance or rewards", async () => {
    const { api, writes } = fixture();
    expect((await acknowledgeSubmission(api, 33)).status).toBe("received");
    expect((await acknowledgeSubmission(api, 33)).status).toBe("already-received");
    expect(writes()).toHaveLength(1);
    expect(receiptBody(33)).toContain("does not confirm eligibility");
    expect(receiptBody(33)).toContain("An external repository link alone is not sufficient");
    expect(receiptBody(33)).toContain("merging code for archival purposes does not");
  });

  it("recognizes an existing maintainer receipt and ignores participant-forged markers", async () => {
    const { api, state, writes } = fixture();
    state.comments = [{ body: RECEIPT_MARKER, user: { login: "maintainer" }, author_association: "MEMBER" }];
    expect((await acknowledgeSubmission(api, 33)).status).toBe("already-received");
    expect(writes()).toHaveLength(0);
    state.comments[0].author_association = "CONTRIBUTOR";
    expect((await acknowledgeSubmission(api, 33)).status).toBe("received");
    expect(writes()).toHaveLength(1);
  });

  it("does not touch closed PRs or the expired activity", async () => {
    const { api, state, writes } = fixture();
    state.pull.state = "closed";
    expect((await acknowledgeSubmission(api, 33)).status).toBe("skipped");
    state.pull.state = "open";
    state.files = [{ filename: "submissions/old-activity/META.md" }];
    expect((await acknowledgeSubmission(api, 33)).status).toBe("skipped");
    expect(writes()).toHaveLength(0);
  });

  it("does not post after a PR changes or the file listing is incomplete", async () => {
    const { api, state, writes } = fixture();
    state.pull.changed_files = 2;
    await expect(acknowledgeSubmission(api, 33)).rejects.toThrow(/incomplete/);
    state.pull.changed_files = 1;
    state.mutatePullRead = (count, value) => count >= 3 ? { ...value, head: { ...value.head, sha: merge } } : value;
    await expect(acknowledgeSubmission(api, 33)).rejects.toThrow(/changed during inspection/);
    expect(writes()).toHaveLength(0);
  });

  it("does not blindly repeat a comment POST after an uncertain response", async () => {
    const { api, state, writes } = fixture();
    state.failPost = true;
    state.persistBeforePostError = true;
    await expect(acknowledgeSubmission(api, 33)).rejects.toThrow(/lost POST/);
    expect((await acknowledgeSubmission(api, 33)).status).toBe("already-received");
    expect(writes()).toHaveLength(1);
  });
});

describe("bounded, read-only source inspection", () => {
  it("rejects invalid PR numbers, other repositories, mixed paths, and rename escapes", async () => {
    const { api, state } = fixture();
    await expect(readPull(api, "33/../1")).rejects.toThrow(/number/);
    state.pull.base.repo.full_name = "elsewhere/repo";
    await expect(readPull(api, 33)).rejects.toThrow(/official main/);
    expect(() => submissionSlug([{ filename: `${project}/source/index.js`, previous_filename: "README.md" }])).toThrow(/one project directory/);
    expect(() => submissionSlug([{ filename: `${project}/source/index.js` }, { filename: "README.md", status: "removed" }])).toThrow(/one project directory/);
  });

  it("reads and validates source as data, never installing or executing it", async () => {
    const { api, state, writes } = fixture();
    const scratch = await temporary();
    const report = await validatePull(api, state.pull, onlineOptions(scratch));
    expect(report.status).toBe("pass");
    expect(report.headSha).toBe(head);
    expect(report.submissionTree).toBe(treeHashes[2]);
    expect(writes()).toHaveLength(0);
    expect(await readdir(scratch)).toEqual([]);
  });

  it.each([
    ["symlink", (entries) => [{ ...entries[0], mode: "120000" }], /symbolic links/],
    ["submodule", (entries) => [{ ...entries[0], mode: "160000", type: "commit" }], /submodules/],
    ["path traversal", (entries) => [{ ...entries[0], path: "../escaped" }], /path/],
    ["absolute path", (entries) => [{ ...entries[0], path: "/escaped" }], /path/],
    ["control character", (entries) => [{ ...entries[0], path: "file\nname" }], /path/],
    ["Git metadata", (entries) => [{ ...entries[0], path: ".git/config" }], /Git metadata/],
    ["oversized file", (entries) => [{ ...entries[0], size: 5 * 1024 * 1024 + 1 }], /5 MiB/],
    ["oversized package", (entries) => Array.from({ length: 5 }, (_, index) => ({ ...entries[0], path: `source/${index}.js`, size: 5 * 1024 * 1024 })), /20 MiB/]
  ])("rejects %s before reading blobs or writing files", async (_label, change, expected) => {
    const { api, state } = fixture();
    state.mutateEntries = change;
    const scratch = await temporary();
    await expect(materializeSubmission(api, head, slug, scratch)).rejects.toThrow(expected);
    expect(api.request.mock.calls.some(([path]) => path.includes("/git/blobs/"))).toBe(false);
    expect(await readdir(scratch)).toEqual([]);
  });

  it("rejects truncated trees and mismatched blob contents", async () => {
    const { api, state } = fixture();
    const scratch = await temporary();
    state.truncated = true;
    await expect(materializeSubmission(api, head, slug, scratch)).rejects.toThrow(/safe limits/);
    state.truncated = false;
    state.corruptBlob = true;
    await expect(materializeSubmission(api, head, slug, scratch)).rejects.toThrow(/content does not match/);
  });

  it("cleans up failed validation and detects base-branch changes", async () => {
    const { api, state } = fixture();
    const scratch = await temporary();
    state.content["RIGHTS.md"] = "";
    await expect(validatePull(api, state.pull, onlineOptions(scratch))).rejects.toThrow(/cannot be empty/);
    expect(await readdir(scratch)).toEqual([]);
    state.content = packageFiles();
    state.mutatePullRead = (_count, value) => ({ ...value, base: { ...value.base, sha: merge } });
    await expect(validatePull(api, state.pull, onlineOptions(scratch))).rejects.toThrow(/changed during inspection/);
    expect(await readdir(scratch)).toEqual([]);
  });
});

describe("official source archive", () => {
  it("independently checks source before creating one exact, additive ref", async () => {
    const { api, writes } = fixture();
    const options = onlineOptions(await temporary());
    const result = await archiveValidatedRun(api, 42, options);
    expect(result.status).toBe("archived-not-reviewed");
    expect(result.ref).toBe(`heads/submission-archive/pr-33-${head}`);
    expect(options.validationOptions.commitVerifier).toHaveBeenCalledOnce();
    expect(writes()).toEqual([[`${prefix}/git/refs`, {
      method: "POST", body: { ref: `refs/${archiveRef(33, head)}`, sha: head }
    }]]);
    expect((await archiveValidatedRun(api, 42, options)).status).toBe("already-archived");
    expect(writes()).toHaveLength(1);
  });

  it.each([
    ["failed", (state) => { state.run.conclusion = "failure"; }, "skip"],
    ["stale", (state) => { state.associated = [pull({ head: { sha: merge } })]; }, "skip"],
    ["closed", (state) => { state.pull.state = "closed"; }, "skip"],
    ["wrong workflow", (state) => { state.run.path = ".github/workflows/other.yml"; }, /official/],
    ["privileged event", (state) => { state.run.event = "pull_request_target"; }, /official/],
    ["wrong repository", (state) => { state.run.repository.full_name = "other/repo"; }, /official/],
    ["wrong fork", (state) => { state.run.head_repository.full_name = "another/fork"; }, /same source/],
    ["ambiguous association", (state) => { state.associated = [pull(), pull({ number: 34 })]; }, /ambiguous/]
  ])("does not archive a %s run", async (_label, change, expected) => {
    const { api, state, writes } = fixture();
    change(state);
    const result = archiveValidatedRun(api, 42, onlineOptions(await temporary()));
    if (expected === "skip") expect((await result).status).toBe("skipped");
    else await expect(result).rejects.toThrow(expected);
    expect(writes()).toHaveLength(0);
  });

  it("does not trust a green run for a PR modifying official code", async () => {
    const { api, state, writes } = fixture();
    state.files.push({ filename: ".github/workflows/submission-validation.yml", status: "modified" });
    state.pull.changed_files = 2;
    await expect(archiveValidatedRun(api, 42, onlineOptions(await temporary()))).rejects.toThrow(/one project directory/);
    expect(writes()).toHaveLength(0);
  });

  it("refuses to replace an existing archive at a different commit", async () => {
    const { api, state, writes } = fixture();
    state.refs.set(archiveRef(33, head), { object: { sha: merge } });
    await expect(archiveValidatedRun(api, 42)).rejects.toThrow(/refusing to replace/);
    expect(writes()).toHaveLength(0);
  });

  it("rechecks a changed PR immediately before creating a ref", async () => {
    const { api, state, writes } = fixture();
    state.mutatePullRead = (count, value) => count >= 3 ? { ...value, head: { ...value.head, sha: merge } } : value;
    await expect(archiveValidatedRun(api, 42, onlineOptions(await temporary()))).rejects.toThrow(/changed during inspection/);
    expect(writes()).toHaveLength(0);
  });

  it.each([true, false])("resolves an uncertain ref POST without rewriting or retrying (persisted: %s)", async (persisted) => {
    const { api, state, writes } = fixture();
    state.failPost = true;
    state.persistBeforePostError = persisted;
    const result = archiveValidatedRun(api, 42, onlineOptions(await temporary()));
    if (persisted) expect((await result).status).toBe("archived-not-reviewed");
    else await expect(result).rejects.toThrow(/lost POST/);
    expect(writes()).toHaveLength(1);
  });
});

describe("manual acceptance source verification", () => {
  function mergedFixture() {
    const result = fixture();
    result.state.pull = pull({ state: "closed", merged: true, merged_at: "2026-09-03T00:00:00Z", merge_commit_sha: merge });
    const ref = archiveRef(33, head);
    result.state.refs.set(ref, { ref: `refs/${ref}`, object: { sha: head } });
    return result;
  }

  it("uses the official archived copy even if the external repository disappears", async () => {
    const { api, writes } = mergedFixture();
    const result = await verifySealSource(api, 33, slug, base);
    expect(result.officialMergeCommit).toBe(merge);
    expect(result.sourceTree).toBe(treeHashes[2]);
    expect(writes()).toHaveLength(0);
    expect(api.request.mock.calls.every(([path]) => path.startsWith(`${prefix}/`))).toBe(true);
  });

  it("requires the correct merged PR, archive, and source tree", async () => {
    const { api, state } = mergedFixture();
    state.pull.merged = false;
    await expect(verifySealSource(api, 33, slug, base)).rejects.toThrow(/already be merged/);
    state.pull.merged = true;
    await expect(verifySealSource(api, 33, "wrong-project", base)).rejects.toThrow(/does not match/);
    state.treeForCommit[base] = "e".repeat(40);
    await expect(verifySealSource(api, 33, slug, base)).rejects.toThrow(/source differ/);
    state.treeForCommit = {};
    state.refs.clear();
    await expect(verifySealSource(api, 33, slug, base)).rejects.toThrow(/missing from the official archive/);
  });

  it("can verify existing short-name archives but never creates them", async () => {
    const { api, state } = mergedFixture();
    const original = state.refs.get(archiveRef(33, head));
    state.refs.clear();
    const old = `heads/submission-archive/pr-33-${head.slice(0, 12)}`;
    state.refs.set(old, { ...original, ref: `refs/${old}` });
    expect((await verifySealSource(api, 33, slug, base)).archiveRef).toBe(`refs/${old}`);
  });
});

describe("GitHub API boundary", () => {
  it("uses a fixed API host, blocks redirects, and does not leak error bodies", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ number: 33 }), { status: 200 }));
    const api = createGitHubClient("test-token", fetcher);
    await expect(api.request(`${prefix}/pulls/33`)).resolves.toEqual({ number: 33 });
    expect(fetcher.mock.calls[0][0]).toBe(`https://api.github.com${prefix}/pulls/33`);
    expect(fetcher.mock.calls[0][1].redirect).toBe("error");
    await expect(api.request("/repos/other/repo/pulls/33")).rejects.toThrow(/outside/);
    await expect(api.request(`${prefix}/../secrets`)).rejects.toThrow(/outside/);
    fetcher.mockImplementationOnce(async () => new Response("private error details", { status: 403 }));
    await expect(api.request(`${prefix}/pulls/33`)).rejects.toThrow(/^GitHub GET request failed \(403\)$/);
  });

  it("paginates lists and rejects unbounded responses", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(Array(100).fill({ id: 1 }))));
    fetcher.mockImplementationOnce(async () => new Response(JSON.stringify(Array(100).fill({ id: 1 }))));
    fetcher.mockImplementationOnce(async () => new Response(JSON.stringify([{ id: 2 }])));
    const api = createGitHubClient("test-token", fetcher);
    expect(await api.list(`${prefix}/pulls/33/files`)).toHaveLength(101);
    expect(fetcher.mock.calls[1][0]).toContain("page=2");
    await expect(api.list(`${prefix}/pulls/33/files`)).rejects.toThrow(/pagination limit/);
    fetcher.mockImplementationOnce(async () => new Response(" ".repeat(8 * 1024 * 1024 + 1)));
    await expect(api.request(`${prefix}/pulls/33`)).rejects.toThrow(/8 MiB/);
  });
});

describe("workflow configuration contract", () => {
  it("keeps code inspection separate from writes and never checks out fork code", async () => {
    const names = ["submission-validation", "submission-receipt", "archive-validated-submission", "seal-accepted-submission"];
    const workflows = await Promise.all(names.map((name) => readFile(new URL(`../.github/workflows/${name}.yml`, import.meta.url), "utf8")));
    const [validation, receipt, archive, seal] = workflows;
    for (const workflow of workflows) {
      expect(workflow).not.toMatch(/allow-unsafe-pr-checkout|pull_request\.head|checkout@v|npm (?:ci|install)|pnpm|^\s+cache:\s/m);
      expect(workflow).toContain("persist-credentials: false");
      expect(workflow).toContain('node-version: "24"');
      expect(workflow).toContain("package-manager-cache: false");
      expect(workflow.match(/uses: actions\/[\w-]+@[a-f0-9]{40}/g)).toHaveLength(2);
    }
    expect(validation).toMatch(/\n  pull_request:\n/);
    expect(validation).not.toContain(": write");
    expect(validation).toContain("ref: ${{ github.event.pull_request.base.sha }}");
    expect(receipt).toContain("pull-requests: write");
    expect(receipt).not.toContain("contents: write");
    expect(archive).toContain("workflow_run:");
    expect(archive).toContain("node scripts/submission-lifecycle.mjs archive");
    expect(seal).toContain("workflow_dispatch:");
    expect(seal).toContain("github.ref == 'refs/heads/main'");
    expect(seal).toContain("ref: ${{ github.sha }}");
    expect(seal).not.toMatch(/--force|--clobber/);
  });
});
