#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { promises as dns } from "node:dns";
import { readFile, readdir, lstat } from "node:fs/promises";
import https from "node:https";
import { isIP } from "node:net";
import { basename, join, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const MAX_FILES = 2_000;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_BYTES = 20 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 64 * 1024;
const REQUEST_TIMEOUT_MS = 10_000;

export async function validateSubmissionDirectory(directory, options = {}) {
  const submissionDirectory = resolve(directory);
  const slug = basename(submissionDirectory);
  const checks = [];
  const manifestPath = join(submissionDirectory, "submission.json");
  const submissionPath = join(submissionDirectory, "SUBMISSION.md");
  const rightsPath = join(submissionDirectory, "RIGHTS.md");
  const verificationPath = join(submissionDirectory, "verification", "README.md");

  assertSlug(slug);
  const files = await collectSubmissionFiles(submissionDirectory);
  await requireFile(submissionPath, "SUBMISSION.md");
  await requireFile(rightsPath, "RIGHTS.md");
  await requireFile(verificationPath, "verification/README.md");
  await requireFile(manifestPath, "submission.json");
  const manifest = JSON.parse((await readFile(manifestPath, "utf8")).replace(/^\uFEFF/, ""));
  validateManifest(manifest, slug);
  checks.push("submission structure and manifest are valid");

  const sourceFiles = files.filter((file) => file.relativePath.startsWith("source/"));
  if (!sourceFiles.some((file) => /\.(?:[cm]?[jt]sx?|py|go|rs|java|kt|kts|c|cc|cpp|h|hpp|cs|fs|rb|php|swift|scala|sh|bash|sol|vy|ex|exs|erl|clj|lua|r|jl|ipynb|html|vue|svelte|sql)$/i.test(file.relativePath))) {
    throw new Error("source/ must contain implementation files, not only documentation or repository links; completeness still requires manual review");
  }
  await scanSourceFiles(files);
  checks.push(`${sourceFiles.length} source files are present; all submission files passed the baseline secret scan (not a completeness or security certification)`);

  const verification = await readFile(verificationPath, "utf8");
  if (!/curl\s/i.test(verification) || !/health/i.test(verification)) {
    throw new Error("verification/README.md must contain a repeatable curl call and health-check evidence");
  }
  checks.push("verification evidence contains a health check and repeatable curl command");

  if (options.online) {
    const commitVerifier = options.commitVerifier ?? verifyGitHubCommit;
    const jsonRequester = options.jsonRequester ?? requestJsonPinned;
    await commitVerifier(manifest.sourceRepository, manifest.reviewCommit, options.githubToken);
    checks.push("the declared source version has been verified");

    const health = await jsonRequester(manifest.healthCheckUrl);
    const healthCommit = health.headers["x-source-commit"] ?? health.body.commit ?? health.body.version;
    if (!isHealthy(health.body.status) || healthCommit !== manifest.reviewCommit) {
      throw new Error("health check must report status=ok|healthy and the exact review commit");
    }
    checks.push("the live health check is reachable and bound to the review commit");

    const proof = await jsonRequester(manifest.deploymentProofUrl);
    if (
      proof.body.schemaVersion !== 1 ||
      proof.body.slug !== manifest.slug ||
      proof.body.commit !== manifest.reviewCommit
    ) {
      throw new Error("deployment proof does not match schemaVersion, slug, and review commit");
    }
    checks.push("the standard deployment proof confirms control of the live service");
  }

  return { status: "pass", slug, checks, manifest };
}

export function findChangedSubmissionDirectory(repoRoot, baseSha, headSha) {
  if (![baseSha, headSha].every((sha) => /^[a-f0-9]{40}$/i.test(sha))) {
    throw new Error("scope comparison requires exact commit hashes");
  }
  const output = execFileSync(
    "git",
    ["-C", repoRoot, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", `${baseSha}...${headSha}`],
    { encoding: "utf8", timeout: 30_000 }
  );
  const files = output.split("\0").filter(Boolean);
  return resolveChangedSubmissionDirectory(repoRoot, files);
}

export function resolveChangedSubmissionDirectory(repoRoot, files) {
  if (files.length === 0) throw new Error("the pull request has no changed files");

  const directories = new Set();
  for (const file of files) {
    if (typeof file !== "string" || file.includes("\\") || /[\x00-\x1f\x7f]/.test(file) || file.split("/").some((part) => !part || part === "." || part === "..")) {
      throw new Error("invalid submission file path");
    }
    const parts = file.split("/");
    if (parts[0] !== "submissions" || parts[1] !== "mcp-hackathon" || parts.length < 4) {
      throw new Error(`submission PRs may only change one project directory under submissions/mcp-hackathon/: ${file}`);
    }
    assertSlug(parts[2]);
    directories.add(parts[2]);
  }
  if (directories.size !== 1) throw new Error("a submission PR must change exactly one project directory");
  return join(repoRoot, "submissions", "mcp-hackathon", [...directories][0]);
}

function validateManifest(manifest, directorySlug) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) throw new Error("submission.json must contain an object");
  const requiredStrings = [
    "name",
    "slug",
    "sourceRepository",
    "reviewCommit",
    "apiBaseUrl",
    "healthCheckUrl",
    "deploymentProofUrl"
  ];
  if (manifest.schemaVersion !== 1) throw new Error("submission.json schemaVersion must be 1");
  for (const key of requiredStrings) {
    if (typeof manifest[key] !== "string" || !manifest[key].trim()) {
      throw new Error(`submission.json ${key} is required`);
    }
  }
  if (manifest.slug !== directorySlug) throw new Error("submission.json slug must match the directory name");
  assertSlug(manifest.slug);
  if (!/^[a-f0-9]{40}$/i.test(manifest.reviewCommit)) {
    throw new Error("submission.json reviewCommit must be a 40-character Git commit SHA");
  }

  const source = assertPublicHttpsUrl(manifest.sourceRepository, "sourceRepository");
  if (source.hostname !== "github.com" || !/^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(source.pathname) || source.search || source.hash) {
    throw new Error("sourceRepository must be a public https://github.com/<owner>/<repo> URL");
  }
  const api = assertPublicHttpsUrl(manifest.apiBaseUrl, "apiBaseUrl");
  const health = assertPublicHttpsUrl(manifest.healthCheckUrl, "healthCheckUrl");
  const proof = assertPublicHttpsUrl(manifest.deploymentProofUrl, "deploymentProofUrl");
  if (api.origin !== health.origin || api.origin !== proof.origin) {
    throw new Error("API, health check, and deployment proof must use the same public origin");
  }
  if (proof.pathname !== "/.well-known/xagent-verification.json" || proof.search || proof.hash) {
    throw new Error("deploymentProofUrl must use /.well-known/xagent-verification.json");
  }
}

