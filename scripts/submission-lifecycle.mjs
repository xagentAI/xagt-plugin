#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { appendFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { resolveChangedSubmissionDirectory, validateSubmissionDirectory } from "./validate-submission.mjs";

export const REPOSITORY = "xagentAI/xagt-plugin";
export const VALIDATION_WORKFLOW = ".github/workflows/submission-validation.yml";
export const RECEIPT_MARKER = "<!-- xagent-mcp-submission-receipt-v1 -->";
const PREFIX = "submissions/mcp-hackathon/";
const MAX_FILES = 2_000;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_BYTES = 20 * 1024 * 1024;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha(value) {
  assert(typeof value === "string" && /^[a-f0-9]{40}$/.test(value), "expected an exact lowercase commit or object hash");
  return value;
}

function prNumber(value) {
  assert(/^[1-9][0-9]*$/.test(String(value)) && Number.isSafeInteger(Number(value)), "invalid pull request number");
  return Number(value);
}

export function createGitHubClient(token, fetcher = fetch) {
  assert(token, "a GitHub workflow token is required");
  async function request(path, { method = "GET", body } = {}) {
    assert(path.startsWith(`/repos/${REPOSITORY}/`) && !path.includes("..") && !/[\x00-\x20\\#]/.test(path), "GitHub request is outside the official repository");
    const response = await fetcher(`https://api.github.com${path}`, {
      method,
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
        "user-agent": "xagent-submission-lifecycle",
        "x-github-api-version": "2022-11-28"
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      redirect: "error",
      signal: AbortSignal.timeout(15_000)
    });
    if (!response.ok) {
      // Do not echo response bodies: they may contain participant-controlled text.
      const error = new Error(`GitHub ${method} request failed (${response.status})`);
      error.status = response.status;
      await response.body?.cancel();
      throw error;
    }
    let size = 0;
    const chunks = [];
    for await (const chunk of response.body) {
      size += chunk.length;
      assert(size <= 8 * 1024 * 1024, "GitHub response exceeds the 8 MiB limit");
      chunks.push(chunk);
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  }
  return {
    request,
    async list(path) {
      const items = [];
      for (let page = 1; page <= 30; page += 1) {
        const result = await request(`${path}${path.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
        assert(Array.isArray(result), "expected a GitHub list response");
        items.push(...result);
        if (result.length < 100) return items;
      }
      throw new Error("GitHub list exceeds the safe pagination limit; manual inspection is required");
    }
  };
}

async function optional(api, path) {
  try { return await api.request(path); }
  catch (error) { if (error.status === 404) return null; throw error; }
}

export async function readPull(api, number) {
  const pull = await api.request(`/repos/${REPOSITORY}/pulls/${prNumber(number)}`);
  assert(pull.number === prNumber(number) && pull.base?.repo?.full_name === REPOSITORY && pull.base.ref === "main", "pull request must target the official main branch");
  sha(pull.head.sha);
  sha(pull.base.sha);
  return pull;
}

async function changedFiles(api, pull) {
  assert(Number.isInteger(pull.changed_files) && pull.changed_files > 0 && pull.changed_files < 3_000, "pull request file count requires manual inspection");
  const files = await api.list(`/repos/${REPOSITORY}/pulls/${pull.number}/files`);
  assert(files.length === pull.changed_files, "pull request changed during inspection or file listing is incomplete");
  return files;
}

export function submissionSlug(files) {
  // Both sides of renames and deletions count, not only added/modified paths.
  const paths = files.flatMap((file) => [file.filename, ...(file.previous_filename ? [file.previous_filename] : [])]);
  return basename(resolveChangedSubmissionDirectory("/", paths));
}

async function currentHead(api, pull, requireOpen = true) {
  const current = await readPull(api, pull.number);
  assert(current.head.sha === pull.head.sha && current.base.sha === pull.base.sha, "pull request changed during inspection; retry the latest version");
  assert(!requireOpen || current.state === "open", "pull request is no longer open");
}

export function receiptBody(number) {
  return `${RECEIPT_MARKER}
### Submission received — #${prNumber(number)}

Thank you for submitting to the current X-Agent MCP Hackathon. We have received your pull request.

**This is a receipt only. It does not confirm eligibility, completeness, technical approval, a judging result, or an award. Passing automated checks or merging code for archival purposes does not, by itself, mean the entry has passed review or won a prize.**

Please include the complete source for the submitted capability in this repository under \`submissions/mcp-hackathon/<slug>/source/\`, with dependency files, configuration examples, and reproducible setup/build instructions. An external repository link alone is not sufficient. The official copy is intended to remain available if the original repository later becomes unavailable. Do not include secrets, credentials, or private user data; clearly disclose external and private-service dependencies.

The [automated checks](https://github.com/${REPOSITORY}/pull/${number}/checks) report technical checks separately. A workflow failure is not a judging decision. Keep updates in this PR while submissions remain open, and keep the documented source version and deployment evidence consistent.

See the [submission instructions](https://github.com/${REPOSITORY}/blob/main/submissions/README.md). Final review results and awards will be announced separately through the official event channels.`;
}

export function workflowSummary(action, report, error) {
  // Participant-controlled messages must not become HTML or clickable Markdown.
  const escape = (value) => String(value).replace(/[\x00-\x1f\x7f]/g, " ").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const title = { receipt: "Submission receipt", validate: "Submission checks", archive: "Source preservation", seal: "Manual acceptance archive" }[action] ?? "Submission workflow";
  const boundary = "A receipt, successful automated check, or source archive is not eligibility approval, a judging result, or an award. Final decisions are recorded separately by the event team.";
  if (error) {
    return `## ${title}: not completed\n\n${boundary}\n\n<pre>${escape(error.message).slice(0, 2000)}</pre>\n\nIf this message identifies missing or inconsistent submission material, update the same PR and follow the [submission instructions](https://github.com/${REPOSITORY}/blob/main/submissions/README.md). Repository permissions, checkout, API, and runner failures need maintainer attention; they are not judging decisions.\n`;
  }
  const details = report.checks?.map((check) => `<li>${escape(check)}</li>`).join("") ?? "";
  return `## ${title}\n\n${boundary}\n\nStatus: <code>${escape(report.status ?? "sealed")}</code>\n\n${report.reason ? `<p>${escape(report.reason)}</p>\n` : ""}${details ? `<ul>${details}</ul>\n` : ""}\nFor review and retention details, see the [source retention policy](https://github.com/${REPOSITORY}/blob/main/docs/submission-retention-and-reward.md).\n`;
}

async function publishSummary(action, report, error) {
  if (process.env.GITHUB_STEP_SUMMARY) {
    await appendFile(process.env.GITHUB_STEP_SUMMARY, workflowSummary(action, report, error));
  }
}

export async function acknowledgeSubmission(api, number) {
  const pull = await readPull(api, number);
  if (pull.state !== "open") return { status: "skipped", reason: "pull request is not open" };
  const files = await changedFiles(api, pull);
  if (!files.some((file) => file.filename.startsWith(PREFIX))) return { status: "skipped", reason: "not a current hackathon submission" };
  const comments = await api.list(`/repos/${REPOSITORY}/issues/${pull.number}/comments`);
  const receipt = comments.find((comment) => comment.body?.includes(RECEIPT_MARKER) && (
    comment.user?.login === "github-actions[bot]" || ["OWNER", "MEMBER", "COLLABORATOR"].includes(comment.author_association)
  ));
  if (receipt) return { status: "already-received", url: receipt.html_url };
  await currentHead(api, pull);
  // Workflow concurrency serializes receipts for one PR. A failed POST is never
  // retried blindly; the next run lists comments again before deciding to post.
  const comment = await api.request(`/repos/${REPOSITORY}/issues/${pull.number}/comments`, {
    method: "POST", body: { body: receiptBody(pull.number) }
  });
  return { status: "received", url: comment.html_url };
}

export async function submissionTree(api, commit, slug) {
  assert(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug), "invalid submission slug");
  let treeSha = sha(commit);
  for (const part of ["submissions", "mcp-hackathon", slug]) {
    const tree = await api.request(`/repos/${REPOSITORY}/git/trees/${treeSha}`);
    assert(!tree.truncated && Array.isArray(tree.tree), "incomplete Git tree");
    const entry = tree.tree.find((item) => item.path === part);
    assert(entry?.type === "tree" && entry.mode === "040000", "submission directory is missing or is not a regular directory");
    treeSha = sha(entry.sha);
  }
  return treeSha;
}

export async function materializeSubmission(api, commit, slug, directory) {
  const treeSha = await submissionTree(api, commit, slug);
  const tree = await api.request(`/repos/${REPOSITORY}/git/trees/${treeSha}?recursive=1`);
  assert(!tree.truncated && Array.isArray(tree.tree) && tree.tree.length <= MAX_FILES * 2, "submission tree exceeds safe limits");
  const files = tree.tree.filter((entry) => entry.type !== "tree");
  assert(files.length > 0 && files.length <= MAX_FILES, "submission file count exceeds safe limits");
  let totalBytes = 0;
  for (const entry of tree.tree) {
    resolveChangedSubmissionDirectory("/", [`${PREFIX}${slug}/${entry.path}`]);
    assert(!entry.path.split("/").some((part) => part.toLowerCase() === ".git"), "Git metadata is not a submission artifact");
    assert(entry.type === "tree" ? entry.mode === "040000" : entry.type === "blob" && ["100644", "100755"].includes(entry.mode), "symbolic links and submodules cannot be archived as source; submit actual files");
  }
  // Validate all metadata before writing anything. Never extract contributor tar
  // files, follow links, check out fork code, or execute submitted package scripts.
  for (const entry of files) {
    assert(Number.isSafeInteger(entry.size) && entry.size >= 0 && entry.size <= MAX_FILE_BYTES, "submission file exceeds 5 MiB");
    totalBytes += entry.size;
    assert(totalBytes <= MAX_TOTAL_BYTES, "submission exceeds 20 MiB");
    sha(entry.sha);
  }
  for (const entry of files) {
    const blob = await api.request(`/repos/${REPOSITORY}/git/blobs/${entry.sha}`);
    assert(blob.encoding === "base64" && typeof blob.content === "string", "unexpected Git blob encoding");
    const bytes = Buffer.from(blob.content, "base64");
    assert(bytes.length === entry.size, "Git blob size does not match the inspected tree");
    const digest = createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
    assert(digest === entry.sha, "Git blob content does not match the inspected tree");
    const file = join(directory, entry.path);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, bytes, { flag: "wx", mode: entry.mode === "100755" ? 0o700 : 0o600 });
  }
  return treeSha;
}

export async function validatePull(api, pull, options = {}) {
  assert(pull.state === "open", "pull request is not open");
  const slug = submissionSlug(await changedFiles(api, pull));
  const scratchRoot = options.scratchRoot ?? process.env.RUNNER_TEMP ?? resolve("node_modules/.cache");
  await mkdir(scratchRoot, { recursive: true });
  const temporary = await mkdtemp(join(scratchRoot, "xagt-review-"));
  try {
    const directory = join(temporary, slug);
    const tree = await materializeSubmission(api, pull.head.sha, slug, directory);
    const report = await validateSubmissionDirectory(directory, { online: true, ...options.validationOptions });
    await currentHead(api, pull);
    return { ...report, pullRequest: pull.number, headSha: pull.head.sha, submissionTree: tree };
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

export function archiveRef(number, headSha) {
  return `heads/submission-archive/pr-${prNumber(number)}-${sha(headSha)}`;
}

export async function archiveValidatedRun(api, runId, options = {}) {
  const id = prNumber(runId);
  const run = await api.request(`/repos/${REPOSITORY}/actions/runs/${id}`);
  assert(run.repository?.full_name === REPOSITORY && run.path === VALIDATION_WORKFLOW && run.event === "pull_request", "not an official submission-validation run");
  if (run.status !== "completed" || run.conclusion !== "success") return { status: "skipped", reason: "validation did not succeed" };
  sha(run.head_sha);
  // Fork workflow_run payloads may omit pull_requests. Resolve through GitHub's
  // commit association instead of trusting participant-uploaded artifacts.
  const associated = await api.list(`/repos/${REPOSITORY}/commits/${run.head_sha}/pulls`);
  const matches = associated.filter((pull) => pull.base?.repo?.full_name === REPOSITORY && pull.base.ref === "main" && pull.head?.sha === run.head_sha && pull.state === "open");
  if (matches.length === 0) return { status: "skipped", reason: "the checked version is no longer an open PR head" };
  assert(matches.length === 1, "validation run has an ambiguous pull request association");
  const pull = await readPull(api, matches[0].number);
  assert(pull.head.sha === run.head_sha && pull.head.repo?.full_name === run.head_repository?.full_name && pull.head.ref === run.head_branch, "run and current pull request do not identify the same source version");
  const reference = archiveRef(pull.number, pull.head.sha);
  const existing = await optional(api, `/repos/${REPOSITORY}/git/ref/${reference}`);
  if (existing) {
    assert(existing.object?.sha === pull.head.sha, "archive ref already exists with a different commit; refusing to replace it");
    return { status: "already-archived", ref: reference, headSha: pull.head.sha };
  }
  // A green fork workflow is not an authority: rerun the trusted default-branch
  // validator here. Read only bounded GitHub blobs, never fork code or artifacts.
  const report = await validatePull(api, pull, options);
  await currentHead(api, pull);
  try {
    await api.request(`/repos/${REPOSITORY}/git/refs`, { method: "POST", body: { ref: `refs/${reference}`, sha: pull.head.sha } });
  } catch (error) {
    // Creation can have succeeded despite a lost response. Only accept an exact
    // existing ref; never force-update, fall back to unsafe checkout, or guess.
    const found = await optional(api, `/repos/${REPOSITORY}/git/ref/${reference}`);
    if (found?.object?.sha !== pull.head.sha) throw error;
  }
  const saved = await api.request(`/repos/${REPOSITORY}/git/ref/${reference}`);
  assert(saved.object?.sha === pull.head.sha, "official archive could not be verified");
  return { ...report, status: "archived-not-reviewed", ref: reference, validationRun: id };
}

export async function verifySealSource(api, number, slug, repositoryCommit) {
  const pull = await readPull(api, number);
  assert(pull.merged === true && pull.merged_at && pull.state === "closed", "submission PR must already be merged");
  assert(submissionSlug(await changedFiles(api, pull)) === slug, "merged PR does not match the requested submission");
  const ref = archiveRef(pull.number, pull.head.sha);
  // Compatibility with official archives created before full-length ref names.
  const saved = await optional(api, `/repos/${REPOSITORY}/git/ref/${ref}`)
    ?? await optional(api, `/repos/${REPOSITORY}/git/ref/heads/submission-archive/pr-${pull.number}-${pull.head.sha.slice(0, 12)}`);
  assert(saved?.object?.sha === pull.head.sha, "the exact submitted version is missing from the official archive");
  const archivedTree = await submissionTree(api, pull.head.sha, slug);
  const mergedTree = await submissionTree(api, sha(pull.merge_commit_sha), slug);
  const currentTree = await submissionTree(api, sha(repositoryCommit), slug);
  assert(archivedTree === mergedTree && mergedTree === currentTree, "submitted, merged, and release source differ; review the changed version before sealing");
  return { pullRequest: pull.number, officialMergeCommit: pull.merge_commit_sha, archivedHead: pull.head.sha, archiveRef: saved.ref, sourceTree: currentTree };
}

async function main() {
  assert(process.env.GITHUB_REPOSITORY === REPOSITORY, "run this workflow only in the official repository");
  const api = createGitHubClient(process.env.GITHUB_TOKEN);
  const event = JSON.parse(await readFile(process.env.GITHUB_EVENT_PATH, "utf8"));
  const action = process.argv[2];
  const eventName = process.env.GITHUB_EVENT_NAME;
  let report;
  if (action === "receipt") {
    assert(["pull_request_target", "workflow_dispatch"].includes(eventName), "receipt event is not allowed");
    report = await acknowledgeSubmission(api, eventName === "workflow_dispatch" ? process.env.PR_NUMBER : event.pull_request.number);
  } else if (action === "validate") {
    assert(eventName === "pull_request", "validation must run without base-repository write permissions");
    const pull = await readPull(api, event.pull_request.number);
    assert(pull.head.sha === event.pull_request.head.sha, "a newer version was submitted; use its validation run");
    report = await validatePull(api, pull, { validationOptions: { githubToken: process.env.GITHUB_TOKEN } });
  } else if (action === "archive") {
    assert(eventName === "workflow_run", "archive event is not allowed");
    report = await archiveValidatedRun(api, event.workflow_run.id, { validationOptions: { githubToken: process.env.GITHUB_TOKEN } });
  } else if (action === "seal") {
    assert(eventName === "workflow_dispatch" && process.env.GITHUB_REF === "refs/heads/main", "sealing requires a manual run on main");
    const commit = sha(process.env.GITHUB_SHA);
    const root = process.cwd();
    assert(execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim() === commit, "checkout does not match the selected release commit");
    const slug = process.env.SLUG;
    const source = await verifySealSource(api, process.env.PR_NUMBER, slug, commit);
    const directory = `${PREFIX}${slug}`;
    assert(execFileSync("git", ["rev-parse", `HEAD:${directory}`], { encoding: "utf8" }).trim() === source.sourceTree, "local source does not match the official archive");
    const checked = await validateSubmissionDirectory(join(root, directory), {
      online: true,
      // Source provenance was verified against the official archived Git tree
      // above. Do not require the participant's external repository to survive.
      commitVerifier: async () => undefined
    });
    const reviewer = process.env.REVIEWER;
    const record = new URL(process.env.REVIEW_RECORD_URL);
    assert(reviewer?.trim() && reviewer.length <= 300 && !/[\r\n]/.test(reviewer), "reviewer is required");
    assert(record.protocol === "https:" && !record.username && !record.password, "final review record must be an HTTPS URL without credentials");
    report = { schemaVersion: 1, slug, ...source, repositoryCommit: commit, reviewCommit: checked.manifest.reviewCommit, reviewer, reviewRecordUrl: record.href, sealedAt: new Date().toISOString(), rewardGate: "sealed-before-payment" };
    await writeFile(join(process.env.RUNNER_TEMP, "xagt-acceptance.json"), `${JSON.stringify(report, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  } else {
    throw new Error("choose receipt, validate, archive, or seal");
  }
  await publishSummary(action, report);
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch(async (error) => {
    await publishSummary(process.argv[2], undefined, error).catch(() => undefined);
    process.stderr.write(`submission workflow failed: ${JSON.stringify(error.message)}\n`);
    process.exitCode = 1;
  });
}