function assertSlug(slug) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    throw new Error(`invalid submission slug: ${slug}`);
  }
}

function assertPublicHttpsUrl(raw, label) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`${label} must be a valid URL`);
  }
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) {
    throw new Error(`${label} must be a public HTTPS URL without credentials or a custom port`);
  }
  const hostname = url.hostname.toLowerCase();
  if (hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local")) {
    throw new Error(`${label} cannot target a local hostname`);
  }
  if (isIP(hostname) && isPrivateIp(hostname)) throw new Error(`${label} cannot target a private IP`);
  return url;
}

export function isPrivateIp(address) {
  if (address.includes(":")) {
    const normalized = address.toLowerCase();
    if (normalized === "::" || normalized === "::1" || normalized.startsWith("fc") || normalized.startsWith("fd") || normalized.startsWith("fe8") || normalized.startsWith("fe9") || normalized.startsWith("fea") || normalized.startsWith("feb")) return true;
    if (normalized.startsWith("::ffff:")) return isPrivateIp(normalized.slice(7));
    return !/^[23]/.test(normalized);
  }
  const octets = address.split(".").map(Number);
  if (octets.length !== 4 || octets.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) return true;
  const [a, b] = octets;
  return (
    a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && (b === 0 || b === 168)) ||
    (a === 198 && (b === 18 || b === 19))
  );
}

async function collectSubmissionFiles(sourcePath) {
  const files = [];
  let totalBytes = 0;

  async function walk(directory) {
    const directoryStat = await lstat(directory);
    if (directoryStat.isSymbolicLink()) throw new Error("symbolic links are not allowed in the submission");
    if (!directoryStat.isDirectory()) throw new Error("submission source must be a directory");
    const entries = await readdir(directory, { withFileTypes: true }).catch(() => {
      throw new Error("source/ must exist and contain the complete review source");
    });
    for (const entry of entries) {
      const fullPath = join(directory, entry.name);
      const relativePath = relative(sourcePath, fullPath).split(sep).join("/");
      if (entry.isSymbolicLink()) throw new Error(`symbolic links are not allowed in submitted source: ${relativePath}`);
      if (entry.isDirectory()) {
        if (["node_modules", ".git", "dist", "build", ".next", "vendor"].includes(entry.name)) {
          throw new Error(`generated or vendored directory is not allowed: ${relativePath}`);
        }
        await walk(fullPath);
        continue;
      }
      if (!entry.isFile()) continue;
      const details = await lstat(fullPath);
      if (details.size > MAX_FILE_BYTES) throw new Error(`source file exceeds 5 MiB: ${relativePath}`);
      totalBytes += details.size;
      if (totalBytes > MAX_TOTAL_BYTES) throw new Error("submitted source exceeds the 20 MiB review limit");
      files.push({ fullPath, relativePath, size: details.size });
      if (files.length > MAX_FILES) throw new Error("submitted source exceeds the 2,000-file review limit");
    }
  }

  await walk(sourcePath);
  if (files.length === 0) throw new Error("source/ is empty");
  return files;
}

async function scanSourceFiles(files) {
  const secretPatterns = [
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
    /\bAKIA[0-9A-Z]{16}\b/,
    /\bgh[pousr]_[A-Za-z0-9]{36,}\b/,
    /\bsk-[A-Za-z0-9_-]{20,}\b/,
    /\bxox[baprs]-[A-Za-z0-9-]{20,}\b/
  ];
  for (const file of files) {
    const name = basename(file.relativePath).toLowerCase();
    if ((name.startsWith(".env") && !name.includes("example")) || /\.(?:pem|p12|pfx|key)$/.test(name)) {
      throw new Error(`secret-bearing file type is not allowed: ${file.relativePath}`);
    }
    const content = await readFile(file.fullPath, "utf8");
    if (content.startsWith("version https://git-lfs.github.com/spec/v1")) {
      throw new Error(`Git LFS pointers are not source archives; include the actual file: ${file.relativePath}`);
    }
    if (secretPatterns.some((pattern) => pattern.test(content))) {
      throw new Error(`possible secret detected in ${file.relativePath}`);
    }
  }
}

async function requireFile(path, label) {
  const details = await lstat(path).catch(() => null);
  if (details?.isSymbolicLink()) throw new Error(`symbolic links are not allowed: ${label}`);
  if (!details?.isFile() || details.size === 0) throw new Error(`${label} is required and cannot be empty`);
}

async function verifyGitHubCommit(repositoryUrl, commit, githubToken) {
  const url = new URL(repositoryUrl);
  const [owner, repo] = url.pathname.split("/").filter(Boolean);
  const headers = { accept: "application/vnd.github+json", "user-agent": "xagent-submission-validator" };
  if (githubToken) headers.authorization = `Bearer ${githubToken}`;
  const response = await fetch(`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/commits/${commit}`, { headers, redirect: "error", signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (!response.ok) throw new Error(`declared source commit is not publicly verifiable on GitHub (${response.status})`);
}

export async function requestJsonPinned(rawUrl) {
  const url = assertPublicHttpsUrl(rawUrl, "online verification URL");
  const addresses = await dns.lookup(url.hostname, { all: true, verbatim: true });
  const publicAddress = addresses.find((item) => !isPrivateIp(item.address));
  if (!publicAddress) throw new Error(`verification host has no public IP address: ${url.hostname}`);

  return new Promise((resolveRequest, rejectRequest) => {
    const request = https.request({
      protocol: "https:",
      hostname: publicAddress.address,
      family: publicAddress.family,
      port: 443,
      path: `${url.pathname}${url.search}`,
      method: "GET",
      servername: url.hostname,
      headers: { host: url.host, accept: "application/json", "user-agent": "xagent-submission-validator" },
      timeout: REQUEST_TIMEOUT_MS,
      rejectUnauthorized: true
    }, (response) => {
      if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
        response.resume();
        rejectRequest(new Error(`online verification returned HTTP ${response.statusCode ?? "unknown"}`));
        return;
      }
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > MAX_RESPONSE_BYTES) request.destroy(new Error("online verification response exceeds 64 KiB"));
        else chunks.push(chunk);
      });
      response.on("end", () => {
        try {
          const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          resolveRequest({ body, headers: response.headers });
        } catch {
          rejectRequest(new Error("online verification response must be valid JSON"));
        }
      });
    });
    request.on("timeout", () => request.destroy(new Error("online verification timed out")));
    request.on("error", rejectRequest);
    request.end();
  });
}

function isHealthy(status) {
  return status === "ok" || status === "healthy";
}

function parseArgs(args) {
  const options = { online: false };
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (value === "--online") { options.online = true; continue; }
    if (["--dir", "--repo-root", "--base", "--head"].includes(value)) {
      options[value.slice(2).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = args[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`unsupported option: ${value}`);
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  let directory = options.dir;
  if (!directory && options.repoRoot && options.base && options.head) {
    directory = findChangedSubmissionDirectory(options.repoRoot, options.base, options.head);
  }
  if (!directory) throw new Error("provide --dir, or --repo-root with --base and --head");
  const report = await validateSubmissionDirectory(directory, {
    online: options.online,
    githubToken: process.env.XAGT_GITHUB_TOKEN
  });
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((error) => {
    process.stderr.write(`submission validation failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
